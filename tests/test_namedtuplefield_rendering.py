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


class NamedTupleFieldRenderingTestCase(SimpleTestCase):
    """Make sure ``NamedTupleField`` renders and compares an initial named tuple value.

    Each test examines the rendered values or change detection."""

    def test_initial_accepts_a_namedtuple_instance(self):
        """A namedtuple_type instance given as initial renders like a mapping."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint, required=False
            )

        form = Form(initial={"point": NamedTuplePoint(x=5, y=6)})

        self.assertEqual(form["point"].initial, {"x": 5, "y": 6})

    def test_has_changed_compares_against_a_namedtuple_initial(self):
        """Change detection compares submitted rows against a namedtuple initial."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm, output=NamedTuplePoint
            )

        unchanged = Form(
            {"point-x": "5", "point-y": "6"},
            initial={"point": NamedTuplePoint(x=5, y=6)},
        )
        changed = Form(
            {"point-x": "5", "point-y": "7"},
            initial={"point": NamedTuplePoint(x=5, y=6)},
        )

        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def test_callable_initial_renders_and_round_trips_unchanged(self):
        """A callable initial value renders its values. Change detection reports no change."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                NamedTuplePointForm,
                output=NamedTuplePoint,
                initial=lambda: NamedTuplePoint(x=1, y=2),
            )

        html = Form().as_div()

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIs(Form({"point-x": "1", "point-y": "2"}).has_changed(), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
