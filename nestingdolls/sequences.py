from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime, time
from itertools import islice
from typing import Any, Self, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.fields import BooleanField, FileField
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DEFAULT_MIN_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    BaseFormSet,
    ManagementForm,
)
from django.forms.utils import ErrorList
from django.forms.widgets import Media as WidgetMedia
from django.forms.widgets import MultipleHiddenInput, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from nestingdolls._shared import CompositeWidget

__all__ = [
    "FrozenSequenceField",
    "FrozenSetField",
    "ListField",
    "SequenceBoundField",
    "SequenceField",
    "SequenceWidget",
    "SetField",
    "TupleField",
]

from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MissingManagementFormValidationError,
    SequenceInputValidationError,
    TooManyFormsValidationError,
)
from nestingdolls.rendering import FormLayout


class SequenceBoundField(BoundField):
    """Render indexed child errors without storing validation state on the field.

    Django passes a widget no errors when it renders a ``BoundField``. A sequence
    has one field-level error list but several visible child widgets, so this
    real ``BoundField`` subclass is the small, public adapter that places a
    child error beside the row identified by its validation index.
    """

    field: SequenceField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")

    @property
    def errors(self) -> ErrorList:
        """Return only field-level errors for Django's normal field rendering."""
        errors = super().errors
        if not errors:
            return errors
        field_errors = []
        for error in errors.as_data():
            if isinstance(error, ItemValidationError):
                continue
            field_errors.append(error)
        if len(field_errors) == len(errors):
            return errors
        return self.form.error_class(
            field_errors,
            renderer=self.form.renderer,
            field_id=self.auto_id,
        )

    def as_widget(
        self,
        widget: Widget | None = None,
        attrs: dict[str, str | bool] | None = None,
        only_initial: bool = False,
    ) -> SafeString:
        """Delegate normal rendering to Django and only patch sequence rows when needed."""
        widget = widget or self.field.widget
        if only_initial or not isinstance(widget, SequenceWidget):
            return super().as_widget(widget, attrs, only_initial)
        errors = super().errors
        item_errors: dict[int, list[object]] = defaultdict(list)
        for error in errors.as_data():
            if isinstance(error, ItemValidationError) and isinstance(error.item, int):
                item_errors[error.item].extend([error.message])
        deleted_indexes = self._deleted_indexes
        if not deleted_indexes and not errors:
            return super().as_widget(widget, attrs, only_initial)

        if self.field.localize:
            widget.is_localized = True
        attrs = self.build_widget_attrs(dict(attrs or {}), widget)
        if self.auto_id and "id" not in widget.attrs:
            attrs.setdefault("id", self.auto_id)

        context = widget.get_context(
            self.html_name,
            self.value(),
            attrs,
            management_data=self._data_input,
        )

        # A simple widget stores its HTML attributes in this context. A MultiWidget
        # also creates one child context for each rendered input. Changes to the
        # parent context do not update those child contexts. Walk the complete tree
        # so every rendered input is invalid and refers to the same row error. Keep
        # existing descriptions, and add no error reference when Django has no ID.
        def set_error_attributes(
            widget_context: dict[str, Any], error_id: str | None
        ) -> None:
            child_attrs = widget_context["attrs"]
            child_attrs["aria-invalid"] = "true"
            if error_id:
                described_by = child_attrs.get("aria-describedby")
                child_attrs["aria-describedby"] = (
                    f"{described_by} {error_id}" if described_by else error_id
                )
            for child_context in widget_context.get("subwidgets", []):
                set_error_attributes(child_context, error_id)

        rows = []
        for row in context["widget"]["rows"]:
            if row["index"] in deleted_indexes:
                continue
            row["errors"] = item_errors[row["index"]]
            if row["errors"]:
                subwidget = row["subwidget"]
                child_id = subwidget["attrs"].get("id")
                error_id = f"{child_id}_error" if child_id else None
                if error_id:
                    row["error_id"] = error_id
                set_error_attributes(subwidget, error_id)
            rows.append(row)
        context["widget"]["rows"] = rows
        if deleted_indexes:
            context["widget"]["deleted_rows"] = [
                {"delete_name": f"{self.html_name}-{index}-{DELETION_FIELD_NAME}"}
                for index in sorted(deleted_indexes)
            ]

        # Widget.render() builds a new context and would lose the row changes above.
        # Django has no public API for a prepared widget context, so use _render().
        return widget._render(  # type: ignore[attr-defined, no-any-return]
            f"nestingdolls/sequence/{FormLayout.current().value}.html",
            context,
            self.form.renderer,
        )

    @cached_property
    def _data_input(self) -> MultiValueDict[str, object]:
        """Cache normalized submitted form data for this field."""
        return self.field.widget._normalize_mapping(self.form.data, self.html_name)

    @cached_property
    def _file_input(self) -> MultiValueDict[str, object]:
        """Cache normalized submitted files for this field."""
        if not self.form.files:
            return MultiValueDict()
        return self.field.widget._normalize_mapping(self.form.files, self.html_name)

    @cached_property
    def _management_form(self) -> ManagementForm | None:
        """Build a management form from normalized sequence inputs."""
        if not any(
            name in self._data_input
            for name in self.field.widget.management_names(self.html_name)
        ):
            return None
        management_form = ManagementForm(self._data_input, prefix=self.html_name)
        management_form.full_clean()
        return management_form

    @cached_property
    def data(self) -> list[object]:
        """Return the bound value extracted from normalized data and files."""
        return self.field.widget._value_from_normalized_data(
            self._data_input,
            self._file_input,
            self.html_name,
        )

    @cached_property
    def initial(self) -> list[object]:
        """Use Django's normal initial path unless flattened row keys need normalizing."""
        if self.form.initial and self.name not in self.form.initial:
            value = self._normalize_initial_mapping(self.form.initial)
            if value is None:
                value = super().initial
        else:
            value = super().initial
        if isinstance(value, Mapping):
            normalized_value = self._normalize_initial_mapping(value)
            if normalized_value is not None:
                value = normalized_value
        try:
            value = self.field._initial_values(value, limit=self.field.absolute_max)
        except InvalidInitialValueError:
            value = [value]
        if not self.field.child_field.widget.supports_microseconds:
            return [
                item.replace(microsecond=0)
                if isinstance(item, (datetime, time))
                else item
                for item in value
            ]
        return value

    def _normalize_initial_mapping(
        self, value: Mapping[str, object]
    ) -> list[object] | None:
        """Return normalized initial rows for mapping-style values when possible."""
        value = self.field.widget._normalize_mapping(value, self.name)
        if not value:
            return None
        return self.field.widget._value_from_normalized_data(
            value,
            MultiValueDict(),
            self.name,
        )

    @cached_property
    def _deleted_indexes(self) -> frozenset[int]:
        """Return submitted deleted rows, as ``BaseFormSet.deleted_forms`` does."""
        if not isinstance(self.field.widget, SequenceWidget):
            return frozenset()
        data_input = self._data_input
        return frozenset(
            index
            for index in range(len(self.data))
            if self.field.widget.deletion_field.clean(
                data_input.get(f"{self.html_name}-{index}-{DELETION_FIELD_NAME}")
            )
        )

    @cached_property
    def _omitted_indexes(self) -> frozenset[int]:
        """Return extra submitted rows that were omitted by the child widget."""
        if not isinstance(self.field.widget, SequenceWidget):
            return frozenset()
        data_input = self._data_input
        file_input = self._file_input
        if self.html_name in data_input or self.html_name in file_input:
            return frozenset()
        initial_count = len(self.field._initial_values(self.initial))
        return frozenset(
            index
            for index in range(len(self.data))
            if index >= initial_count
            and self.field.widget.child_field.widget.value_omitted_from_data(
                data_input,
                file_input,
                f"{self.html_name}-{index}",
            )
        )

    def _has_changed(self) -> bool:
        """Treat deleted initial rows as a real change."""
        if self.field.show_hidden_initial:
            hidden_widget = self.field.hidden_widget()
            try:
                initial = self.field.to_python(
                    hidden_widget.value_from_datadict(
                        self.form.data, self.form.files, self.html_initial_name
                    )
                )
                initial = [self.field.child_field.to_python(value) for value in initial]
            except ValidationError:
                return True
            changed = self.field.has_changed(initial, self.data)
        else:
            changed = cast(bool, super()._has_changed())  # type: ignore[misc]
        if not isinstance(self.field.widget, SequenceWidget):
            return changed
        if changed or not self._deleted_indexes:
            return changed
        try:
            initial_length = len(self.field._initial_values(self.initial))
        except InvalidInitialValueError:
            return True
        return any(index < initial_length for index in self._deleted_indexes)


