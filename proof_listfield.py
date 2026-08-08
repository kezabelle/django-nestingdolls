# crosshair: analysis_kind=PEP316

from __future__ import annotations

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


_PARSER_WIDGET = nestingdolls.SequenceWidget(
    forms.CharField(required=False), max_length=2, absolute_max=4
)


def actual_sequence_direct_extraction(
    data_present: bool, files_present: bool, data: list[int], files: list[int]
) -> tuple[int, ...]:
    """pre: len(data) <= 6
    pre: len(files) <= 6
    """
    submitted_data: dict[str, object] = {"values": data} if data_present else {}
    submitted_files: dict[str, object] = {"values": files} if files_present else {}
    return tuple(
        _PARSER_WIDGET._value_from_normalized_data(
            submitted_data, submitted_files, "values"
        )
    )


def model_sequence_direct_extraction(
    data_present: bool, files_present: bool, data: list[int], files: list[int]
) -> tuple[int, ...]:
    """pre: len(data) <= 6
    pre: len(files) <= 6
    """
    if data_present:
        return tuple(data[:5])
    if files_present:
        return tuple(files[:5])
    return ()


def prove_sequence_direct_extraction(
    data_present: bool, files_present: bool, data: list[int], files: list[int]
) -> bool:
    """pre: len(data) <= 6
    pre: len(files) <= 6
    post[]: __return__
    """
    return actual_sequence_direct_extraction(
        data_present, files_present, data, files
    ) == model_sequence_direct_extraction(data_present, files_present, data, files)
