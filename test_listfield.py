import json
import unittest
from collections import deque
from datetime import datetime
from decimal import Decimal

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils import translation
from hypothesis import HealthCheck, assume, example, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

import nestingdolls

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=("nestingdolls",),
        USE_I18N=False,
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()


def setUpModule():
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule():
    # Undo the global template instrumentation after these unittest-based tests.
    teardown_test_environment()


HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
PARSER_HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=500,
    deadline=None,
)
SMALL_INTEGERS = st.integers(min_value=-5, max_value=5)
SMALL_INTEGER_LISTS = st.lists(SMALL_INTEGERS, max_size=5)
JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-5, max_value=5)
    | st.text(max_size=5)
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=8,
)
DATETIME_ROWS = st.lists(
    st.datetimes(timezones=st.none()).map(lambda value: value.replace(microsecond=0)),
    max_size=4,
)
PARSER_KEYS = st.one_of(
    st.none(),
    st.integers(),
    st.text(max_size=40),
    st.builds(
        lambda separator, index, suffix: f"values{separator}{index}{suffix}",
        st.sampled_from(("-", ".", "[")),
        st.text(alphabet="0123456789²١", max_size=30),
        st.text(alphabet="]_-.[]junk", max_size=12),
    ),
)
PARSER_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=20),
    st.lists(st.text(max_size=10), max_size=5),
)
PARSER_MAPPINGS = st.dictionaries(PARSER_KEYS, PARSER_VALUES, max_size=20)
PARSER_WIDGET = nestingdolls.SequenceWidget(
    forms.CharField(required=False),
    max_length=4,
    absolute_max=8,
)


