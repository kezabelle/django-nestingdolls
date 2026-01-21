from __future__ import annotations

import functools
import inspect
import logging
from functools import partial
from statistics import median
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
from django.forms.widgets import Widget, MultiWidget
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
    def __init__(self, form, field, name):
        super().__init__(form, field, name)
        # Get item-level errors from the field and store on widget
        item_errors = getattr(field, '_item_errors', {})
        if isinstance(self.field.widget, SequenceWidget):
            self.field.widget._item_errors = item_errors
    
    @property
    def errors(self):
        # Only show field-level errors (like "invalid")
        # Item-level errors are passed to individual widgets
        errors = super().errors
        # Filter out any errors that are actually item-level errors
        # The field should only show "invalid" type errors
        return errors


class SequenceField(Field):
    default_error_messages: ClassVar[_ErrorMessagesMapping] = MappingProxyType(
        {
            "invalid": _("Enter a list of values."),
        }
    )
    bound_field_class = SequenceBoundField
    __slots__ = ()

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_num: int = 0,
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
        widget.min_num = min_num
        widget.max_num = max_num
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

    def to_python(self, value) -> list[object]:
        if value in self.empty_values:
            return ()
        cleaned = []
        cleaner = self.child_field.clean
        # Track item-level errors by index
        self._item_errors = {}
        for index, v in enumerate(value):
            try:
                cleaned.append(cleaner(v))
            except ValidationError as e:
                # Store the error for this specific item index
                self._item_errors[index] = e
                # Add None as placeholder for failed item
                cleaned.append(None)
        return cleaned
    
    def clean(self, value):
        # Reset item errors before validation
        self._item_errors = {}
        try:
            result = super().clean(value)
            # If we have item errors after cleaning, raise ValidationError
            # but keep item errors separate for widget rendering
            if self._item_errors:
                # Field is invalid due to item errors, but we keep them separate
                raise ValidationError(self.error_messages["invalid"], code="invalid")
            return result
        except ValidationError as e:
            # If it's not an item error case, re-raise as-is
            if not self._item_errors:
                raise
            # If we have item errors, the field is invalid
            # but item errors are stored separately
            raise ValidationError(self.error_messages["invalid"], code="invalid")


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

    def value_from_datadict(self, data, files, name):
        return data.getlist(name)

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
        id_ = final_attrs.get("id")
        context["widget"]["min_num"] = self.min_num
        context["widget"]["max_num"] = self.max_num
        context["widget"]["subwidgets"] = subwidgets = []
        # Get item errors if they exist
        item_errors = getattr(self, '_item_errors', {})
        index = 0
        for index, item in enumerate(value[: self.max_num]):
            widget = self.child_widget
            if id_:
                widget_attrs = final_attrs.copy()
                widget_attrs["id"] = "%s_%s" % (id_, index)
            else:
                widget_attrs = final_attrs
            
            # Attach error to this subwidget if it exists
            widget_context = widget.get_context(
                name=name,
                value=item,
                attrs=widget_attrs,
            )
            if index in item_errors:
                # Convert ValidationError to ErrorList format for widget
                error = item_errors[index]
                if isinstance(error, ValidationError):
                    widget_context["widget"]["errors"] = error.error_list if hasattr(error, 'error_list') else ErrorList([error])
                else:
                    widget_context["widget"]["errors"] = ErrorList([error])
                # Add aria-invalid attribute
                widget_context["widget"]["attrs"]["aria-invalid"] = "true"
            
            subwidgets.append(widget_context["widget"])

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
        return self.child_widget.media

    def __deepcopy__(self, memo):
        obj = super().__deepcopy__(memo)
        obj.child_widget = self.child_widget.__deepcopy__(memo)
        return obj


class FrozenSequenceField(SequenceField): ...


ListField = SequenceField
TupleField = FrozenSequenceField
