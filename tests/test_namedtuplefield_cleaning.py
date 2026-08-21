"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    NamedTuplePoint,
    NamedTuplePointForm,
    SimpleTestCase,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class NamedTupleFieldCleaningTestCase(SimpleTestCase):
    """Make sure ``NamedTupleField`` cleans a submission to one named tuple.

    Each test examines the cleaned value, the validator input, or the error code
    for required, optional, and disabled fields."""

    def test_clean_builds_the_namedtuple_output(self):
        """Cleaning a whole Python value returns one output instance."""
        field = nestingdolls.NamedTupleField(
            NamedTuplePointForm, output=NamedTuplePoint
        )
        self.assertIs(field.output, NamedTuplePoint)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertIsInstance(cleaned, NamedTuplePoint)
        self.assertEqual(cleaned, NamedTuplePoint(x=1, y=2))

    def test_cleaned_output_cleans_again(self):
        """The named tuple ``compress`` produced is valid input for ``clean``.

        ``initial_value`` already normalises a named tuple, so ``to_python``
        accepts the same shape.
        """
        field = nestingdolls.NamedTupleField(
            NamedTuplePointForm, output=NamedTuplePoint
        )

        once = field.clean({"x": "1", "y": "2"})

        self.assertEqual(field.clean(once), once)

    def test_required_field_rejects_missing_submission(self):
        """A required field with no submitted value reports "required"."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint
            )

        form = Form({})

        self.assertIs(form.is_valid(), False)
        self.assertIn("point", form.errors)

    def test_optional_field_cleans_missing_submission_to_none(self):
        """An optional field with no submitted value cleans to None."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint, required=False
            )

        form = Form({})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertIsNone(form.cleaned_data["point"])

    def test_submitted_form_data_builds_the_namedtuple_output(self):
        """A bound submission cleans to one namedtuple_type instance."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], NamedTuplePoint(x=3, y=4))

    def test_validators_receive_the_compressed_namedtuple(self):
        """A user validator gets the namedtuple, not the raw child-form dict.

        This is what makes the ``_clean_child_form`` compress-before-validate
        ordering in step 1 load-bearing rather than cosmetic.
        """
        seen = []

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(seen, [NamedTuplePoint(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self):
        """A disabled field cleans its initial named tuple value. It does not clean submitted input."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm,
                output=NamedTuplePoint,
                disabled=True,
                initial=NamedTuplePoint(x=1, y=2),
            )

        form = Form({"point-x": "9", "point-y": "9"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], NamedTuplePoint(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self):
        """A required disabled field with no initial value reports ``required``."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint, disabled=True
            )

        form = Form({"point-x": "1", "point-y": "2"})

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "required")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
