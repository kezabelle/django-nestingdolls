from __future__ import annotations

import dataclasses
import unittest

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


@dataclasses.dataclass
class Point:
    x: int
    y: int


class PointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()


class DataclassFieldConstructionTestCase(SimpleTestCase):
    def test_rejects_a_non_dataclass_output(self):
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(PointForm, output=tuple)

    def test_rejects_mismatched_output_names(self):
        class WrongForm(forms.Form):
            x = forms.IntegerField()
            z = forms.IntegerField()

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.DataclassField(WrongForm, output=Point)

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

        cleaned = nestingdolls.DataclassField(Form, output=Point).clean({"x": "1"})

        self.assertIsInstance(cleaned, Point)
        self.assertEqual(cleaned, Point(x=1, y=None))

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


class DataclassFieldCleaningTestCase(SimpleTestCase):
    def test_clean_builds_the_dataclass_output(self):
        field = nestingdolls.DataclassField(PointForm, output=Point)
        self.assertIs(field.output, Point)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertEqual(cleaned, Point(x=1, y=2))

    def test_required_field_rejects_missing_submission(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(PointForm, output=Point)

        form = Form({})

        self.assertIs(form.is_valid(), False)
        self.assertIn("point", form.errors)

    def test_optional_field_cleans_missing_submission_to_none(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(PointForm, output=Point, required=False)

        form = Form({})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertIsNone(form.cleaned_data["point"])

    def test_validators_receive_the_compressed_dataclass(self):
        seen = []

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                PointForm, output=Point, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(seen, [Point(x=3, y=4)])

    def test_disabled_field_cleans_the_instance_initial(self):
        """A disabled field cleans its initial dataclass value. It does not clean submitted input."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                PointForm, output=Point, disabled=True, initial=Point(x=1, y=2)
            )

        form = Form({"point-x": "9", "point-y": "9"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], Point(x=1, y=2))

    def test_disabled_required_field_reports_required_with_no_initial(self):
        """A required disabled field with no initial value reports ``required``."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(PointForm, output=Point, disabled=True)

        form = Form({"point-x": "1", "point-y": "2"})

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "required")


class DataclassFieldRenderingTestCase(SimpleTestCase):
    def test_initial_and_change_detection_accept_a_dataclass_instance(self):
        class Form(forms.Form):
            point = nestingdolls.DataclassField(PointForm, output=Point)

        initial = {"point": Point(x=5, y=6)}
        unchanged = Form({"point-x": "5", "point-y": "6"}, initial=initial)
        changed = Form({"point-x": "5", "point-y": "7"}, initial=initial)

        self.assertEqual(unchanged["point"].initial, {"x": 5, "y": 6})
        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def test_callable_initial_renders_and_round_trips_unchanged(self):
        """A callable initial value renders its values. Change detection reports no change."""

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                PointForm, output=Point, initial=lambda: Point(x=1, y=2)
            )

        html = Form().as_div()

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIs(Form({"point-x": "1", "point-y": "2"}).has_changed(), False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
