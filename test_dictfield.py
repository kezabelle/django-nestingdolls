import datetime
import unittest
import django
from django import forms
from django.conf import settings
from django.forms.boundfield import BoundField
from django.http.request import QueryDict
from django.test.testcases import SimpleTestCase
from django.test.utils import override_settings

import nestingdolls


if not settings.configured:
    settings.configure(
        INSTALLED_APPS=(),
        USE_I18N=False,
        TIME_ZONE="UTC",
        FORM_RENDERER="django.forms.renderers.DjangoTemplates",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {},
            },
        ],
    )
    django.setup()


class ChildForm(forms.Form):
    full_name = forms.CharField()
    date_of_birth = forms.DateField()


class ParentForm(forms.Form):
    full_name = forms.CharField()
    year_of_birth = forms.IntegerField()
    parent = forms.BooleanField()
    child1 = nestingdolls.DictField(ChildForm)
    child2 = nestingdolls.DictField(
        ChildForm(label_suffix="label suffix"), required=False
    )


class DictFieldSetupTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()

    def test_field_exists_on_form_fields(self):
        form = ParentForm()
        self.assertSetEqual(
            set(form.fields.keys()),
            {"full_name", "year_of_birth", "parent", "child1", "child2"},
        )

    def test_field_exists_on_form_base_fields(self):
        form = ParentForm()
        self.assertSetEqual(
            set(form.base_fields.keys()),
            {"full_name", "year_of_birth", "parent", "child1", "child2"},
        )

    def test_field_exists_on_form_declared_fields(self):
        form = ParentForm()
        self.assertSetEqual(
            set(form.declared_fields.keys()),
            {"full_name", "year_of_birth", "parent", "child1", "child2"},
        )


class DictFieldBoundDataTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()

    def test_bound_items(self):
        form = ParentForm(
            data=QueryDict(
                "full_name=<NAME>&year_of_birth=1985&parent=1&child1[full_name]=<NAME>&child1[date_of_birth]=2025-01-01"
            )
        )
        self.assertEqual(
            {k: bf.__class__ for k, bf in form._bound_items()},
            {
                "child1": nestingdolls.DictBoundField,
                "child2": nestingdolls.DictBoundField,
                "full_name": BoundField,
                "parent": BoundField,
                "year_of_birth": BoundField,
            },
        )


class DictFieldParseBoundDataTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()

    def test_with_no_child2(self):
        test_cases = (
            (
                "query dict",
                QueryDict(
                    "full_name=<NAME>&year_of_birth=1985&parent=1&child1[full_name]=<CHILDNAME>&child1[date_of_birth]=2025-01-01"
                ),
            ),
            (
                "raw dict",
                {
                    "child1": {
                        "date_of_birth": datetime.date(2025, 1, 1),
                        "full_name": "<CHILDNAME>",
                    },
                    "child2": {},
                    "full_name": "<NAME>",
                    "parent": True,
                    "year_of_birth": 1985,
                },
            ),
        )
        for test_name, test_data in test_cases:
            with self.subTest(test_name=test_name):
                form = ParentForm(data=test_data)
                self.assertTrue(form.is_bound)
                self.assertTrue(form.is_valid(), msg=form.errors)
                self.assertEqual(
                    form.cleaned_data,
                    {
                        "child1": {
                            "date_of_birth": datetime.date(2025, 1, 1),
                            "full_name": "<CHILDNAME>",
                        },
                        "child2": {},
                        "full_name": "<NAME>",
                        "parent": True,
                        "year_of_birth": 1985,
                    },
                )

    def test_with_complete_child2(self):
        test_cases = (
            (
                "query dict",
                QueryDict(
                    "full_name=<NAME>&year_of_birth=1985&parent=1&child1[full_name]=<CHILDNAME>&child1[date_of_birth]=2025-01-01&child2[full_name]=<CHILDNAME2>&child2[date_of_birth]=2025-01-02"
                ),
            ),
            (
                "raw dict",
                {
                    "child1": {
                        "date_of_birth": datetime.date(2025, 1, 1),
                        "full_name": "<CHILDNAME>",
                    },
                    "child2": {
                        "date_of_birth": datetime.date(2025, 1, 2),
                        "full_name": "<CHILDNAME2>",
                    },
                    "full_name": "<NAME>",
                    "parent": True,
                    "year_of_birth": 1985,
                },
            ),
        )
        for test_name, test_data in test_cases:
            with self.subTest(test_name=test_name):
                form = ParentForm(data=test_data)
                self.assertTrue(form.is_bound)
                self.assertTrue(form.is_valid(), msg=form.errors)
                self.assertEqual(
                    form.cleaned_data,
                    {
                        "child1": {
                            "date_of_birth": datetime.date(2025, 1, 1),
                            "full_name": "<CHILDNAME>",
                        },
                        "child2": {
                            "date_of_birth": datetime.date(2025, 1, 2),
                            "full_name": "<CHILDNAME2>",
                        },
                        "full_name": "<NAME>",
                        "parent": True,
                        "year_of_birth": 1985,
                    },
                )

    def test_with_invalid_child_fields(self):
        test_cases = (
            (
                "query dict",
                QueryDict(
                    "full_name=<NAME>&year_of_birth=1985&parent=1&child1[full_name]=<CHILDNAME>&child1[date_of_birth]="
                ),
            ),
            (
                "raw dict",
                {
                    "child1": {
                        "date_of_birth": None,
                        "full_name": "<CHILDNAME>",
                    },
                    "full_name": "<NAME>",
                    "parent": True,
                    "year_of_birth": 1985,
                },
            ),
        )
        for test_name, test_data in test_cases:
            with self.subTest(test_name=test_name):
                form = ParentForm(data=test_data)
                self.assertTrue(form.is_bound)
                self.assertFalse(form.is_valid(), msg=form.cleaned_data)
                self.assertEqual(
                    form.cleaned_data,
                    {
                        "child2": {},
                        "full_name": "<NAME>",
                        "parent": True,
                        "year_of_birth": 1985,
                    },
                )


# class DictFieldRenderingTestCase(SimpleTestCase):
#     def test_default_rendering_for_unbound(self):
#         form = str(ParentForm())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
