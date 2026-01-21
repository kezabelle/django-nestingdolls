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
    "DictField",
    "FrozenDictField",
    "SequenceField",
    "FrozenSequenceField",
    "FormField",  # Alias
    "FrozenFormField",  # Alias
    "ListField",  # Alias
    "TupleField",  # Alias
]


NestedPrefix = NewType("NestedPrefix", str)


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
        self.name = cast(NestedPrefix, nested_name)
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
    bound_field_class = DictBoundField
    default_error_messages = MappingProxyType(
        {
            "required": _("This section is required."),
            "incomplete": _("This section is incomplete"),
        }
    )
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

    def _clean_bound_field(self, bf: DictBoundField):
        """
        Short circuit here so that we know the parent "name" this subform is bound to.
        This means additional cleaning won't run...
        """
        value = bf.initial if self.disabled else bf.data
        return self.clean(value=value, name=cast(NestedPrefix, bf.name))

    def clean(self, value: Mapping[str, Any], name: NestedPrefix) -> Mapping[str, Any]:
        """
        value is either DictBoundField.data or initial
        """
        # TODO(now): bf.name isn't the complete prefix...
        subform = self.subform_instance(
            prefix=name,
            data=value,
            empty_permitted=not self.required,
            use_required_attribute=self.required,
        )
        del value, name
        # TODO(now): Do I want to do this, or do I want to use has_changed and to_python????
        for subform_bf in subform:
            subform_bf.field.required = False
        valid = subform.is_valid()
        # breakpoint()
        cleaned = self.to_python(subform.cleaned_data if valid else {})
        if self.required:
            if cleaned in self.empty_values:
                raise ValidationError(
                    self.error_messages["required"],
                    code="required",
                )
        else:
            if not valid:
                raise ValidationError(
                    self.error_messages["incomplete"],
                    code="incomplete",
                )
        self.validate(cleaned)
        self.run_validators(cleaned)
        return cleaned

    # def has_changed(self, initial, data):
    #     """This is used by empty_permitted"""
    #     breakpoint()
    #     return super().has_changed(initial, data)
    #
    # #
    def to_python(
        self, value: QueryDict | MultiValueDict | Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """This is used by has_changed + ...?"""
        # TODO(now): Unnest?
        if hasattr(value, "getlist"):
            value = value.dict()
        return super().to_python(value)


class FrozenDictField(DictField): ...


class SequenceBoundField(BoundField):
    pass


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

    def to_python(self, value) -> Sequence[object]:
        if value in self.empty_values:
            return ()
        cleaned = ()
        cleaner = self.child_field.clean
        for v in value:
            cleaned += (cleaner(v),)
        return cleaned


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
        index = 0
        for index, item in enumerate(value[: self.max_num]):
            widget = self.child_widget
            if id_:
                widget_attrs = final_attrs.copy()
                widget_attrs["id"] = "%s_%s" % (id_, index)
            else:
                widget_attrs = final_attrs
            rendered = widget.get_context(
                name=name,
                value=item,
                attrs=widget_attrs,
            )["widget"]
            subwidgets.append(rendered)

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
FormField = DictField
FrozenFormField = FrozenDictField