class SequenceFieldTestCase(SimpleTestCase):
    field_class = nestingdolls.ListField
    collection_class = list

    def assert_cleaned_values(self, cleaned_data, values):
        self.assertIsInstance(cleaned_data, self.collection_class)
        self.assertEqual(cleaned_data, self.collection_class(values))

    def test_cleans_indexed_values(self):
        """It cleans ordinary indexed rows."""
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2&values-2=3"
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assert_cleaned_values(form.cleaned_data["values"], [1, 2, 3])

    def test_plain_mapping_uses_indexed_values_without_management_data(self):
        """It accepts plain indexed mappings without management fields."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form({"values-0": "1", "values-1": "2"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_accepts_direct_and_flat_data_spellings(self):
        """It accepts all supported submitted row spellings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        data_shapes = (
            {"values": ["1", "2", "3"]},
            {"values-0": "1", "values-1": "2", "values-2": "3"},
            {"values.0": "1", "values.1": "2", "values.2": "3"},
            {"values[0]": "1", "values[1]": "2", "values[2]": "3"},
        )

        for data in data_shapes:
            with self.subTest(data=data):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], [1, 2, 3])

    def test_sparse_high_index_dot_and_bracket_rows_are_accepted_without_management_data(
        self,
    ):
        """It accepts sparse dot and bracket spellings without explicit management rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        data_shapes = (
            {"values.2": "3"},
            {"values[2]": "3"},
        )

        for data in data_shapes:
            with self.subTest(data=data):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], [3])

    def test_json_null_row_is_rejected_consistently_across_supported_spellings(self):
        """It rejects JSON null rows consistently across all supported spellings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        data_shapes = (
            {"values": ["null"]},
            {"values-0": "null"},
            {"values.0": "null"},
            {"values[0]": "null"},
        )

        for data in data_shapes:
            with self.subTest(data=data):
                form = Form(data)
                self.assertFalse(form.is_valid())
                self.assertIsInstance(
                    form.errors.as_data()["values"][0],
                    nestingdolls.ItemValidationError,
                )
                self.assertEqual(
                    form.errors.as_data()["values"][0].code, "item_invalid"
                )
            self.assertEqual(
                form.errors.as_data()["values"][0].params["child_code"], "required"
            )

    def test_accepts_direct_and_flat_initial_spellings(self):
        """It accepts all supported initial row spellings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        initial_shapes = (
            {"values": [1, 2, 3]},
            {"values-0": 1, "values-1": 2, "values-2": 3},
            {"values.0": 1, "values.1": 2, "values.2": 3},
            {"values[0]": 1, "values[1]": 2, "values[2]": 3},
        )

        for initial in initial_shapes:
            with self.subTest(initial=initial):
                self.assertEqual(Form(initial=initial)["values"].value(), [1, 2, 3])

    def test_field_initial_accepts_flat_spellings(self):
        """It accepts flat spellings in field-level initial data."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial={"values[0]": 1, "values[1]": 2}
            )

    def test_initial_accepts_generic_sequence_and_collection_types(self):
        """It accepts non-string collection-shaped initial values beyond builtins."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        class FieldInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, initial=range(1, 3)
            )

        self.assertEqual(
            Form(initial={"values": range(3)})["values"].value(), [0, 1, 2]
        )
        self.assertEqual(
            Form(initial={"values": deque([4, 5])})["values"].value(),
            [4, 5],
        )
        self.assertEqual(FieldInitialForm()["values"].value(), [1, 2])

    def test_exact_name_scalar_mapping_is_treated_as_one_row(self):
        """It treats an exact-name scalar mapping as one row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        bound = Form({"values": "1"})
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertEqual(bound.cleaned_data["values"], [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            bound.as_p(),
        )

        unbound = Form(initial={"values": 1})
        self.assertEqual(unbound["values"].value(), [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            unbound.as_p(),
        )

    def test_flattened_initial_mapping_is_normalized(self):
        """It normalizes flattened initial mappings through the bound-field path."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            initial={
                "values.0": 1,
                "values[1]": 2,
            }
        )

        self.assertEqual(form["values"].value(), [1, 2])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            form.as_p(),
        )
        self.assertInHTML(
            '<input type="number" name="values-1" value="2" id="id_values_1">',
            form.as_p(),
        )

    def test_partial_management_data_is_an_error(self):
        """It rejects partial management form data."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        missing_initial = Form(QueryDict("values-TOTAL_FORMS=1&values-0=1"))
        self.assertFalse(missing_initial.is_valid())
        self.assertFormError(
            missing_initial,
            "values",
            [
                "ManagementForm data is missing or has been tampered with. Missing fields: values-INITIAL_FORMS. You may need to file a bug report if the issue persists."
            ],
        )
        self.assertEqual(
            missing_initial.errors.as_data()["values"][0].params["field_names"],
            "values-INITIAL_FORMS",
        )

        missing_total = Form(QueryDict("values-INITIAL_FORMS=0&values-0=1"))
        self.assertFalse(missing_total.is_valid())
        self.assertFormError(
            missing_total,
            "values",
            [
                "ManagementForm data is missing or has been tampered with. Missing fields: values-TOTAL_FORMS. You may need to file a bug report if the issue persists."
            ],
        )
        self.assertEqual(
            missing_total.errors.as_data()["values"][0].params["field_names"],
            "values-TOTAL_FORMS",
        )

    def test_duplicate_management_data_uses_last_submitted_value(self):
        """It matches Django formsets by using the last management value."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        form = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-TOTAL_FORMS=2&values-INITIAL_FORMS=0"
                "&values-0=1&values-1=2"
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_overlapping_spellings_use_normal_overwrite_semantics(self):
        """It lets later overlapping spellings overwrite earlier ones."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            ({"values-1": "2", "values.1": "3"}, [3], "later canonical row wins"),
            (
                {"values": ["1"], "values-0": "2"},
                [1],
                "direct value wins over indexed convenience",
            ),
            ({"values-01": "2", "values-1": "3"}, [3], "later normalized index wins"),
            ({"values-0": "2", "values[00]": "3"}, [3], "later bracket alias wins"),
            (
                {"values.0": "2", "values[00]": "3"},
                [3],
                "later bracket canonical alias wins",
            ),
        )
        for data, expected, label in cases:
            with self.subTest(label=label, data=data):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], expected)

    def test_item_errors_are_inline_and_available_to_api_consumers(self):
        """It exposes per-row errors in HTML and error data."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=bad&values-2=also-bad"
            )
        )

        self.assertFalse(form.is_valid())
        errors = form.errors.as_data()["values"]
        self.assertEqual(
            [error.code for error in errors], ["item_invalid", "item_invalid"]
        )
        self.assertEqual([error.params["item"] for error in errors], [1, 2])
        self.assertEqual(list(form["values"].errors), [])

        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertInHTML(
            '<input type="number" name="values-1" value="bad" id="id_values_1" aria-invalid="true" aria-describedby="id_values_1_error">',
            html,
        )
        self.assertInHTML("<li>Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 1: Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 2: Enter a whole number.</li>", html)

    def test_invalid_added_row_keeps_initial_count(self):
        """It keeps the initial count when an added row is invalid."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                "values-0=1&values-1=2"
            ),
            initial={"values": [1]},
        )

        self.assertFalse(form.is_valid())
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total id="id_values-TOTAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
            html,
        )

    def test_minimum_length_error_keeps_initial_count(self):
        """It keeps the initial count after minimum length validation."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=3)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                "values-0=1&values-1=2"
            ),
            initial={"values": [1]},
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "min_length")
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
            form.as_p(),
        )

    def test_invalid_original_row_keeps_deletion(self):
        """It keeps a deleted added row when an original row is invalid."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=bad&values-1=2",
            mutable=True,
        )
        data[f"values-1-{DELETION_FIELD_NAME}"] = "on"
        form = Form(data, initial={"values": [1]})

        self.assertFalse(form.is_valid())
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="values-1-DELETE" value="1" data-sequence-deleted-row data-sequence-field="values">',
            html,
        )
        self.assertNotInHTML(
            '<input type="number" name="values-1" value="2" id="id_values_1">',
            html,
        )

    def test_missing_initial_count_keeps_submitted_rows(self):
        """It keeps submitted rows when the initial count is missing."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=2&values-0=1&values-1=bad"),
            initial={"values": [1]},
        )

        self.assertFalse(form.is_valid())
        self.assertIsInstance(
            form.errors.as_data()["values"][0],
            nestingdolls.MissingManagementFormValidationError,
        )
        html = form.as_p()
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-1" value="bad" id="id_values_1">',
            html,
        )

    def test_item_errors_do_not_promote_to_field_errors(self):
        """It keeps child validation errors out of the field-level error list."""

        class Form(forms.Form):
            emails = nestingdolls.ListField(forms.EmailField(), min_length=4)

        form = Form(
            QueryDict(
                f"emails-{TOTAL_FORM_COUNT}=5&"
                f"emails-{INITIAL_FORM_COUNT}=0&"
                "emails-0=&emails-1=&emails-2=&emails-3=&emails-4="
            )
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            [error.code for error in form.errors.as_data()["emails"]],
            ["item_invalid"] * 5,
        )
        self.assertEqual(list(form["emails"].errors), [])

        html = form.as_p()
        self.assertNotInHTML("<li>Item 0: This field is required.</li>", html)
        self.assertInHTML("<li>This field is required.</li>", html)

    def test_outer_item_invalid_validator_error_stays_visible(self):
        """A validator collision with the child code remains a field-level error."""

        def reject_sequence(value):
            raise ValidationError(
                "Outer sequence error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), validators=[reject_sequence]
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1"
            )
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(list(form["values"].errors), ["Outer sequence error."])
        self.assertEqual(form.as_p().count("Outer sequence error."), 1)

    def test_deletion_preserves_initial_indices(self):
        """It deletes rows without renumbering initial items."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2&"
                f"values-1-{DELETION_FIELD_NAME}=1"
            ),
            initial={"values": [1, 2]},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])
        self.assertTrue(form.has_changed())

    def test_delete_flags_follow_django_boolean_semantics(self):
        """It treats standard Django truthy delete flags as deletes."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        for delete_value in ("1", "on", "true"):
            with self.subTest(delete_value=delete_value):
                data = QueryDict(
                    f"values-{TOTAL_FORM_COUNT}=1&"
                    f"values-{INITIAL_FORM_COUNT}=1&"
                    "values-0=1",
                    mutable=True,
                )
                data["values-0-DELETE"] = delete_value
                form = Form(data, initial={"values": [1]})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], [])

    def test_cardinality_is_independent_from_required(self):
        """It keeps cardinality checks separate from required checks."""

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, min_length=2
            )

        empty = OptionalForm(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=0&values-{INITIAL_FORM_COUNT}=0")
        )
        short = OptionalForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1"
            )
        )

        self.assertTrue(empty.is_valid(), empty.errors)
        self.assertEqual(empty.cleaned_data["values"], [])
        self.assertFalse(short.is_valid())
        self.assertFormError(
            short,
            "values",
            ["Ensure this value has at least 2 items (it has 1)."],
        )
        self.assertEqual(short.errors.as_data()["values"][0].code, "min_length")

    def test_deleted_extra_rows_do_not_consume_final_maximum(self):
        """It ignores deleted extra rows when enforcing the maximum."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&"
                f"values-1-{DELETION_FIELD_NAME}=1"
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])

    def test_management_total_uses_formset_absolute_maximum(self):
        """It uses the formset absolute maximum for management totals."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        data = QueryDict("", mutable=True)
        data[f"values-{TOTAL_FORM_COUNT}"] = str(DEFAULT_MAX_NUM + 2)
        data[f"values-{INITIAL_FORM_COUNT}"] = "0"
        form = Form(data)

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "too_many_forms")

    def test_flat_mapping_uses_the_same_absolute_maximum(self):
        """It applies the same absolute maximum to flat mappings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        form = Form({f"values-{DEFAULT_MAX_NUM + 1}": "1"})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "too_many_forms")

    def test_indexes_are_ascii_only_and_do_not_use_unbounded_integer_parsing(self):
        """It ignores Unicode digits, densifies sparse rows, and bounds overflow."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), max_length=1, required=False
            )

        unicode_digits = Form({"values-²": "1", "values[١]": "2"})
        self.assertTrue(unicode_digits.is_valid(), unicode_digits.errors)
        self.assertEqual(unicode_digits.cleaned_data["values"], [])

        class SparseForm(forms.Form):
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        for style, data in (
            ("dash", {"values-1999": "on"}),
            ("dot", {"values.1999": "on"}),
            ("bracket", {"values[1999]": "on"}),
        ):
            with self.subTest(style=style):
                form = SparseForm(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], [False, True])
                normalized = form.fields["values"].widget._normalize_mapping(
                    form.data, "values"
                )
                self.assertEqual(normalized[f"values-{TOTAL_FORM_COUNT}"], "2")
                self.assertIn("values-1", normalized)

        long_index = Form({f"values-{'9' * 5000}": "1"})
        self.assertFalse(long_index.is_valid())
        self.assertEqual(
            long_index.errors.as_data()["values"][0].code, "too_many_forms"
        )
        normalized = long_index.fields["values"].widget._normalize_mapping(
            long_index.data, "values"
        )
        self.assertFalse(any(key.startswith("values-1001") for key in normalized))

    def test_sparse_unmanaged_indexes_do_not_expand_rendering(self):
        """A sparse flat index renders as one dense row when management data is absent."""

        class Form(forms.Form):
            other = forms.IntegerField()
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        form = Form({"other": "bad", "values-1999": "on"})

        self.assertFalse(form.is_valid())
        html = form.as_p()
        self.assertIn('name="values-1"', html)
        self.assertNotIn('name="values-1999"', html)

    def test_direct_payload_enforces_absolute_max_before_child_cleaning(self):
        """It bounds hostile direct lists independently of their management total."""

        class UnreachableField(forms.IntegerField):
            def clean(self, value):
                raise AssertionError("oversized child value was cleaned")

            def bound_data(self, data, initial):
                raise AssertionError("oversized child value was bound")

            def prepare_value(self, value):
                raise AssertionError("oversized child value was prepared")

            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        class Form(forms.Form):
            values = nestingdolls.ListField(UnreachableField(), max_length=1)

        field = Form.base_fields["values"]
        values = ["1"] * (field.absolute_max + 1)
        self.assertEqual(
            field.widget._value_from_normalized_data(
                {"values": values}, {"values": ["ignored"]}, "values"
            ),
            values,
        )
        with self.assertRaises(ValidationError) as context:
            field.clean(values)
        self.assertEqual(context.exception.error_list[0].code, "too_many_forms")
        self.assertTrue(field.has_changed([], values))

        form = Form(
            {
                "values": values,
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "too_many_forms")
        form.as_p()

    def test_direct_file_payload_uses_the_sequence_extraction_path(self):
        """It extracts direct files when the matching data key is absent."""
        widget = nestingdolls.SequenceWidget(
            forms.CharField(required=False), max_length=1, absolute_max=2
        )

        self.assertEqual(
            widget.value_from_datadict({}, {"values": ["first", "second"]}, "values"),
            ["first", "second"],
        )

    def test_child_change_validation_errors_mark_the_sequence_changed(self):
        """It treats a child comparison validation error as a change."""

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise ValidationError("comparison failed")

        class Form(forms.Form):
            values = nestingdolls.ListField(ErrorField(), required=False)

        form = Form({"values": ["1"]})

        self.assertTrue(form.has_changed())

    def test_management_data_and_file_inference_are_deterministic(self):
        """It infers across both inputs and accepts management data from files."""

        class DataOrFilesWidget(forms.TextInput):
            def value_from_datadict(self, data, files, name):
                return data.get(name, files.get(name))

            def value_omitted_from_data(self, data, files, name):
                return name not in data and name not in files

        class TextForm(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(widget=DataOrFilesWidget), required=False
            )

        inferred = TextForm({"values-0": "data"}, files={"values-1": "file"})
        self.assertTrue(inferred.is_valid(), inferred.errors)
        self.assertEqual(inferred.cleaned_data["values"], ["data", "file"])

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), required=False)

        first = SimpleUploadedFile("first.txt", b"first")
        second = SimpleUploadedFile("second.txt", b"second")
        files = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "0",
            "values-0": first,
            "values-1": second,
        }
        files_authoritative = UploadForm({}, files=files)
        self.assertTrue(files_authoritative.is_valid(), files_authoritative.errors)
        self.assertEqual(files_authoritative.cleaned_data["values"], [first, second])

        malformed = TextForm(
            {
                f"values-{TOTAL_FORM_COUNT}": "not a number",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "data",
            },
            files={"values-1": "file"},
        )
        self.assertFalse(malformed.is_valid())
        self.assertIsInstance(
            malformed.errors.as_data()["values"][0],
            nestingdolls.MissingManagementFormValidationError,
        )
        self.assertEqual(
            malformed.errors.as_data()["values"][0].code,
            "missing_management_form",
        )

    def test_rows_beyond_an_authoritative_total_are_ignored(self):
        """It matches formsets by ignoring indexed rows beyond the submitted total."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        data["values-1"] = "not an integer"
        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])

    def test_disabled_children_clean_and_validate_sequence_initials(self):
        """It coerces valid disabled initials and rejects invalid ones."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(disabled=True))

        valid = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=99"
            ),
            initial={"values": ["7"]},
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.cleaned_data["values"], [7])

        invalid = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=99"
            ),
            initial={"values": ["bad"]},
        )
        self.assertFalse(invalid.is_valid())
        error = invalid.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "invalid")

    def test_sparse_extra_rows_are_skipped_but_initial_rows_are_not(self):
        """It skips missing extra rows but still requires initial rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        extra_only = Form({"values-1": "2"})
        self.assertTrue(extra_only.is_valid(), extra_only.errors)
        self.assertEqual(extra_only.cleaned_data["values"], [2])

        initial_missing = Form(
            QueryDict("values-TOTAL_FORMS=1&values-INITIAL_FORMS=1"),
            initial={"values": [1]},
        )
        self.assertFalse(initial_missing.is_valid())
        self.assertEqual(
            initial_missing.errors.as_data()["values"][0].params["item"], 0
        )

    def test_explicit_management_data_skips_omitted_extra_rows(self):
        """It skips omitted extra rows while keeping submitted initial rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                "values-0=10&values-2=30"
            ),
            initial={"values": [10]},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [10, 30])

    def test_leading_zero_indexes_normalize_once(self):
        """It normalizes leading-zero indexes to one row key."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form({"values-01": "2"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [2])

    def test_rejects_unhashable_cleaned_values(self):
        """It rejects unhashable cleaned values for sets."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.JSONField())

        self.assertNotIn(
            "unhashable", nestingdolls.ListField(forms.JSONField()).error_messages
        )

        form = Form({"values": [{"answer": 42}]})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "unhashable")

    def test_has_changed_uses_child_field_semantics(self):
        """It delegates change detection to the child field."""

        class JsonForm(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        class SetForm(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        json_form = JsonForm({"values": ["1"]}, initial={"values": [True]})
        set_form = SetForm({"values": ["2", "1", "1"]}, initial={"values": {1, 2}})

        self.assertTrue(json_form.has_changed())
        self.assertFalse(set_form.has_changed())

        upload = SimpleUploadedFile("same.txt", b"same")

        class FileForm(forms.Form):
            values = nestingdolls.ListField(
                forms.FileField(required=False), required=False
            )

        file_form = FileForm(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0"),
            files={"values-0": upload},
            initial={"values": [upload]},
        )

        self.assertTrue(file_form.has_changed())

    def test_disabled_oversized_sequences_are_unchanged(self):
        """Disabled sequence fields never inspect or reject submitted rows as changes."""

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("disabled child value was compared")

        for field_class in (nestingdolls.ListField, nestingdolls.SetField):

            class Form(forms.Form):
                values = field_class(
                    UnreachableField(), max_length=0, required=False, disabled=True
                )

            absolute_max = Form.base_fields["values"].absolute_max
            values = ["1"] * (absolute_max + 1)
            with self.subTest(field_class=field_class.__name__):
                form = Form({"values": values})
                self.assertFalse(form.has_changed())

    def test_has_changed_detects_added_and_removed_integer_rows(self):
        """It treats added and removed integer rows as changes."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertFalse(Form({"values": []}, initial={"values": []}).has_changed())
        self.assertTrue(Form({"values": [0]}, initial={"values": []}).has_changed())
        self.assertTrue(Form({"values": []}, initial={"values": [0]}).has_changed())
        self.assertFalse(
            Form({"values": [0, 1]}, initial={"values": [0, 1]}).has_changed()
        )

    def test_has_changed_propagates_child_value_errors(self):
        """It preserves child has_changed() value errors."""

        class ExtraRowBoomField(forms.CharField):
            def has_changed(self, initial, data):
                if initial is None:
                    raise ValueError("extra row boom")
                return super().has_changed(initial, data)

        class Form(forms.Form):
            values = nestingdolls.ListField(ExtraRowBoomField(), required=False)

        form = Form({"values-0": "x"})

        with self.assertRaises(ValueError):
            form.has_changed()

    def test_clean_empty_required_sequence_raises_required(self):
        """It raises the normal required error for an empty required sequence."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form({"values": []})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "required")

    def test_to_python_rejects_errors_as_values(self):
        """It rejects validation errors passed in as raw values."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.to_python(ValidationError("not submitted data"))
        self.assertEqual(context.exception.code, "invalid")

    def test_widget_value_from_datadict_accepts_each_single_row_spelling(self):
        """It extracts one row from each supported indexed spelling."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(required=False), required=False
            )

        for data in ({"values-0": "x"}, {"values.0": "x"}, {"values[0]": "x"}):
            with self.subTest(data=data):
                self.assertEqual(Form(data)["values"].value(), ["x"])

    def test_disabled_field_uses_initial_without_management_data(self):
        """It keeps disabled fields on their initial value."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, initial=[1]
            )

        form = Form(QueryDict("values-TOTAL_FORMS=1&values-0=9"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" disabled id="id_values_0">',
            form.as_p(),
        )

    def test_show_hidden_initial_uses_the_sequence_hidden_widget(self):
        """It supports hidden initial values for change detection."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        data.setlist("initial-values", ["1"])
        form = Form(data)

        self.assertFalse(form.has_changed())
        self.assertInHTML(
            '<input type="hidden" name="initial-values" value="1" id="initial-id_values_0">',
            form.as_p(),
        )

        malformed_initial = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        malformed_initial.setlist("initial-values", ["not-an-integer"])
        self.assertTrue(Form(malformed_initial).has_changed())

    def test_item_invalid_errors_preserve_child_codes(self):
        """It preserves child error codes inside item errors."""

        class MultiErrorField(forms.Field):
            def clean(self, value):
                raise ValidationError(
                    [
                        ValidationError("first", code="first_code"),
                        ValidationError("second", code="second_code"),
                    ]
                )

        class Form(forms.Form):
            values = nestingdolls.ListField(MultiErrorField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=x"
            )
        )
        self.assertFalse(form.is_valid())
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.message for error in errors], ["first", "second"])
        self.assertEqual(
            [error.params["child_code"] for error in errors],
            ["first_code", "second_code"],
        )

    def test_flattened_initial_sequence_falls_back_to_the_field_initial(self):
        """It uses flattened rows when present and Django's initial otherwise."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, initial=[3]
            )

        self.assertEqual(
            Form(initial={"values-0": "1", "values-1": "2"})["values"].initial,
            ["1", "2"],
        )
        self.assertEqual(Form(initial={"other": "value"})["values"].initial, [3])


