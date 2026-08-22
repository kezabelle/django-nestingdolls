"""Reusable sequence form fixtures for test cohorts."""

from __future__ import annotations

from django import forms

import nestingdolls

from .mapping import SparseAssetRowForm


class SequenceRootSubmissionLimitForm(forms.Form):
    """This form has a nested list of optional boolean values named outer."""

    outer = nestingdolls.ListField(
        nestingdolls.ListField(
            forms.BooleanField(required=False),
            max_length=10,
            absolute_max=10,
        ),
        max_length=10,
        absolute_max=10,
    )


class SequenceMappingSequenceSubmissionItemForm(forms.Form):
    """This form has an optional boolean list named tags."""

    tags = nestingdolls.ListField(
        forms.BooleanField(required=False),
        required=False,
        max_length=10,
        absolute_max=10,
    )


class SequenceMappingSequenceSubmissionLimitForm(forms.Form):
    """This form has an optional list of mappings named items."""

    items = nestingdolls.ListField(
        nestingdolls.DictField(SequenceMappingSequenceSubmissionItemForm),
        required=False,
        max_length=10,
        absolute_max=10,
    )


class SequenceSubmissionForm(forms.Form):
    """This form has an optional integer list named values."""

    values = nestingdolls.ListField(forms.IntegerField(), required=False)


class NestedIntegerValuesSequenceForm(forms.Form):
    """This form has a list of integer lists named values."""

    values = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))


class DisabledSequenceForm(forms.Form):
    """This form has a disabled integer list named values with initial value one."""

    values = nestingdolls.ListField(forms.IntegerField(), disabled=True, initial=[1])


class MaximumOneSequenceForm(forms.Form):
    """This form has an integer list named values with maximum length one."""

    values = nestingdolls.ListField(forms.IntegerField(), max_length=1)


class JSONSequenceSubmissionForm(forms.Form):
    """This form has an optional JSON value list named values."""

    values = nestingdolls.ListField(forms.JSONField(), required=False)


class AbsoluteMaximumSequenceForm(forms.Form):
    """This form has an integer list named values with limits one and two."""

    values = nestingdolls.ListField(forms.IntegerField(), max_length=1, absolute_max=2)


class SequencePointRowForm(forms.Form):
    """This form has required integer fields named a, b, and c."""

    a = forms.IntegerField()
    b = forms.IntegerField()
    c = forms.IntegerField()


class SequenceOfPointsForm(forms.Form):
    """This form has a point mapping list named values with limits five and ten."""

    values = nestingdolls.ListField(
        nestingdolls.DictField(SequencePointRowForm), max_length=5, absolute_max=10
    )


class SetSubmissionForm(forms.Form):
    """This form has an integer set named values with minimum and maximum two."""

    values = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)


class ExactNestedSequenceSubmissionForm(forms.Form):
    """This form has an optional nested text list named outer with maximum 1999."""

    outer = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), max_length=1999),
        required=False,
    )


class SparseAssetSequenceForm(forms.Form):
    """This form has an optional list of asset mappings named values."""

    values = nestingdolls.ListField(
        nestingdolls.MappingField(SparseAssetRowForm), required=False
    )


class NestedSequenceDeletionForm(forms.Form):
    """This form has an optional nested text list named values."""

    values = nestingdolls.ListField(
        nestingdolls.ListField(forms.CharField(required=False), required=False),
        required=False,
    )


class SequenceForm(forms.Form):
    """This form has an integer list named values."""

    values = nestingdolls.ListField(forms.IntegerField())


class OptionalRequiredTextSequenceForm(forms.Form):
    """This form has an optional list of required text values named values."""

    values = nestingdolls.ListField(forms.CharField(), required=False)


class OptionalSplitDateTimeSequenceForm(forms.Form):
    """This form has an optional date and time list named values."""

    values = nestingdolls.ListField(forms.SplitDateTimeField(), required=False)


class OptionalFileSequenceForm(forms.Form):
    """This form has an optional file list named uploads."""

    uploads = nestingdolls.ListField(forms.FileField(), required=False)


class BoundedNestedIntegerSequenceForm(forms.Form):
    """This form has a nested integer list named outer with limits ten and ten."""

    outer = nestingdolls.ListField(
        nestingdolls.ListField(forms.IntegerField(), max_length=10, absolute_max=10),
        max_length=10,
        absolute_max=10,
    )


class NestedIntegerSequenceForm(forms.Form):
    """This form has a nested integer list named outer."""

    outer = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))


class HiddenInitialIntegerSequenceForm(forms.Form):
    """This form has an integer list named values with hidden initial value one."""

    values = nestingdolls.ListField(
        forms.IntegerField(), initial=[1], show_hidden_initial=True
    )


class MinimumOneIntegerSequenceForm(forms.Form):
    """This form has an integer list named values with minimum length one."""

    values = nestingdolls.ListField(forms.IntegerField(), min_length=1)


class MinimumTwoIntegerSequenceForm(forms.Form):
    """This form has an integer list named values with minimum length two."""

    values = nestingdolls.ListField(forms.IntegerField(), min_length=2)


class SequenceHelpTextForm(forms.Form):
    """This form has a text list named values with help text and label."""

    values = nestingdolls.ListField(
        forms.CharField(help_text="ROWHELP", label="ROWLABEL")
    )


class StyledSequenceAndPlainTextForm(forms.Form):
    """This form has an integer list named values and text field named plain."""

    error_css_class = "has-error"
    required_css_class = "is-required"
    values = nestingdolls.ListField(forms.IntegerField())
    plain = forms.CharField()


class RequiredBCRowForm(forms.Form):
    """This form has required integer b and optional integer c fields."""

    b = forms.IntegerField()
    c = forms.IntegerField(required=False)


class RequiredBCSequenceForm(forms.Form):
    """This form has a list of b and c mappings named a."""

    a = nestingdolls.ListField(nestingdolls.DictField(RequiredBCRowForm))


class OptionalBCRowForm(forms.Form):
    """This form has optional integer b and c fields."""

    b = forms.IntegerField(required=False)
    c = forms.IntegerField(required=False)


class OptionalBCSequenceForm(forms.Form):
    """This form has a list of optional b and c mappings named a."""

    a = nestingdolls.ListField(nestingdolls.DictField(OptionalBCRowForm))


class RequiredBRowForm(forms.Form):
    """This form has a required integer b field."""

    b = forms.IntegerField()


class RequiredBSequenceForm(forms.Form):
    """This form has a list of b mappings named a."""

    a = nestingdolls.ListField(nestingdolls.DictField(RequiredBRowForm))
