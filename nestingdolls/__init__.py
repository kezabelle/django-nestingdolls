from __future__ import annotations

import functools
import inspect
import logging
from functools import partial
from types import MappingProxyType
from typing import Protocol, Mapping, Any, Iterable, Sequence, cast

from django.forms.fields import MultiValueField
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.renderers import BaseRenderer
from django.forms.utils import ErrorList, pretty_name
from django.forms.widgets import Widget, MultiWidget
from django.http.request import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise

logger = logging.getLogger(__name__)

__all__ = [
    "DictField",
    "FrozenDictField",
    "SequenceField",
    "FrozenSequenceField",
    "FormField",  # Alias
    "FrozenFormField",  # Alias
    "ListField",  # Alias
    "TupleField",  # Alias
]


class DictFieldForm:
    prefix: str | None

    def add_prefix(self, name):
        if self.prefix:
            return f"{self.prefix}.{name}"
        return name


class DictBoundField(BoundField):
    """
    A field + data 🤷
    The BoundField is responsible for rendering the widget, via as_widget(...)
    which calls into DictWidget.render(...)
    """

    def __init__(self, form: BaseForm, field: DictField, field_name: str):
        label = pretty_name(field_name) if field.label is None else field.label
        super().__init__(form=form, field=field, name=field_name)
        nested_name = f"{form.prefix}.{field_name}" if form.prefix else field_name
        self.name = nested_name
        self.html_name = nested_name
        self.label = label

    def as_widget(self, widget=None, attrs=None, only_initial=False):
        widget = widget or self.field.widget
        widget.subform = cast(DictField, self.field).subform_instance
        return super().as_widget(widget=widget, attrs=attrs, only_initial=only_initial)


class DictWidget(Widget):
    """
    A widget is necessary because the BoundField is where data is fetched
    from during cleaning, and that ends up asking the Form for the data.
    🙄
    """

    template_name = "django/forms/widgets/dictwidget.html"
    use_fieldset = True
    subform: functools.partial[BaseForm]

    def get_context(self, name: str, value, attrs):
        if name.startswith("child2"):
            breakpoint()
        subform = self.subform(
            prefix=name,
            data=value if self.is_required or bool(value) else None,
            # Mark the whole subform as optional?
            empty_permitted=not self.is_required,
            use_required_attribute=self.is_required,
        )
        shortcut = self._nearest_renderable_form_shortcut()
        context = super().get_context(name, value, attrs)
        context.update(
            subform=subform,
            renderer=shortcut,
            use_fieldset=self.use_fieldset,
        )
        return context

    def _nearest_renderable_form_shortcut(
        self, shortcuts: set[str] = frozenset({"as_p", "as_table", "as_ul", "as_div"})
    ):
        """
        Django doesn't provide a hint of which renderer shortcut was used, so
        to correctly emulate the parent form's chosen layout (if any) we must scrape
        the parent frames 😭
        """
        frame = inspect.currentframe()
        try:
            while frame:
                if frame.f_code.co_name in shortcuts:
                    return frame.f_code.co_name
                frame = frame.f_back
        finally:
            del frame

    def value_from_datadict(
        self,
        data: QueryDict | MultiValueDict | Mapping[str, Any],
        files,
        name: str,
    ) -> dict[str, Any]:
        if isinstance(data, MultiValueDict):
            subdata = QueryDict(mutable=True)
            for k in data:
                if k.startswith(name):
                    subdata[k] = data[k]
            subdata._mutable = False
            return subdata
        elif isinstance(data, Mapping):
            return data.get(name, {})
        raise TypeError("Unexpected data type", type(data))


