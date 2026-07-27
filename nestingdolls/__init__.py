from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Sequence, TYPE_CHECKING

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import Field
from django.forms.boundfield import BoundField
from django.forms.widgets import MultipleHiddenInput, Widget
from django.utils.translation import gettext_lazy as _, ngettext_lazy

if TYPE_CHECKING:
    from django.core.validators import _ValidatorCallable
    from django.db.models.fields import _ErrorMessagesMapping
    from django.utils.functional import _StrOrPromise

__all__ = [
    "SequenceField",
    "FrozenSequenceField",
    "ListField",
    "TupleField",
    "SetField",
]


class SequenceBoundField(BoundField):
    def build_widget_attrs(self, attrs, widget=None):
        attrs = super().build_widget_attrs(attrs, widget)
        widget = widget or self.field.widget
        if isinstance(widget, SequenceWidget) and self.field._item_errors:
            attrs["_item_errors"] = self.field._item_errors
        return attrs


class SequenceField(Field):
    default_error_messages: ClassVar[_ErrorMessagesMapping] = MappingProxyType(
        {
            "invalid": _("Enter a list of values."),
            "invalid_items": _("One or more values are invalid."),
            "min_num": ngettext_lazy(
                "Ensure this value has at least %(limit_value)d item (it has %(show_value)d).",
                "Ensure this value has at least %(limit_value)d items (it has %(show_value)d).",
                "limit_value",
            ),
            "max_num": ngettext_lazy(
                "Ensure this value has at most %(limit_value)d item (it has %(show_value)d).",
                "Ensure this value has at most %(limit_value)d items (it has %(show_value)d).",
                "limit_value",
            ),
            "unhashable": _("Set items must be hashable."),
        }
    )
    bound_field_class = SequenceBoundField
    hidden_widget = MultipleHiddenInput
    __slots__ = ("child_field", "min_num", "max_num", "_item_errors")

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_num: int | None = None,
        max_num: int = 1_000,
        required: bool | None = None,
        widget: Widget | type[Widget] | None = None,
        label: _StrOrPromise | None = None,
        initial: Any | None = None,
        help_text: _StrOrPromise = "",
        error_messages: _ErrorMessagesMapping | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[_ValidatorCallable] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[BoundField] = SequenceBoundField,
    ):
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        if min_num is None:
            min_num = 0 if required is False else 1
        if required is None:
            required = min_num > 0
        if (
            isinstance(min_num, bool)
            or isinstance(max_num, bool)
            or not isinstance(required, bool)
            or not isinstance(min_num, int)
            or not isinstance(max_num, int)
            or min_num < 0
            or max_num < min_num
        ):
            raise ValueError("min_num and max_num must be non-negative integers")
        if required != (min_num > 0):
            raise ValueError("required and min_num must agree")

        self.child_field = child_field
        self.min_num = min_num
        self.max_num = max_num
        self._reset_item_errors()
        if localize:
            self.child_field.localize = True
            self.child_field.widget.is_localized = True

        if widget is None:
            widget = SequenceWidget(
                child_field.widget,
                min_num=min_num,
                max_num=max_num,
            )
        elif isinstance(widget, SequenceWidget):
            widget.min_num = min_num
            widget.max_num = max_num
        else:
            child_widget = widget() if isinstance(widget, type) else widget
            child_widget.is_required = self.child_field.required
            if localize:
                child_widget.is_localized = True
            child_widget.attrs.update(self.child_field.widget_attrs(child_widget))
            widget = SequenceWidget(
                child_widget,
                min_num=min_num,
                max_num=max_num,
            )

        super().__init__(
            required=required,
            widget=widget,
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
            bound_field_class=bound_field_class,
        )

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.child_field = self.child_field.__deepcopy__(memo)
        result._reset_item_errors()
        return result

    def _reset_item_errors(self):
        self._item_errors: dict[int, ValidationError] = {}

    def to_python(self, value: object) -> list[object]:
        if isinstance(value, Mapping):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
            if value in self.empty_values:
                return []
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return list(value)

    def validate(self, value):
        super().validate(value)
        length = len(value)
        if length < self.min_num:
            raise ValidationError(
                self.error_messages["min_num"],
                code="min_num",
                params={"limit_value": self.min_num, "show_value": length},
            )
        if length > self.max_num:
            raise ValidationError(
                self.error_messages["max_num"],
                code="max_num",
                params={"limit_value": self.max_num, "show_value": length},
            )

    def clean(self, value):
        self._reset_item_errors()
        value = self.to_python(value)
        self.validate(value)

        cleaned_data = []
        for index, item in enumerate(value):
            try:
                cleaned_data.append(self.child_field.clean(item))
            except ValidationError as error:
                self._item_errors[index] = error

        if self._item_errors:
            raise ValidationError(
                self.error_messages["invalid_items"],
                code="invalid_items",
            )

        result = self.compress(cleaned_data)
        self.run_validators(result)
        return result

    def compress(self, data_list: list[object]) -> list[object]:
        return data_list

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            initial = self.compress(
                [self.child_field.to_python(item) for item in self.to_python(initial)]
            )
            data = self.compress(
                [self.child_field.to_python(item) for item in self.to_python(data)]
            )
        except (TypeError, ValidationError):
            return True
        return initial != data


