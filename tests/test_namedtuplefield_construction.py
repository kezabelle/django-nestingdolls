"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    ImproperlyConfigured,
    NamedTuple,
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


class NamedTupleFieldConstructionTestCase(SimpleTestCase):
    """Make sure ``NamedTupleField`` accepts or rejects an ``output`` type.

    The field checks the ``output`` names against the fields that the child Form
    class declares."""

    def test_rejects_a_plain_tuple_output(self):
        """An output must expose ``_fields``, not just be a tuple subclass."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(NamedTuplePointForm, output=tuple)

    def test_rejects_mismatched_output_names(self):
        """The child Form's field names must match output._fields exactly."""

        class WrongForm(forms.Form):
            x = forms.IntegerField()
            z = forms.IntegerField()

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(WrongForm, output=NamedTuplePoint)

    def test_infers_type_from_base_fields_and_fills_removed_fields(self):
        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("y")

        cleaned = nestingdolls.NamedTupleField(Form).clean({"x": "1"})

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

        cleaned = nestingdolls.NamedTupleField(Form, output=NamedTuplePoint).clean(
            {"x": "1"}
        )

        self.assertIsInstance(cleaned, NamedTuplePoint)
        self.assertEqual(cleaned, NamedTuplePoint(x=1, y=None))

    def test_rejects_an_output_that_matches_only_runtime_fields(self):
        """The output must use names declared by the Form.

        Do not use fields after ``__init__`` runs.
        """

        class XOnly(NamedTuple):
            x: int

        class Form(forms.Form):
            x = forms.IntegerField()
            y = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("y")

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(Form, output=XOnly)

    def test_field_added_in_init_cleans_under_the_default_output(self):
        """The Form adds a field in ``__init__``. The default output does not include it."""

        class Form(forms.Form):
            x = forms.IntegerField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["extra"] = forms.IntegerField(required=False)

        cleaned = nestingdolls.NamedTupleField(Form).clean({"x": "1", "extra": "2"})

        self.assertEqual(cleaned.x, 1)
        self.assertEqual(cleaned._fields, ("x",))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
