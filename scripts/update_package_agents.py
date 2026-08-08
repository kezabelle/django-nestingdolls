from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

from django.utils.functional import cached_property

import nestingdolls
from nestingdolls import _shared, mappings

BEGIN_MARKER = "<!-- BEGIN GENERATED METHOD REFERENCE -->"
END_MARKER = "<!-- END GENERATED METHOD REFERENCE -->"
AGENTS_PATH = Path("nestingdolls/AGENTS.md")


def defined_methods(cls: type[object]) -> list[str]:
    """Return the method-like names that the class body defines, in source order.

    A dataclass generates its own special methods, so list only the methods a
    dataclass body writes.
    """
    written_only = dataclasses.is_dataclass(cls)
    return [
        name
        for name, value in cls.__dict__.items()
        if (
            inspect.isfunction(value)
            or isinstance(value, (staticmethod, classmethod, property, cached_property))
        )
        and not (written_only and name.startswith("__"))
    ]


def split_methods(cls: type[object]) -> tuple[list[str], list[str]]:
    overrides: list[str] = []
    introduced: list[str] = []
    parents = cls.__mro__[1:]
    for name in defined_methods(cls):
        if any(hasattr(parent, name) for parent in parents):
            overrides.append(name)
        else:
            introduced.append(name)
    return overrides, introduced


def render_method_group(
    title: str, methods: list[str], depth: str = "####"
) -> list[str]:
    if not methods:
        return []
    return [
        f"{depth} {title}",
        "",
        *(f"- `{name}`" for name in methods),
        "",
    ]


def nested_classes(cls: type[object]) -> list[type[object]]:
    """Return the helper classes that the class body defines, in source order.

    A class attribute can also hold a class, so use the qualified name to find
    the classes this body defines.
    """
    return [
        value
        for name, value in cls.__dict__.items()
        if isinstance(value, type)
        and name != "Media"
        and value.__qualname__ == f"{cls.__qualname__}.{name}"
    ]


def render_nested_class(owner: type[object], cls: type[object]) -> list[str]:
    overrides, introduced = split_methods(cls)
    title = f"#### {owner.__name__}.{cls.__name__}"
    if not overrides and not introduced:
        return [title, "", f"`{cls.__name__}` holds data only.", ""]
    return [
        title,
        "",
        *render_method_group("Overrides parent methods", overrides, "#####"),
        *render_method_group("Methods introduced here", introduced, "#####"),
    ]


def render_class_section(cls: type[object]) -> list[str]:
    overrides, introduced = split_methods(cls)
    nested = [
        line
        for value in nested_classes(cls)
        for line in render_nested_class(cls, value)
    ]
    if not overrides and not introduced and not nested:
        return [
            f"### {cls.__name__}",
            "",
            f"`{cls.__name__}` defines no methods of its own.",
        ]
    section = [
        f"### {cls.__name__}",
        "",
        *render_method_group("Overrides parent methods", overrides),
        *render_method_group("Methods introduced here", introduced),
        *nested,
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
        *render_class_section(_shared.CompositeField),
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
        *render_class_section(nestingdolls.FrozenSequenceField),
        "",
        *render_alias_section("TupleField", "FrozenSequenceField"),
        "",
        *render_class_section(nestingdolls.SetField),
        "",
        *render_inherited_section("FrozenSetField", "SetField"),
        "",
        *render_class_section(_shared.CompositeWidget),
        "",
        *render_class_section(nestingdolls.MappingWidget),
        "",
        *render_class_section(nestingdolls.SequenceWidget),
        "",
        *render_class_section(_shared.CompositeBoundField),
        "",
        *render_class_section(nestingdolls.MappingBoundField),
        "",
        *render_class_section(nestingdolls.SequenceBoundField),
        "",
        *render_class_section(mappings._ValueBoundField),
        "",
        END_MARKER,
    ]
    return "\n".join(sections)


def replace_generated_block(text: str, block: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != 1 or end_count != 1:
        raise RuntimeError(
            "Expected exactly one generated method reference block in nestingdolls/AGENTS.md"
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
