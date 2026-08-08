from __future__ import annotations

from contextvars import ContextVar
from enum import StrEnum
from functools import wraps
from typing import Any, Self

from django.forms.forms import BaseForm
from django.forms.renderers import BaseRenderer
from django.forms.utils import RenderableMixin
from django.utils.safestring import SafeString

active_form_layout: ContextVar[FormLayout | None] = ContextVar(
    "active_form_layout",
    default=None,
)


class FormLayout(StrEnum):
    div = "div"
    p = "p"
    table = "table"
    ul = "ul"

    @classmethod
    def current(cls) -> Self:
        return active_form_layout.get() or cls.div

    @staticmethod
    def set(value: FormLayout) -> object:
        return active_form_layout.set(value)

    @classmethod
    def from_template_name(cls, t: str | None, /) -> FormLayout | None:
        if t == BaseForm.template_name_div:
            return cls.div
        if t == BaseForm.template_name_p:
            return cls.p
        if t == BaseForm.template_name_ul:
            return cls.ul
        if t == BaseForm.template_name_table:
            return cls.table
        return None


def install_form_rendering_patch() -> None:
    if bool(getattr(BaseForm, "nestingdolls_render_patch_installed", False)):
        return

    original_render = BaseForm.render
    BaseForm.nestingdolls_original_render = original_render  # type: ignore[attr-defined]

    @wraps(original_render)
    def render_with_form_layout(
        self: RenderableMixin,
        template_name: str | None = None,
        context: dict[str, Any] | None = None,
        renderer: BaseRenderer | type[BaseRenderer] | None = None,
    ) -> SafeString:
        layout = FormLayout.from_template_name(template_name)
        if layout is None:
            return original_render(self, template_name, context, renderer)
        token = active_form_layout.set(layout)
        try:
            return original_render(self, template_name, context, renderer)
        finally:
            active_form_layout.reset(token)

    BaseForm.render = render_with_form_layout  # type: ignore[method-assign]
    BaseForm.nestingdolls_render_patch_installed = True  # type: ignore[attr-defined]