class SequenceField(Field):
    """Validate a variable-length collection with one homogeneous child field."""

    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a list of values."),
        "missing_management_form": BaseFormSet.default_error_messages[
            "missing_management_form"
        ],
        "too_many_forms": BaseFormSet.default_error_messages["too_many_forms"],
        "min_length": ngettext_lazy(
            "Ensure this value has at least %(limit_value)d item (it has %(show_value)d).",
            "Ensure this value has at least %(limit_value)d items (it has %(show_value)d).",
            "limit_value",
        ),
        "max_length": ngettext_lazy(
            "Ensure this value has at most %(limit_value)d item (it has %(show_value)d).",
            "Ensure this value has at most %(limit_value)d items (it has %(show_value)d).",
            "limit_value",
        ),
    }
    bound_field_class: type[SequenceBoundField] = SequenceBoundField
    hidden_widget = MultipleHiddenInput
    widget: SequenceWidget

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        required: bool = True,
        widget: SequenceWidget | type[SequenceWidget] | None = None,
        label: str | Promise | None = None,
        initial: object | Callable[[], object] | None = None,
        help_text: str | Promise = "",
        error_messages: Mapping[str, str | Promise] | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Callable[[Collection[object]], None]] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[SequenceBoundField] | None = None,
    ) -> None:
        """Configure a homogeneous variable-length field."""
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        if min_length < 0 or max_length < min_length:
            raise ValueError("min_length and max_length must be non-negative integers")
        if absolute_max is None:
            absolute_max = max_length + DEFAULT_MAX_NUM
        if max_length > absolute_max:
            raise ValueError("'absolute_max' must be greater or equal to 'max_length'.")
        if (
            initial is not None
            and not callable(initial)
            and not isinstance(initial, Mapping)
            and len(self._initial_values(initial)) > max_length
        ):
            raise ValueError("initial must not contain more than max_length values")

        self.child_field = copy.deepcopy(child_field)
        self.min_length = min_length
        self.max_length = max_length
        self.absolute_max = absolute_max
        self.child_field.localize = localize

        widget = SequenceWidget if widget is None else widget
        if not (
            isinstance(widget, SequenceWidget)
            or isinstance(widget, type)
            and issubclass(widget, SequenceWidget)
        ):
            raise TypeError("widget must be a SequenceWidget instance or subclass")
        if isinstance(widget, type):
            widget = widget(self.child_field)

        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, SequenceBoundField):
            raise TypeError("bound_field_class must inherit from SequenceBoundField")
        super().__init__(
            required=required,
            widget=widget,
            label=label,  # type: ignore[arg-type]
            initial=initial,
            help_text=help_text,  # type: ignore[arg-type]
            error_messages=error_messages,  # type: ignore[arg-type]
            show_hidden_initial=show_hidden_initial,
            validators=validators,
            localize=localize,
            disabled=disabled,
            label_suffix=label_suffix,
            template_name=template_name,
            bound_field_class=bound_field_class,
        )
        # Django copies the widget. Configure that copy to match this field.
        self.widget.child_field = self.child_field
        self.widget.min_length = min_length
        self.widget.max_length = max_length
        self.widget.absolute_max = self.absolute_max

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy the field and its child field together."""
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def _initial_values(value: object, *, limit: int | None = None) -> list[object]:
        """Normalize supported initial collections into a list."""
        if value is None or value == "":
            return []
        if (
            isinstance(value, Collection)
            and not isinstance(value, Mapping)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            if limit is not None:
                return list(islice(value, limit))
            return list(value)
        raise InvalidInitialValueError("initial must be a collection of values")

    def to_python(self, value: object) -> list[object]:
        """Require sequence input to already be list-shaped."""
        if value is None or value == "":
            return []
        if not isinstance(value, list):
            raise SequenceInputValidationError(self.error_messages["invalid"])
        return value

    def _clean_values(
        self,
        values: list[object],
        initial_values: list[object],
        deleted_indexes: frozenset[int] = frozenset(),
        omitted_indexes: frozenset[int] = frozenset(),
    ) -> list[object]:
        """Clean each submitted row and return the cleaned row list."""
        if len(values) > self.absolute_max:
            raise TooManyFormsValidationError(
                self.error_messages["too_many_forms"], num=self.max_length
            )
        cleaned_data: list[object] = []
        errors = []
        for index, value in enumerate(values):
            if index in deleted_indexes or index in omitted_indexes:
                continue
            initial = initial_values[index] if index < len(initial_values) else None
            try:
                if self.child_field.disabled:
                    cleaned = self.child_field.clean(initial)
                elif isinstance(self.child_field, FileField):
                    cleaned = self.child_field.clean(value, initial)
                else:
                    cleaned = self.child_field.clean(value)
            except ValidationError as error:
                for item_error in error.error_list:
                    for message in item_error.messages:
                        errors.append(
                            ItemValidationError(
                                index,
                                message,
                                ValidationError(
                                    message,
                                    code=(item_error.params or {}).get(
                                        "child_code", item_error.code
                                    ),
                                    params=item_error.params,
                                ),
                            )
                        )
            else:
                cleaned_data.append(cleaned)
        if errors:
            raise ValidationError(errors)
        return cleaned_data

    def clean(self, value: object) -> Collection[object]:
        """Clean an already-collected sequence value."""
        result = self.compress(self._clean_values(self.to_python(value), []))
        self.validate(result)
        self.run_validators(result)
        return result

    def _clean_bound_field(self, bound_field: BoundField) -> Collection[object]:
        """Validate Django's management form and retain FileField initial values.

        ``ManagementForm`` owns management-input validation. ``FileField.clean()``
        is deliberately called with ``(data, initial)``; that public API
        implements Django's upload, clear, and contradiction semantics. Ordinary
        child fields continue to use their normal one-value ``clean()`` API.
        """
        assert isinstance(bound_field, SequenceBoundField)
        if self.disabled:
            return cast(
                Collection[object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        management_form = bound_field._management_form
        deleted_indexes = bound_field._deleted_indexes
        omitted_indexes = bound_field._omitted_indexes
        if (
            management_form is None
            and not deleted_indexes
            and not omitted_indexes
            and not isinstance(self.child_field, FileField)
        ):
            return cast(
                Collection[object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )

        if management_form is not None:
            if not management_form.is_valid():
                raise MissingManagementFormValidationError(
                    self.error_messages["missing_management_form"],
                    field_names=", ".join(
                        management_form.add_prefix(field_name)
                        for field_name in management_form.errors
                    ),
                )
            submitted_total = management_form.cleaned_data[TOTAL_FORM_COUNT]
            if isinstance(submitted_total, int) and submitted_total > self.absolute_max:
                raise TooManyFormsValidationError(
                    self.error_messages["too_many_forms"], num=self.max_length
                )

        initial = self._initial_values(bound_field.initial)
        data = self.to_python(bound_field.data)
        if (
            management_form is None
            and isinstance(self.child_field, FileField)
            and not data
            and initial
        ):
            data = [None] * len(initial)
        result = self.compress(
            self._clean_values(
                data,
                initial,
                deleted_indexes,
                omitted_indexes,
            )
        )
        self.validate(result)
        self.run_validators(result)
        return result

    def validate(self, value: Collection[object]) -> None:
        """Apply required, minimum, and maximum length checks."""
        if not value:
            super().validate([])
            return
        length = len(value)
        if length < self.min_length:
            raise ValidationError(
                self.error_messages["min_length"],
                code="min_length",
                params={"limit_value": self.min_length, "show_value": length},
            )
        if length > self.max_length:
            raise ValidationError(
                self.error_messages["max_length"],
                code="max_length",
                params={"limit_value": self.max_length, "show_value": length},
            )

    def compress(self, data_list: list[object]) -> Collection[object]:
        """Return the cleaned list unchanged."""
        return data_list

    def bound_data(self, data: object, initial: object) -> Collection[object]:
        """Bind each submitted row against its matching initial value."""
        if self.disabled:
            return self._initial_values(initial)
        if isinstance(data, list) and len(data) > self.absolute_max:
            return []
        initial = self._initial_values(initial)
        values = []
        for index, value in enumerate(self.to_python(data)):
            initial_value = initial[index] if index < len(initial) else None
            try:
                value = self.child_field.bound_data(value, initial_value)
            except (InvalidInitialValueError, ValidationError):
                # BoundField.value() calls this while rendering. Composite children
                # may reject a hostile row shape here after cleaning has already
                # recorded a form error. Django's base contract for an enabled field
                # is to redisplay the submitted value; prepare_value() mirrors this
                # fallback so no widget-specific replacement value is needed.
                value = super().bound_data(value, initial_value)
            values.append(value)
        return values

    def prepare_value(self, value: object) -> list[object]:
        """Prepare each row for widget rendering."""
        values = []
        for row in self._initial_values(value, limit=self.absolute_max):
            try:
                row = self.child_field.prepare_value(row)
            except (InvalidInitialValueError, ValidationError):
                row = super().prepare_value(row)
            values.append(row)
        return values

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare submitted rows using child-field change semantics."""
        if self.disabled:
            return False
        if isinstance(data, list) and len(data) > self.absolute_max:
            return True
        try:
            initial = self._initial_values(initial)
        except InvalidInitialValueError:
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True
        shared_length = min(len(initial), len(data))
        for index in range(shared_length):
            try:
                if self.child_field.has_changed(initial[index], data[index]):
                    return True
            except ValidationError:
                return True
        if len(initial) > len(data):
            return True
        for value in data[shared_length:]:
            try:
                if self.child_field.has_changed(None, value):
                    return True
            except ValidationError:
                return True
        return False