class TupleFieldTestCase(SequenceFieldTestCase):
    field_class = nestingdolls.TupleField
    collection_class = tuple


class SetFieldTestCase(SimpleTestCase):
    def test_cardinality_is_checked_after_deduplication(self):
        """It checks set cardinality after removing duplicates."""
        field = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)

        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "1"])
        self.assertEqual(context.exception.code, "min_length")

        field = nestingdolls.SetField(forms.IntegerField(), max_length=1)
        self.assertEqual(field.clean(["1", "1"]), {1})

    def test_frozen_set_field_is_an_immutable_set_variant(self):
        """It exposes a frozenset variant of the set field."""
        field = nestingdolls.FrozenSetField(forms.IntegerField())

        cleaned = field.clean(["2", "1", "1"])
        self.assertIsInstance(cleaned, frozenset)
        self.assertEqual(cleaned, frozenset({1, 2}))
        self.assertFalse(field.has_changed(frozenset({1, 2}), ["2", "1", "1"]))
        with self.assertRaises(ValidationError) as context:
            nestingdolls.FrozenSetField(forms.JSONField()).clean([{"answer": 42}])
        self.assertEqual(context.exception.code, "unhashable")
        parent = nestingdolls.ListField(
            nestingdolls.FrozenSetField(forms.IntegerField(), required=False),
            required=False,
        )
        self.assertFalse(parent.has_changed([frozenset({1, 2})], [["2", "1", "1"]]))

    def test_oversized_direct_payload_short_circuits_set_comparison(self):
        """It stops set comparison immediately for oversized direct lists."""

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        for field_class, expected_initial in (
            (nestingdolls.SetField, set()),
            (nestingdolls.FrozenSetField, frozenset()),
        ):
            field = field_class(UnreachableField(), max_length=0, required=False)
            values = ["1"] * (field.absolute_max + 1)
            with self.subTest(field_class=field_class.__name__):
                self.assertTrue(field.has_changed(expected_initial, values))

    def test_has_changed_propagates_child_value_errors(self):
        """It preserves child comparison value errors."""

        class AnyBoomField(forms.CharField):
            def has_changed(self, initial, data):
                raise ValueError("boom")

        class Form(forms.Form):
            values = nestingdolls.SetField(AnyBoomField(), required=False)

        form = Form({"values-0": "x", "values-1": "x"})

        with self.assertRaises(ValueError):
            form.has_changed()

    def test_has_changed_uses_linear_comparisons_for_hashable_members(self):
        """Reordered unique integer members use indexed child comparisons."""

        class CountingIntegerField(forms.IntegerField):
            comparisons = 0

            def has_changed(self, initial, data):
                self.comparisons += 1
                return super().has_changed(initial, data)

        size = 1001
        field = nestingdolls.SetField(
            CountingIntegerField(), max_length=size, required=False
        )

        self.assertFalse(
            field.has_changed(
                set(range(size)), [str(value) for value in reversed(range(size))]
            )
        )
        self.assertLessEqual(field.child_field.comparisons, size * 3)

    def test_has_changed_uses_fallback_for_multiple_choice_lists(self):
        """It compares multiple-choice lists without hashing them."""
        field = nestingdolls.SetField(
            forms.MultipleChoiceField(
                choices=[("first", "First"), ("second", "Second")]
            ),
            required=False,
        )

        self.assertFalse(
            field.has_changed({("first", "second")}, [["second", "first"]])
        )
        self.assertTrue(field.has_changed({("first", "second")}, [["first"]]))

    def test_has_changed_keeps_duplicate_blank_invalid_and_json_semantics(self):
        """Indexed matching preserves the child field's semantic edge cases."""
        integer_field = nestingdolls.SetField(
            forms.IntegerField(required=False), required=False
        )
        json_field = nestingdolls.SetField(forms.JSONField(), required=False)

        self.assertFalse(integer_field.has_changed({1}, ["1", "1", ""]))
        self.assertTrue(integer_field.has_changed({1}, ["invalid"]))
        self.assertTrue(json_field.has_changed({True}, ["1"]))

    def test_tuple_child_set_has_changed_ignores_order_for_equal_members(self):
        """It treats reordered tuple-set members as unchanged."""

        class Form(forms.Form):
            values = nestingdolls.SetField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        form = Form(
            {
                "values-0-0": "1",
                "values-0-1": "1",
                "values-1-0": "1",
                "values-1-1": "0",
            },
            initial={"values": {(1, 0), (1, 1)}},
        )

        self.assertFalse(form.has_changed())

    def test_splitdatetime_child_set_has_changed_ignores_order_for_equal_members(self):
        """It treats reordered SplitDateTime set members as unchanged."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.SplitDateTimeField(), required=False)

        form = Form(
            {
                "values-0_0": "2024-06-07",
                "values-0_1": "08:09:10",
                "values-1_0": "2024-01-02",
                "values-1_1": "03:04:05",
            },
            initial={
                "values": {
                    datetime(2024, 1, 2, 3, 4, 5),  # noqa: DTZ001
                    datetime(2024, 6, 7, 8, 9, 10),  # noqa: DTZ001
                }
            },
        )

        self.assertFalse(form.has_changed())

    def test_frozenset_tuple_child_has_changed_ignores_order_for_equal_members(self):
        """It keeps frozenset tuple children order-insensitive as well."""

        class Form(forms.Form):
            values = nestingdolls.FrozenSetField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        form = Form(
            {
                "values-0-0": "1",
                "values-0-1": "1",
                "values-1-0": "1",
                "values-1-1": "0",
            },
            initial={"values": frozenset({(1, 0), (1, 1)})},
        )

        self.assertFalse(form.has_changed())


class NestedSequenceFieldTestCase(SimpleTestCase):
    def test_invalid_nested_added_row_keeps_initial_count(self):
        """It keeps the inner initial count when an added row is invalid."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField())
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                f"values-0-{TOTAL_FORM_COUNT}=2&"
                f"values-0-{INITIAL_FORM_COUNT}=1&"
                "values-0-0=1&values-0-1=bad"
            ),
            initial={"values": [[1]]},
        )

        self.assertFalse(form.is_valid())
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="values-0-INITIAL_FORMS" value="1" id="id_values-0-INITIAL_FORMS">',
            html,
        )

    def test_nested_tuple_has_changed_uses_semantic_equality(self):
        """It treats equal nested tuple values as unchanged."""
        field = nestingdolls.ListField(
            nestingdolls.TupleField(
                forms.IntegerField(),
                min_length=2,
                max_length=2,
            ),
            required=False,
        )

        self.assertFalse(field.has_changed([(2, 0)], [[2, 0]]))
        self.assertTrue(field.has_changed([(2, 0)], [[2, 1]]))
        self.assertTrue(field.has_changed([(2, 0)], []))
        self.assertTrue(field.has_changed([], [[2, 0]]))

    def test_list_field_accepts_nested_tuple_children(self):
        """It cleans a list of pair tuples from flat nested keys."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                )
            )

        form = Form(
            {
                "values-0-0": "1",
                "values-0-1": "2",
                "values-1-0": "3",
                "values-1-1": "4",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [(1, 2), (3, 4)])

    def test_list_field_rejects_nested_tuple_children_with_extra_items(self):
        """It rejects tuple children that submit more than two items."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                )
            )

        form = Form(
            {
                "values-0-0": "1",
                "values-0-1": "2",
                "values-0-2": "3",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "item_invalid")
        self.assertEqual(
            form.errors.as_data()["values"][0].params["child_code"], "max_length"
        )

    def test_list_field_accepts_deeply_nested_list_children(self):
        """It cleans nested list children from flat nested keys."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))
            )

        form = Form(
            {
                "values-0-0-0": "1",
                "values-0-0-1": "2",
                "values-0-1-0": "3",
                "values-1-0-0": "4",
                "values-1-1-0": "5",
                "values-1-1-1": "6",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["values"],
            [[[1, 2], [3]], [[4], [5, 6]]],
        )

    def test_list_field_cleans_deeply_nested_alternating_fields(self):
        """It cleans list, mapping, and list layers together from mixed flat keys."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class EntryForm(forms.Form):
            point = nestingdolls.MappingField(PointForm)
            title = forms.CharField()

        class SectionForm(forms.Form):
            name = forms.CharField()
            entries = nestingdolls.ListField(nestingdolls.MappingField(EntryForm))

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(SectionForm))

        data = {
            "values[0][name]": "alpha",
            "values[0][entries][0][point][a]": "1",
            "values[0][entries][0][point][label]": "north",
            "values[0][entries][0][title]": "first",
            "values[0][entries][1][point][a]": "2",
            "values[0][entries][1][title]": "second",
            "values[1][name]": "beta",
            "values[1][entries][0][point][a]": "3",
            "values[1][entries][0][title]": "third",
        }

        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["values"],
            [
                {
                    "name": "alpha",
                    "entries": [
                        {"point": {"a": 1, "label": "north"}, "title": "first"},
                        {"point": {"a": 2, "label": ""}, "title": "second"},
                    ],
                },
                {
                    "name": "beta",
                    "entries": [
                        {"point": {"a": 3, "label": ""}, "title": "third"},
                    ],
                },
            ],
        )

    def test_nested_list_has_changed_uses_child_semantics(self):
        """It keeps nested list change detection semantic."""
        child = nestingdolls.ListField(
            nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False),
                required=False,
            ),
            required=False,
        )
        field = nestingdolls.ListField(child, required=False)

        self.assertFalse(field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]))
        self.assertTrue(field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]))
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]),
            child.has_changed([[[2], [0]]], [[[2], [1]]]),
        )
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]),
            child.has_changed([[[2], [0]]], [[[2], [0]]]),
        )


