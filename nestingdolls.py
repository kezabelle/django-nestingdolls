from __future__ import annotations

import inspect
import logging
from types import MappingProxyType
from typing import Protocol, Mapping, Any, Iterable, Sequence

from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.renderers import BaseRenderer
from django.forms.utils import ErrorList
from django.forms.widgets import Widget
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


class DictBoundField(BoundField):
    # def __init__(self, form, field, name) -> None:
    #     breakpoint()
    ...


class DictWidget(Widget):
    """
    A widget is necessary because the BoundField is where data is fetched
    from during cleaning, and that ends up asking the Form for the data.
    🙄
    """

    def value_from_datadict(
        self,
        data: QueryDict | MultiValueDict | Mapping[str, Any],
        files,
        name: str,
    ):
        # Normal Django POST data
        if isinstance(data, MultiValueDict):
            subdata = QueryDict(mutable=True)
            # TODO: Is there a better way to do this?
            for k in data:
                if k.startswith(f"{name}[") and k[-1] == "]":
                    newk = k.removeprefix(f"{name}[").rstrip("]")
                    subdata[newk] = data[k]
            return subdata
        # Actual proper nested dictionary
        elif isinstance(data, Mapping):
            return super().value_from_datadict(data, files, name)


class DictField(Field):
    default_error_messages = MappingProxyType(
        {
            "invalid": _("Sub-form data is invalid"),
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
        bound_field_class: type[DictBoundField] | None = None,
        # auto_id: str = "id_%s",
        # prefix: str | None = None,
        # initial: Mapping[str, Any] = None,
        # error_class: type[ErrorList] = ErrorList,
        # label_suffix: str | None = None,
        # empty_permitted: bool = False,
        # field_order: Iterable[str] = None,
        # use_required_attribute: bool | None = None,
        # renderer: BaseRenderer | None = None,
    ):
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
        self.subform = subform
        if bound_field_class is not None:
            self.bound_field_class = bound_field_class

    def _get_form_class(self):
        """
        Returns the form class that this field is bound to.
        """
        if isinstance(self.subform, BaseForm):
            return self.subform.__class__
        # Received form=type[BaseForm] during __init__
        return self.subform

    def _get_form_default_kwargs(self) -> MappingProxyType[str, Any]:
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

    def _get_form_instance(self, data: MultiValueDict | Mapping[str, Any]) -> BaseForm:
        form_class = self._get_form_class()
        form_default_kwargs = self._get_form_default_kwargs()
        form_kwargs = {**form_default_kwargs, **{"data": data}}
        return form_class(**form_kwargs)

    def get_bound_field(self, form: BaseForm, field_name: str):
        """We need a custom bound field instance?"""
        return self.bound_field_class(form, self, field_name)

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

    def to_python(self, value: MultiValueDict | Mapping[str, Any]) -> Mapping[str, Any]:
        subform = self._get_form_instance(data=value)
        valid = subform.is_valid()
        value = subform.cleaned_data
        # Force checking empty values + required manually because we have
        # to return a dict here, but if we raise a validation error at this
        # point the subsequent validate call won't run.
        # TODO: Is this granular enough?
        if not valid and self.required:
            if self.required:
                raise ValidationError(
                    message=self.error_messages["required"], code="required"
                )
            raise ValidationError(
                message=self.error_messages["invalid"], code="invalid"
            )
        return value
        # if isinstance(value, MultiValueDict):
        #     return value.dict()
        # return value

    # def validate(self, value: Mapping[str, Any]) -> None:
    #     pass

    # def validate(self, value: MultiValueDict | Mapping[str, Any]) -> bool:
    #     subform = self.form(data=value)
    #     breakpoint()
    #     if not subform.is_valid():
    #         # TODO: Is this granular enough?
    #         raise ValidationError(subform.errors)
    #     return subform.cleaned_data

    # def clean(self, value: MultiValueDict | Mapping[str, Any]):
    #     return super().clean(value=value)

    #
    # def clean(self, value: MultiValueDict | Mapping) -> MultiValueDict:
    #     ...


class FrozenDictField(DictField): ...


class SequenceField(Field): ...


class FrozenSequenceField(SequenceField): ...


ListField = SequenceField
TupleField = FrozenSequenceField
FormField = DictField
FrozenFormField = FrozenDictField
