from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import cast

from django.core.exceptions import ValidationError
from django.forms import Field
from django.forms.boundfield import BoundField
from django.forms.utils import ErrorList
from django.forms.widgets import Widget
from django.utils.functional import cached_property
from django.utils.safestring import SafeString

from nestingdolls.errors import ItemValidationError
from nestingdolls.patches import FormLayout


class CompositeWidget(Widget):
    _template_name: str
    input_type: str | None = None
    # Submitted state that Widget.render() cannot pass to get_context(). The
    # bound field sets it before each render. A Form deep-copies its fields, so
    # this state stays with one field of one form.
    hidden_initial_value: object = None

    def _child_widget(self, field: Field) -> Widget:
        """Return the widget one child renders with, hidden when this widget is."""
        widget: Widget = field.widget
        if self.input_type != "hidden":
            return widget
        # Test the hidden mode of this widget. Do not test is_hidden. A child
        # widget can be hidden already and keep its own attributes and choices.
        # Django's field.hidden_widget() makes a new HiddenInput and loses them.
        return field.hidden_widget()

    @property
    def template_name(self) -> str:
        return self._template_name.format(layout=FormLayout.current().value)

    @template_name.setter
    def template_name(self, value: str) -> None:
        self._template_name = value

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Return the submitted composite value extracted by child widgets."""
        return self._value_from_normalized_data(
            self._normalized_datadict(data, name),
            self._normalized_datadict(files, name) if files else {},
            name,
        )

    def value_omitted_from_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether all supported composite inputs are absent."""
        return not (
            self._normalized_datadict(data, name)
            or self._normalized_datadict(files, name)
        )

    def _normalized_datadict(
        self, data: Mapping[str, object], name: str
    ) -> Mapping[str, object]:
        raise NotImplementedError

    def _value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        raise NotImplementedError

    @staticmethod
    def _split_child_key(key: object, name: str) -> tuple[str, str] | None:
        """Split one supported child key spelling into its child token and suffix.

        The dash, dot, and bracket spellings all name one child of ``name``. This
        returns the text that identifies the child and the text that follows it,
        which each composite widget reads in its own way.
        """
        if not isinstance(key, str):
            return None
        for separator in ("-", ".", "["):
            prefix = f"{name}{separator}"
            if not key.startswith(prefix):
                continue
            remainder = key.removeprefix(prefix)
            if separator != "[":
                return (remainder, "") if remainder else None
            end = remainder.find("]")
            if end <= 0:
                return None
            suffix = remainder[end + 1 :]
            if suffix and suffix[0] not in "_-.[":
                return None
            return (remainder[:end], suffix)
        return None

    def use_required_attribute(self, initial: object) -> bool:
        """Let child fields own HTML required attributes."""
        return False

    def id_for_label(self, id_: str) -> str:
        """Suppress label targeting, as ``MultiWidget.id_for_label`` does."""
        return ""


class CompositeField(Field):
    """Hold the field behavior that mapping and sequence fields share."""

    widget: CompositeWidget

    # Django keeps a widget class here, but it only ever calls this attribute:
    # BoundField.as_hidden() and BoundField._has_changed() do field.hidden_widget().
    # A composite widget needs its child configuration, so build the copy here.
    def hidden_widget(self) -> CompositeWidget:  # type: ignore[override]
        """Return an independent copy of this field's widget that renders hidden."""
        widget = copy.deepcopy(self.widget)
        widget.input_type = "hidden"
        return widget

    @staticmethod
    def hidden_initial_to_python(field: Field, value: object, /) -> object:
        """Convert what one child's hidden initial widget submitted."""
        if isinstance(field, CompositeField):
            return field.children_from_hidden_initial(value)
        return field.to_python(value)

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert this field's children back from their hidden initial values."""
        return self.to_python(value)


class CompositeBoundField(BoundField):
    """Hold the bound-field behavior that mapping and sequence fields share."""

    field: CompositeField

    @property
    def _all_errors(self) -> ErrorList:
        """Return every error recorded for this field, child item errors included."""
        return super().errors

    @property
    def errors(self) -> ErrorList:
        """Return only errors owned by the outer composite field."""
        errors = self._all_errors
        if not errors:
            return errors
        field_errors = []
        for error in errors.as_data():
            if isinstance(error, ItemValidationError):
                continue
            field_errors.append(error)
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
        return self.field.widget._normalized_datadict(self.form.data, self.html_name)

    @cached_property
    def _file_input(self) -> Mapping[str, object]:
        """Cache normalized submitted files for this field."""
        if not self.form.files:
            return {}
        return self.field.widget._normalized_datadict(self.form.files, self.html_name)

    @cached_property
    def data(self) -> object:
        """Return the bound value extracted from normalized data and files."""
        return self.field.widget._value_from_normalized_data(
            self._data_input,
            self._file_input,
            self.html_name,
        )

    def as_widget(
        self,
        widget: Widget | None = None,
        attrs: dict[str, str | bool] | None = None,
        only_initial: bool = False,
    ) -> SafeString:
        """Give the widget the submitted state, then let Django render it."""
        widget = widget or self.field.widget
        if isinstance(widget, CompositeWidget):
            self._prepare_widget(widget, only_initial)
        return super().as_widget(widget, attrs, only_initial)

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Put the submitted state this render needs on the widget.

        Set all of the state each time. ``hidden_widget()`` copies the widget
        with the state of the last render, and a hidden initial render must not
        keep it.
        """
        widget.hidden_initial_value = (
            self._hidden_initial_value(widget)[0] if only_initial else None
        )

    def _hidden_initial_value(
        self, widget: CompositeWidget
    ) -> tuple[object, Mapping[str, object] | None]:
        """Return the submitted hidden initial value and the data it came from.

        Django only propagates a hidden initial when the initial name is a key of
        the submitted data. A composite submits child names instead, so read the
        value here. Django's value would be the current data, which would replace
        the hidden initial and hide a change.
        """
        name = self.html_initial_name
        data_input = widget._normalized_datadict(self.form.data, name)
        file_input = (
            widget._normalized_datadict(self.form.files, name)
            if self.form.files
            else {}
        )
        if data_input or file_input:
            return (
                widget._value_from_normalized_data(data_input, file_input, name),
                data_input,
            )
        return self.value(), None

    def _flat_initial_value(self, source: Mapping[str, object]) -> object | None:
        """Return an initial value rebuilt from flattened child keys, if any match."""
        normalized = self.field.widget._normalized_datadict(source, self.name)
        if not normalized:
            return None
        value: object = self.field.widget._value_from_normalized_data(
            normalized, {}, self.name
        )
        return value

    def _has_changed(self) -> bool:
        """Read hidden composite initial values through the composite widget."""
        if self.field.disabled:
            return False
        if not self.field.show_hidden_initial:
            return cast(bool, super()._has_changed())  # type: ignore[misc]
        widget = self.field.hidden_widget()
        try:
            initial_value = self.field.children_from_hidden_initial(
                widget.value_from_datadict(
                    self.form.data, self.form.files, self.html_initial_name
                )
            )
        except (TypeError, ValidationError):
            return True
        return self.field.has_changed(initial_value, self.data)
