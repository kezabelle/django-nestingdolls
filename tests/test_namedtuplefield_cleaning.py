"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.outputs import (
    DisabledNamedTuplePointForm,
    NamedTuplePoint,
    OptionalNamedTuplePointForm,
    OutputPointForm,
    RequiredNamedTuplePointForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class NamedTupleFieldCleaningTestCase(CompositeFieldTestCase):
    """Make sure ``NamedTupleField`` cleans a submission to one named tuple.

    Each test examines the cleaned value, the validator input, or the error code
    for required, optional, and disabled fields.
    """

    def test_clean_builds_the_namedtuple_output(self) -> None:
        """Cleaning a whole Python value returns one output instance."""
        field = nestingdolls.NamedTupleField(OutputPointForm, output=NamedTuplePoint)
        self.assertIs(field.output, NamedTuplePoint)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertIsInstance(cleaned, NamedTuplePoint)
        self.assertEqual(cleaned, NamedTuplePoint(x=1, y=2))

    def test_cleaned_output_cleans_again(self) -> None:
        """The named tuple ``compress`` produced is valid input for ``clean``.

        ``initial_value`` already normalises a named tuple, so ``to_python``
        accepts the same shape.
        """
        self.assertCleanedOutputCleansAgain(
            nestingdolls.NamedTupleField(OutputPointForm, output=NamedTuplePoint),
            {"x": "1", "y": "2"},
        )

    def test_required_field_rejects_missing_submission(self) -> None:
        """A required field with no submitted value reports "required"."""
        form = RequiredNamedTuplePointForm({})

        self.assertFormInvalid(form)
        self.assertIn("point", form.errors)

    def test_optional_field_cleans_missing_submission_to_none(self) -> None:
        """An optional field with no submitted value cleans to None."""
        form = OptionalNamedTuplePointForm({})

        self.assertFormValid(form)
        self.assertIsNone(form.cleaned_data["point"])

    def test_submitted_form_data_builds_the_namedtuple_output(self) -> None:
        """A bound submission cleans to one namedtuple_type instance."""
        form = RequiredNamedTuplePointForm({"point-x": "3", "point-y": "4"})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], NamedTuplePoint(x=3, y=4))

    def test_validators_receive_the_compressed_namedtuple(self) -> None:
        """A user validator gets the namedtuple, not the raw child-form dict.

        This is what makes the ``_clean_child_form`` compress-before-validate
        ordering in step 1 load-bearing rather than cosmetic.
        """
        seen = []

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                OutputPointForm, output=NamedTuplePoint, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertFormValid(form)
        self.assertEqual(seen, [NamedTuplePoint(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self) -> None:
        """A disabled field cleans its initial named tuple value. It does not clean submitted input."""
        form = DisabledNamedTuplePointForm(
            {"point-x": "9", "point-y": "9"},
            initial={"point": NamedTuplePoint(x=1, y=2)},
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], NamedTuplePoint(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self) -> None:
        """A required disabled field with no initial value reports ``required``."""
        form = DisabledNamedTuplePointForm({"point-x": "1", "point-y": "2"})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "point", "required")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
