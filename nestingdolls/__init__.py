from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import Field
from django.forms.boundfield import BoundField
from django.forms.fields import FileField
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
from django.forms.widgets import Media, MultipleHiddenInput, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _, ngettext_lazy

__all__ = [
    "SequenceField",
    "FrozenSequenceField",
    "ListField",
    "TupleField",
    "SetField",
    "FrozenSetField",
    "SequenceWidget",
    "SequenceBoundField",
]


class SequenceBoundField(BoundField):
    """Render indexed child errors without storing validation state on the field.

    Django passes a widget no errors when it renders a ``BoundField``. A sequence
    has one field-level error list but several visible child widgets, so this
    real ``BoundField`` subclass is the small, public adapter that places a
    child error beside the row identified by its validation index.
    """

    def as_widget(self, widget=None, attrs=None, only_initial=False):
        widget = widget or self.field.widget
        if only_initial or not isinstance(widget, SequenceWidget):
            return super().as_widget(widget, attrs, only_initial)

        if self.field.localize:
            widget.is_localized = True
        attrs = self.build_widget_attrs(attrs or {}, widget)
        if self.auto_id and "id" not in widget.attrs:
            attrs.setdefault("id", self.auto_id)

        context = widget.get_context(self.html_name, self.value(), attrs)
        deleted_indexes = self._deleted_indexes()
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
        item_errors: dict[int, list[str]] = defaultdict(list)
        for error in self.errors.as_data():
            params = error.params or {}
            if error.code == "item_invalid" and "index" in params:
                item_errors[params["index"]].extend(error.messages)
        for row in context["widget"]["rows"]:
            row["errors"] = item_errors[row["index"]]
            if row["errors"]:
                row["subwidget"]["attrs"]["aria-invalid"] = "true"
        return widget._render(widget.template_name, context, self.form.renderer)

    @cached_property
    def _normalized_data(self):
        return self.field.widget.normalize_data(self.form.data, self.html_name)

    @cached_property
    def _normalized_files(self):
        if not self.form.files:
            return MultiValueDict()
        return self.field.widget.normalize_data(self.form.files, self.html_name)

    @cached_property
    def data(self):
        return self.field.widget._value_from_normalized_data(
            self._normalized_data,
            self._normalized_files,
            self.html_name,
        )

    @cached_property
    def initial(self):
        if self.name in self.form.initial:
            value = self.form.get_initial_for_field(self.field, self.name)
            return self._normalized_initial(value)

        if self.form.initial:
            normalized_initial = self.field.widget.normalize_data(
                self.form.initial, self.name
            )
            if normalized_initial:
                return self.field.widget._value_from_normalized_data(
                    normalized_initial,
                    MultiValueDict(),
                    self.name,
                )
        return self._normalized_initial(
            self.form.get_initial_for_field(self.field, self.name)
        )

    def _normalized_initial(self, value):
        if not isinstance(value, Mapping):
            return value
        normalized_initial = self.field.widget.normalize_data(value, self.name)
        if not normalized_initial:
            return value
        return self.field.widget._value_from_normalized_data(
            normalized_initial,
            MultiValueDict(),
            self.name,
        )

    def _deleted_indexes(self) -> set[int]:
        """Return submitted deleted rows, as ``BaseFormSet.deleted_forms`` does."""
        if not isinstance(self.field.widget, SequenceWidget):
            return set()
        return {
            index
            for index in range(len(self.data))
            if self._normalized_data.get(
                f"{self.html_name}-{index}-{DELETION_FIELD_NAME}"
            )
            == "1"
        }

    def _has_changed(self):
        if not isinstance(self.field.widget, SequenceWidget):
            return super()._has_changed()
        if self.field.disabled:
            return False
        initial_values = self.field._initial_values(self.initial)
        if any(index < len(initial_values) for index in self._deleted_indexes()):
            return True
        return super()._has_changed()


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
        validators: Sequence[Callable] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[BoundField] | None = None,
    ):
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
        if initial is not None and not callable(initial) and not isinstance(initial, Mapping):
            initial_values = self._initial_values(initial)
            if len(initial_values) > max_length:
                raise ValueError("initial must not contain more than max_length values")

        self.child_field = copy.deepcopy(child_field)
        self.min_length = min_length
        self.max_length = max_length
        self.absolute_max = max_length + DEFAULT_MAX_NUM
        if localize:
            self.child_field.localize = True
            self.child_field.widget.is_localized = True

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
            label=label,
            initial=initial,
            help_text=help_text,
            error_messages=error_messages,
            show_hidden_initial=show_hidden_initial,
            validators=validators,
            localize=localize,
            disabled=disabled,
            label_suffix=label_suffix,
            template_name=template_name,
            bound_field_class=selected_bound_field_class,
        )

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def _initial_values(value: object) -> list[object]:
        if value is None or value == "":
            return []
        if isinstance(value, (list, tuple, set, frozenset)):
            return list(value)
        raise ValueError("initial must be a collection of values")

    def to_python(self, value: object) -> list[object]:
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
    ) -> object:
        """Clean rows with FileField's public clean(value, initial) API."""
        cleaned_data = []
        errors = []
        for index, value in enumerate(values):
            if index in deleted_indexes:
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
                for message in error.messages:
                    errors.append(
                        ValidationError(
                            _("Item %(index)d: %(message)s"),
                            code="item_invalid",
                            params={
                                "index": index,
                                "message": message,
                                "child_code": error.code,
                            },
                        )
                    )
            else:
                cleaned_data.append(cleaned)
        if errors:
            raise ValidationError(errors)

        result = self.compress(cleaned_data)
        self.validate(result)
        if result:
            self.run_validators(result)
        return result

    def clean(self, value):
        return self._clean_values(self.to_python(value), [])

    def _clean_bound_field(self, bound_field):
        """Validate Django's management form and retain FileField initial values.

        ``ManagementForm`` owns management-input validation. ``FileField.clean()``
        is deliberately called with ``(data, initial)``; that public API
        implements Django's upload, clear, and contradiction semantics. Ordinary
        child fields continue to use their normal one-value ``clean()`` API.
        """
        initial_values = self._initial_values(bound_field.initial)
        if self.disabled:
            return self._clean_values(initial_values, initial_values)

        if bound_field._normalized_data:
            management_form = ManagementForm(
                bound_field._normalized_data,
                prefix=bound_field.html_name,
            )
            if not management_form.is_valid():
                raise ValidationError(
                    self.error_messages["missing_management_form"],
                    code="missing_management_form",
                    params={
                        "field_names": ", ".join(
                            management_form.add_prefix(field_name)
                            for field_name in management_form.errors
                        )
                    },
                )
            total_forms = management_form.cleaned_data[TOTAL_FORM_COUNT]
        else:
            total_forms = 0
        if total_forms > self.absolute_max:
            raise ValidationError(
                self.error_messages["too_many_forms"],
                code="too_many_forms",
                params={"num": self.max_length},
            )

        values = self.to_python(bound_field.data)
        deleted_indexes = frozenset(
            index
            for index in range(len(values))
            if bound_field._normalized_data.get(
                f"{bound_field.html_name}-{index}-{DELETION_FIELD_NAME}"
            )
            == "1"
        )
        return self._clean_values(values, initial_values, deleted_indexes)

    def validate(self, value):
        length = len(value)
        if not length:
            if self.required:
                raise ValidationError(self.error_messages["required"], code="required")
            return
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

    def compress(self, data_list: list[object]) -> list[object]:
        return data_list

    def bound_data(self, data, initial):
        if self.disabled:
            return initial
        initial_values = self._initial_values(initial)
        return [
            self.child_field.bound_data(
                value, initial_values[index] if index < len(initial_values) else None
            )
            for index, value in enumerate(self.to_python(data))
        ]

    def prepare_value(self, value):
        return [
            self.child_field.prepare_value(value)
            for value in self._initial_values(value)
        ]

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            initial_values = self._initial_values(initial)
            data_values = self.to_python(data)
        except (ValidationError, ValueError):
            return True
        for index, initial_value in enumerate(initial_values):
            if index >= len(data_values):
                return True
            try:
                initial_value = self.child_field.to_python(initial_value)
            except ValidationError:
                return True
            if self.child_field.has_changed(initial_value, data_values[index]):
                return True
        return any(
            self.child_field.has_changed(None, value)
            for value in data_values[len(initial_values) :]
        )


