"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import dataclasses
import unittest

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.outputs import (
    DataclassPoint,
    OutputPointForm,
    PointWithExtraFieldForm,
    PointWithRemovedYForm,
    PointWithZForm,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class DataclassFieldConstructionTestCase(SimpleTestCase):
    """Make sure ``DataclassField`` accepts or rejects an ``output`` type.

    The field checks the ``output`` names against the fields that the child Form
    class declares.
    """

    def test_rejects_a_non_dataclass_output(self) -> None:
        """Test rejects a non dataclass output."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(OutputPointForm, output=tuple)

    def test_rejects_mismatched_output_names(self) -> None:
        """Test rejects mismatched output names."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(PointWithZForm, output=DataclassPoint)

    def test_rejects_an_output_with_non_constructor_fields(self) -> None:
        """Test rejects an output with non constructor fields."""

        @dataclasses.dataclass
        class PointWithDerivedValue:
            x: int
            y: int
            distance: int = dataclasses.field(init=False, default=0)

        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()
            distance = forms.IntegerField(required=False)

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(Form, output=PointWithDerivedValue)

    def test_infers_type_from_base_fields_and_fills_removed_fields(self) -> None:
        """Test infers type from base fields and fills removed fields."""
        cleaned = nestingdolls.DataclassField(PointWithRemovedYForm).clean({"x": "1"})

        self.assertIs(dataclasses.is_dataclass(cleaned), True)
        self.assertEqual(cleaned.x, 1)
        self.assertIsNone(cleaned.y)

    def test_custom_output_fills_a_field_removed_in_init(self) -> None:
        """A custom output has a name for a field that ``__init__`` removes from the Form."""
        cleaned = nestingdolls.DataclassField(
            PointWithRemovedYForm, output=DataclassPoint
        ).clean({"x": "1"})

        self.assertIsInstance(cleaned, DataclassPoint)
        self.assertEqual(cleaned, DataclassPoint(x=1, y=None))

    def test_rejects_an_output_that_matches_only_runtime_fields(self) -> None:
        """The output must use names declared by the Form.

        Do not use fields after ``__init__`` runs.
        """

        @dataclasses.dataclass
        class XOnly:
            x: int

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(PointWithRemovedYForm, output=XOnly)

    def test_field_added_in_init_cleans_under_the_default_output(self) -> None:
        """The Form adds a field in ``__init__``. The default output does not include it."""
        cleaned = nestingdolls.DataclassField(PointWithExtraFieldForm).clean(
            {"x": "1", "extra": "2"}
        )

        self.assertEqual(cleaned.x, 1)
        self.assertEqual([field.name for field in dataclasses.fields(cleaned)], ["x"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