class _HypothesisTestCase(SimpleTestCase):
    _row_spelling_names = ("direct", "dash", "dot", "bracket")
    _multiwidget_spelling_names = ("dash", "dot", "bracket")

    @staticmethod
    def _spelled_sequence_data(name, values, style, formatter=str):
        if style == "direct":
            return {name: [formatter(value) for value in values]}
        if style == "dash":
            return {
                f"{name}-{index}": formatter(value)
                for index, value in enumerate(values)
            }
        if style == "dot":
            return {
                f"{name}.{index}": formatter(value)
                for index, value in enumerate(values)
            }
        if style == "bracket":
            return {
                f"{name}[{index}]": formatter(value)
                for index, value in enumerate(values)
            }
        raise AssertionError(f"unsupported style: {style}")

    @staticmethod
    def _cardinality_result(required, min_length, max_length, values):
        length = len(values)
        if length == 0 and required:
            return "required"
        if length == 0:
            return "ok"
        if length < min_length:
            return "min_length"
        if length > max_length:
            return "max_length"
        return "ok"

    @staticmethod
    def _undeleted_rows(values, deleted):
        return [value for index, value in enumerate(values) if index not in deleted]

    @staticmethod
    def _nested_tuple_data(name, rows):
        return {
            f"{name}-{row_index}-{column_index}": str(value)
            for row_index, row in enumerate(rows)
            for column_index, value in enumerate(row)
        }

    def _json_row_data(self, name, values, style):
        return self._spelled_sequence_data(name, values, style, formatter=json.dumps)

    def _boolean_row_data(self, name, values):
        data = QueryDict("", mutable=True)
        data[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(values))
        data[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            if value:
                data[f"{name}-{index}"] = "on"
        return data

    def _splitdatetime_row_data(self, name, values, style):
        data = {}
        for index, value in enumerate(values):
            date_part = value.date().isoformat()
            time_part = value.time().strftime("%H:%M:%S")
            if style == "dash":
                prefix = f"{name}-{index}"
            elif style == "dot":
                prefix = f"{name}.{index}"
            elif style == "bracket":
                prefix = f"{name}[{index}]"
            else:
                raise AssertionError(f"unsupported style: {style}")
            data[f"{prefix}_0"] = date_part
            data[f"{prefix}_1"] = time_part
        return data


class SequenceFieldPropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(values=[{"answer": 42}])
    @given(values=st.lists(JSON_VALUES, max_size=4))
    def test_json_rows_clean_equally_across_supported_spellings(self, values):
        """It gives the same public outcome for every supported JSON spelling."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        outcomes = []
        for style in self._row_spelling_names:
            form = Form(self._json_row_data("values", values, style))
            if form.is_valid():
                outcomes.append(("ok", form.cleaned_data["values"]))
            else:
                outcomes.append(
                    (
                        "error",
                        tuple(error.code for error in form.errors.as_data()["values"]),
                    )
                )
        self.assertEqual(outcomes, [outcomes[0]] * len(self._row_spelling_names))

    @HYPOTHESIS_SETTINGS
    @given(
        required=st.booleans(),
        bounds=st.integers(min_value=0, max_value=5).flatmap(
            lambda min_length: st.tuples(
                st.just(min_length), st.integers(min_value=min_length, max_value=5)
            )
        ),
        values=SMALL_INTEGER_LISTS,
    )
    def test_cardinality_matches_the_public_validation_contract(
        self, required, bounds, values
    ):
        """It applies required/min/max exactly from final row cardinality."""
        min_length, max_length = bounds

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                required=required,
                min_length=min_length,
                max_length=max_length,
            )

        submitted = QueryDict("", mutable=True)
        submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
        submitted[f"values-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            submitted[f"values-{index}"] = str(value)

        form = Form(submitted)
        expected = self._cardinality_result(required, min_length, max_length, values)
        self.assertEqual(form.is_valid(), expected == "ok")
        if expected == "ok":
            self.assertEqual(form.cleaned_data["values"], values)
        else:
            self.assertEqual(form.errors.as_data()["values"][0].code, expected)

    @HYPOTHESIS_SETTINGS
    @given(
        values=SMALL_INTEGER_LISTS,
        initial_forms=st.integers(min_value=0, max_value=5),
        data=st.data(),
    )
    def test_delete_flags_remove_rows_before_cleaned_output(
        self, values, initial_forms, data
    ):
        """It removes deleted rows from cleaned output regardless of initial_forms."""
        initial_forms = min(initial_forms, len(values))
        deleted = (
            data.draw(
                st.sets(
                    st.integers(min_value=0, max_value=len(values) - 1),
                    max_size=len(values),
                )
            )
            if values
            else set()
        )

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        submitted = QueryDict("", mutable=True)
        submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
        submitted[f"values-{INITIAL_FORM_COUNT}"] = str(initial_forms)
        for index, value in enumerate(values):
            submitted[f"values-{index}"] = str(value)
        for index in sorted(deleted):
            submitted[f"values-{index}-{DELETION_FIELD_NAME}"] = "1"

        form = Form(submitted)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["values"], self._undeleted_rows(values, deleted)
        )

    @HYPOTHESIS_SETTINGS
    @given(
        bounds=st.integers(min_value=0, max_value=5).flatmap(
            lambda min_length: st.tuples(
                st.just(min_length), st.integers(min_value=min_length, max_value=5)
            )
        ),
        values=SMALL_INTEGER_LISTS,
        data=st.data(),
    )
    def test_cardinality_after_deletion_uses_only_remaining_rows(
        self, bounds, values, data
    ):
        """It validates cardinality against undeleted rows, not raw submissions."""
        min_length, max_length = bounds
        deleted = (
            data.draw(
                st.sets(
                    st.integers(min_value=0, max_value=len(values) - 1),
                    max_size=len(values),
                )
            )
            if values
            else set()
        )
        remaining = self._undeleted_rows(values, deleted)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                required=False,
                min_length=min_length,
                max_length=max_length,
            )

        submitted = QueryDict("", mutable=True)
        submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
        submitted[f"values-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            submitted[f"values-{index}"] = str(value)
        for index in sorted(deleted):
            submitted[f"values-{index}-{DELETION_FIELD_NAME}"] = "1"

        form = Form(submitted)
        expected = self._cardinality_result(False, min_length, max_length, remaining)
        self.assertEqual(form.is_valid(), expected == "ok")
        if expected == "ok":
            self.assertEqual(form.cleaned_data["values"], remaining)
        else:
            self.assertEqual(form.errors.as_data()["values"][0].code, expected)

    @HYPOTHESIS_SETTINGS
    @given(values=st.lists(st.booleans(), max_size=5))
    def test_boolean_rows_preserve_unchecked_positions(self, values):
        """It keeps false boolean rows in position with management data."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.BooleanField(required=False), required=False
            )

        form = Form(self._boolean_row_data("values", values))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], values)

    @HYPOTHESIS_SETTINGS
    @example(values=[{"nested": [1, 2]}], style="dash")
    @given(
        values=st.lists(JSON_VALUES, max_size=4),
        style=st.sampled_from(_HypothesisTestCase._row_spelling_names),
    )
    def test_json_rows_use_semantic_change_detection(self, values, style):
        """It compares JSON rows semantically instead of by raw string form."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        form = Form(
            self._json_row_data("values", values, style), initial={"values": values}
        )
        self.assertFalse(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(values=DATETIME_ROWS)
    def test_splitdatetime_rows_clean_equally_across_indexed_spellings(self, values):
        """It cleans compound datetime rows identically across indexed spellings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField(), required=False)

        cleaned_results = []
        for style in self._multiwidget_spelling_names:
            form = Form(self._splitdatetime_row_data("values", values, style))
            self.assertTrue(form.is_valid(), (style, form.errors))
            cleaned_results.append(
                [item.replace(tzinfo=None) for item in form.cleaned_data["values"]]
            )
        self.assertEqual(
            cleaned_results, [values] * len(self._multiwidget_spelling_names)
        )

    @HYPOTHESIS_SETTINGS
    @example(
        cases=(
            (
                "scalar-row-only",
                {
                    "direct": {"values": ["1"]},
                    "dash": {"values-0": "1"},
                    "dot": {"values.0": "1"},
                    "bracket": {"values[0]": "1"},
                },
            ),
        )
    )
    @example(
        cases=(
            (
                "scalar-row-plus-leaf",
                {
                    "direct": {"values": ["1"]},
                    "dash": {"values-0": "1", "values-0[a]": "2"},
                    "dot": {"values.0": "1", "values.0[a]": "2"},
                    "bracket": {"values[0]": "1", "values[0][a]": "2"},
                },
            ),
        )
    )
    @given(
        cases=st.lists(
            st.sampled_from(
                (
                    (
                        "scalar-row-only",
                        {
                            "direct": {"values": ["1"]},
                            "dash": {"values-0": "1"},
                            "dot": {"values.0": "1"},
                            "bracket": {"values[0]": "1"},
                        },
                    ),
                    (
                        "scalar-row-plus-leaf",
                        {
                            "direct": {"values": ["1"]},
                            "dash": {"values-0": "1", "values-0[a]": "2"},
                            "dot": {"values.0": "1", "values.0[a]": "2"},
                            "bracket": {"values[0]": "1", "values[0][a]": "2"},
                        },
                    ),
                    (
                        "malformed-row-suffix",
                        {
                            "dash": {"values-0junk": "1"},
                            "dot": {"values.0junk": "1"},
                            "bracket": {"values[0]junk": "1"},
                        },
                    ),
                    (
                        "nested-repeat-into-row",
                        {
                            "dash": {"values-0-0": "1"},
                            "dot": {"values.0.0": "1"},
                            "bracket": {"values[0][0]": "1"},
                        },
                    ),
                    (
                        "second-row-plus-leaf",
                        {
                            "dash": {"values-1": "1", "values-1[a]": "2"},
                            "dot": {"values.1": "1", "values.1[a]": "2"},
                            "bracket": {"values[1]": "1", "values[1][a]": "2"},
                        },
                    ),
                )
            ),
            min_size=1,
            max_size=1,
            unique_by=lambda item: item[0],
        )
    )
    def test_mapping_row_hostile_cases_match_public_outcomes_across_spellings(
        self, cases
    ):
        """Hostile row-shape spellings should agree on validation and rendering."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        spellings = {style: {} for style in self._row_spelling_names}
        for _, family in cases:
            for style, payload in family.items():
                spellings[style].update(payload)
        populated_styles = [
            style for style in self._row_spelling_names if spellings.get(style)
        ]
        if not populated_styles:
            populated_styles = ["direct"]
        is_valid_results = []
        error_results = []
        render_results = []
        value_results = []
        for style in populated_styles:
            form = Form(spellings[style])
            is_valid_results.append(form.is_valid())
            error_results.append(
                tuple(
                    (error.code, (error.params or {}).get("child_code"))
                    for error in form.errors.as_data().get("values", [])
                )
            )
            try:
                str(form["values"])
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                render_results.append(type(exc).__name__)
            else:
                render_results.append(None)
            try:
                form["values"].value()
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                value_results.append(type(exc).__name__)
            else:
                value_results.append(None)
        self.assertEqual(
            is_valid_results, [is_valid_results[0]] * len(is_valid_results)
        )
        self.assertEqual(error_results, [error_results[0]] * len(error_results))
        self.assertEqual(render_results, [render_results[0]] * len(render_results))
        self.assertEqual(value_results, [value_results[0]] * len(value_results))

    @HYPOTHESIS_SETTINGS
    @given(
        data=st.sampled_from(
            (
                {"values0": "1"},
                {"values_0": "1"},
                {"valuesx[0]": "1"},
                {"values[0]junk": "1"},
                {"values[a]": "1"},
            )
        )
    )
    def test_unrelated_sequence_prefixes_and_suffixes_do_not_satisfy_the_field(
        self, data
    ):
        """Keys outside the exact indexed row prefix cannot satisfy a required field."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(data)

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "required")


class SetFieldPropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(values=[1, 1])
    @given(values=SMALL_INTEGER_LISTS)
    def test_set_field_cleans_to_the_semantic_set(self, values):
        """It deduplicates rows exactly as a set would."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        form = Form(
            QueryDict(
                "&".join(
                    [
                        f"values-{TOTAL_FORM_COUNT}={len(values)}",
                        f"values-{INITIAL_FORM_COUNT}=0",
                        *[
                            f"values-{index}={value}"
                            for index, value in enumerate(values)
                        ],
                    ]
                )
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], set(values))

    @HYPOTHESIS_SETTINGS
    @given(
        initial_members=st.lists(SMALL_INTEGERS, unique=True, max_size=5),
        data=st.data(),
    )
    def test_set_field_has_changed_is_false_for_duplicate_permutations(
        self, initial_members, data
    ):
        """It treats duplicate permutations of the same set as unchanged."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        initial_set = set(initial_members)
        extras = (
            data.draw(
                st.lists(
                    st.sampled_from(initial_members),
                    max_size=3,
                )
            )
            if initial_members
            else []
        )
        submitted = data.draw(st.permutations(tuple(initial_members + extras)))
        form = Form(
            QueryDict(
                "&".join(
                    [
                        f"values-{TOTAL_FORM_COUNT}={len(submitted)}",
                        f"values-{INITIAL_FORM_COUNT}=0",
                        *[
                            f"values-{index}={value}"
                            for index, value in enumerate(submitted)
                        ],
                    ]
                )
            ),
            initial={"values": initial_set},
        )
        self.assertFalse(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_values=SMALL_INTEGER_LISTS,
        submitted_values=SMALL_INTEGER_LISTS,
    )
    def test_set_field_has_changed_tracks_semantic_set_changes(
        self, initial_values, submitted_values
    ):
        """It reports changes from semantic set inequality."""
        assume(set(initial_values) != set(submitted_values))

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        form = Form(
            QueryDict(
                "&".join(
                    [
                        f"values-{TOTAL_FORM_COUNT}={len(submitted_values)}",
                        f"values-{INITIAL_FORM_COUNT}=0",
                        *[
                            f"values-{index}={value}"
                            for index, value in enumerate(submitted_values)
                        ],
                    ]
                )
            ),
            initial={"values": set(initial_values)},
        )
        self.assertTrue(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_members=st.lists(
            st.tuples(SMALL_INTEGERS, SMALL_INTEGERS),
            unique=True,
            max_size=5,
        ),
        data=st.data(),
    )
    def test_tuple_child_set_has_changed_is_false_for_reordered_equal_members(
        self, initial_members, data
    ):
        """It treats reordered tuple-set members as unchanged."""

        class Form(forms.Form):
            values = nestingdolls.SetField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        submitted = data.draw(st.permutations(tuple(initial_members)))
        form = Form(
            self._nested_tuple_data("values", list(submitted)),
            initial={"values": set(initial_members)},
        )
        self.assertFalse(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_members=st.lists(
            st.tuples(SMALL_INTEGERS, SMALL_INTEGERS),
            unique=True,
            max_size=5,
        ),
        submitted_members=st.lists(
            st.tuples(SMALL_INTEGERS, SMALL_INTEGERS),
            unique=True,
            max_size=5,
        ),
    )
    def test_tuple_child_set_has_changed_is_true_for_semantic_difference(
        self, initial_members, submitted_members
    ):
        """It reports changes when tuple-set members differ semantically."""
        assume(set(initial_members) != set(submitted_members))

        class Form(forms.Form):
            values = nestingdolls.SetField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        form = Form(
            self._nested_tuple_data("values", submitted_members),
            initial={"values": set(initial_members)},
        )
        self.assertTrue(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_members=st.lists(
            st.datetimes(timezones=st.none()).map(
                lambda value: value.replace(microsecond=0)
            ),
            unique=True,
            max_size=4,
        ),
        data=st.data(),
    )
    def test_splitdatetime_child_set_has_changed_is_false_for_reordered_equal_members(
        self, initial_members, data
    ):
        """It treats reordered SplitDateTime set members as unchanged."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.SplitDateTimeField(), required=False)

        submitted = list(data.draw(st.permutations(tuple(initial_members))))
        form = Form(
            self._splitdatetime_row_data("values", submitted, "dash"),
            initial={"values": set(initial_members)},
        )
        self.assertFalse(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_members=st.lists(
            st.datetimes(timezones=st.none()).map(
                lambda value: value.replace(microsecond=0)
            ),
            unique=True,
            max_size=4,
        ),
        submitted_members=st.lists(
            st.datetimes(timezones=st.none()).map(
                lambda value: value.replace(microsecond=0)
            ),
            unique=True,
            max_size=4,
        ),
    )
    def test_splitdatetime_child_set_has_changed_is_true_for_semantic_difference(
        self, initial_members, submitted_members
    ):
        """It reports changes when SplitDateTime set members differ semantically."""
        assume(set(initial_members) != set(submitted_members))

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.SplitDateTimeField(), required=False)

        form = Form(
            self._splitdatetime_row_data("values", submitted_members, "dash"),
            initial={"values": set(initial_members)},
        )
        self.assertTrue(form.has_changed())


class NestedSequencePropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(rows=[(2, 0)])
    @given(
        rows=st.lists(
            st.tuples(
                SMALL_INTEGERS,
                SMALL_INTEGERS,
            ),
            max_size=5,
        )
    )
    def test_nested_tuple_rows_are_unchanged_under_semantic_equality(self, rows):
        """It treats tuple initials and list submissions as equal when values match."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        submitted_rows = [list(row) for row in rows]
        form = Form(
            self._nested_tuple_data("values", submitted_rows), initial={"values": rows}
        )
        self.assertFalse(form.has_changed())

    @HYPOTHESIS_SETTINGS
    @given(
        initial_rows=st.lists(
            st.tuples(
                SMALL_INTEGERS,
                SMALL_INTEGERS,
            ),
            max_size=5,
        ),
        submitted_rows=st.lists(
            st.tuples(
                SMALL_INTEGERS,
                SMALL_INTEGERS,
            ),
            max_size=5,
        ),
    )
    def test_nested_tuple_rows_report_changes_when_semantic_values_differ(
        self, initial_rows, submitted_rows
    ):
        """It reports a change whenever nested tuple rows differ semantically."""
        assume(initial_rows != submitted_rows)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        form = Form(
            self._nested_tuple_data("values", [list(row) for row in submitted_rows]),
            initial={"values": initial_rows},
        )
        self.assertTrue(form.has_changed())


