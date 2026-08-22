"""Reusable outputs form fixtures for test cohorts."""

from __future__ import annotations

import dataclasses
from typing import NamedTuple

from django import forms

import nestingdolls


class PointWithRemovedYForm(forms.Form):
    """This form has required integer x and y fields and removes y at setup."""

    x = forms.IntegerField()
    y = forms.IntegerField()

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields.pop("y")


class PointWithExtraFieldForm(forms.Form):
    """This form has a required integer x field and optional integer extra field."""

    x = forms.IntegerField()

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["extra"] = forms.IntegerField(required=False)


class PointWithZForm(forms.Form):
    """This form has required integer x and z fields."""

    x = forms.IntegerField()
    z = forms.IntegerField()


@dataclasses.dataclass
class DataclassPoint:  # noqa: D101
    x: int
    y: int


class OutputPointForm(forms.Form):
    """This form has required integer x and y fields."""

    x = forms.IntegerField()
    y = forms.IntegerField()


class RequiredDataclassPointForm(forms.Form):
    """This form has a required dataclass point."""

    point = nestingdolls.DataclassField(OutputPointForm, output=DataclassPoint)


class OptionalDataclassPointForm(forms.Form):
    """This form has an optional dataclass point."""

    point = nestingdolls.DataclassField(
        OutputPointForm, output=DataclassPoint, required=False
    )


class DisabledDataclassPointForm(forms.Form):
    """This form has a disabled dataclass point."""

    point = nestingdolls.DataclassField(
        OutputPointForm, output=DataclassPoint, disabled=True
    )


class NamedTuplePoint(NamedTuple):  # noqa: D101
    x: int
    y: int


class RequiredNamedTuplePointForm(forms.Form):
    """This form has a required named tuple point."""

    point = nestingdolls.NamedTupleField(OutputPointForm, output=NamedTuplePoint)


class OptionalNamedTuplePointForm(forms.Form):
    """This form has an optional named tuple point."""

    point = nestingdolls.NamedTupleField(
        OutputPointForm, output=NamedTuplePoint, required=False
    )


class DisabledNamedTuplePointForm(forms.Form):
    """This form has a disabled named tuple point."""

    point = nestingdolls.NamedTupleField(
        OutputPointForm, output=NamedTuplePoint, disabled=True
    )
