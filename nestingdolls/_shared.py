from __future__ import annotations

from collections.abc import Mapping

from django.forms.widgets import Widget

from nestingdolls.rendering import FormLayout


class CompositeWidget(Widget):
    _template_name: str

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