class ListField(SequenceField):
    pass


class TupleField(SequenceField):
    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        return tuple(data_list)


class FrozenSequenceField(TupleField):
    pass


class SetField(SequenceField):
    def compress(self, data_list: list[object]) -> set[object]:
        try:
            return set(data_list)
        except TypeError as error:
            raise ValidationError(
                self.error_messages["unhashable"],
                code="unhashable",
            ) from error


class SequenceWidget(Widget):
    template_name = "django/forms/widgets/sequence.html"
    use_fieldset = True

    def __init__(self, child_widget: Widget, *, min_num: int, max_num: int, attrs=None):
        self.child_widget = child_widget
        self.min_num = min_num
        self.max_num = max_num
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        source = data
        if self.child_widget.needs_multipart_form and files is not None and name in files:
            source = files

        getter = getattr(source, "getlist", source.get)
        if name in source:
            return getter(name)

        array_name = f"{name}[]"
        if array_name in source:
            return getter(array_name)

        values = []
        for key in source:
            if not key.startswith(f"{name}[") or not key.endswith("]"):
                continue
            try:
                index = int(key.removeprefix(f"{name}[").removesuffix("]"))
            except ValueError:
                continue
            values.append((index, source.get(key)))
        return [value for _, value in sorted(values)] if values else None

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if self.is_localized:
            self.child_widget.is_localized = True

        final_attrs = context["widget"]["attrs"]
        item_errors = final_attrs.pop("_item_errors", {})
        final_attrs.pop("aria-invalid", None)
        final_attrs.pop("required", None)

        if value is None or value == "":
            values = [None] * self.min_num
        elif isinstance(value, (str, bytes)):
            values = [value]
        else:
            try:
                values = list(value)
            except TypeError:
                values = [value]
            if not values:
                values = [None] * self.min_num

        id_ = final_attrs.get("id")
        subwidgets = []
        for index, item in enumerate(values):
            widget_attrs = final_attrs.copy()
            if id_:
                widget_attrs["id"] = f"{id_}_{index}"
            if (
                self.child_widget.is_required
                and self.child_widget.use_required_attribute(item)
            ):
                widget_attrs["required"] = True

            subwidget = self.child_widget.get_context(name, item, widget_attrs)[
                "widget"
            ]
            if error := item_errors.get(index):
                subwidget["attrs"]["aria-invalid"] = "true"
                subwidget["errors"] = error.messages
            subwidgets.append(subwidget)

        context["widget"]["subwidgets"] = subwidgets
        return context

    def id_for_label(self, id_):
        return ""

    @property
    def is_hidden(self):
        return self.child_widget.is_hidden

    @property
    def needs_multipart_form(self):
        return self.child_widget.needs_multipart_form

    @property
    def media(self):
        return self.child_widget.media

    def __deepcopy__(self, memo):
        obj = super().__deepcopy__(memo)
        obj.child_widget = self.child_widget.__deepcopy__(memo)
        return obj
