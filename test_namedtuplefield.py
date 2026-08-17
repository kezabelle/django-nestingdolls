from __future__ import annotations

import unittest
from typing import NamedTuple

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

import nestingdolls

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=("nestingdolls",),
        USE_I18N=False,
        TIME_ZONE="UTC",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()


class Point(NamedTuple):
    x: int
    y: int


class PointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()


class NamedTupleFieldConstructionTestCase(SimpleTestCase):
    def test_rejects_a_plain_tuple_output(self):
        """An output must expose ``_fields``, not just be a tuple subclass."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(PointForm, output=tuple)

    def test_rejects_mismatched_output_names(self):
        """The child Form's field names must match output._fields exactly."""

        class WrongForm(forms.Form):
            x = forms.IntegerField()
            z = forms.IntegerField()

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.NamedTupleField(WrongForm, output=Point)

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

        cleaned = nestingdolls.NamedTupleField(Form, output=Point).clean({"x": "1"})

        self.assertIsInstance(cleaned, Point)
        self.assertEqual(cleaned, Point(x=1, y=None))

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


class NamedTupleFieldCleaningTestCase(SimpleTestCase):
    def test_clean_builds_the_namedtuple_output(self):
        """Cleaning a whole Python value returns one output instance."""
        field = nestingdolls.NamedTupleField(PointForm, output=Point)
        self.assertIs(field.output, Point)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertIsInstance(cleaned, Point)
        self.assertEqual(cleaned, Point(x=1, y=2))

    def test_required_field_rejects_missing_submission(self):
        """A required field with no submitted value reports "required"."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(PointForm, output=Point)

        form = Form({})

        self.assertIs(form.is_valid(), False)
        self.assertIn("point", form.errors)

    def test_optional_field_cleans_missing_submission_to_none(self):
        """An optional field with no submitted value cleans to None."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                PointForm, output=Point, required=False
            )

        form = Form({})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertIsNone(form.cleaned_data["point"])

    def test_submitted_form_data_builds_the_namedtuple_type(self):
        """A bound submission cleans to one namedtuple_type instance."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(PointForm, output=Point)

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], Point(x=3, y=4))

    def test_validators_receive_the_compressed_namedtuple(self):
        """A user validator gets the namedtuple, not the raw child-form dict.

        This is what makes the ``_clean_child_form`` compress-before-validate
        ordering in step 1 load-bearing rather than cosmetic.
        """
        seen = []

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                PointForm, output=Point, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(seen, [Point(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self):
        """A disabled field cleans its initial named tuple value. It does not clean submitted input."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                PointForm, output=Point, disabled=True, initial=Point(x=1, y=2)
            )

        form = Form({"point-x": "9", "point-y": "9"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], Point(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self):
        """A required disabled field with no initial value reports ``required``."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(PointForm, output=Point, disabled=True)

        form = Form({"point-x": "1", "point-y": "2"})

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "required")


class NamedTupleFieldRenderingTestCase(SimpleTestCase):
    def test_initial_accepts_a_namedtuple_instance(self):
        """A namedtuple_type instance given as initial renders like a mapping."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                PointForm, output=Point, required=False
            )

        form = Form(initial={"point": Point(x=5, y=6)})

        self.assertEqual(form["point"].initial, {"x": 5, "y": 6})

    def test_has_changed_compares_against_a_namedtuple_initial(self):
        """Change detection compares submitted rows against a namedtuple initial."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(PointForm, output=Point)

        unchanged = Form(
            {"point-x": "5", "point-y": "6"}, initial={"point": Point(x=5, y=6)}
        )
        changed = Form(
            {"point-x": "5", "point-y": "7"}, initial={"point": Point(x=5, y=6)}
        )

        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def test_callable_initial_renders_and_round_trips_unchanged(self):
        """A callable initial value renders its values. Change detection reports no change."""

        class Form(forms.Form):
            point = nestingdolls.NamedTupleField(
                PointForm, output=Point, initial=lambda: Point(x=1, y=2)
            )

        html = Form().as_div()

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIs(Form({"point-x": "1", "point-y": "2"}).has_changed(), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
