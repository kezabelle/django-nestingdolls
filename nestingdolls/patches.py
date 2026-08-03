from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from django.forms import BaseForm

from nestingdolls.rendering import active_form_layout, form_layout_from_template_name

RenderMethod = Callable[[BaseForm, str | None, dict[str, Any] | None, Any], str]


def install_form_rendering_patch() -> None:
    if bool(getattr(BaseForm, "nestingdolls_render_patch_installed", False)):
        return

    original_render = cast(RenderMethod, BaseForm.render)
    BaseForm.nestingdolls_original_render = original_render

    def render_with_form_layout(
        self: BaseForm,
        template_name: str | None = None,
        context: dict[str, Any] | None = None,
        renderer: Any = None,
    ) -> str:
        layout = form_layout_from_template_name(template_name)
        if layout is None:
            return original_render(self, template_name, context, renderer)
        token = active_form_layout.set(layout)
        try:
            return original_render(self, template_name, context, renderer)
        finally:
            active_form_layout.reset(token)

    BaseForm.render = render_with_form_layout
    BaseForm.nestingdolls_render_patch_installed = True
