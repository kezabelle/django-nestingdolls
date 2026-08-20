"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    DataclassPoint,
    DataclassPointForm,
    ImproperlyConfigured,
    SimpleTestCase,
    dataclasses,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class DataclassFieldConstructionTestCase(SimpleTestCase):
    """Make sure ``DataclassField`` accepts or rejects an ``output`` type.

    The field checks the ``output`` names against the fields that the child Form
    class declares."""

    def test_rejects_a_non_dataclass_output(self):
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(DataclassPointForm, output=tuple)

    def test_rejects_mismatched_output_names(self):
        class WrongForm(forms.Form):
            x = forms.IntegerField()
            z = forms.IntegerField()

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(WrongForm, output=DataclassPoint)

    def test_rejects_an_output_with_non_constructor_fields(self):
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

    def test_infers_type_from_base_fields_and_fills_removed_fields(self):
        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("y")

        cleaned = nestingdolls.DataclassField(Form).clean({"x": "1"})

        self.assertTrue(dataclasses.is_dataclass(cleaned))
        self.assertEqual(cleaned.x, 1)
        self.assertIsNone(cleaned.y)

    def test_custom_output_fills_a_field_removed_in_init(self):
        """A custom output has a name for a field that ``__init__`` removes from the Form."""

        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("y")

        cleaned = nestingdolls.DataclassField(Form, output=DataclassPoint).clean(
            {"x": "1"}
        )

        self.assertIsInstance(cleaned, DataclassPoint)
        self.assertEqual(cleaned, DataclassPoint(x=1, y=None))

    def test_rejects_an_output_that_matches_only_runtime_fields(self):
        """The output must use names declared by the Form.

        Do not use fields after ``__init__`` runs.
        """

        @dataclasses.dataclass
        class XOnly:
            x: int

        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("y")

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(Form, output=XOnly)

    def test_field_added_in_init_cleans_under_the_default_output(self):
        """The Form adds a field in ``__init__``. The default output does not include it."""

        class Form(forms.Form):
            x = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["extra"] = forms.IntegerField(required=False)

        cleaned = nestingdolls.DataclassField(Form).clean({"x": "1", "extra": "2"})

        self.assertEqual(cleaned.x, 1)
        self.assertEqual([field.name for field in dataclasses.fields(cleaned)], ["x"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
