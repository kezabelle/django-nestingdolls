# crosshair: analysis_kind=PEP316

from __future__ import annotations

from typing import cast

import django
from django import forms
from django.conf import settings

import nestingdolls

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=("nestingdolls",),
        USE_I18N=False,
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()


class _IntegerForm(forms.Form):
    a = forms.IntegerField()


class _AjunkForm(forms.Form):
    ajunk = forms.IntegerField()


class _IntegerListForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField(), required=False)


class _RequiredIntegerMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerForm)


class _OptionalIntegerMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerForm, required=False)


class _AjunkMappingForm(forms.Form):
    value = nestingdolls.MappingField(_AjunkForm)


class _NestedSequenceMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerListForm)


def _integer_outcome(form: forms.Form) -> tuple[str, int]:
    if form.is_valid():
        cleaned = cast(dict[str, object], form.cleaned_data["value"])
        return ("ok", cast(int, cleaned["a"]))
    error = form.errors.as_data()["value"][0]
    return (error.code or "invalid", 0)


def actual_alias_collision(
    first_style: int, first: int, second_style: int, second: int
) -> tuple[str, int]:
    if not 0 <= first_style <= 2 or not 0 <= second_style <= 2:
        return ("invalid_style", 0)
    keys = ("value-a", "value.a", "value[a]")
    data: dict[str, object] = {}
    data[keys[first_style]] = str(first)
    data[keys[second_style]] = str(second)
    return _integer_outcome(_RequiredIntegerMappingForm(data))


def model_alias_collision(
    first_style: int, first: int, second_style: int, second: int
) -> tuple[str, int]:
    if not 0 <= first_style <= 2 or not 0 <= second_style <= 2:
        return ("invalid_style", 0)
    del first_style, first, second_style
    return ("ok", second)


def prove_alias_collision(
    first_style: int, first: int, second_style: int, second: int
) -> bool:
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    post[]: __return__
    """
    return actual_alias_collision(
        first_style, first, second_style, second
    ) == model_alias_collision(first_style, first, second_style, second)


def actual_mapping_presence(
    required: bool, present: bool, value: int
) -> tuple[str, int]:
    form_class = (
        _RequiredIntegerMappingForm if required else _OptionalIntegerMappingForm
    )
    form = form_class({"value": {"a": str(value)}} if present else {})
    if not form.is_valid():
        error = form.errors.as_data()["value"][0]
        return (error.code or "invalid", 0)
    cleaned = cast(dict[str, object], form.cleaned_data["value"])
    return ("ok", cast(int, cleaned.get("a", 0)))


def model_mapping_presence(
    required: bool, present: bool, value: int
) -> tuple[str, int]:
    if not present and required:
        return ("required", 0)
    return ("ok", value if present else 0)


def prove_mapping_presence(required: bool, present: bool, value: int) -> bool:
    """post[]: __return__"""
    return actual_mapping_presence(required, present, value) == model_mapping_presence(
        required, present, value
    )


def actual_malformed_bracket_suffix(value: int) -> str:
    form = _AjunkMappingForm({"value[a]junk": str(value)})
    if form.is_valid():
        return "ok"
    return form.errors.as_data()["value"][0].code or "invalid"


def model_malformed_bracket_suffix(value: int) -> str:
    del value
    return "required"


def prove_malformed_bracket_suffix(value: int) -> bool:
    """post[]: __return__"""
    return actual_malformed_bracket_suffix(value) == model_malformed_bracket_suffix(
        value
    )


def actual_mapping_has_changed(initial: int, submitted: int) -> bool:
    form = _OptionalIntegerMappingForm(
        {"value-a": str(submitted)}, initial={"value": {"a": initial}}
    )
    return form.has_changed()


def model_mapping_has_changed(initial: int, submitted: int) -> bool:
    return initial != submitted


def prove_mapping_has_changed(initial: int, submitted: int) -> bool:
    """post[]: __return__"""
    return actual_mapping_has_changed(initial, submitted) == model_mapping_has_changed(
        initial, submitted
    )


def actual_nested_sequence(first: int, second: int) -> tuple[int, int]:
    form = _NestedSequenceMappingForm(
        {"value.values.0": str(first), "value[values][1]": str(second)}
    )
    if not form.is_valid():
        return (0, 0)
    cleaned = cast(dict[str, object], form.cleaned_data["value"])
    values = cast(list[int], cleaned["values"])
    return (values[0], values[1])


def model_nested_sequence(first: int, second: int) -> tuple[int, int]:
    return (first, second)


def prove_nested_sequence(first: int, second: int) -> bool:
    """post[]: __return__"""
    return actual_nested_sequence(first, second) == model_nested_sequence(first, second)
