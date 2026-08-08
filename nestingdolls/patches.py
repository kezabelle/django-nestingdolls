"""Give the layout of the outer form to the composite widget templates.

A composite widget has one template for each of Django's four form layouts.
Django selects a form template when it renders a form, but it gives that
choice to the form template only. A widget cannot read it. This module keeps
the layout of the current render in a context variable, and it patches
``BaseForm.render`` to set that variable.
"""

from __future__ import annotations

from contextvars import ContextVar
from enum import StrEnum
from functools import wraps
from typing import Any, Self, cast

from django.forms.forms import BaseForm
from django.forms.renderers import BaseRenderer
from django.forms.utils import RenderableMixin
from django.utils.safestring import SafeString

active_form_layout: ContextVar[FormLayout | None] = ContextVar(
    "active_form_layout",
    default=None,
)


class FormLayout(StrEnum):
    """Name the four form layouts that Django supplies.

    The value of a member is the file name of the widget template for that
    layout, without the extension. ``CompositeWidget.template_name`` in
    ``_shared.py`` puts the value into the template path.
    """

    div = "div"
    p = "p"
    table = "table"
    ul = "ul"

    @classmethod
    def current(cls) -> Self:
        """Return the layout of the current render, or ``div``.

        ``div`` is the default layout of Django, so a render that this module
        did not patch, and a direct call to a widget, also get the div
        templates.
        """
        return active_form_layout.get() or cls.div

    @staticmethod
    def set(value: FormLayout) -> object:
        """Set the layout of the current context and return the reset token.

        Code that renders a widget without a form can select a layout with this
        method. Give the token to ``active_form_layout.reset()`` after the
        render.
        """
        return active_form_layout.set(value)

    @classmethod
    def from_template_name(cls, t: str | None, /) -> FormLayout | None:
        """Return the layout of one Django form template, or None for another.

        A caller can give a template name of its own. That template keeps the
        layout that is already set.
        """
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
    """Patch ``BaseForm.render`` so that it records the layout of the render.

    ``NestingDollsConfig.ready()`` calls this function one time. Django has no
    hook that tells a widget which form template renders it, and a composite
    widget template must agree with the form around it. The patch adds the
    record of the layout, and it keeps all other Django behavior.

    ``RenderableMixin`` binds ``__str__`` and ``__html__`` to the
    ``render`` function object. It does this at class-creation time.
    Replacing only ``render`` leaves ``{{ form }}`` and ``str(form)`` on
    the unpatched function. So this patch replaces all three names with
    the wrapper.
    """

    # ready() can run more than one time in one process. Patch one time only.
    if bool(getattr(BaseForm, "nestingdolls_render_patch_installed", False)):
        return

    original_render = BaseForm.render
    # Keep the original method. Tests restore it, and a second patch must not
    # wrap this wrapper.
    BaseForm.nestingdolls_original_render = original_render  # type: ignore[attr-defined]

    @wraps(original_render)
    def render_with_form_layout(
        self: RenderableMixin,
        template_name: str | None = None,
        context: dict[str, Any] | None = None,
        renderer: BaseRenderer | type[BaseRenderer] | None = None,
    ) -> SafeString:
        """Record the layout of this render, then call the original method."""
        # Resolve the template Django uses. RenderableMixin.render falls
        # back to self.template_name when template_name is None. So
        # {{ form }}, str(form), and form.render() can all arrive here
        # with None, and still render a named Django layout.
        # BaseForm.template_name is the renderer's form_template_name. A
        # renderer can change that name.
        form = cast(BaseForm, self)
        layout = FormLayout.from_template_name(template_name or form.template_name)
        # The template name is not one of Django's four. Keep the layout of the
        # render around this one, because a custom template can hold a form of
        # any layout.
        if layout is None:
            return original_render(self, template_name, context, renderer)
        token = active_form_layout.set(layout)
        try:
            return original_render(self, template_name, context, renderer)
        finally:
            # Reset the value, because a form can render inside another form.
            active_form_layout.reset(token)

    BaseForm.render = render_with_form_layout  # type: ignore[method-assign]
    BaseForm.__str__ = render_with_form_layout  # type: ignore[method-assign]
    BaseForm.__html__ = render_with_form_layout  # type: ignore[method-assign]
    BaseForm.nestingdolls_render_patch_installed = True  # type: ignore[attr-defined]
