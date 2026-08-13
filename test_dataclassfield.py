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


class DataclassFieldCleaningTestCase(SimpleTestCase):
    def test_clean_builds_the_dataclass_output(self):
        field = nestingdolls.DataclassField(PointForm, output=Point)
        self.assertIs(field.output, Point)

        cleaned = field.clean({"x": "1", "y": "2"})

        self.assertEqual(cleaned, Point(x=1, y=2))

    def test_validators_receive_the_compressed_dataclass(self):
        seen = []

        class Form(forms.Form):
            point = nestingdolls.DataclassField(
                PointForm, output=Point, validators=[seen.append]
            )

        form = Form({"point-x": "3", "point-y": "4"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(seen, [Point(x=3, y=4)])


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
