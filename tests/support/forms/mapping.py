"""Reusable mapping form fixtures for test cohorts."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

import nestingdolls


class MappingRootSubmissionLimitValuesForm(forms.Form):
    """This form has optional boolean lists named first and second."""

    first = nestingdolls.ListField(
        forms.BooleanField(required=False),
        required=False,
        max_length=10,
        absolute_max=10,
    )
    second = nestingdolls.ListField(
        forms.BooleanField(required=False),
        required=False,
        max_length=10,
        absolute_max=10,
    )


class MappingRootSubmissionLimitForm(forms.Form):
    """This form has a mapping named values."""

    values = nestingdolls.DictField(MappingRootSubmissionLimitValuesForm)


class SparseAssetRowForm(forms.Form):
    """This form has optional text label and file upload fields."""

    label = forms.CharField(required=False)
    upload = forms.FileField(required=False)


class MappingPointForm(forms.Form):
    """This form has required integer a and optional text label fields."""

    a = forms.IntegerField()
    label = forms.CharField(required=False)


class RequiredMappingPointForm(forms.Form):
    """This form has a required point mapping named point."""

    point = nestingdolls.MappingField(MappingPointForm)


class HiddenInitialMappingPointForm(forms.Form):
    """This form has a point mapping named point with hidden initial data."""

    point = nestingdolls.MappingField(MappingPointForm, show_hidden_initial=True)


class OptionalMappingPointForm(forms.Form):
    """This form has an optional point mapping named point."""

    point = nestingdolls.MappingField(MappingPointForm, required=False)


class MappingOptionalPointsForm(forms.Form):
    """This form has required and optional point mappings."""

    required_point = nestingdolls.MappingField(MappingPointForm)
    optional_point = nestingdolls.MappingField(MappingPointForm, required=False)


class ValidatedMappingPointForm(forms.Form):
    """This form has an optional point mapping named point."""

    @staticmethod
    def reject_two(value: object) -> object:  # noqa: D102
        if value["a"] == 2:
            raise ValidationError("No two.", code="no_two")

    point = nestingdolls.MappingField(
        MappingPointForm,
        required=False,
        validators=[reject_two],
    )


class PrefixedMappingPointForm(forms.Form):
    """This form has a point mapping named point."""

    point = nestingdolls.MappingField(MappingPointForm)


class DisabledMappingPointForm(forms.Form):
    """This form has a disabled point mapping named point with initial data."""

    point = nestingdolls.MappingField(
        MappingPointForm,
        disabled=True,
        initial={"a": 8, "label": "initial"},
    )


class MappingAssetChildForm(forms.Form):
    """This form has required text title and optional file upload fields."""

    title = forms.CharField()
    upload = forms.FileField(required=False)


class MappingAssetForm(forms.Form):
    """This form has an asset mapping named asset."""

    asset = nestingdolls.MappingField(MappingAssetChildForm)


class MappingFileChangeChildForm(forms.Form):
    """This form has an optional file document field."""

    document = forms.FileField(required=False)


class MappingFileChangeForm(forms.Form):
    """This form has an optional asset mapping with hidden initial data."""

    asset = nestingdolls.MappingField(
        MappingFileChangeChildForm,
        required=False,
        initial={"document": "saved.txt"},
        show_hidden_initial=True,
    )


class MultipleFileInput(forms.ClearableFileInput):
    """Read all files for one child input."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Clean each file of a child that accepts more than one file."""

    widget = MultipleFileInput

    def clean(self, data: object, initial: object = None) -> object:  # noqa: D102
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class RepeatedFileMappingChildForm(forms.Form):
    """This form has an optional multiple file upload field."""

    upload = MultipleFileField(required=False)


class RepeatedFileMappingForm(forms.Form):
    """This form has an optional asset mapping named asset."""

    asset = nestingdolls.MappingField(RepeatedFileMappingChildForm, required=False)


class MappingHookChildForm(forms.Form):
    """This form has a required integer a field."""

    a = forms.IntegerField()

    def clean_a(self) -> object:  # noqa: D102
        return self.cleaned_data["a"] + 1

    def clean(self) -> object:  # noqa: D102
        cleaned_data = super().clean()
        cleaned_data["double"] = cleaned_data["a"] * 2
        return cleaned_data


class MappingHookForm(forms.Form):
    """This form has a mapping named value."""

    value = nestingdolls.MappingField(MappingHookChildForm)


class MappingNonFieldErrorChildForm(forms.Form):
    """This form has a required integer a field."""

    a = forms.IntegerField()

    def clean(self) -> object:  # noqa: D102
        cleaned_data = super().clean()
        if cleaned_data.get("a") == 2:
            raise forms.ValidationError("Two is unavailable.", code="unavailable")
        return cleaned_data


class MappingNonFieldErrorForm(forms.Form):
    """This form has a mapping named value."""

    value = nestingdolls.MappingField(MappingNonFieldErrorChildForm)


class TrippableMappingPointChildForm(forms.Form):
    """This form has an optional integer a field."""

    a = forms.IntegerField(required=False)

    def clean(self) -> object:  # noqa: D102
        if self.cleaned_data.get("a") == 9:
            raise ValidationError("Whole child is wrong.")
        return super().clean()


class TrippableMappingPointForm(forms.Form):
    """This form has a point mapping named point."""

    point = nestingdolls.MappingField(TrippableMappingPointChildForm)


class SequenceIntegerTagsForm(forms.Form):
    """This form has an integer list named tags."""

    tags = nestingdolls.ListField(forms.IntegerField())


class MappingIntegerTagsForm(forms.Form):
    """This form has a mapping named point with integer tags."""

    point = nestingdolls.DictField(SequenceIntegerTagsForm)


class MappingRecordRowForm(forms.Form):
    """This form has a required text name field."""

    name = forms.CharField()


class SequenceOfMappingRecordsForm(forms.Form):
    """This form has a record mapping list named records."""

    records = nestingdolls.ListField(nestingdolls.DictField(MappingRecordRowForm))


class MappingRecordPayloadForm(forms.Form):
    """This form has a record list mapping named payload."""

    payload = nestingdolls.DictField(SequenceOfMappingRecordsForm)
