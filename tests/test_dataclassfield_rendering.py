"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.outputs import (
    DataclassPoint,
    OutputPointForm,
    RequiredDataclassPointForm,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class DataclassFieldRenderingTestCase(SimpleTestCase):
    """Make sure ``DataclassField`` renders and compares an initial dataclass value.

    Each test examines the rendered values or change detection.
    """

    def test_initial_and_change_detection_accept_a_dataclass_instance(self) -> None:
        """Test initial and change detection accept a dataclass instance."""
        initial = {"point": DataclassPoint(x=5, y=6)}
        unchanged = RequiredDataclassPointForm(
            {"point-x": "5", "point-y": "6"}, initial=initial
        )
        changed = RequiredDataclassPointForm(
            {"point-x": "5", "point-y": "7"}, initial=initial
        )

        self.assertEqual(unchanged["point"].initial, {"x": 5, "y": 6})
        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def test_callable_initial_renders_and_round_trips_unchanged(self) -> None:
        """A callable initial value renders its values. Change detection reports no change."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                OutputPointForm,
                output=DataclassPoint,
                initial=lambda: DataclassPoint(x=1, y=2),
            )

        html = Form().as_div()

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIs(Form({"point-x": "1", "point-y": "2"}).has_changed(), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