class ListField(SequenceField):
    pass


class TupleField(SequenceField):
    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        return tuple(data_list)


FrozenSequenceField = TupleField


class SetField(SequenceField):
    default_error_messages = {
        "unhashable": _("Set items must be hashable."),
    }

    collection_type = set

    def compress(self, data_list: list[object]) -> set[object] | frozenset[object]:
        try:
            return self.collection_type(data_list)
        except TypeError as error:
            raise ValidationError(
                self.error_messages["unhashable"], code="unhashable"
            ) from error

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            initial_values = self._initial_values(initial)
            data_values = self.to_python(data)
        except (ValidationError, ValueError):
            return True

        def unique(values):
            result = []
            for value in values:
                if not any(
                    not self.child_field.has_changed(
                        self.child_field.to_python(existing), value
                    )
                    for existing in result
                ):
                    result.append(value)
            return result

        try:
            unmatched = unique(data_values)
            for initial_value in unique(initial_values):
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
    collection_type = frozenset


SequenceField = ListField


class SequenceWidget(Widget):
    """Render dynamic homogeneous rows while delegating each row to one widget."""

    template_name = "django/forms/widgets/sequence.html"
    use_fieldset = True

    def __init__(
        self,
        child_field: Field,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        attrs=None,
    ):
        self.child_field = child_field
        self.min_length = min_length
        self.max_length = max_length
        self.absolute_max = (
            max_length + DEFAULT_MAX_NUM if absolute_max is None else absolute_max
        )
        super().__init__(attrs)

    def use_required_attribute(self, initial):
        return False

    def value_from_datadict(self, data, files, name):
        normalized_data = self.normalize_data(data, name)
        normalized_files = self.normalize_data(files, name) if files else files
        return self._value_from_normalized_data(normalized_data, normalized_files, name)

    def _value_from_normalized_data(self, data, files, name):
        if name in data:
            return data.get(name)
        management_name = f"{name}-{TOTAL_FORM_COUNT}"
        try:
            total_forms = int(data.get(management_name, 0))
        except (TypeError, ValueError):
            return []
        if total_forms < 0 or total_forms > self.absolute_max:
            return []

        values = []
        for index in range(total_forms):
            row_name = f"{name}-{index}"
            values.append(self.child_field.widget.value_from_datadict(data, files, row_name))
        return values

    def value_omitted_from_data(self, data, files, name):
        return not self.normalize_data(data, name)

    def normalize_data(self, data, name) -> MultiValueDict:
        """Convert every accepted sequence spelling into canonical widget data."""
        normalized = MultiValueDict()
        management_names = {
            f"{name}-{TOTAL_FORM_COUNT}",
            f"{name}-{INITIAL_FORM_COUNT}",
            f"{name}-{MIN_NUM_FORM_COUNT}",
            f"{name}-{MAX_NUM_FORM_COUNT}",
        }
        has_management_data = False
        direct_value = None
        for key in data:
            if key == name:
                direct_value = self._value_list(data, key)
                normalized.setlist(name, [direct_value])
            elif key in management_names:
                has_management_data = True
                normalized.setlist(key, self._values(data, key))
            else:
                canonical_key = self._canonical_row_key(key, name)
                if canonical_key is not None:
                    normalized.setlist(canonical_key, self._values(data, key))
        if normalized and not has_management_data:
            total_forms = (
                len(direct_value)
                if isinstance(direct_value, list)
                else self._indexed_row_count(normalized, name)
            )
            normalized.setlist(f"{name}-{TOTAL_FORM_COUNT}", [str(total_forms)])
            normalized.setlist(f"{name}-{INITIAL_FORM_COUNT}", ["0"])
        return normalized

    def _indexed_row_count(self, data, name) -> int:
        prefix = f"{name}-"
        largest_index = -1
        for key in data:
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            suffix = key.removeprefix(prefix)
            index_end = 0
            while index_end < len(suffix) and suffix[index_end].isdigit():
                index_end += 1
            if not index_end or (
                index_end < len(suffix) and suffix[index_end] not in "_-"
            ):
                continue
            index = int(suffix[:index_end])
            if index >= self.absolute_max:
                return self.absolute_max + 1
            largest_index = max(largest_index, index)
        return largest_index + 1

    @staticmethod
    def _values(data, key):
        try:
            return data.getlist(key)
        except AttributeError:
            value = data.get(key)
            return value if isinstance(value, list) else [value]

    @staticmethod
    def _value_list(data, key):
        try:
            value = data.getlist(key)
        except AttributeError:
            value = data.get(key)
        return list(value) if isinstance(value, (list, tuple)) else value

    @staticmethod
    def _canonical_row_key(key, name) -> str | None:
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
            index = suffix[:index_end]
            if separator == "[":
                if index_end == len(suffix) or suffix[index_end] != "]":
                    return None
                suffix = suffix[index_end + 1 :]
            else:
                suffix = suffix[index_end:]
                if suffix and suffix[0] not in "_-":
                    return None
            return f"{name}-{index}{suffix}"
        return None

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if self.is_localized:
            self.child_field.widget.is_localized = True

        values = [] if value is None else list(value)
        initial_forms = len(values)
        if not values:
            values = [None] * min(max(self.min_length, int(self.is_required)), self.max_length)
        final_attrs = context["widget"]["attrs"]
        final_attrs.pop("aria-invalid", None)
        id_ = final_attrs.get("id")

        def make_row(index, item):
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
        management_form.fields[TOTAL_FORM_COUNT].widget.attrs["data-sequence-total"] = ""
        if final_attrs.get("disabled"):
            for management_field in management_form.fields.values():
                management_field.widget.attrs["disabled"] = True

        context["widget"].update(
            {
                "rows": [
                    make_row(index, item) for index, item in enumerate(values)
                ],
                "empty_row": make_row("__prefix__", None),
                "management_form": management_form,
                "maximum_forms": self.max_length,
                "absolute_maximum_forms": self.absolute_max,
                "disabled": bool(final_attrs.get("disabled")),
            }
        )
        return context

    def id_for_label(self, id_):
        return ""

    @property
    def is_hidden(self):
        return self.child_field.widget.is_hidden

    @property
    def needs_multipart_form(self):
        return self.child_field.widget.needs_multipart_form

    @property
    def media(self):
        return Media(js=["nestingdolls/sequence.js"]) + self.child_field.widget.media
