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
        TIME_ZONE="UTC",
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


_MAPPING_WIDGET = nestingdolls.MappingWidget(_IntegerForm)


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
