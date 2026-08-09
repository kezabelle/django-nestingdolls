from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Self, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.fields import FileField
from django.forms.widgets import Media as WidgetMedia
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _

from nestingdolls._shared import CompositeBoundField, CompositeField, CompositeWidget
from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MappingInputValidationError,
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
    """Read one child value that the mapping field extracted already.

    ``MappingField.clean()`` builds the child Form from a dict of Python
    values, and that dict has no prefixed input names. Django's
    ``BoundField.data`` reads the widget of the child, so it would find
    nothing. This class reads the child name from the dict instead.

    Only two callers reach this path: a direct ``field.clean(dict)`` call,
    or a ``SequenceField`` parent that cleans one row. A bound outer form
    uses ``_clean_bound_field`` and the prefixed subform instead. So this
    path is not a hot path.
    """

    @property
    def data(self) -> object:
        return self.form.data.get(self.name)


class MappingWidget(CompositeWidget):
    """Render one child Form as the widget of a mapping field."""

    _template_name = "nestingdolls/mapping/{layout}.html"
    use_fieldset = True
    form_class: type[BaseForm]

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bound(CompositeWidget.Bound):
        """Hold the child Form that one render of a mapping widget needs.

        The bound field builds the child Form, because only the bound field
        holds the data that the browser sent and the errors of that Form. A
        render that gets no child Form builds a new one from the value that it
        gets.
        """

        subform: BaseForm | None = None

    bound: Bound = Bound()

    @dataclasses.dataclass(frozen=True)
    class Keys(CompositeWidget.Keys):
        """Read the input keys of one mapping field as child keys.

        Every child of a mapping has a declared name. This object changes each
        accepted key format into one canonical child key. It drops a key that
        no child declares. It holds the child Form class, and it reads the
        child names from an instance of that class, so the names contain the
        fields that ``__init__`` adds. This dataclass has no ``slots``, because
        ``cached_property`` needs the instance dictionary.
        """

        form_class: type[BaseForm]

        @cached_property
        def names(self) -> tuple[str, ...]:
            """Return the declared child names of the child Form."""
            return tuple(self.form_class().fields)

        def canonical(self, key: object, name: str) -> str | None:
            """Return the canonical child key of one accepted key, or None."""
            if (child_key := self.split(key, name)) is None:
                return None
            token, suffix = child_key
            key = f"{name}-{token}{suffix}"
            # A key that only starts with the field name is not a child key.
            # Refuse it, so that forged input cannot stay in the value.
            return (
                key
                if any(
                    key == f"{name}-{child_name}"
                    or key.startswith(f"{name}-{child_name}{separator}")
                    for child_name in self.names
                    for separator in "_-.["
                )
                else None
            )

        def reads_whole_value(self, data: Mapping[str, object], name: str) -> bool:
            """Refuse a browser value under this field's own name.

            A browser cannot submit a mapping under one key, so a key spelled
            exactly like the field name is a submit button or forged input.
            """
            return not isinstance(data, QueryDict) and super().reads_whole_value(
                data, name
            )

        def normalized(
            self, data: Mapping[str, object], name: str
        ) -> Mapping[str, object]:
            """Return the data of the children under canonical keys.

            The values stay as the caller gave them.
            """
            if not data:
                return MultiValueDict()

            if name in data and self.reads_whole_value(data, name):
                # A whole mapping value and flat child keys can both be
                # present. See reads_whole_value() for which one wins.
                value = data.get(name)
                if not isinstance(value, Mapping):
                    normalized = MultiValueDict[str, object]()
                    normalized.setlist(name, [value])
                    return normalized
                if isinstance(value, MultiValueDict):
                    # Keep every repeated value, because a child widget can
                    # read all values of one key.
                    normalized = MultiValueDict[str, object]()
                    for child_name in self.names:
                        if child_name in value:
                            normalized.setlist(
                                f"{name}-{child_name}", value.getlist(child_name)
                            )
                    return normalized
                # Copy the declared children only, so that forged keys do not
                # stay in the value.
                normalized = MultiValueDict[str, object]()
                for child_name in self.names:
                    if child_name in value:
                        normalized.setlist(f"{name}-{child_name}", [value[child_name]])
                return normalized

            if isinstance(data, MultiValueDict):
                # Keep repeated values in a MultiValueDict, as Django request
                # data does.
                normalized = MultiValueDict[str, object]()
                for source_key in data:
                    key = self.canonical(source_key, name)
                    if key is not None:
                        normalized.setlist(key, data.getlist(source_key))
                return normalized

            # Plain mappings keep one value for each child key.
            result: dict[str, object] = {}
            for source_key, value in data.items():
                key = self.canonical(source_key, name)
                if key is not None:
                    result[key] = value
            return result

    keys: Keys

    def __init__(
        self,
        form_class: type[BaseForm] | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store the child Form class that this widget renders.

        A field can supply the widget class only. Django then builds the widget
        with no Form class, and the field configures that copy.
        """
        if form_class is not None:
            self.configure(form_class)
        super().__init__(dict(attrs) if attrs is not None else None)

    def configure(self, form_class: type[BaseForm]) -> None:
        """Store the configuration of the field that owns this widget.

        Django copies a widget before a field uses it, so the field calls this
        method on its own copy. This method makes a new key reader, because a
        key reader must read the child names of this Form class only.
        """
        self.form_class = form_class
        self.keys = self.Keys(form_class)

    @cached_property
    def fields(self) -> dict[str, Field]:
        """Return the fields of one instance of the child Form."""
        return self.form_class().fields

    def value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values from canonical data and files."""
        # A whole value holds the whole mapping. Return it, because the caller
        # gave Python data and no child widget must read it again.
        if name in data:
            return data.get(name)
        if name in files:
            return files.get(name)
        if not data and not files:
            return {}

        files = cast("MultiValueDict[str, UploadedFile[Any]]", files)
        value: dict[str, object] = {}
        # Only a child widget knows how to read its own input, and only it
        # knows when the browser sent nothing. A child that sent nothing stays
        # out of the value, so that its initial value survives.
        for child_name, field in self.fields.items():
            child_widget = self._child_widget(field)
            child_input_name = f"{name}-{child_name}"
            if child_widget.value_omitted_from_data(data, files, child_input_name):
                continue
            value[child_name] = child_widget.value_from_datadict(
                data, files, child_input_name
            )
        return value

    def get_context(
        self, name: str, value: object, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build the context of the widget, with a prefixed child Form.

        The bound field supplies the child Form when the outer form is bound.
        An unbound render gets no Form, and it builds one from the value that it
        gets. The shared budget covers sequence descendants because Django
        bounds each formset level, not aggregate nested rows.
        """
        context = super().get_context(name, value, attrs)
        subform = self.bound.subform
        if subform is None:
            # A hidden initial render must show the initial value, because
            # change detection compares it with the value that the browser
            # sent.
            if self.bound.hidden_initial_value is not None:
                value = self.bound.hidden_initial_value
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

    def _child_media(self) -> WidgetMedia:
        """Return the media of the child Form.

        ``BaseForm.media`` already aggregates every child widget's media.
        """
        return self.form_class().media

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy this widget. Do not share its cached child widgets.

        ``Widget.__deepcopy__`` makes only a shallow ``copy.copy``. A
        warmed ``fields`` cache holds child ``Field`` and ``Widget``
        objects. This method clears that cache, so no two forms share it.

        ``ClearableFileInput.value_from_datadict`` changes
        ``self.checked`` on its widget. A shared cache turns that change
        into a cross-request bug. ``MultiValueField.__deepcopy__`` clears
        its own cache for the same reason.
        """
        result = super().__deepcopy__(memo)
        result.__dict__.pop("fields", None)
        return result


class MappingBoundField(CompositeBoundField):
    """Bind and render the child Form of a mapping field.

    The child Form keeps its own errors beside its own fields. The outer field
    does not repeat them.
    """

    field: MappingField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, MappingField):
            raise TypeError("field must be a MappingField")

    @cached_property
    def initial(self) -> object:
        """Return the initial mapping, and keep an unusable value as it is.

        Initial data can use flat child keys, for example ``address-city``.
        Read those keys when the initial data of the form has no key for this
        field. Initial data uses the field's own ``name`` as its key.
        Submitted data uses ``html_name`` instead. So this method reads
        ``self.name``, while ``_data_input`` reads ``self.html_name``.
        """
        if self.form.initial and self.name not in self.form.initial:
            value = self._initial_from_flat_keys(self.form.initial)
            if isinstance(value, Mapping) and value:
                return self.field.initial_value(value)
        value = super().initial
        try:
            return self.field.initial_value(value)
        except InvalidInitialValueError:
            # Do not raise during a render. The widget can render a wrong
            # initial value, and validation reports the problem to the user.
            return value

    @cached_property
    def is_bound_subform(self) -> bool:
        """Report whether the child Form must bind the data and the files.

        A browser sends no file input when the user selects no file. If the
        initial data holds files, the Form still binds, so that the child
        ``FileField`` can keep the file or clear it.

        A value that is not a ``Mapping`` means the caller sent a scalar
        under this field's name. There are no children to distribute that
        scalar over. So the subform must not bind. ``to_python`` reports
        the "invalid" error instead.
        """
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
        """Return the child Form for the clean step and for the render."""
        is_bound = self.is_bound_subform
        initial = self.initial
        subform = self.field.form_class(
            data=self._data_input if is_bound else None,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", self._file_input)
            if is_bound
            else None,
            initial=initial if isinstance(initial, dict) else {},
            prefix=self.html_name,
            auto_id=self.form.auto_id,
            use_required_attribute=(
                self.field.required and self.form.use_required_attribute
            ),
            renderer=self.form.renderer,
        )
        # Django does not give ``disabled`` to a child field, so set it on each
        # one. A disabled child keeps its initial value and ignores the input.
        if self.field.disabled:
            for field in subform.fields.values():
                field.disabled = True
        return subform

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the mapping widget the child Form that holds the bound data."""
        if not isinstance(widget, MappingWidget):
            return super()._prepare_widget(widget, only_initial)
        # A hidden initial render must not use the bound child Form, because
        # that Form holds the prefix and the data of the visible render.
        value, _ = self._hidden_initial_value(widget) if only_initial else (None, None)
        widget.bound = widget.Bound(
            hidden_initial_value=value,
            subform=None if only_initial else self.subform,
        )


class MappingField(CompositeField):
    """Clean and validate the fixed set of children that one Form declares.

    A mapping has named child fields. It has no row count. A sequence child
    starts and owns its row count.
    """

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
        # Build the Form one time now. A Form class that needs arguments would
        # fail later, in the middle of a render, and the reason would be hard
        # to find.
        try:
            form_class()
        except TypeError as exc:
            raise ImproperlyConfigured(
                "form_class argument for MappingField must be default-constructible"
            ) from exc
        if initial is not None and not callable(initial):
            self.initial_value(initial)

        self.form_class = form_class
        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, MappingBoundField):
            raise TypeError("bound_field_class must inherit from MappingBoundField")
        super().__init__(
            required=required,
            # Django accepts a widget class and copies the instance. The call
            # to configure() below makes that copy match this field.
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
        # Configure the copy that Django made, not the widget that the caller
        # gave.
        self.widget.configure(form_class)

    @staticmethod
    def initial_value(value: object) -> dict[str, object]:
        """Return the initial value as a dict, or raise ``InvalidInitialValueError``."""
        if value is None or value == "":
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        raise InvalidInitialValueError("initial must be a mapping of values")

    def to_python(self, value: object) -> dict[str, object]:
        """Return the value as a dict, and refuse a value that is not a mapping.

        The widget extracted the children already, so this method does no work
        on keys.
        """
        if value is None or value == "":
            return {}
        if not isinstance(value, Mapping):
            raise MappingInputValidationError(self.error_messages["invalid"])
        return dict(value)

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert each member back from its hidden initial value."""
        # to_python() gives a mapping of members here, or raises for other input.
        value = cast(dict[str, object], super().children_from_hidden_initial(value))
        for name, child_field in self.widget.fields.items():
            # A file has no text form in a hidden input, so keep the value of a
            # FileField child as it is.
            if name in value and not isinstance(child_field, FileField):
                value[name] = self._hidden_initial_to_python(child_field, value[name])
        return value

    def _clean_form(self, form: BaseForm) -> dict[str, object]:
        """Return the cleaned data of the child Form, or raise its errors.

        Django keeps the leaf messages of a composite error only, so this
        method makes one ``ItemValidationError`` for each message. Each message
        then keeps the name of the child that it came from.
        """
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
        """Clean a mapping of values that a caller collected.

        The child Form gets ``_ValueBoundField``, because this input holds
        Python values under child names and no prefixed input names. The shared
        budget protects nested sequence rows that bypass Django request parsing.
        """
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
        """Clean the prefixed child Form of a bound outer form.

        The child Form cleans the input when the browser sent data. It
        also cleans the input when the initial data holds files only.
        Two other cases go back to the normal Django path:

        - A value that is not a mapping. The base field turns this into
          the "invalid" error.
        - An empty value with no bound subform. The base field turns
          this into "required", or into the empty default.

        One scope makes sequence descendants share the aggregate-row budget:
        Django formsets cap each level but not nested-row work.
        """
        assert isinstance(bound_field, MappingBoundField), "for mypy"
        if self.disabled:
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        value = bound_field.data
        if not isinstance(value, Mapping) or (
            not value and not bound_field.is_bound_subform
        ):
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        return self._clean_form(bound_field.subform)

    def bound_data(self, data: object, initial: object) -> object:
        """Bind submitted members with their matching initial values."""
        try:
            initial = self.initial_value(initial)
            if self.disabled:
                return initial
            data = self.to_python(data)
            return {
                name: field.bound_data(data.get(name), initial.get(name))
                for name, field in self.widget.fields.items()
            }
        except (InvalidInitialValueError, ValidationError):
            # BoundField.value() calls this method during a render of an
            # invalid form. Keep forged input in the normal Django channel, so
            # that the user sees what the browser sent.
            return super().bound_data(data, initial)

    def prepare_value(self, value: object) -> object:
        """Prepare each mapping member for widget rendering.

        The shared scope clips nested sequence descendants before recursive
        preparation, which Django's per-formset limits cannot do.
        """
        try:
            value = self.initial_value(value)
            return {
                name: field.prepare_value(value[name])
                for name, field in self.widget.fields.items()
                if name in value
            }
        except (InvalidInitialValueError, ValidationError):
            return super().prepare_value(value)

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare mapping members using child-field change semantics."""
        if self.disabled:
            return False
        # A value that no field can read counts as a change. A change that the
        # form misses would lose data, and an extra change costs one save.
        try:
            initial = self.initial_value(initial)
            data = self.to_python(data)
        except (InvalidInitialValueError, ValidationError):
            return True
        for name, field in self.widget.fields.items():
            try:
                if field.has_changed(initial.get(name), data.get(name)):
                    return True
            except ValidationError:
                return True
        return False


DictField = MappingField
FormField = MappingField
Subform = MappingField
