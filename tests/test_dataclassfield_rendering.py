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


class DataclassFieldRenderingTestCase(SimpleTestCase):
    """Make sure ``DataclassField`` renders and compares an initial dataclass value.

    Each test examines the rendered values or change detection."""

    def test_initial_and_change_detection_accept_a_dataclass_instance(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm, output=DataclassPoint
            )

        initial = {"point": DataclassPoint(x=5, y=6)}
        unchanged = Form({"point-x": "5", "point-y": "6"}, initial=initial)
        changed = Form({"point-x": "5", "point-y": "7"}, initial=initial)

        self.assertEqual(unchanged["point"].initial, {"x": 5, "y": 6})
        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def test_callable_initial_renders_and_round_trips_unchanged(self):
        """A callable initial value renders its values. Change detection reports no change."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                DataclassPointForm,
                output=DataclassPoint,
                initial=lambda: DataclassPoint(x=1, y=2),
            )

        html = Form().as_div()

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIs(Form({"point-x": "1", "point-y": "2"}).has_changed(), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
