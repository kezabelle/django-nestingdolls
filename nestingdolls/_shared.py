from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Self

from django.forms import Field
from django.forms.widgets import Widget

from nestingdolls.rendering import FormLayout


class CompositeWidget(Widget):
    _template_name: str
    input_type: str | None = None

    def hidden_widget(self) -> Self:
        """Return an independent hidden copy of this composite widget."""
        widget: Self = copy.deepcopy(self)
        widget.input_type = "hidden"
        return widget

    @staticmethod
    def _hidden_child_widget(field: Field) -> Widget:
        """Return the field's hidden widget, preserving composite behavior."""
        widget: Widget = field.widget
        if isinstance(widget, CompositeWidget):
            return widget.hidden_widget()
        return field.hidden_widget()

    def _normalize_hidden_initial(self, field: Field, value: object) -> object:
        """Convert one submitted hidden value to its Python form."""
        return field.to_python(value)

    @property
    def template_name(self) -> str:
        return self._template_name.format(layout=FormLayout.current().value)

    @template_name.setter
    def template_name(self, value: str) -> None:
        self._template_name = value

    def value_omitted_from_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether all supported composite inputs are absent."""
        return not (
            self._normalize_mapping(data, name) or self._normalize_mapping(files, name)
        )

    def _normalize_mapping(
        self, data: Mapping[str, object], name: str
    ) -> Mapping[str, object]:
        raise NotImplementedError

    def use_required_attribute(self, initial: object) -> bool:
        """Let child fields own HTML required attributes."""
        return False

    def id_for_label(self, id_: str) -> str:
        """Suppress label targeting for the composite widget."""
        return ""
