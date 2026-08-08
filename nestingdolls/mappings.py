from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.fields import FileField
from django.forms.widgets import Media as WidgetMedia
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _

from nestingdolls._shared import CompositeBoundField, CompositeField, CompositeWidget
from nestingdolls.errors import (
    InvalidInitialValueError,
    InvalidMappingInputError,
    ItemValidationError,
)

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


class MappingWidget(CompositeWidget):
    """Render one child Form as a mapping-shaped widget."""

    _template_name = "nestingdolls/mapping/{layout}.html"
    use_fieldset = True
    form_class: type[BaseForm]
    # Submitted state that Widget.render() cannot pass to get_context(). The
    # bound field sets it before each render.
    subform: BaseForm | None = None

    def __init__(
        self,
        form_class: type[BaseForm] | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store the child Form class this widget renders.

        Django builds this widget from its class, and gives it no Form class,
        when a field supplies only the class. The field configures the copy.
        """
        if form_class is not None:
            self.form_class = form_class
        super().__init__(dict(attrs) if attrs is not None else None)

    @cached_property
    def fields(self) -> dict[str, Field]:
        return self.form_class().fields

    def _normalized_child_key(self, key: object, name: str) -> str | None:
        """Normalize one supported child key into its canonical declared name."""
        if (child_key := self._split_child_key(key, name)) is None:
            return None
        token, suffix = child_key
        key = f"{name}-{token}{suffix}"
        # Drop undeclared keys so a matching prefix cannot retain untrusted data.
        return (
            key
            if any(
                key == f"{name}-{child_name}"
                or key.startswith(f"{name}-{child_name}{separator}")
                for child_name in self.fields
                for separator in "_-.["
            )
            else None
        )

    def _normalized_datadict(
        self, data: Mapping[str, object], name: str
    ) -> Mapping[str, object]:
        """Canonicalize accepted child names while preserving source values."""
        if not data:
            return {}

        if name in data:
            # Use the direct mapping value when both shapes are present.
            value = data.get(name)
            if not isinstance(value, Mapping):
                return {name: value}
            if isinstance(value, MultiValueDict):
                # Keep repeated child values for widgets that read all values.
                normalized = MultiValueDict[str, object]()
                for child_name in self.fields:
                    if child_name in value:
                        normalized.setlist(
                            f"{name}-{child_name}", value.getlist(child_name)
                        )
                return normalized
            # Keep direct mapping input from retaining undeclared data.
            return {
                f"{name}-{child_name}": value[child_name]
                for child_name in self.fields
                if child_name in value
            }

        if isinstance(data, MultiValueDict):
            # Keep repeated flat input values in Django's multi-value shape.
            normalized = MultiValueDict[str, object]()
            for source_key in data:
                key = self._normalized_child_key(source_key, name)
                if key is not None:
                    normalized.setlist(key, data.getlist(source_key))
            return normalized

        # Plain mappings keep one value for each child key.
        return {
            key: value
            for source_key, value in data.items()
            if (key := self._normalized_child_key(source_key, name)) is not None
        }

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

        file_data = cast(MultiValueDict[str, UploadedFile], files)
        value: dict[str, object] = {}
        for child_name, field in self.fields.items():
            child_widget = self._child_widget(field)
            child_input_name = f"{name}-{child_name}"
            if child_widget.value_omitted_from_data(data, file_data, child_input_name):
                continue
            value[child_name] = child_widget.value_from_datadict(
                data, file_data, child_input_name
            )
        return value

    def get_context(
        self, name: str, value: object, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build widget context with a prefixed child Form."""
        context = super().get_context(name, value, attrs)
        subform = self.subform
        if subform is None:
            if self.hidden_initial_value is not None:
                value = self.hidden_initial_value
            subform = self.form_class(
                initial=dict(value) if isinstance(value, Mapping) else {},
                prefix=name,
                use_required_attribute=self.is_required,
            )
        context["widget"].update(
            {
                "subform": subform,
                "visible_fields": subform.visible_fields(),
                "hidden_fields": (
                    [field.as_hidden() for field in subform]
                    if self.is_hidden
                    else subform.hidden_fields()
                ),
                "non_field_errors": subform.non_field_errors(),
            }
        )
        return context

    @property
    def is_hidden(self) -> bool:
        """Report whether the mapping or every child widget is hidden."""
        return super().is_hidden or all(
            field.widget.is_hidden for field in self.fields.values()
        )

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Report whether any child widget accepts files."""
        return any(field.widget.needs_multipart_form for field in self.fields.values())

    @property
    def media(self) -> WidgetMedia:
        """Return this widget's media with the child Form media."""
        media: WidgetMedia = super().media + self.form_class().media
        return media


class MappingBoundField(CompositeBoundField):
    """Render child Form errors without duplicating them on the parent field."""

    field: MappingField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, MappingField):
            raise TypeError("field must be a MappingField")

    @cached_property
    def initial(self) -> object:
        """Normalize recognized mapping initials and preserve invalid ones."""
        if self.form.initial and self.name not in self.form.initial:
            value = self._flat_initial_value(self.form.initial)
            if isinstance(value, Mapping) and value:
                return self.field._initial_value(value)
        value = super().initial
        try:
            return self.field._initial_value(value)
        except InvalidInitialValueError:
            return value

    @cached_property
    def _is_bound_subform(self) -> bool:
        """Return whether the child form should bind submitted data/files."""
        if not self.form.is_bound:
            return False
        if self.field.disabled:
            return False
        if not isinstance(self.data, Mapping):
            return False
        if self._data_input or self._file_input:
            return True
        return (
            isinstance(self.initial, dict)
            and bool(self.initial)
            and self.field.widget.needs_multipart_form
        )

    @cached_property
    def subform(self) -> BaseForm:
        """Return the child Form used for bound cleaning and rendering."""
        is_bound = self._is_bound_subform
        initial = self.initial
        subform = self.field.form_class(
            data=self._data_input if is_bound else None,
            files=cast(Any, self._file_input) if is_bound else None,
            initial=initial if isinstance(initial, dict) else {},
            prefix=self.html_name,
            auto_id=self.form.auto_id,
            use_required_attribute=(
                self.field.required and self.form.use_required_attribute
            ),
            renderer=self.form.renderer,
        )
        if self.field.disabled:
            for field in subform.fields.values():
                field.disabled = True
        return subform

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the mapping widget the child Form that holds the bound data."""
        super()._prepare_widget(widget, only_initial)
        if isinstance(widget, MappingWidget):
            # A hidden initial render builds its own Form, with the initial prefix.
            widget.subform = None if only_initial else self.subform


class MappingField(CompositeField):
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
        validators: Sequence[Callable[[dict[str, object]], None]] = (),
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
        try:
            form_class()
        except TypeError as exc:
            raise ImproperlyConfigured(
                "form_class argument for MappingField must be default-constructible"
            ) from exc
        if initial is not None and not callable(initial):
            self._initial_value(initial)

        self.form_class = form_class
        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, MappingBoundField):
            raise TypeError("bound_field_class must inherit from MappingBoundField")
        super().__init__(
            required=required,
            # Django builds a widget class and copies a widget instance. The
            # configuration below then makes that copy match this field.
            widget=widget or MappingWidget,
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
        if not isinstance(self.widget, MappingWidget):
            raise TypeError("widget must be a MappingWidget instance or subclass")
        # Django copies the widget. Configure that copy to match this field.
        self.widget.form_class = form_class

    @staticmethod
    def _initial_value(value: object) -> dict[str, object]:
        """Normalize a supported initial mapping."""
        if value is None or value == "":
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        raise InvalidInitialValueError("initial must be a mapping of values")

    def to_python(self, value: object) -> dict[str, object]:
        """Require input to be mapping-shaped."""
        if value is None or value == "":
            return {}
        if not isinstance(value, Mapping):
            raise InvalidMappingInputError(self.error_messages["invalid"])
        return dict(value)

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert each member back from its hidden initial value."""
        # to_python() gives a mapping of members here, or raises for other input.
        value = cast(dict[str, object], super().children_from_hidden_initial(value))
        for name, child_field in self.form_class().fields.items():
            if name in value and not isinstance(child_field, FileField):
                value[name] = self.hidden_initial_to_python(child_field, value[name])
        return value

    def _clean_form(self, form: BaseForm) -> dict[str, object]:
        """Return child cleaned data or raise its leaf errors."""
        if not form.is_valid():
            raise ValidationError(
                [
                    item_error
                    for name, errors in form.errors.as_data().items()
                    for error in errors
                    for item_error in ItemValidationError.for_messages_of(name, error)
                ]
            )
        result: dict[str, object] = form.cleaned_data
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
                bound_field_class=_ValueBoundField,
            )
        )

    def _clean_bound_field(self, bound_field: BoundField) -> dict[str, object]:
        """Clean the prefixed child Form when bound input or file-only initials apply."""
        assert isinstance(bound_field, MappingBoundField)
        if self.disabled:
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        value = bound_field.data
        if not isinstance(value, Mapping) or (
            not value and not bound_field._is_bound_subform
        ):
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        return self._clean_form(bound_field.subform)

    def bound_data(self, data: object, initial: object) -> object:
        """Bind submitted members with their matching initial values."""
        try:
            initial = self._initial_value(initial)
            if self.disabled:
                return initial
            data = self.to_python(data)
            return {
                name: field.bound_data(data.get(name), initial.get(name))
                for name, field in self.form_class().fields.items()
            }
        except (InvalidInitialValueError, ValidationError):
            # BoundField.value() calls this while rendering an invalid form.
            # Keep hostile input in Django's normal rendering channel.
            return super().bound_data(data, initial)

    def prepare_value(self, value: object) -> object:
        """Prepare each mapping member for widget rendering."""
        try:
            value = self._initial_value(value)
            return {
                name: field.prepare_value(value[name])
                for name, field in self.form_class().fields.items()
                if name in value
            }
        except (InvalidInitialValueError, ValidationError):
            return super().prepare_value(value)

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare mapping members using child-field change semantics."""
        if self.disabled:
            return False
        try:
            initial = self._initial_value(initial)
            data = self.to_python(data)
        except (InvalidInitialValueError, ValidationError):
            return True
        for name, field in self.form_class().fields.items():
            try:
                if field.has_changed(initial.get(name), data.get(name)):
                    return True
            except ValidationError:
                return True
        return False


DictField = MappingField
FormField = MappingField
Subform = MappingField
