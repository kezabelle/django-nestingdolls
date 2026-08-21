"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    DataclassPoint,
    DataclassPointForm,
    SimpleTestCase,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class DataclassFieldCleaningTestCase(SimpleTestCase):
    """Make sure ``DataclassField`` cleans a submission to one dataclass.

    Each test examines the cleaned value, the validator input, or the error code
    for required, optional, and disabled fields."""

    def test_clean_builds_the_dataclass_output(self):
        field = nestingdolls.DataclassField(DataclassPointForm, output=DataclassPoint)
        self.assertIs(field.output, DataclassPoint)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertEqual(cleaned, DataclassPoint(x=1, y=2))

    def test_cleaned_output_cleans_again(self):
        """The dataclass ``compress`` produced is valid input for ``clean``.

        ``initial_value`` already normalises a dataclass instance, so
        ``to_python`` accepts the same shape.
        """
        field = nestingdolls.DataclassField(DataclassPointForm, output=DataclassPoint)

        once = field.clean({"x": "1", "y": "2"})

        self.assertEqual(field.clean(once), once)

    def test_required_field_rejects_missing_submission(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm, output=DataclassPoint
            )

        form = Form({})

        self.assertIs(form.is_valid(), False)
        self.assertIn("point", form.errors)

    def test_optional_field_cleans_missing_submission_to_none(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm, output=DataclassPoint, required=False
            )

        form = Form({})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertIsNone(form.cleaned_data["point"])

    def test_validators_receive_the_compressed_dataclass(self):
        seen = []

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm, output=DataclassPoint, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(seen, [DataclassPoint(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self):
        """A disabled field cleans its initial dataclass value. It does not clean submitted input."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm,
                output=DataclassPoint,
                disabled=True,
                initial=DataclassPoint(x=1, y=2),
            )

        form = Form({"point-x": "9", "point-y": "9"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], DataclassPoint(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self):
        """A required disabled field with no initial value reports ``required``."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm, output=DataclassPoint, disabled=True
            )

        form = Form({"point-x": "1", "point-y": "2"})

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "required")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
