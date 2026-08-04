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


class _IntegerListForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField(), required=False)


class _RequiredIntegerMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerForm)


class _OptionalIntegerMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerForm, required=False)


class _NestedSequenceMappingForm(forms.Form):
    value = nestingdolls.MappingField(_IntegerListForm)


_MAPPING_WIDGET = nestingdolls.MappingWidget(_IntegerForm)


def actual_mapping_key_normalization(key: str) -> str | None:
    """pre: len(key) <= 8"""
    normalized = _MAPPING_WIDGET._normalize_mapping({key: 1}, "value")
    return next(iter(normalized), None)


def model_mapping_key_normalization(key: str) -> str | None:
    """pre: len(key) <= 8"""
    for prefix in ("value-", "value."):
        if key.startswith(prefix) and len(key) > len(prefix):
            return f"value-{key.removeprefix(prefix)}"
    prefix = "value["
    if not key.startswith(prefix):
        return None
    end = key.find("]", len(prefix))
    if end < 0:
        return None
    child_name = key[len(prefix) : end]
    suffix = key[end + 1 :]
    if not child_name or suffix and suffix[0] not in "_-.[":
        return None
    return f"value-{child_name}{suffix}"


def prove_mapping_key_normalization(key: str) -> bool:
    """pre: len(key) <= 8
    post[]: __return__
    """
    return actual_mapping_key_normalization(key) == model_mapping_key_normalization(key)


def actual_mapping_direct_precedence(
    direct_data: bool, direct_files: bool, data_value: int, file_value: int
) -> tuple[str, int]:
    data: dict[str, object] = {"value": data_value} if direct_data else {"value-a": 1}
    files: dict[str, object] = {"value": file_value} if direct_files else {"value-a": 2}
    result = _MAPPING_WIDGET._value_from_normalized_data(data, files, "value")
    if isinstance(result, int):
        return ("direct", result)
    return (
        ("mapping", int(result.get("a", 0)))
        if isinstance(result, dict)
        else ("other", 0)
    )


def model_mapping_direct_precedence(
    direct_data: bool, direct_files: bool, data_value: int, file_value: int
) -> tuple[str, int]:
    if direct_data:
        return ("direct", data_value)
    if direct_files:
        return ("direct", file_value)
    return ("mapping", 1)


def prove_mapping_direct_precedence(
    direct_data: bool, direct_files: bool, data_value: int, file_value: int
) -> bool:
    """post[]: __return__"""
    return actual_mapping_direct_precedence(
        direct_data, direct_files, data_value, file_value
    ) == model_mapping_direct_precedence(
        direct_data, direct_files, data_value, file_value
    )


def actual_mapping_hostile_fallback(disabled: bool, initial: int, data: int) -> int:
    field = nestingdolls.MappingField(_IntegerForm, required=False, disabled=disabled)
    return cast(int, field.bound_data(data, initial))


def model_mapping_hostile_fallback(disabled: bool, initial: int, data: int) -> int:
    return initial if disabled else data


def prove_mapping_hostile_fallback(disabled: bool, initial: int, data: int) -> bool:
    """post[]: __return__"""
    return actual_mapping_hostile_fallback(
        disabled, initial, data
    ) == model_mapping_hostile_fallback(disabled, initial, data)


def _integer_outcome(form: forms.Form) -> tuple[str, int]:
    if form.is_valid():
        cleaned = cast(dict[str, object], form.cleaned_data["value"])
        return ("ok", cast(int, cleaned["a"]))
    error = form.errors.as_data()["value"][0]
    return (error.code or "invalid", 0)


def actual_alias_collision(
    first_style: int, first: int, second_style: int, second: int
) -> tuple[str, int]:
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    """
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
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    """
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
