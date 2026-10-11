"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import dataclasses
import unittest

from django import forms
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.outputs import (
    DataclassPoint,
    DisabledDataclassPointForm,
    OptionalDataclassPointForm,
    OutputPointForm,
    RequiredDataclassPointForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class DataclassFieldCleaningTestCase(CompositeFieldTestCase):
    """Make sure ``DataclassField`` cleans a submission to one dataclass.

    Each test examines the cleaned value, the validator input, or the error code
    for required, optional, and disabled fields.
    """

    def test_clean_builds_the_dataclass_output(self) -> None:
        """Test clean builds the dataclass output."""
        field = nestingdolls.DataclassField(OutputPointForm, output=DataclassPoint)
        self.assertIs(field.output, DataclassPoint)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertEqual(cleaned, DataclassPoint(x=1, y=2))

    def test_cleaned_output_cleans_again(self) -> None:
        """The dataclass ``compress`` produced is valid input for ``clean``.

        ``initial_value`` already normalises a dataclass instance, so
        ``to_python`` accepts the same shape.
        """
        self.assertCleanedOutputCleansAgain(
            nestingdolls.DataclassField(OutputPointForm, output=DataclassPoint),
            {"x": "1", "y": "2"},
        )

    def test_required_field_rejects_missing_submission(self) -> None:
        """A required field with no submitted value reports ``required``."""
        form = RequiredDataclassPointForm({})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "point", "required")

    def test_optional_field_cleans_missing_submission_to_none(self) -> None:
        """Test optional field cleans missing submission to none."""
        form = OptionalDataclassPointForm({})

        self.assertFormValid(form)
        self.assertIsNone(form.cleaned_data["point"])

    def test_validators_receive_the_compressed_dataclass(self) -> None:
        """Test validators receive the compressed dataclass."""
        seen = []

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                OutputPointForm, output=DataclassPoint, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertFormValid(form)
        self.assertEqual(seen, [DataclassPoint(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self) -> None:
        """A disabled field cleans its initial dataclass value. It does not clean submitted input."""
        form = DisabledDataclassPointForm(
            {"point-x": "9", "point-y": "9"},
            initial={"point": DataclassPoint(x=1, y=2)},
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], DataclassPoint(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self) -> None:
        """A required disabled field with no initial value reports ``required``."""
        form = DisabledDataclassPointForm({"point-x": "1", "point-y": "2"})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "point", "required")

    def test_submission_the_dataclass_rejects_is_a_field_error_not_a_crash(
        self,
    ) -> None:
        """A user's ordinary submission must not crash ``is_valid()``.

        Each child value is valid on its own, so the child form accepts it. Only
        the dataclass's own ``__post_init__`` check rejects the combination, and
        that check runs when ``compress`` builds the output. Its ``ValueError``
        must become an error on the field, as a validator's would, instead of
        escaping ``is_valid()`` and turning user input into a server error.
        """

        # A booking window: the dataclass, not the form, knows that a window
        # cannot end before it starts.
        @dataclasses.dataclass
        class BookingWindow:
            start_hour: int
            end_hour: int

            def __post_init__(self) -> None:
                if self.end_hour < self.start_hour:
                    msg = "The window cannot end before it starts."
                    raise ValueError(msg)

        class BookingWindowForm(forms.Form):
            start_hour = forms.IntegerField()
            end_hour = forms.IntegerField()

        class BookingForm(forms.Form):
            window = nestingdolls.DataclassField(
                BookingWindowForm, output=BookingWindow
            )

        # A browser posts these values after the user types 17 and 9.
        form = BookingForm({"window-start_hour": "17", "window-end_hour": "9"})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "window", "invalid")
        self.assertEqual(
            form.errors["window"], ["The window cannot end before it starts."]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