ListField = SequenceField


class FrozenSequenceField(SequenceField):
    """Collect cleaned rows into an immutable tuple."""

    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        """Return cleaned rows as a tuple."""
        return tuple(data_list)


TupleField = FrozenSequenceField


class SetField(SequenceField):
    """Collect cleaned rows into a deduplicated set-like value."""

    default_error_messages = {  # noqa: RUF012
        "unhashable": _("Set items must be hashable."),
    }

    collection_type: Callable[[list[object]], set[object] | frozenset[object]] = set

    def compress(self, data_list: list[object]) -> set[object] | frozenset[object]:
        """Return cleaned rows in the configured set type."""
        try:
            return self.collection_type(data_list)
        except TypeError as error:
            raise ValidationError(
                self.error_messages["unhashable"], code="unhashable"
            ) from error

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare semantic set members, not raw row order or raw row spelling.

        ``has_changed()`` receives raw submitted row data but initial members are
        already cleaned Python values. A plain ``==`` comparison would therefore
        be wrong for child fields that coerce input or use compound widget data.

        This method indexes ordinary hashable members and falls back to semantic
        scans for compound or custom child values.
        """
        if self.disabled:
            return False
        if isinstance(data, list) and len(data) > self.absolute_max:
            return True
        try:
            initial = list(self.compress(self._initial_values(initial)))
        except (InvalidInitialValueError, ValidationError):
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True

        try:
            indexed: dict[object, list[int]] = defaultdict(list)
            for index, value in enumerate(initial):
                try:
                    indexed[value].append(index)
                except TypeError:
                    pass

            matched: set[int] = set()
            all_indexes = range(len(initial))

            def matching_index(
                value: object, candidates: Collection[int]
            ) -> int | None:
                for indexes, already_matched in (
                    (candidates, False),
                    (all_indexes, False),
                    (candidates, True),
                    (all_indexes, True),
                ):
                    for index in indexes:
                        if (index in matched) != already_matched:
                            continue
                        if not self.child_field.has_changed(initial[index], value):
                            return index
                return None

            for data_value in data:
                try:
                    value = self.child_field.to_python(data_value)
                except (TypeError, ValidationError):
                    return True
                try:
                    candidates = indexed.get(value, ())
                except TypeError:
                    candidates = ()

                match = matching_index(data_value, candidates)
                if match is None:
                    if self.child_field.has_changed(None, data_value):
                        return True
                    continue
                matched.add(match)
        except (TypeError, ValidationError):
            return True
        return len(matched) != len(initial)


class FrozenSetField(SetField):
    """Collect cleaned rows into a frozenset."""

    collection_type = frozenset


class SequenceWidget(CompositeWidget):
    """Render dynamic homogeneous rows while delegating each row to one widget."""

    _template_name = "nestingdolls/sequence/{layout}.html"
    use_fieldset = True
    deletion_field = BooleanField(required=False)

    class Media:
        """Load the client-side row add/remove controller."""

        js = ("nestingdolls/sequence.js",)

    def __init__(
        self,
        child_field: Field,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store child-widget settings for a sequence field."""
        self.child_field = child_field
        self.min_length = min_length
        self.max_length = max_length
        self.absolute_max = (
            max_length + DEFAULT_MAX_NUM if absolute_max is None else absolute_max
        )
        super().__init__(dict(attrs) if attrs is not None else None)

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> list[object]:
        """Extract a sequence value from raw submitted inputs."""
        return self._value_from_normalized_data(
            self._normalize_mapping(data, name),
            self._normalize_mapping(files, name) if files else MultiValueDict(),
            name,
        )

    def _value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> list[object]:
        """Extract row values from canonicalized data and files."""

        def direct_sequence_value(
            source: Mapping[str, object],
        ) -> list[object] | None:
            if name not in source:
                return None
            value = source.get(name)
            return value[: self.absolute_max + 1] if isinstance(value, list) else []

        def submitted_total_forms(source: Mapping[str, object]) -> int | None:
            value = source.get(f"{name}-{TOTAL_FORM_COUNT}")
            if value is None or not isinstance(value, (str, int)):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        direct_data = direct_sequence_value(data)
        if direct_data is not None:
            return direct_data
        direct_files = direct_sequence_value(files)
        if direct_files is not None:
            return direct_files

        counts = [
            count
            for source in (data, files)
            if (count := submitted_total_forms(source)) is not None
        ]
        if not counts:
            return []
        form_count = max(counts)
        if form_count < 0 or form_count > self.absolute_max:
            return []
        return [
            self.child_field.widget.value_from_datadict(data, files, f"{name}-{index}")
            for index in range(form_count)
        ]

    @staticmethod
    def management_names(name: str) -> set[str]:
        """Return the management keys for a sequence field name."""
        return {
            f"{name}-{TOTAL_FORM_COUNT}",
            f"{name}-{INITIAL_FORM_COUNT}",
            f"{name}-{MIN_NUM_FORM_COUNT}",
            f"{name}-{MAX_NUM_FORM_COUNT}",
        }

    def _normalized_row_key(self, key: object, name: str) -> tuple[str, int] | None:
        """Normalize one supported row key into its canonical name and index."""
        if not isinstance(key, str):
            return None
        for separator in ("-", ".", "["):
            prefix = f"{name}{separator}"
            if not key.startswith(prefix):
                continue
            suffix = key.removeprefix(prefix)
            index_end = 0
            index = 0
            while index_end < len(suffix) and "0" <= suffix[index_end] <= "9":
                digit = ord(suffix[index_end]) - ord("0")
                index = min(self.absolute_max, index * 10 + digit)
                index_end += 1
            if not index_end:
                return None
            if separator == "[":
                if index_end == len(suffix) or suffix[index_end] != "]":
                    return None
                suffix = suffix[index_end + 1 :]
            else:
                suffix = suffix[index_end:]
            if suffix and suffix[0] not in "_-.[":
                return None
            return (f"{name}-{index}{suffix}", index)
        return None

    def _normalize_mapping(
        self, data: Mapping[str, object], name: str
    ) -> MultiValueDict[str, object]:
        """Canonicalize accepted row spellings into Django-style keys and dense rows.

        post[]:
            implies(not data, not __return__)
            implies(name in data, name in __return__)
            all(key == name or key.startswith(f"{name}-") for key in __return__)
            len(__return__) <= len(data) + 2
        """
        normalized = MultiValueDict[str, object]()
        if not data:
            return normalized

        def values_for(key: str) -> list[object]:
            # Treat repeated input the same way Django request data does.
            if isinstance(data, MultiValueDict):
                return list(data.getlist(key))
            value = data.get(key)
            return value if isinstance(value, list) else [value]

        # Keep formset control fields in the repeated-value shape Django expects.
        management_keys = {key for key in self.management_names(name) if key in data}
        if name in data:
            # Use the direct list value when both shapes are present.
            direct_value = values_for(name)
            normalized[name] = direct_value
            if not management_keys:
                # Build missing control fields for a direct Python list.
                normalized[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(direct_value))
                normalized[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
                return normalized
            for key in management_keys:
                normalized.setlist(key, values_for(key))
            return normalized

        overflowed_index = False
        row_inputs: list[tuple[int, str, list[object]]] = []
        for key in management_keys:
            normalized.setlist(key, values_for(key))

        for key in data:
            if key in management_keys:
                continue
            row_key = self._normalized_row_key(key, name)
            if row_key is None:
                continue
            row_name, index = row_key
            if index >= self.absolute_max:
                # Keep this overflow so Django rejects too many rows.
                overflowed_index = True
                continue
            row_inputs.append((index, row_name, values_for(key)))

        if management_keys:
            # Trust submitted row numbers when control fields are present.
            for _, row_name, values in row_inputs:
                normalized.setlist(row_name, values)
            return normalized

        if not row_inputs and not overflowed_index:
            return normalized

        # Renumber sparse rows so plain mappings bind like form input.
        row_indexes = sorted({index for index, _, _ in row_inputs})
        remapped_indexes = {
            original_index: min(original_index, dense_index + 1)
            for dense_index, original_index in enumerate(row_indexes)
        }
        for original_index, row_name, values in row_inputs:
            suffix = row_name.removeprefix(f"{name}-{original_index}")
            normalized.setlist(
                f"{name}-{remapped_indexes[original_index]}{suffix}",
                values,
            )

        total_forms = max(remapped_indexes.values(), default=-1) + 1
        if overflowed_index:
            # Keep one extra row count so Django raises too_many_forms.
            total_forms = self.absolute_max + 1
        normalized[f"{name}-{TOTAL_FORM_COUNT}"] = str(total_forms)
        normalized[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
        return normalized

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, Any] | None,
        *,
        management_data: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Build rows and use bound management data when it is available."""
        context = super().get_context(name, value, attrs)
        context["widget"]["template_name"] = (
            f"nestingdolls/sequence/{FormLayout.current().value}.html"
        )
        child_widget = self.child_field.widget
        if self.is_localized:
            child_widget.is_localized = True

        value = [] if value is None else list(islice(value, self.absolute_max))
        if management_data is not None and any(
            key in management_data for key in self.management_names(name)
        ):
            management_form = ManagementForm(management_data, prefix=name)
            management_invalid = not management_form.is_valid()
            total_forms = cast(int, management_form.cleaned_data[TOTAL_FORM_COUNT])
            value = value[: max(0, min(total_forms, self.absolute_max))]
        else:
            initial_forms = len(value)
            if not value:
                value = [None] * min(
                    max(self.min_length, int(self.is_required)), self.max_length
                )
            management_form = ManagementForm(
                prefix=name,
                initial={
                    TOTAL_FORM_COUNT: len(value),
                    INITIAL_FORM_COUNT: initial_forms,
                    MIN_NUM_FORM_COUNT: self.min_length,
                    MAX_NUM_FORM_COUNT: self.max_length,
                },
            )
            management_invalid = False
        final_attrs = context["widget"]["attrs"]
        final_attrs.pop("aria-invalid", None)
        id_ = final_attrs.get("id")
        disabled = bool(final_attrs.get("disabled"))

        def make_row(index: int | str, item: object | None) -> dict[str, object]:
            row_name = f"{name}-{index}"
            child_attrs = final_attrs.copy()
            if id_:
                child_attrs["id"] = f"{id_}_{index}"
            if self.child_field.disabled:
                child_attrs["disabled"] = True
            if isinstance(child_widget, SequenceWidget):
                child_context = child_widget.get_context(
                    row_name,
                    cast(Sequence[object] | None, item),
                    child_attrs,
                    management_data=management_data,
                )
            else:
                child_context = child_widget.get_context(row_name, item, child_attrs)
            return {
                "index": index,
                "delete_name": f"{row_name}-{DELETION_FIELD_NAME}",
                "subwidget": child_context["widget"],
                "errors": [],
            }

        management_form.fields[TOTAL_FORM_COUNT].widget.attrs["data-sequence-total"] = (
            ""
        )
        if disabled:
            for management_field in management_form.fields.values():
                management_field.widget.attrs["disabled"] = True
        rows = [make_row(index, item) for index, item in enumerate(value)]

        context["widget"].update(
            {
                "rows": rows,
                "empty_row": make_row("__prefix__", None),
                "management_form": management_form,
                "minimum_forms": self.min_length,
                "maximum_forms": self.max_length,
                "absolute_maximum_forms": self.absolute_max,
                "disabled": disabled or management_invalid,
            }
        )
        return context

    @property
    def is_hidden(self) -> bool:
        """Expose whether the child widget is hidden."""
        return bool(self.child_field.widget.is_hidden)

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Expose whether the child widget needs multipart form data."""
        return bool(self.child_field.widget.needs_multipart_form)

    @property
    def media(self) -> WidgetMedia:
        """Return widget media including the sequence controller script."""
        media: WidgetMedia = super().media + WidgetMedia(self.Media)
        media += self.child_field.widget.media
        return media
