from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, Self, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import Field
from django.forms.boundfield import BoundField
from django.forms.fields import BooleanField, FileField, MultiValueField
from django.forms.formsets import (
    BaseFormSet,
    DEFAULT_MAX_NUM,
    DEFAULT_MIN_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    ManagementForm,
    TOTAL_FORM_COUNT,
)
from django.forms.utils import ErrorList
from django.forms.widgets import Media as WidgetMedia, MultipleHiddenInput, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _, ngettext_lazy

__all__ = [
    "InvalidInitialValueError",
    "SequenceField",
    "FrozenSequenceField",
    "ListField",
    "TupleField",
    "SetField",
    "FrozenSetField",
    "SequenceWidget",
    "SequenceBoundField",
]


class InvalidInitialValueError(ValueError):
    """Raised when a sequence initial value is not collection-shaped."""


class SequenceBoundField(BoundField):
    """Render indexed child errors without storing validation state on the field.

    Django passes a widget no errors when it renders a ``BoundField``. A sequence
    has one field-level error list but several visible child widgets, so this
    real ``BoundField`` subclass is the small, public adapter that places a
    child error beside the row identified by its validation index.
    """

    @property
    def errors(self) -> ErrorList:
        """Return only field-level errors for Django's normal field rendering."""
        errors = super().errors
        if not errors:
            return errors
        field_errors = [error for error in errors.as_data() if error.code != "item_invalid"]
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
        attrs: dict[str, Any] | None = None,
        only_initial: bool = False,
    ) -> SafeString:
        """Delegate normal rendering to Django and only patch sequence rows when needed."""
        widget = widget or self.field.widget
        if only_initial or not isinstance(widget, SequenceWidget):
            return super().as_widget(widget, attrs, only_initial)
        item_errors: dict[int, list[object]] = defaultdict(list)
        for error in super().errors.as_data():
            params = error.params or {}
            if error.code == "item_invalid" and "index" in params:
                message = params.get("message")
                item_errors[cast(int, params["index"])].extend(
                    [message] if message is not None else error.messages
                )
        deleted_indexes = self._deleted_indexes
        if not deleted_indexes and not item_errors:
            return super().as_widget(widget, attrs, only_initial)

        if self.field.localize:
            widget.is_localized = True
        attrs = self.build_widget_attrs(dict(attrs or {}), widget)
        if self.auto_id and "id" not in widget.attrs:
            attrs.setdefault("id", self.auto_id)

        context = widget.get_context(self.html_name, self.value(), attrs)
        if deleted_indexes:
            context["widget"]["rows"] = [
                row
                for row in context["widget"]["rows"]
                if row["index"] not in deleted_indexes
            ]
            context["widget"]["deleted_rows"] = [
                {"delete_name": f"{self.html_name}-{index}-{DELETION_FIELD_NAME}"}
                for index in sorted(deleted_indexes)
            ]
        for row in context["widget"]["rows"]:
            row["errors"] = item_errors[row["index"]]
            if row["errors"]:
                row["subwidget"]["attrs"]["aria-invalid"] = "true"
        return cast(
            SafeString,
            cast(Any, widget)._render(widget.template_name, context, self.form.renderer),
        )

    @cached_property
    def _data_input(self) -> MultiValueDict[str, object]:
        """Cache normalized submitted form data for this field."""
        return cast(
            MultiValueDict[str, object],
            self.field.widget._normalize_mapping(self.form.data, self.html_name),
        )

    @cached_property
    def _file_input(self) -> MultiValueDict[str, object]:
        """Cache normalized submitted files for this field."""
        if not self.form.files:
            return MultiValueDict()
        return cast(
            MultiValueDict[str, object],
            self.field.widget._normalize_mapping(self.form.files, self.html_name),
        )

    @cached_property
    def _management_form(self) -> ManagementForm | None:
        """Build a management form from normalized sequence inputs."""
        management_data: MultiValueDict[str, object] = MultiValueDict()
        management_names = self.field.widget.management_names(self.html_name)
        data_input = self._data_input
        file_input = self._file_input
        normalized_source = (
            data_input
            if any(name in data_input for name in management_names)
            else file_input
        )
        for name in management_names:
            if name in normalized_source:
                management_data.setlist(name, normalized_source.getlist(name))
        if not management_data:
            return None
        management_form = ManagementForm(management_data, prefix=self.html_name)
        management_form.full_clean()
        return management_form

    @cached_property
    def data(self) -> list[object]:
        """Return the bound value extracted from normalized data and files."""
        return cast(
            list[object],
            self.field.widget._value_from_normalized_data(
                self._data_input,
                self._file_input,
                self.html_name,
            ),
        )

    @cached_property
    def initial(
        self,
    ) -> list[object] | tuple[object, ...] | set[object] | frozenset[object] | Mapping[str, object]:
        """Use Django's normal initial path unless flattened row keys need normalizing."""
        if self.form.initial and self.name not in self.form.initial:
            normalized_initial = self._normalize_initial_mapping(self.form.initial)
            if normalized_initial is not None:
                return normalized_initial
        return self._coerce_initial_value(super().initial)

    def _coerce_initial_value(
        self, value: object
    ) -> list[object] | tuple[object, ...] | set[object] | frozenset[object] | Mapping[str, object]:
        """Convert raw initial input into the sequence value shape."""
        if isinstance(value, Mapping):
            normalized_value = self._normalize_initial_mapping(value)
            if normalized_value is None:
                return cast(Mapping[str, object], value)
            return normalized_value
        try:
            return cast(SequenceField, self.field)._initial_values(value)
        except InvalidInitialValueError:
            return [value]

    def _normalize_initial_mapping(self, value: Mapping[str, object]) -> list[object] | None:
        """Return normalized initial rows for mapping-style values when possible."""
        value = self.field.widget._normalize_mapping(value, self.name)
        if not value:
            return None
        return cast(
            list[object],
            self.field.widget._value_from_normalized_data(
                value,
                MultiValueDict(),
                self.name,
            ),
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
        initial_count = len(cast(SequenceField, self.field)._initial_values(self.initial))
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
        changed = cast(bool, super()._has_changed())  # type: ignore[misc]
        if not isinstance(self.field.widget, SequenceWidget):
            return changed
        if changed or not self._deleted_indexes:
            return changed
        try:
            initial_length = len(cast(SequenceField, self.field)._initial_values(self.initial))
        except InvalidInitialValueError:
            return True
        return any(index < initial_length for index in self._deleted_indexes)


class SequenceField(Field):
    """Validate a variable-length collection with one homogeneous child field."""

    default_error_messages = {
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
    bound_field_class = SequenceBoundField
    hidden_widget = MultipleHiddenInput

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        required: bool = True,
        widget: SequenceWidget | type[SequenceWidget] | None = None,
        label: str | Promise | None = None,
        initial: Any | Callable[[], Any] | None = None,
        help_text: str | Promise = "",
        error_messages: Mapping[str, str | Promise] | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[BoundField] | None = None,
    ) -> None:
        """Configure a homogeneous variable-length field."""
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        if (
            isinstance(min_length, bool)
            or isinstance(max_length, bool)
            or not isinstance(min_length, int)
            or not isinstance(max_length, int)
            or min_length < 0
            or max_length < min_length
        ):
            raise ValueError("min_length and max_length must be non-negative integers")
        if not isinstance(required, bool):
            raise TypeError("required must be a bool")
        if (
            initial is not None
            and not callable(initial)
            and not isinstance(initial, Mapping)
        ):
            initial_values = self._initial_values(initial)
            if len(initial_values) > max_length:
                raise ValueError("initial must not contain more than max_length values")

        self.child_field = copy.deepcopy(child_field)
        self.min_length = min_length
        self.max_length = max_length
        self.absolute_max = max_length + DEFAULT_MAX_NUM
        self.child_field.localize = localize

        if widget is None:
            sequence_widget = SequenceWidget(
                self.child_field,
                min_length=min_length,
                max_length=max_length,
                absolute_max=self.absolute_max,
            )
        elif isinstance(widget, type):
            if not issubclass(widget, SequenceWidget):
                raise TypeError("widget must be a SequenceWidget instance or subclass")
            sequence_widget = widget(
                self.child_field,
                min_length=min_length,
                max_length=max_length,
                absolute_max=self.absolute_max,
            )
        elif isinstance(widget, SequenceWidget):
            sequence_widget = copy.deepcopy(widget)
            sequence_widget.child_field = self.child_field
            sequence_widget.min_length = min_length
            sequence_widget.max_length = max_length
            sequence_widget.absolute_max = self.absolute_max
        else:
            raise TypeError("widget must be a SequenceWidget instance or subclass")

        selected_bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(selected_bound_field_class, SequenceBoundField):
            raise TypeError("bound_field_class must inherit from SequenceBoundField")
        super().__init__(
            required=required,
            widget=sequence_widget,
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
            bound_field_class=selected_bound_field_class,
        )

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Copy the field and its child field together."""
        result = cast(Self, super().__deepcopy__(memo))  # type: ignore[misc]
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def _initial_values(value: object) -> list[object]:
        """Normalize supported initial collections into a list.

        post[]: isinstance(__return__, list)
        post[]: (value is None or value == "") implies __return__ == []
        post[]: isinstance(value, Collection) and not isinstance(value, Mapping) implies len(__return__) == len(value)
        raises: InvalidInitialValueError
        """
        if value is None or value == "":
            return []
        if (
            isinstance(value, Collection)
            and not isinstance(value, Mapping)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            return list(value)
        raise InvalidInitialValueError("initial must be a collection of values")

    def to_python(self, value: object) -> list[object]:
        """Require sequence input to already be list-shaped.

        post[]: isinstance(__return__, list)
        post[]: (value is None or value == "") implies __return__ == []
        post[]: isinstance(value, list) implies __return__ == value
        raises: ValidationError
        """
        if value is None or value == "":
            return []
        if not isinstance(value, list):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value

    def _clean_values(
        self,
        values: list[object],
        initial_values: list[object],
        deleted_indexes: frozenset[int] = frozenset(),
        omitted_indexes: frozenset[int] = frozenset(),
    ) -> list[object]:
        """Clean each submitted row and return the cleaned row list."""
        cleaned_data: list[object] = []
        errors = []
        for index, value in enumerate(values):
            if index in deleted_indexes or index in omitted_indexes:
                continue
            initial = initial_values[index] if index < len(initial_values) else None
            try:
                if self.child_field.disabled:
                    cleaned = initial
                elif isinstance(self.child_field, FileField):
                    cleaned = self.child_field.clean(value, initial)
                else:
                    cleaned = self.child_field.clean(value)
            except ValidationError as error:
                for item_error in error.error_list:
                    for message in item_error.messages:
                        errors.append(
                            ValidationError(
                                message,
                                code="item_invalid",
                                params={
                                    "index": index,
                                    "message": message,
                                    "child_code": item_error.code,
                                },
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
        sequence_bound_field = cast(SequenceBoundField, bound_field)
        if self.disabled:
            return cast(
                Collection[object],
                super()._clean_bound_field(sequence_bound_field),  # type: ignore[misc]
            )
        management_form = sequence_bound_field._management_form
        deleted_indexes = sequence_bound_field._deleted_indexes
        omitted_indexes = sequence_bound_field._omitted_indexes
        if (
            management_form is None
            and not deleted_indexes
            and not omitted_indexes
            and not isinstance(self.child_field, FileField)
        ):
            return cast(
                Collection[object],
                super()._clean_bound_field(sequence_bound_field),  # type: ignore[misc]
            )

        errors = []
        if management_form is not None and not management_form.is_valid():
            errors.append(
                ValidationError(
                    self.error_messages["missing_management_form"],
                    code="missing_management_form",
                    params={
                        "field_names": ", ".join(
                            management_form.add_prefix(field_name)
                            for field_name in management_form.errors
                        )
                    },
                )
            )
        elif management_form is not None:
            submitted_total = management_form.cleaned_data[TOTAL_FORM_COUNT]
            if isinstance(submitted_total, int) and submitted_total > self.absolute_max:
                errors.append(
                    ValidationError(
                        self.error_messages["too_many_forms"],
                        code="too_many_forms",
                        params={"num": self.max_length},
                    )
                )
        if errors:
            raise ValidationError(errors)

        result = self.compress(
            self._clean_values(
                self.to_python(sequence_bound_field.data),
                self._initial_values(sequence_bound_field.initial),
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
        """Return the cleaned list unchanged.

        post[]: isinstance(__return__, list)
        post[]: __return__ == data_list
        """
        return data_list

    def bound_data(self, data: object, initial: object) -> Collection[object]:
        """Bind each submitted row against its matching initial value.

        post[]: self.disabled implies __return__ == self._initial_values(initial)
        post[]: (not self.disabled) implies len(__return__) == len(self.to_python(data))
        """
        if self.disabled:
            return self._initial_values(initial)
        initial = self._initial_values(initial)
        return [
            self.child_field.bound_data(
                value, initial[index] if index < len(initial) else None
            )
            for index, value in enumerate(self.to_python(data))
        ]

    def prepare_value(self, value: object) -> list[object]:
        """Prepare each row for widget rendering.

        post[]: isinstance(__return__, list)
        post[]: len(__return__) == len(self._initial_values(value))
        """
        return [
            self.child_field.prepare_value(value)
            for value in self._initial_values(value)
        ]

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare submitted rows using child-field change semantics.

        post[]: isinstance(__return__, bool)
        """
        if not super().has_changed(initial, data):
            return False
        try:
            initial = self._initial_values(initial)
        except InvalidInitialValueError:
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True
        for index, initial_value in enumerate(initial):
            if index >= len(data):
                return True
            try:
                if self.child_field.has_changed(initial_value, data[index]):
                    return True
            except ValidationError:
                return True
        for value in data[len(initial) :]:
            try:
                if self.child_field.has_changed(None, value):
                    return True
            except ValidationError:
                return True
        return False


class ListField(SequenceField):
    """Collect cleaned rows into a mutable list."""
    pass


class TupleField(SequenceField):
    """Collect cleaned rows into an immutable tuple."""

    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        """Return cleaned rows as a tuple."""
        return tuple(data_list)


FrozenSequenceField = TupleField


class SetField(SequenceField):
    """Collect cleaned rows into a deduplicated set-like value."""

    default_error_messages = {
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

        This method deduplicates submitted and initial members using the child
        field's own ``has_changed()`` semantics, then matches those semantic
        members without caring about row order.
        """
        if not super().has_changed(initial, data):
            return False
        try:
            initial = self._initial_values(initial)
        except InvalidInitialValueError:
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True

        def comparison_data(value: object) -> object:
            if isinstance(self.child_field, MultiValueField):
                return self.child_field.widget.decompress(value)
            return self.child_field.prepare_value(value)

        def unique(values: list[object], same_value: Callable[[object, object], bool]) -> list[object]:
            result: list[object] = []
            for value in values:
                if not any(same_value(existing, value) for existing in result):
                    result.append(value)
            return result

        def submitted_equals(existing: object, value: object) -> bool:
            return not self.child_field.has_changed(
                self.child_field.to_python(existing), value
            )

        def initial_equals(existing: object, value: object) -> bool:
            return not self.child_field.has_changed(existing, comparison_data(value))

        try:
            unmatched = unique(data, submitted_equals)
            for initial_value in unique(initial, initial_equals):
                for index, data_value in enumerate(unmatched):
                    if not self.child_field.has_changed(initial_value, data_value):
                        unmatched.pop(index)
                        break
                else:
                    return True
        except (TypeError, ValidationError):
            return True
        return bool(unmatched)


class FrozenSetField(SetField):
    """Collect cleaned rows into a frozenset."""

    collection_type = frozenset


SequenceField = ListField  # type: ignore[misc]


class SequenceWidget(Widget):
    """Render dynamic homogeneous rows while delegating each row to one widget."""

    template_name = "django/forms/widgets/sequence.html"
    use_fieldset = True
    deletion_field = BooleanField(required=False)

    class Media:
        """Load the client-side row add/remove controller."""

        js = ["nestingdolls/sequence.js"]

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
        self.needs_multipart_form = bool(child_field.widget.needs_multipart_form)
        super().__init__(dict(attrs) if attrs is not None else None)

    def use_required_attribute(self, initial: Any) -> bool:
        """Disable HTML required handling for dynamic rows."""
        return False

    def value_from_datadict(self, data: Any, files: Any, name: str) -> list[object]:
        """Extract a sequence value from raw submitted inputs."""
        return self._value_from_normalized_data(
            self._normalize_mapping(data, name),
            self._normalize_mapping(files, name) if files else MultiValueDict(),
            name,
        )

    def _value_from_normalized_data(
        self,
        data: MultiValueDict[str, object],
        files: MultiValueDict[str, object],
        name: str,
    ) -> list[object]:
        """Extract row values from canonicalized data and files.

        post[]: isinstance(__return__, list)
        post[]: (name in data and isinstance(data.get(name), list)) implies __return__ == data.get(name)
        post[]: (name in files and isinstance(files.get(name), list) and name not in data) implies __return__ == files.get(name)
        """
        def direct_sequence_value(
            source: MultiValueDict[str, object],
        ) -> list[object] | None:
            if name not in source:
                return None
            value = source.get(name)
            return value if isinstance(value, list) else []

        def submitted_total_forms(source: MultiValueDict[str, object]) -> int | None:
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

        values: list[object] = []
        for index in range(form_count):
            row_name = f"{name}-{index}"
            values.append(
                self.child_field.widget.value_from_datadict(data, files, row_name)
            )
        return values

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Report whether the sequence is entirely absent from submission data."""
        return not (
            self._normalize_mapping(data, name) or self._normalize_mapping(files, name)
        )

    @staticmethod
    def management_names(name: str) -> tuple[str, str, str, str]:
        """Return the management keys for a sequence field name.

        post[]: len(__return__) == 4
        post[]: __return__[0] == f"{name}-{TOTAL_FORM_COUNT}"
        post[]: __return__[1] == f"{name}-{INITIAL_FORM_COUNT}"
        post[]: __return__[2] == f"{name}-{MIN_NUM_FORM_COUNT}"
        post[]: __return__[3] == f"{name}-{MAX_NUM_FORM_COUNT}"
        """
        return (
            f"{name}-{TOTAL_FORM_COUNT}",
            f"{name}-{INITIAL_FORM_COUNT}",
            f"{name}-{MIN_NUM_FORM_COUNT}",
            f"{name}-{MAX_NUM_FORM_COUNT}",
        )

    def _normalize_mapping(self, data: Any, name: str) -> MultiValueDict[str, object]:
        """Canonicalize accepted row spellings into Django-style keys.

        post[]: (not data) implies not __return__
        post[]: (data and name in data) implies name in __return__
        """
        normalized = MultiValueDict[str, object]()
        if not data:
            return normalized

        def values_for(key: str) -> list[object]:
            try:
                return cast(list[object], data.getlist(key))
            except AttributeError:
                value = data.get(key)
                return value if isinstance(value, list) else [value]

        def normalized_row_key(key: object) -> tuple[str, int] | None:
            if not isinstance(key, str):
                return None
            for separator in ("-", ".", "["):
                prefix = f"{name}{separator}"
                if not key.startswith(prefix):
                    continue
                suffix = key.removeprefix(prefix)
                index_end = 0
                while index_end < len(suffix) and suffix[index_end].isdigit():
                    index_end += 1
                if not index_end:
                    return None
                index = int(suffix[:index_end])
                if separator == "[":
                    if index_end == len(suffix) or suffix[index_end] != "]":
                        return None
                    suffix = suffix[index_end + 1 :]
                else:
                    suffix = suffix[index_end:]
                    if suffix and suffix[0] not in "_-":
                        return None
                return (f"{name}-{index}{suffix}", index)
            return None

        management_names = set(self.management_names(name))
        has_management_data = False
        direct_value: list[object] | None = None
        largest_index = -1

        for key in data:
            if key == name:
                direct_value = values_for(key)
                normalized.setlist(name, [direct_value])
                continue
            if key in management_names:
                has_management_data = True
                normalized.setlist(key, values_for(key))
                continue
            row_key = normalized_row_key(key)
            if row_key is None:
                continue
            row_name, index = row_key
            largest_index = max(largest_index, index)
            normalized.setlist(row_name, values_for(key))
        if normalized and not has_management_data:
            total_forms = (
                len(direct_value) if direct_value is not None else largest_index + 1
            )
            normalized.setlist(f"{name}-{TOTAL_FORM_COUNT}", [str(total_forms)])
            normalized.setlist(f"{name}-{INITIAL_FORM_COUNT}", ["0"])
        return normalized

    def get_context(
        self, name: str, value: Sequence[Any] | None, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build widget context for visible rows and the empty row template."""
        context = super().get_context(name, value, attrs)
        if self.is_localized:
            self.child_field.widget.is_localized = True

        values = [] if value is None else list(value)
        initial_forms = len(values)
        if not values:
            values = [None] * min(
                max(self.min_length, int(self.is_required)), self.max_length
            )
        final_attrs = context["widget"]["attrs"]
        final_attrs.pop("aria-invalid", None)
        id_ = final_attrs.get("id")

        def make_row(index: int | str, item: object | None) -> dict[str, object]:
            row_name = f"{name}-{index}"
            child_attrs = final_attrs.copy()
            if id_:
                child_attrs["id"] = f"{id_}_{index}"
            if self.child_field.disabled:
                child_attrs["disabled"] = True
            subwidget = self.child_field.widget.get_context(
                row_name, item, child_attrs
            )["widget"]
            return {
                "index": index,
                "delete_name": f"{row_name}-{DELETION_FIELD_NAME}",
                "subwidget": subwidget,
                "errors": [],
            }

        management_form = ManagementForm(
            prefix=name,
            initial={
                TOTAL_FORM_COUNT: len(values),
                INITIAL_FORM_COUNT: initial_forms,
                MIN_NUM_FORM_COUNT: self.min_length,
                MAX_NUM_FORM_COUNT: self.max_length,
            },
        )
        management_form.fields[TOTAL_FORM_COUNT].widget.attrs["data-sequence-total"] = (
            ""
        )
        if final_attrs.get("disabled"):
            for management_field in management_form.fields.values():
                management_field.widget.attrs["disabled"] = True

        context["widget"].update(
            {
                "rows": [make_row(index, item) for index, item in enumerate(values)],
                "empty_row": make_row("__prefix__", None),
                "management_form": management_form,
                "maximum_forms": self.max_length,
                "absolute_maximum_forms": self.absolute_max,
                "disabled": bool(final_attrs.get("disabled")),
            }
        )
        return context

    def id_for_label(self, id_: str) -> str:
        """Suppress label targeting for the composite sequence widget."""
        return ""

    @property
    def is_hidden(self) -> bool:
        """Expose whether the child widget is hidden."""
        return bool(self.child_field.widget.is_hidden)

    @property
    def media(self) -> WidgetMedia:
        """Return widget media including the sequence controller script."""
        media = super().media + WidgetMedia(self.Media)
        media += self.child_field.widget.media
        return media