class DictField(Field):
    widget = DictWidget
    default_error_messages = MappingProxyType(
        {
            "required": _("This section is required."),
            "incomplete": _("This section is incomplete"),
        }
    )
    bound_field_class = DictBoundField
    subform: type[BaseForm] | BaseForm

    def __init__(
        self,
        subform: type[BaseForm] | BaseForm,
        *,
        required: bool = True,
        widget: DictWidget | type[DictWidget] | None = DictWidget,
        label: Promise | str | None = None,
        initial: Any = None,
        help_text: Promise | str | None = "",
        error_messages: Any = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Any] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: Promise | str | None = None,
        template_name: str | None = None,
    ):
        self.subform = subform
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
        )

    @functools.cached_property
    def subform_class(self) -> type[BaseForm]:
        """
        Returns the form class that this field is bound to.
        """
        if isinstance(self.subform, BaseForm):
            cls = self.subform.__class__
        # Received form=type[BaseForm] during __init__
        else:
            cls = self.subform
        return cast(
            type[BaseForm],
            type(
                f"DictFieldFormFor{cls.__name__}",
                (
                    DictFieldForm,
                    cls,
                ),
                {},
            ),
        )

    def get_bound_field(self, form, field_name):
        return self.bound_field_class(form, self, field_name)

    @functools.cached_property
    def subform_kwargs(self) -> MappingProxyType[str, Any]:
        """
        Returns the default kwargs passed to the form, if an instance was given instead of
        a class. Otherwise provides all "default" arguments explicitly
        """
        if isinstance(self.subform, BaseForm):
            sig = inspect.signature(self.subform.__init__)
            # Get the names + defaults for the subform's instantiation
            initkwargs = {
                param.name: param.default for k, param in sig.parameters.items()
            }
            initkwargs.pop("data", None)
            initkwargs.pop("files", None)
            # breakpoint()
            # initkwargs.update(prefix="child1.")
            # TODO:pass down from parent form?
            # Get the actual "values" used at the time of subform instantiation
            # Note: This assumes they're all bound to "the same" instance local attribute
            #       as their argument name, which isn't _necessarily_ true 😒
            return MappingProxyType(
                {
                    k: getattr(self.subform, k, default)
                    for k, default in initkwargs.items()
                }
            )
        return MappingProxyType({})

    @functools.cached_property
    def subform_instance(
        self,
        # data: MultiValueDict | Mapping[str, Any],
    ) -> functools.partial[BaseForm]:
        form_default_kwargs = self.subform_kwargs
        form_kwargs = {**form_default_kwargs}
        # breakpoint()
        return functools.partial(self.subform_class, **form_kwargs)

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        # Delete any cached values, so that every form instantiation creates a new
        # subform instance.
        result.__dict__.pop("subform_kwargs", None)
        result.__dict__.pop("subform_class", None)
        result.__dict__.pop("subform_instance", None)
        return result

    # To get data out of this field requires going through the following call chain,
    # which is ... kind of confusing 😮‍💨 but here we are:
    # -> Form.is_valid
    # -> Form.errors
    # -> Form.full_clean
    # -> Form._clean_fields
    # -> DictField._clean_bound_field
    #    -> BoundField.data
    #    -> Form._widget_data_value
    #    -> Widget.value_from_datadict
    # -> DictField.clean
    #    -> DictField.to_python
    #    -> DictField.validate
    #    -> DictField.run_validators

    def _clean_bound_field(self, bf):
        """
        Short circuit here so that we know the parent "name" this subform is bound to.
        This means additional cleaning won't run...
        """
        value = bf.initial if self.disabled else bf.data
        # TODO(now): bf.name isn't the complete prefix...
        subform = self.subform_instance(prefix=bf.name, data=value)
        valid = subform.is_valid()
        cleaned = subform.cleaned_data if valid else {}
        if self.required and cleaned in self.empty_values:
            raise ValidationError(self.error_messages["required"], code="required")
        elif not self.required and not valid:
            raise ValidationError(self.error_messages["incomplete"], code="incomplete")
        return self.clean(cleaned)

    def clean(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return value


class FrozenDictField(DictField): ...


class SequenceField(Field): ...


class FrozenSequenceField(SequenceField): ...


ListField = SequenceField
TupleField = FrozenSequenceField
FormField = DictField
FrozenFormField = FrozenDictField
