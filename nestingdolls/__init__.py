from __future__ import annotations

import functools
import inspect
import logging
from functools import partial
from statistics import median
import string
from types import MappingProxyType
from typing import (
    Protocol,
    Mapping,
    Any,
    Iterable,
    Sequence,
    cast,
    NewType,
    TYPE_CHECKING,
    ClassVar,
)

from django.forms.fields import MultiValueField
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.renderers import BaseRenderer
from django.forms.utils import ErrorList, pretty_name
from django.forms.widgets import Widget, MultiWidget, Media
from django.http.request import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise

if TYPE_CHECKING:
    from django.utils.functional import _StrOrPromise
    from django.core.validators import _ValidatorCallable
    from django.db.models.fields import _ErrorMessagesMapping

logger = logging.getLogger(__name__)

__all__ = [
    "SequenceField",
    "FrozenSequenceField",
    "FormField",  # Alias
    "FrozenFormField",  # Alias
    "ListField",  # Alias
    "TupleField",  # Alias
]


NestedPrefix = NewType("NestedPrefix", str)


class SequenceBoundField(BoundField):
    __slots__ = ()

    def __repr__(self):
        return f"<{self.__class__.__qualname__} name={self.name!r}, label={self.label!r}, field={self.field!r}>"

    def build_widget_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_widget_attrs(base_attrs, extra_attrs)
        # Get item errors from field dynamically (set during validation)
        item_errors = getattr(self.field, "_item_errors", {})
        # Pass item errors, error_class, and renderer through attrs (will be extracted in get_context)
        if item_errors and isinstance(self.field.widget, SequenceWidget):
            attrs["_item_errors"] = item_errors
            # Pass the form's error_class so we can use it for ErrorList
            attrs["_error_class"] = getattr(self.form, "error_class", ErrorList)
            attrs["_renderer"] = getattr(self.form, "renderer", None)
        return attrs


