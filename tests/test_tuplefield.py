"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.core.exceptions import ValidationError
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import QueryDict
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class TupleFieldTestCase(CompositeFieldTestCase):
    """`TupleField` is `SequenceField` with one line changed: ``compress``.

    These tests cover that difference and nothing else.
    """

    def test_clean_returns_an_immutable_tuple(self) -> None:
        """It collects cleaned rows into a tuple, through clean() and a bound form."""
        field = nestingdolls.TupleField(forms.IntegerField())

        cleaned = field.clean(["1", "2"])

        self.assertIsInstance(cleaned, tuple)
        self.assertEqual(cleaned, (1, 2))
        with self.assertRaises(TypeError):
            cleaned[0] = 3  # type: ignore[index]

        class Form(forms.Form):
            values = nestingdolls.TupleField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2"
            )
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], (1, 2))
        self.assertIsInstance(form.cleaned_data["values"], tuple)

    def test_has_changed_compares_a_tuple_initial(self) -> None:
        """A tuple initial compares against submitted rows, order included."""
        field = nestingdolls.TupleField(forms.IntegerField(), required=False)

        self.assertIs(field.has_changed((1, 2), ["1", "2"]), False)
        self.assertIs(field.has_changed((1, 2), ["2", "1"]), True)
        self.assertIs(field.has_changed((1, 2), ["1"]), True)

    def test_cardinality_limits_apply_to_the_tuple(self) -> None:
        """Length limits are checked on the compressed value."""
        field = nestingdolls.TupleField(
            forms.IntegerField(), min_length=2, max_length=2
        )

        with self.assertRaises(ValidationError) as context:
            field.clean(["1"])
        self.assertEqual(context.exception.code, "min_length")
        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "2", "3"])
        self.assertEqual(context.exception.code, "max_length")

    def test_cleaned_output_cleans_again(self) -> None:
        """The tuple ``compress`` produced is valid input for ``clean``."""
        self.assertCleanedOutputCleansAgain(
            nestingdolls.TupleField(forms.IntegerField()), ["1", "2"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