class NestedParserRegressionTestCase(SimpleTestCase):
    def test_unrecognized_mapping_initial_becomes_one_renderable_row(self):
        """A mapping that is not flattened sequence data remains one raw row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        value = {"unexpected": "saved"}
        form = Form(initial={"values": value})

        self.assertEqual(form["values"].initial, [value])
        self.assertIn("unexpected", str(form["values"]))

    def test_mapping_row_shape_errors_stay_in_the_validation_channel(self):
        """Invalid mapping-shaped rows should become normal form errors."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        cases = (
            ("direct", {"values": ["1"]}),
            ("dash", {"values-0": "1"}),
            ("dot", {"values.0": "1"}),
            ("bracket", {"values[0]": "1"}),
        )
        for label, data in cases:
            with self.subTest(style=label):
                form = Form(data)
                self.assertFalse(form.is_valid())
                self.assertIn(
                    form.errors.as_data()["values"][0].code,
                    ("invalid", "item_invalid"),
                )

    def test_mapping_row_shape_errors_render_without_raising(self):
        """Invalid mapping rows should render as inline field errors, not 500s."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        cases = (
            ("direct", {"values": ["1"]}),
            ("dash", {"values-0": "1"}),
            ("dot", {"values.0": "1"}),
            ("bracket", {"values[0]": "1"}),
        )
        for label, data in cases:
            with self.subTest(style=label):
                form = Form(data)
                self.assertFalse(form.is_valid())
                rendered = str(form["values"])
                self.assertEqual(form["values"].value(), ["1"])
                self.assertIn("Enter a mapping of values.", rendered)

    def test_mixed_scalar_and_nested_mapping_rows_render_without_raising(self):
        """Scalar row aliases plus nested child aliases should remain renderable."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        form = Form({"values[0]": "1", "values[0][a]": "2"})

        self.assertFalse(form.is_valid())
        rendered = str(form["values"])
        self.assertEqual(form["values"].value(), ["1"])
        self.assertIn("Enter a mapping of values.", rendered)

    def test_nested_mapping_row_shape_errors_render_without_raising(self):
        """Repeated sequence-to-mapping boundaries should keep invalid rows renderable."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    nestingdolls.MappingField(PointForm),
                    required=False,
                ),
                required=False,
            )

        form = Form({"values[0][0]": "1"})

        self.assertFalse(form.is_valid())
        rendered = str(form["values"])
        self.assertEqual(form["values"].value(), [["1"]])
        self.assertIn("Enter a mapping of values.", rendered)

    def test_custom_child_rebinding_uses_django_field_fallbacks(self):
        """A custom child widget receives hostile input without type assumptions."""

        class CustomWidget(forms.TextInput):
            pass

        class RejectingField(forms.CharField):
            widget = CustomWidget

            def bound_data(self, data, initial):
                raise ValidationError("Cannot bind this value.")

            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class Form(forms.Form):
            values = nestingdolls.ListField(RejectingField(), required=False)

        form = Form({"values[0]": "hostile"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form["values"].value(), ["hostile"])
        self.assertIn('value="hostile"', str(form["values"]))

    def test_numeric_mapping_child_names_remain_valid_below_a_list(self):
        """A mapping child named ``0`` still accepts ``values[0][0]`` spellings."""

        NumericChildForm = type(
            "NumericChildForm",
            (forms.Form,),
            {"0": forms.IntegerField()},
        )

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(NumericChildForm),
                required=False,
            )

        cases = (
            {"values[0][0]": "1"},
            {"values.0.0": "1"},
            {"values-0-0": "1"},
        )
        for data in cases:
            with self.subTest(data=data):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], [{"0": 1}])
                self.assertEqual(form["values"].value(), [{"0": "1"}])
                str(form["values"])

    def test_text_list_indexes_do_not_bind(self):
        """Text segments cannot name sequence rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            {"values[text]": "1"},
            {"values.text": "1"},
            {"values[text][a]": "1"},
        )
        for data in cases:
            with self.subTest(data=data):
                form = Form(data)
                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors.as_data()["values"][0].code, "required")


