"""Reusable composite form fixtures for test cohorts."""

from __future__ import annotations

from django import forms

import nestingdolls

from .mapping import MappingPointForm


class CompositePointAndSequenceForm(forms.Form):
    """This form has a point mapping and an integer list with minimum two."""

    point = nestingdolls.MappingField(MappingPointForm)
    values = nestingdolls.ListField(forms.IntegerField(), min_length=2)
