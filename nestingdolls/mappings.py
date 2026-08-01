from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.utils import ErrorList
from django.forms.widgets import Media as WidgetMedia
from django.forms.widgets import Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _

from nestingdolls.errors import InvalidInitialValueError

__all__ = [
    "DictField",
    "FormField",
    "MappingBoundField",
    "MappingField",
    "MappingWidget",
    "Subform",
]


class _ValueBoundField(BoundField):
    """Read one already-extracted value from a mapping."""

    @property
    def data(self) -> object:
        return self.form.data.get(self.name)


class MappingWidget(Widget):
    """Render one child Form as a mapping-shaped widget."""

    template_name = "django/forms/widgets/dictwidget.html"
    use_fieldset = True
    input_type: str | None = None

    def __init__(
        self,
        form_class: type[BaseForm],
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        self.form_class = form_class
        super().__init__(dict(attrs) if attrs is not None else None)

    def _normalize_mapping(self, data: Any, name: str) -> Mapping[str, object]:
        """Canonicalize accepted child names while preserving source values.

        post[]: (not data) implies not __return__
        post[]: isinstance(__return__, Mapping)
        """
        if not data:
            return {}

        flat_prefixes = (f"{name}-", f"{name}.")
        bracket_prefix = f"{name}["

        def normalized_key(key: object) -> str | None:
            if not isinstance(key, str):
                return None
            for prefix in flat_prefixes:
                if key.startswith(prefix) and len(key) > len(prefix):
                    return f"{name}-{key.removeprefix(prefix)}"
            if not key.startswith(bracket_prefix):
                return None
            end = key.find("]", len(bracket_prefix))
            if end < 0:
                return None
            child_name = key[len(bracket_prefix) : end]
            suffix = key[end + 1 :]
            if not child_name or suffix and suffix[0] not in "_-.[":
                return None
            return f"{name}-{child_name}{suffix}"

        source = data
        direct = name in data
        if direct:
            value = data.get(name)
            if not isinstance(value, Mapping):
                return {name: value}
            source = value
            child_names = self.form_class().fields
            if hasattr(source, "getlist"):
                normalized = MultiValueDict[str, object]()
                for child_name in child_names:
                    if child_name in source:
                        normalized.setlist(
                            f"{name}-{child_name}", source.getlist(child_name)
                        )
                return normalized
            return {
                f"{name}-{child_name}": source[child_name]
                for child_name in child_names
                if child_name in source
            }

        def output_key(key: object) -> str | None:
            if not direct:
                return normalized_key(key)
            if not isinstance(key, str) or not key:
                return None
            return f"{name}-{key}"

        if hasattr(source, "getlist"):
            normalized = MultiValueDict[str, object]()
            for source_key in source:
                key = output_key(source_key)
                if key is not None:
                    normalized.setlist(key, source.getlist(source_key))
            return normalized

        normalized_dict: dict[str, object] = {}
        for source_key, value in source.items():
            key = output_key(source_key)
            if key is not None:
                normalized_dict[key] = value
        return normalized_dict

    def _value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values from canonical data and files."""
        if name in data:
            return data.get(name)
        if name in files:
            return files.get(name)
        if not data and not files:
            return {}

        return {
            child_name: field.widget.value_from_datadict(
                data, files, f"{name}-{child_name}"
            )
            for child_name, field in self.form_class().fields.items()
            if not field.widget.value_omitted_from_data(
                data, files, f"{name}-{child_name}"
            )
        }

    def value_from_datadict(self, data: Any, files: Any, name: str) -> object:
        """Return the submitted mapping extracted by child widgets."""
        return self._value_from_normalized_data(
            self._normalize_mapping(data, name),
            self._normalize_mapping(files, name) if files else {},
            name,
        )

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Report whether all supported mapping inputs are absent."""
        return not (
            self._normalize_mapping(data, name)
            or self._normalize_mapping(files, name)
        )

    def get_context(
        self, name: str, value: object, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build widget context with a prefixed child Form."""
        context = super().get_context(name, value, attrs)
        subform = (
            value
            if isinstance(value, BaseForm)
            else self.form_class(
                initial=dict(value) if isinstance(value, Mapping) else {},
                prefix=name,
                use_required_attribute=self.is_required,
            )
        )
        context["widget"]["subform"] = subform
        return context

    def use_required_attribute(self, initial: object) -> bool:
        """Let child fields own HTML required attributes."""
        return False

    def id_for_label(self, id_: str) -> str:
        """Suppress label targeting for the composite widget."""
        return ""

    @property
    def is_hidden(self) -> bool:
        """Report whether the mapping or every child widget is hidden."""
        return self.input_type == "hidden" or all(
            field.widget.is_hidden for field in self.form_class().fields.values()
        )

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Report whether any child widget accepts files."""
        return any(
            field.widget.needs_multipart_form
            for field in self.form_class().fields.values()
        )

    @property
    def media(self) -> WidgetMedia:
        """Return the child Form widget media."""
        return self.form_class().media


class MappingBoundField(BoundField):
    """Render child Form errors without duplicating them on the parent field."""

    field: MappingField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, MappingField):
            raise TypeError("field must be a MappingField")

    @property
    def errors(self) -> ErrorList:
        """Return only errors owned by the outer mapping field."""
        errors = super().errors
        if not errors:
            return errors
        field_errors = [
            error for error in errors.as_data() if error.code != "item_invalid"
        ]
        if len(field_errors) == len(errors):
            return errors
        return self.form.error_class(
            field_errors,
            renderer=self.form.renderer,
            field_id=self.auto_id,
        )

    @cached_property
    def _data_input(self) -> Mapping[str, object]:
        """Cache normalized submitted form data for this field."""
        return self.field.widget._normalize_mapping(self.form.data, self.html_name)

    @cached_property
    def _file_input(self) -> Mapping[str, object]:
        """Cache normalized submitted files for this field."""
        if not self.form.files:
            return {}
        return self.field.widget._normalize_mapping(self.form.files, self.html_name)

    @cached_property
    def data(self) -> object:
        """Return the mapping extracted from normalized data and files."""
        return self.field.widget._value_from_normalized_data(
            self._data_input,
            self._file_input,
            self.html_name,
        )

    @cached_property
    def initial(self) -> dict[str, object]:
        """Normalize direct and flattened mapping initial values."""
        value: object = super().initial
        if self.form.initial and self.name not in self.form.initial:
            normalized = self.field.widget._normalize_mapping(
                self.form.initial, self.name
            )
            if normalized:
                candidate = self.field.widget._value_from_normalized_data(
                    normalized, {}, self.name
                )
                if isinstance(candidate, Mapping):
                    value = candidate
        return self.field._initial_value(value)

    @cached_property
    def subform(self) -> BaseForm:
        """Return the child Form used for bound cleaning and rendering."""
        kwargs: dict[str, object] = {
            "initial": self.initial,
            "prefix": self.html_name,
            "auto_id": self.form.auto_id,
            "use_required_attribute": (
                self.field.required and self.form.use_required_attribute
            ),
            "renderer": self.form.renderer,
        }
        if (
            self.form.is_bound
            and not self.field.disabled
            and isinstance(self.data, Mapping)
            and bool(self._data_input or self._file_input)
        ):
            kwargs.update(data=self._data_input, files=self._file_input)
        subform = self.field.form_class(**cast(Any, kwargs))
        if self.field.disabled:
            for field in subform.fields.values():
                field.disabled = True
        return subform

    def as_widget(
        self,
        widget: Widget | None = None,
        attrs: dict[str, str | bool] | None = None,
        only_initial: bool = False,
    ) -> SafeString:
        """Render the cached child Form through the mapping widget."""
        widget = widget or self.field.widget
        if only_initial or not isinstance(widget, MappingWidget):
            return super().as_widget(widget, attrs, only_initial)
        if self.field.localize:
            widget.is_localized = True
        attrs = self.build_widget_attrs(dict(attrs or {}), widget)
        if self.auto_id and "id" not in widget.attrs:
            attrs.setdefault("id", self.auto_id)
        return widget.render(
            self.html_name,
            self.subform,
            attrs=attrs,
            renderer=self.form.renderer,
        )

    def as_hidden(
        self,
        attrs: dict[str, str | bool] | None = None,
        **kwargs: Any,
    ) -> SafeString:
        """Render each child through its own hidden widget."""
        widget = copy.deepcopy(self.field.widget)
        widget.input_type = "hidden"
        return self.as_widget(widget, attrs, **kwargs)

    def _has_changed(self) -> bool:
        """Read hidden mapping initial values through the mapping widget."""
        if not self.field.show_hidden_initial:
            return cast(bool, super()._has_changed())  # type: ignore[misc]
        widget = copy.deepcopy(self.field.widget)
        widget.input_type = "hidden"
        initial_value = widget.value_from_datadict(
            self.form.data, self.form.files, self.html_initial_name
        )
        try:
            initial_value = self.field.to_python(initial_value)
        except ValidationError:
            return True
        return self.field.has_changed(initial_value, self.data)


class MappingField(Field):
    """Validate a fixed mapping shape with one child Form class."""

    widget: MappingWidget
    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a mapping of values."),
    }
    bound_field_class: type[MappingBoundField] = MappingBoundField

    def __init__(
        self,
        form_class: type[BaseForm],
        /,
        *,
        required: bool = True,
        widget: MappingWidget | type[MappingWidget] | None = None,
        label: str | Promise | None = None,
        initial: object | Callable[[], object] | None = None,
        help_text: str | Promise = "",
        error_messages: Mapping[str, str | Promise] | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[MappingBoundField] | None = None,
    ) -> None:
        """Configure a fixed mapping field."""
        if not isinstance(form_class, type) or not issubclass(form_class, BaseForm):
            raise ImproperlyConfigured(
                "form_class argument for MappingField must be a BaseForm subclass"
            )
        if initial is not None and not callable(initial):
            self._initial_value(initial)

        self.form_class = form_class
        widget = MappingWidget if widget is None else widget
        if not (
            isinstance(widget, MappingWidget)
            or isinstance(widget, type)
            and issubclass(widget, MappingWidget)
        ):
            raise TypeError("widget must be a MappingWidget instance or subclass")
        if isinstance(widget, type):
            widget = widget(form_class)

        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, MappingBoundField):
            raise TypeError("bound_field_class must inherit from MappingBoundField")
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
        self.widget.form_class = form_class

    @staticmethod
    def _initial_value(value: object) -> dict[str, object]:
        """Normalize a supported initial mapping.

        post[]: isinstance(__return__, dict)
        post[]: (value is None or value == "") implies __return__ == {}
        raises: InvalidInitialValueError
        """
        if value is None or value == "":
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        raise InvalidInitialValueError("initial must be a mapping of values")

    def to_python(self, value: object) -> dict[str, object]:
        """Require input to be mapping-shaped.

        post[]: isinstance(__return__, dict)
        post[]: (value is None or value == "") implies __return__ == {}
        raises: ValidationError
        """
        if value is None or value == "":
            return {}
        if not isinstance(value, Mapping):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return dict(value)

    @staticmethod
    def _form_errors(form: BaseForm) -> list[ValidationError]:
        errors = []
        for key, error_list in form.errors.as_data().items():
            for error in error_list:
                params = error.params or {}
                child_code = params.get("child_code", error.code)
                for message in error.messages:
                    errors.append(
                        ValidationError(
                            message,
                            code="item_invalid",
                            params={
                                "key": key,
                                "message": message,
                                "child_code": child_code,
                            },
                        )
                    )
        return errors

    def _clean_form(self, form: BaseForm) -> dict[str, object]:
        """Return child cleaned data or raise its leaf errors."""
        if not form.is_valid():
            raise ValidationError(self._form_errors(form))
        result = cast(dict[str, object], form.cleaned_data)
        self.validate(result)
        self.run_validators(result)
        return result

    def clean(self, value: object) -> dict[str, object]:
        """Clean an already-collected mapping value."""
        value = self.to_python(value)
        if not value:
            return cast(dict[str, object], super().clean(value))
        return self._clean_form(
            self.form_class(
                data=value,
                files=cast(Any, value),
                bound_field_class=_ValueBoundField,
            )
        )

    def _clean_bound_field(self, bound_field: BoundField) -> dict[str, object]:
        """Clean the prefixed child Form when raw bound input is available."""
        dict_bound_field = cast(MappingBoundField, bound_field)
        if self.disabled:
            return cast(
                dict[str, object],
                super()._clean_bound_field(dict_bound_field),  # type: ignore[misc]
            )
        value = dict_bound_field.data
        if not isinstance(value, Mapping) or not value:
            return cast(
                dict[str, object],
                super()._clean_bound_field(dict_bound_field),  # type: ignore[misc]
            )
        return self._clean_form(dict_bound_field.subform)

    def bound_data(self, data: object, initial: object) -> dict[str, object]:
        """Bind submitted members with their matching initial values."""
        if self.disabled:
            return self._initial_value(initial)
        initial_value = self._initial_value(initial)
        data_value = self.to_python(data)
        return {
            name: field.bound_data(data_value.get(name), initial_value.get(name))
            for name, field in self.form_class().fields.items()
        }

    def prepare_value(self, value: object) -> dict[str, object]:
        """Prepare each mapping member for widget rendering.

        post[]: isinstance(__return__, dict)
        """
        values = self._initial_value(value)
        return {
            name: field.prepare_value(values[name])
            for name, field in self.form_class().fields.items()
            if name in values
        }

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare mapping members using child-field change semantics.

        post[]: isinstance(__return__, bool)
        """
        if not super().has_changed(initial, data):
            return False
        try:
            initial_value = self._initial_value(initial)
            data_value = self.to_python(data)
        except (InvalidInitialValueError, ValidationError):
            return True
        for name, field in self.form_class().fields.items():
            try:
                if field.has_changed(initial_value.get(name), data_value.get(name)):
                    return True
            except ValidationError:
                return True
        return False


DictField = MappingField
FormField = MappingField
Subform = MappingField