class WidgetIntegrationTestCase(SimpleTestCase):
    def test_custom_child_choices_are_rendered(self):
        """It renders child choice widgets normally."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.ChoiceField(choices=(("a", "A"),)))

        html = Form(initial={"values": ["a"]}).as_p()

        self.assertInHTML('<option value="a" selected>A</option>', html)

    def test_child_prepare_value_is_used(self):
        """It uses the child field's prepared value when rendering."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField())

        html = Form(initial={"values": [{"answer": 42}]}).as_p()

        self.assertInHTML(
            '<textarea name="values-0" cols="40" rows="10" id="id_values_0">{&quot;answer&quot;: 42}</textarea>',
            html,
        )

    def test_boolean_rows_keep_unchecked_positions(self):
        """It keeps unchecked boolean rows in place."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0&values-1=on"
        )
        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [False, True])

    def test_plain_mapping_keeps_unchecked_positions(self):
        """It keeps unchecked boolean positions in flat mappings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        form = Form({"values-1": "on"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [False, True])

    def test_plain_mapping_list_management_values_use_the_last_submitted_value(self):
        """It accepts dict-of-lists management data the same way QueryDict does."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": ["1", "2"],
                f"values-{INITIAL_FORM_COUNT}": ["0"],
                "values-0": ["1"],
                "values-1": ["2"],
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_multiwidget_child_uses_indexed_row_name(self):
        """It passes indexed row names into child multiwidgets."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        data = {"values-0_0": "2024-01-02", "values-0_1": "03:04:05"}
        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["values"][0]
        self.assertEqual(
            cleaned.replace(tzinfo=None),
            datetime(2024, 1, 2, 3, 4, 5),  # noqa: DTZ001
        )

    def test_multiwidget_child_accepts_dotted_and_bracketed_row_names(self):
        """It accepts dotted and bracketed names for child multiwidgets."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        data_shapes = (
            {"values.0_0": "2024-01-02", "values.0_1": "03:04:05"},
            {"values[0]_0": "2024-01-02", "values[0]_1": "03:04:05"},
        )
        for data in data_shapes:
            with self.subTest(data=data):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                cleaned = form.cleaned_data["values"][0]
                self.assertEqual(
                    cleaned.replace(tzinfo=None),
                    datetime(2024, 1, 2, 3, 4, 5),  # noqa: DTZ001
                )

    def test_normalizes_bound_data_once(self):
        """It normalizes one form's bound data only once."""

        class CountingWidget(nestingdolls.SequenceWidget):
            normalizations = 0

            def _normalize_mapping(self, data, name):
                type(self).normalizations += 1
                return super()._normalize_mapping(data, name)

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), widget=CountingWidget)

        form = Form({"values.0": "1"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.has_changed())
        form.as_p()
        self.assertEqual(CountingWidget.normalizations, 1)

    def test_normalized_data_is_not_shared_between_form_instances(self):
        """It keeps normalization caches scoped to one form instance."""

        class CountingWidget(nestingdolls.SequenceWidget):
            normalizations = 0

            def _normalize_mapping(self, data, name):
                type(self).normalizations += 1
                return super()._normalize_mapping(data, name)

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), widget=CountingWidget)

        first = Form({"values.0": "1"})
        second = Form({"values.0": "2"})

        self.assertTrue(first.is_valid(), first.errors)
        self.assertEqual(first.cleaned_data["values"], [1])
        self.assertTrue(second.is_valid(), second.errors)
        self.assertEqual(second.cleaned_data["values"], [2])
        self.assertEqual(CountingWidget.normalizations, 2)

    def test_file_field_keeps_and_clears_initial_values(self):
        """It keeps, clears, and deletes file rows correctly."""
        initial = SimpleUploadedFile("initial.txt", b"initial")

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.FileField(required=False), required=False
            )

        kept = Form(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0"),
            initial={"values": [initial]},
        )
        self.assertTrue(kept.is_valid(), kept.errors)
        self.assertIs(kept.cleaned_data["values"][0], initial)
        self.assertIs(kept["values"].value()[0], initial)

        clear_data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0",
            mutable=True,
        )
        clear_data["values-0-clear"] = "on"
        cleared = Form(clear_data, initial={"values": [initial]})
        self.assertTrue(cleared.is_valid(), cleared.errors)
        self.assertEqual(cleared.cleaned_data["values"], [False])

        contradictory = Form(
            clear_data,
            files={"values-0": SimpleUploadedFile("new.txt", b"new")},
            initial={"values": [initial]},
        )
        self.assertFalse(contradictory.is_valid())
        self.assertEqual(
            contradictory.errors.as_data()["values"][0].code, "item_invalid"
        )

        deleted = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                f"values-0-{DELETION_FIELD_NAME}=1"
            ),
            initial={"values": [initial]},
        )
        self.assertTrue(deleted.is_valid(), deleted.errors)
        self.assertEqual(deleted.cleaned_data["values"], [])

    def test_omitted_file_rows_keep_all_initial_values(self):
        """An omitted sequence preserves every initial upload for either required mode."""
        uploads = [
            SimpleUploadedFile("first.txt", b"first"),
            SimpleUploadedFile("second.txt", b"second"),
        ]

        for required in (False, True):
            Form = type(
                "Form",
                (forms.Form,),
                {
                    "values": nestingdolls.ListField(
                        forms.FileField(), required=required
                    )
                },
            )
            form = Form({}, initial={"values": uploads})

            with self.subTest(required=required):
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["values"], uploads)

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), required=False)

        deleted = OptionalForm({"values": []}, initial={"values": uploads})
        self.assertTrue(deleted.is_valid(), deleted.errors)
        self.assertEqual(deleted.cleaned_data["values"], [])

    def test_file_uploads_use_child_widget_extraction(self):
        """It reads file uploads through the child widget."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.FileField())

        upload = SimpleUploadedFile("one.txt", b"one")
        form = Form(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0"),
            files={"values-0": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"][0].name, "one.txt")

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(self):
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget(forms.CharField())
        file_widget = nestingdolls.SequenceWidget(forms.FileField())

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), widget=text_widget)

        class TextForm(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), widget=file_widget)

        self.assertTrue(UploadForm().is_multipart())
        self.assertFalse(TextForm().is_multipart())

    def test_splitdatetime_initial_microseconds_do_not_report_a_change(self):
        """It applies Django's initial microsecond normalization to each row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        initial = datetime(2024, 1, 2, 3, 4, 5, 123456)  # noqa: DTZ001
        initial_shapes = (
            {"values": [initial]},
            {"values": initial},
        )
        for initial_data in initial_shapes:
            with self.subTest(initial_data=initial_data):
                form = Form(
                    {"values-0_0": "2024-01-02", "values-0_1": "03:04:05"},
                    initial=initial_data,
                )
                self.assertFalse(form.has_changed())

    def test_flat_file_uploads_without_management_data_are_accepted(self):
        """It accepts flat file uploads without management fields."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.FileField())

        upload = SimpleUploadedFile("one.txt", b"one")
        form = Form({}, files={"values.1": upload})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"][0].name, "one.txt")

    def test_form_required_attribute_opt_out_is_preserved(self):
        """It respects the form-level required-attribute opt-out."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertNotIn(" required", Form(use_required_attribute=False).as_p())

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_localize_propagates_to_child_cleaning_and_rendering(self):
        """It propagates localization to child cleaning and rendering."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.DecimalField(), localize=True)

        with translation.override("de"):
            form = Form({"values-0": "1,5"})

        self.assertTrue(Form.base_fields["values"].child_field.localize)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [Decimal("1.5")])

    def test_widget_uses_management_data_and_exposes_media(self):
        """It renders management inputs and enhancement templates."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()
        html = form.as_p()

        self.assertInHTML(
            f'<input type="hidden" name="values-{TOTAL_FORM_COUNT}" value="2" data-sequence-total id="id_values-{TOTAL_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{INITIAL_FORM_COUNT}" value="0" id="id_values-{INITIAL_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{MIN_NUM_FORM_COUNT}" value="2" id="id_values-{MIN_NUM_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{MAX_NUM_FORM_COUNT}" value="1000" id="id_values-{MAX_NUM_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-0" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-1" id="id_values_1">',
            html,
        )
        self.assertIn('id="id_values_widget"', html)
        self.assertIn('id="id_values_rows"', html)
        self.assertIn('data-widget="sequence"', html)
        self.assertIn('data-sequence-field="values"', html)
        self.assertIn('id="id_values_row_0"', html)
        self.assertIn('id="id_values_0_DELETE"', html)
        self.assertIn('id="id_values_row_1"', html)
        self.assertIn('id="id_values_1_DELETE"', html)
        self.assertIn("data-sequence-empty-row", html)
        self.assertIn('id="id_values_row___prefix__"', html)
        self.assertIn('id="id_values___prefix___DELETE"', html)
        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )
        self.assertIn("data-sequence-remove-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-remove data-sequence-field="values" id="id_values___prefix___remove">Remove</button>',
            html,
        )
        self.assertIn("nestingdolls/sequence.js", str(form.media))

    def test_widget_uses_helper_specific_wrapper_markup(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()

        with self.assertTemplateUsed("django/forms/widgets/sequence/div.html"):
            div_html = form.as_div()
        with self.assertTemplateUsed("django/forms/widgets/sequence/table.html"):
            table_html = form.as_table()
        with self.assertTemplateUsed("django/forms/widgets/sequence/ul.html"):
            ul_html = form.as_ul()
        with self.assertTemplateUsed("django/forms/widgets/sequence/p.html"):
            p_html = form.as_p()

        self.assertIn('data-widget="sequence"', div_html)
        self.assertIn('<table role="presentation">', table_html)
        self.assertIn("<tbody", table_html)
        self.assertIn("<ul", ul_html)
        self.assertIn('data-widget="sequence"', p_html)
        self.assertIn("<span", p_html)

    def test_widget_switches_layout_between_sequential_renders(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()

        table_html = form.as_table()
        p_html = form.as_p()
        ul_html = form.as_ul()

        self.assertIn("<tbody", table_html)
        self.assertIn('data-widget="sequence"', p_html)
        self.assertIn("<span", p_html)
        self.assertIn("<ul", ul_html)

    def test_row_error_is_described_by_child_widget(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        form = Form(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"}
        )

        self.assertFalse(form.is_valid())
        html = form.as_div()
        self.assertInHTML(
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            html,
        )

    def test_row_error_without_auto_id_has_no_error_reference(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        form = Form(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"},
            auto_id=False,
        )

        self.assertFalse(form.is_valid())
        html = form.as_div()
        self.assertInHTML(
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
            html,
        )
        self.assertInHTML(
            '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
            html,
        )

    def test_compound_row_error_describes_every_subwidget(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        form = Form(
            {
                "values-0_0": "2026-08-05",
                "values-0_1": "not-a-time",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertFalse(form.is_valid())
        html = form.as_div()
        self.assertInHTML(
            '<input type="text" name="values-0_0" value="2026-08-05" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0_1" value="not-a-time" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_1">',
            html,
        )

    def test_invalid_widget_render_uses_active_helper_layout(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"}
        )

        self.assertFalse(form.is_valid())
        with self.assertTemplateUsed("django/forms/widgets/sequence/p.html"):
            html = form.as_p()

        self.assertIn('data-widget="sequence"', html)
        self.assertIn("<span", html)
        self.assertIn("Enter a whole number.", html)

    def test_widget_hides_add_button_when_initial_reaches_maximum(self):
        """It keeps only the add template when initial rows fill the limit."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": [1, 2]}).as_p()

        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )

    def test_widget_hides_add_button_when_initial_exceeds_maximum(self):
        """It keeps only the add template when initial rows exceed the limit."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": [1, 2, 3]}).as_p()

        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )

    def test_widget_bounds_callable_initial_before_materializing_it(self):
        """It reads at most absolute_max items from a callable initial."""

        class GuardedInitial(list[int]):
            def __iter__(self):
                for index, value in enumerate(super().__iter__()):
                    if index == 2:
                        raise AssertionError("read beyond absolute_max")
                    yield value

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                max_length=2,
                absolute_max=2,
                initial=lambda: GuardedInitial([1, 2, 3]),
            )

        html = Form().as_p()

        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)
        self.assertNotIn('name="values-2"', html)
        self.assertIn('name="values-TOTAL_FORMS" value="2"', html)
        self.assertIn('name="values-INITIAL_FORMS" value="2"', html)

    def test_nested_widget_bounds_runtime_initial_before_materializing_it(self):
        """It applies the same read bound to a nested runtime initial."""

        class GuardedInitial(list[int]):
            def __iter__(self):
                for index, value in enumerate(super().__iter__()):
                    if index == 2:
                        raise AssertionError("read beyond absolute_max")
                    yield value

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(), max_length=2, absolute_max=2
                ),
                max_length=1,
                absolute_max=1,
            )

        html = Form(initial={"values": [GuardedInitial([1, 2, 3])]}).as_p()

        self.assertIn('name="values-0-0"', html)
        self.assertIn('name="values-0-1"', html)
        self.assertNotIn('name="values-0-2"', html)
        self.assertIn('name="values-0-TOTAL_FORMS" value="2"', html)
        self.assertIn('name="values-0-INITIAL_FORMS" value="2"', html)


