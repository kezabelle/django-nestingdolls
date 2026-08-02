from __future__ import annotations

from contextvars import ContextVar
from enum import StrEnum
from typing import Self


class FormLayout(StrEnum):
    div = "div"
    p = "p"
    table = "table"
    ul = "ul"

    @classmethod
    def current(cls) -> Self:
        return active_form_layout.get() or cls.div


active_form_layout: ContextVar[FormLayout | None] = ContextVar(
    "active_form_layout",
    default=None,
)


def form_layout_from_template_name(template_name: str | None) -> FormLayout | None:
    if template_name == "django/forms/div.html":
        return FormLayout.div
    if template_name == "django/forms/p.html":
        return FormLayout.p
    if template_name == "django/forms/table.html":
        return FormLayout.table
    if template_name == "django/forms/ul.html":
        return FormLayout.ul
    return None