class SequenceField(Field):
    default_error_messages: ClassVar[_ErrorMessagesMapping] = MappingProxyType(
        {
            "invalid": _("Invalid values provided."),
        }
    )
    bound_field_class = SequenceBoundField
    __slots__ = ("child_field", "min_num", "max_num", "_item_errors")

    _item_errors: Mapping[int, ValidationError]

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_num: int = 1,
        max_num: int = 1_000,
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
                "child_field argument for ListField must be a forms.Field instance"
            )
        self.child_field = child_field
        self.require_all_fields = False
        if widget is None:
            widget = SequenceWidget(child_widget=self.child_field.widget)
        self.min_num = widget.min_num = min_num
        self.max_num = widget.max_num = max_num
        super().__init__(
            required=False,
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

    def __repr__(self):
        return f"<{self.__class__.__qualname__} of {self.child_field.__class__.__qualname__}, min_num={self.min_num!r}, max_num={self.max_num!r}, required={self.required!r}, disabled={self.disabled!r}>"

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.child_field = self.child_field.__deepcopy__(memo)
        result.min_num = self.min_num
        result.max_num = self.max_num
        return result

    def _reset_index_errors(self):
        self._item_errors = {}

    def to_python(self, value: Iterable[_StrOrPromise]) -> list[object]:
        if value in self.empty_values:
            return []
        cleaned = []
        cleaner = self.child_field.clean
        if not value:
            value = (None,) * self.min_num
        # Track item-level errors by index
        self._reset_index_errors()
        for index, v in enumerate(value[: self.max_num]):
            try:
                cleaned.append(cleaner(v))
            except ValidationError as e:
                # Store the error for this specific item index
                self._item_errors[index] = e
                # Add None as placeholder for failed item
                cleaned.append(None)
        return cleaned

    def clean(self, value):
        self._reset_index_errors()
        # to_python() is called by super().clean() and will set _item_errors if needed
        result = super().clean(value)
        # If we have item errors after cleaning, raise ValidationError
        # but keep item errors separate for widget rendering
        if self._item_errors:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return result


class FrozenSequenceField(SequenceField):
    def to_python(self, value) -> tuple[object, ...]:
        return tuple(super().to_python(value))


class SequenceWidget(Widget):
    template_name = "django/forms/widgets/sequence.html"
    use_fieldset = True

    min_num: int
    max_num: int

    __slots__ = ()

    def __init__(self, child_widget, attrs=None):
        self.child_widget = child_widget
        super().__init__(attrs)

    def __repr__(self):
        return f"<{self.__class__.__qualname__} of {self.child_widget.__class__.__qualname__}>"

    def value_from_datadict(
        self, data: MultiValueDict[str, object] | Mapping[str, object], files, name
    ):
        # TODO(later): Does this all make sense for a series of checkboxes etc?
        getter = data.get
        if isinstance(data, MultiValueDict):
            getter = data.getlist
        if name in data:
            return getter(name)
        # Get PHP style array inputs.
        arrayish = f"{name}[]"
        if arrayish in data:
            return getter(arrayish)
        values: list[tuple[int, object]] = []
        for k in data:
            # Get PHP style array inputs, where the value between the brackets is only digits.
            # Ignore the index if it's not a valid integer.
            # Stores the index for sorting later, but the *value* of the index won't be the position
            # i.e.  given 0, 2, 4, 6 as indexes, you'd still only get 4 associated back, but in that order
            #       even if submitted as 6, 0, 4, 2. But there won't be holes, such that index 1 is None.
            if k.startswith(f"{name}[") and k.endswith("]"):
                index = k.removesuffix("]").removeprefix(f"{name}[")
                try:
                    index = int(index)
                except ValueError:
                    continue
                values.append((index, getter(k)))
        if values:
            # Take and sort the [0], [2] style array inputs, and then discard those to only give back the values.
            return [x[1] for x in sorted(values, key=itemgetter(0))]
        return None

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        # Remove aria-invalid applied by BoundField
        attrs.pop("aria-invalid", None)
        attrs.pop("aria-describedby", None)
        return attrs

    def subwidgets(self, name, value, attrs=None):
        value = value or []
        for item in value:
            yield self.child_widget.get_context(
                name=name,
                value=item,
                attrs=attrs,
            )["widget"]

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        final_attrs = context["widget"]["attrs"]
        # This is donkeyish and terrible, but I can't think of a better way tbh... (passed from BoundField)
        item_errors = final_attrs.pop("_item_errors", {})
        error_class = final_attrs.pop("_error_class", ErrorList)
        renderer = final_attrs.pop("_renderer", None)
        # Remove from final_attrs so they don't appear in HTML
        id_ = final_attrs.get("id")
        context["widget"]["min_num"] = self.min_num
        context["widget"]["max_num"] = self.max_num
        context["widget"]["subwidgets"] = subwidgets = []
        index = 0
        if not value:
            value = (None,) * self.min_num
        for index, item in enumerate(value[: self.max_num]):
            widget = self.child_widget
            if id_:
                widget_attrs = final_attrs.copy()
                widget_attrs["id"] = "%s_%s" % (id_, index)
            else:
                widget_attrs = final_attrs

            # Attach error to this subwidget if it exists
            widget_context: Mapping[str, object] = widget.get_context(
                name=name,
                value=item,
                attrs=widget_attrs,
            )["widget"]

            if index in item_errors:
                # Convert ValidationError to ErrorList format for widget
                error = item_errors[index]
                # error is always a ValidationError (from to_python)
                # ValidationError.error_list is a list, convert to form's error_class with renderer
                widget_context["errors"] = error_class(
                    error.error_list, renderer=renderer
                )
                # Add aria-invalid attribute
                widget_context["attrs"]["aria-invalid"] = "true"

            subwidgets.append(widget_context)

        empty_attrs = final_attrs.copy()
        empty_attrs.pop("id", None)
        context["widget"]["emptywidget"] = self.child_widget.get_context(
            name=name,
            value=None,
            attrs=empty_attrs,
        )["widget"]
        return context

    def use_required_attribute(self, initial):
        return False

    @property
    def is_hidden(self):
        return self.child_widget.is_hidden

    @property
    def needs_multipart_form(self):
        return self.child_widget.needs_multipart_form

    @property
    def media(self):
        return self.child_widget.media + Media(
            js=[],
        )

    def __deepcopy__(self, memo):
        obj = super().__deepcopy__(memo)
        obj.child_widget = self.child_widget.__deepcopy__(memo)
        return obj


class FrozenSequenceField(SequenceField): ...


ListField = SequenceField
TupleField = FrozenSequenceField