class PublicApiTestCase(SimpleTestCase):
    def test_management_names_match_the_formset_contract(self):
        """The widget uses Django's four formset management names."""
        self.assertEqual(
            nestingdolls.SequenceWidget.management_names("values"),
            {
                f"values-{TOTAL_FORM_COUNT}",
                f"values-{INITIAL_FORM_COUNT}",
                f"values-{MIN_NUM_FORM_COUNT}",
                f"values-{MAX_NUM_FORM_COUNT}",
            },
        )

    def test_public_aliases_and_bounds(self):
        """It keeps the public aliases and constructor bounds intact."""
        self.assertIs(nestingdolls.SequenceField, nestingdolls.ListField)
        self.assertTrue(issubclass(nestingdolls.TupleField, nestingdolls.SequenceField))
        self.assertTrue(issubclass(nestingdolls.SetField, nestingdolls.SequenceField))
        self.assertIs(nestingdolls.FrozenSequenceField, nestingdolls.TupleField)
        self.assertTrue(issubclass(nestingdolls.FrozenSetField, nestingdolls.SetField))
        self.assertTrue(issubclass(nestingdolls.InvalidInitialValueError, ValueError))
        self.assertTrue(
            issubclass(
                nestingdolls.SequenceInputValidationError,
                ValidationError,
            )
        )
        self.assertTrue(
            issubclass(
                nestingdolls.MissingManagementFormValidationError,
                ValidationError,
            )
        )
        self.assertTrue(
            issubclass(
                nestingdolls.TooManyFormsValidationError,
                ValidationError,
            )
        )
        self.assertTrue(issubclass(nestingdolls.ItemValidationError, ValidationError))
        self.assertEqual(
            nestingdolls.ListField(forms.IntegerField(), initial=range(2)).initial,
            range(2),
        )
        with self.assertRaises(nestingdolls.SequenceInputValidationError):
            nestingdolls.ListField(forms.IntegerField()).clean("not a list")

        with self.assertRaises(nestingdolls.InvalidInitialValueError):
            nestingdolls.ListField(forms.IntegerField(), initial="not a collection")
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=1, initial=[1, 2])
        with self.assertRaisesMessage(
            ValueError, "'absolute_max' must be greater or equal to 'max_length'."
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=2, absolute_max=1)

        for kwargs in (
            {"min_length": -1},
            {"max_length": -1},
            {"min_length": 2, "max_length": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                nestingdolls.ListField(forms.IntegerField(), **kwargs)

    def test_rejects_non_fields_and_legacy_widget_usage(self):
        """It rejects invalid child fields and legacy widget arguments."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)

    def test_widget_instance_is_copied_and_rebound_to_field_configuration(self):
        """Django copies a supplied widget before the field configures it."""
        original_child = forms.CharField()
        widget = nestingdolls.SequenceWidget(
            original_child,
            min_length=4,
            max_length=5,
            absolute_max=6,
        )

        field = nestingdolls.ListField(
            forms.IntegerField(),
            min_length=1,
            max_length=2,
            absolute_max=3,
            widget=widget,
        )

        self.assertIsNot(field.widget, widget)
        self.assertIs(field.widget.child_field, field.child_field)
        self.assertEqual(field.widget.min_length, 1)
        self.assertEqual(field.widget.max_length, 2)
        self.assertEqual(field.absolute_max, 3)
        self.assertEqual(field.widget.absolute_max, field.absolute_max)
        self.assertIs(widget.child_field, original_child)
        self.assertEqual(widget.min_length, 4)
        self.assertEqual(widget.max_length, 5)
        self.assertEqual(widget.absolute_max, 6)

    def test_management_total_uses_configured_absolute_maximum(self):
        """It enforces a custom absolute maximum for management totals."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                max_length=1,
                absolute_max=2,
            )

        data = QueryDict("", mutable=True)
        data[f"values-{TOTAL_FORM_COUNT}"] = "3"
        data[f"values-{INITIAL_FORM_COUNT}"] = "0"
        form = Form(data)

        self.assertFalse(form.is_valid())
        self.assertIsInstance(
            form.errors.as_data()["values"][0],
            nestingdolls.TooManyFormsValidationError,
        )
        self.assertEqual(form.errors.as_data()["values"][0].code, "too_many_forms")

    def test_custom_bound_field_keeps_sequence_error_integration(self):
        """It lets custom bound fields keep sequence error rendering."""

        class CustomBoundField(nestingdolls.SequenceBoundField):
            pass

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=CustomBoundField
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=bad"
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIsInstance(form["values"], CustomBoundField)
        self.assertIn("Enter a whole number.", form.as_p())

    def test_sequence_bound_field_rejects_non_sequence_field(self):
        """It rejects direct misuse with a non-sequence field under optimized Python."""
        form = forms.Form()

        with self.assertRaisesRegex(TypeError, "field must be a SequenceField"):
            nestingdolls.SequenceBoundField(form, forms.CharField(), "value")


class SequenceParserPropertyTestCase(SimpleTestCase):
    @PARSER_HYPOTHESIS_SETTINGS
    @example(data={f"values-{'9' * 5000}": "x"}, files={})
    @example(data={"values-²": "x", "values[١]": "y"}, files={})
    @given(data=PARSER_MAPPINGS, files=PARSER_MAPPINGS)
    def test_normalization_is_total_bounded_idempotent_and_prefix_local(
        self, data, files
    ):
        """Arbitrary keys cannot escape the canonical bounded parser contract."""
        normalized = PARSER_WIDGET._normalize_mapping(data, "values")
        renormalized = PARSER_WIDGET._normalize_mapping(normalized, "values")
        self.assertEqual(renormalized, normalized)

        management_names = PARSER_WIDGET.management_names("values")
        for key in normalized:
            if key == "values" or key in management_names:
                continue
            self.assertTrue(key.startswith("values-"), key)
            suffix = key.removeprefix("values-")
            digits = suffix[: len(suffix) - len(suffix.lstrip("0123456789"))]
            self.assertTrue(digits, key)
            self.assertLess(int(digits), PARSER_WIDGET.absolute_max)

        unrelated = {f"other:{key}": value for key, value in data.items()}
        self.assertEqual(
            PARSER_WIDGET._normalize_mapping(data | unrelated, "values"), normalized
        )
        value = PARSER_WIDGET.value_from_datadict(data, files, "values")
        self.assertLessEqual(len(value), PARSER_WIDGET.absolute_max)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
