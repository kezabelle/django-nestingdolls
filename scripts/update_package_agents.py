from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

import nestingdolls

BEGIN_MARKER = "<!-- BEGIN GENERATED FIELD METHODS -->"
END_MARKER = "<!-- END GENERATED FIELD METHODS -->"
AGENTS_PATH = Path("nestingdolls/AGENTS.md")


def defined_methods(cls: type[object]) -> list[tuple[str, Callable[..., object]]]:
    methods: list[tuple[str, Callable[..., object]]] = []
    for name, value in cls.__dict__.items():
        if inspect.isfunction(value):
            methods.append((name, value))
    return methods


def split_methods(
    cls: type[object],
) -> tuple[
    list[tuple[str, Callable[..., object]]], list[tuple[str, Callable[..., object]]]
]:
    overrides: list[tuple[str, Callable[..., object]]] = []
    introduced: list[tuple[str, Callable[..., object]]] = []
    parents = cls.__mro__[1:]
    for name, value in defined_methods(cls):
        if any(hasattr(parent, name) for parent in parents):
            overrides.append((name, value))
        else:
            introduced.append((name, value))
    return overrides, introduced


def render_method(name: str, value: Callable[..., object]) -> str:
    return f"- `{name}{inspect.signature(value)}`"


def render_method_group(
    title: str, methods: list[tuple[str, Callable[..., object]]]
) -> list[str]:
    if not methods:
        return []
    return [
        f"#### {title}",
        "",
        *(render_method(name, value) for name, value in methods),
    ]


def render_class_section(cls: type[object]) -> list[str]:
    overrides, introduced = split_methods(cls)
    section = [
        f"### {cls.__name__}",
        "",
        *render_method_group("Overrides parent methods", overrides),
        *render_method_group("Methods introduced here", introduced),
    ]
    if section[-1] == "":
        section.pop()
    return section


def render_alias_section(name: str, target: str) -> list[str]:
    return [
        f"### {name}",
        "",
        f"Alias of `{target}`. It defines no methods of its own.",
    ]


def render_inherited_section(name: str, parent: str) -> list[str]:
    return [
        f"### {name}",
        "",
        f"`{name}` defines no methods of its own.",
        f"It inherits `{parent}` behavior.",
    ]


def render_generated_block() -> str:
    sections: list[str] = [
        BEGIN_MARKER,
        "",
        *render_class_section(nestingdolls.MappingField),
        "",
        *render_alias_section("DictField", "MappingField"),
        "",
        *render_alias_section("FormField", "MappingField"),
        "",
        *render_alias_section("Subform", "MappingField"),
        "",
        *render_class_section(nestingdolls.SequenceField),
        "",
        *render_alias_section("ListField", "SequenceField"),
        "",
        *render_class_section(nestingdolls.TupleField),
        "",
        *render_alias_section("FrozenSequenceField", "TupleField"),
        "",
        *render_class_section(nestingdolls.SetField),
        "",
        *render_inherited_section("FrozenSetField", "SetField"),
        "",
        END_MARKER,
    ]
    return "\n".join(sections)


def replace_generated_block(text: str, block: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != 1 or end_count != 1:
        raise RuntimeError(
            "Expected exactly one generated field-method block in nestingdolls/AGENTS.md"
        )
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER) + len(END_MARKER)
    return text[:start] + block + text[end:]


def main() -> None:
    original = AGENTS_PATH.read_text()
    updated = replace_generated_block(original, render_generated_block())
    if updated != original:
        AGENTS_PATH.write_text(updated)


if __name__ == "__main__":
    main()
