"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from typing import NamedTuple

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.outputs import (
    NamedTuplePoint,
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


class NamedTupleFieldConstructionTestCase(SimpleTestCase):
    """Make sure ``NamedTupleField`` accepts or rejects an ``output`` type.

    The field checks the ``output`` names against the fields that the child Form
    class declares.
    """

    def test_rejects_a_plain_tuple_output(self) -> None:
        """An output must expose ``_fields``, not just be a tuple subclass."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(OutputPointForm, output=tuple)

    def test_rejects_mismatched_output_names(self) -> None:
        """The child Form's field names must match output._fields exactly."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(PointWithZForm, output=NamedTuplePoint)

    def test_infers_type_from_base_fields_and_fills_removed_fields(self) -> None:
        """Test infers type from base fields and fills removed fields."""
        cleaned = nestingdolls.NamedTupleField(PointWithRemovedYForm).clean({"x": "1"})

        self.assertEqual(cleaned.x, 1)
        self.assertIsNone(cleaned.y)

    def test_custom_output_fills_a_field_removed_in_init(self) -> None:
        """A custom output has a name for a field that ``__init__`` removes from the Form."""
        cleaned = nestingdolls.NamedTupleField(
            PointWithRemovedYForm, output=NamedTuplePoint
        ).clean({"x": "1"})

        self.assertIsInstance(cleaned, NamedTuplePoint)
        self.assertEqual(cleaned, NamedTuplePoint(x=1, y=None))

    def test_rejects_an_output_that_matches_only_runtime_fields(self) -> None:
        """The output must use names declared by the Form.

        Do not use fields after ``__init__`` runs.
        """

        class XOnly(NamedTuple):
            x: int

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(PointWithRemovedYForm, output=XOnly)

    def test_field_added_in_init_cleans_under_the_default_output(self) -> None:
        """The Form adds a field in ``__init__``. The default output does not include it."""
        cleaned = nestingdolls.NamedTupleField(PointWithExtraFieldForm).clean(
            {"x": "1", "extra": "2"}
        )

        self.assertEqual(cleaned.x, 1)
        self.assertEqual(cleaned._fields, ("x",))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
