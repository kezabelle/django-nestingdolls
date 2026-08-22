"""Reusable hostile form fixtures for test cohorts."""

from __future__ import annotations

from django import forms

import nestingdolls

from .mapping import MappingPointForm


class NarrowIntegerSequenceForm(forms.Form):
    """This form has an optional integer list named values and limits three and five."""

    values = nestingdolls.ListField(
        forms.IntegerField(), required=False, max_length=3, absolute_max=5
    )


class TriplyNestedTextSequenceForm(forms.Form):
    """This form has an optional list of optional text lists named values."""

    values = nestingdolls.ListField(
        nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        ),
        required=False,
    )


class ManySiblingNestedTextSequenceForm(forms.Form):
    """This form has optional nested text lists named a through h."""

    a = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    b = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    c = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    d = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    e = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    f = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    g = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )
    h = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )


class NestedTypedIntegerSequenceForm(forms.Form):
    """This form has an optional list of integer lists named values."""

    values = nestingdolls.ListField(
        nestingdolls.ListField(
            forms.IntegerField(), required=False, min_length=2, max_length=4
        ),
        required=False,
    )


class AggregateNestedTextSequenceForm(forms.Form):
    """This form has an optional nested text list named values and limits fifty."""

    values = nestingdolls.ListField(
        nestingdolls.ListField(
            forms.CharField(required=False), max_length=50, absolute_max=50
        ),
        required=False,
        max_length=50,
        absolute_max=50,
    )


class OptionalJSONSetForm(forms.Form):
    """This form has an optional JSON set named values."""

    values = nestingdolls.SetField(forms.JSONField(), required=False)


class TripleMappingLeafForm(forms.Form):
    """This form has a required integer field named leaf."""

    leaf = forms.IntegerField()


class TripleMappingLevelOneForm(forms.Form):
    """This form has a required mapping named child."""

    child = nestingdolls.DictField(TripleMappingLeafForm)


class TripleMappingValueForm(forms.Form):
    """This form has a required mapping named value."""

    value = nestingdolls.DictField(TripleMappingLevelOneForm)


class OptionalTripleMappingLeafForm(forms.Form):
    """This form has an optional integer field named leaf."""

    leaf = forms.IntegerField(required=False)


class OptionalTripleMappingLevelOneForm(forms.Form):
    """This form has an optional mapping named child."""

    child = nestingdolls.DictField(OptionalTripleMappingLeafForm, required=False)


class OptionalTripleMappingValueForm(forms.Form):
    """This form has an optional mapping named value."""

    value = nestingdolls.DictField(OptionalTripleMappingLevelOneForm, required=False)


class OptionalIntegerSequenceValueForm(forms.Form):
    """This form has an optional integer list named rows."""

    rows = nestingdolls.ListField(forms.IntegerField(), required=False)


class OptionalIntegerSequenceMappingValueForm(forms.Form):
    """This form has an optional mapping named value."""

    value = nestingdolls.DictField(OptionalIntegerSequenceValueForm, required=False)


class OptionalChoiceValueForm(forms.Form):
    """This form has an optional multiple-choice field named choices."""

    choices = forms.MultipleChoiceField(
        choices=[("a", "a"), ("b", "b")], required=False
    )


class OptionalChoiceMappingValueForm(forms.Form):
    """This form has an optional mapping named value."""

    value = nestingdolls.DictField(OptionalChoiceValueForm, required=False)


class IntegerValuePointForm(forms.Form):
    """This form has a required integer field named a."""

    a = forms.IntegerField()


class PrefixedIntegerValueMappingForm(forms.Form):
    """This form has a required mapping named value."""

    value = nestingdolls.DictField(IntegerValuePointForm)


class OptionalPointValueForm(forms.Form):
    """This form has an optional point mapping named value."""

    value = nestingdolls.DictField(MappingPointForm, required=False)


class ManySiblingSequencesValueForm(forms.Form):
    """This form has an optional mapping named value."""

    value = nestingdolls.DictField(ManySiblingNestedTextSequenceForm, required=False)
