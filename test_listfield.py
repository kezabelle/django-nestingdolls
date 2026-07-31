import unittest
from collections import deque
from datetime import datetime
from decimal import Decimal
import json

import django
from hypothesis import HealthCheck, assume, example, given, settings as hypothesis_settings
from hypothesis import strategies as st
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
from django.utils import translation

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


def sequence_data(name, values=(), *, deleted=(), initial_forms=0):
    data = QueryDict("", mutable=True)
    data[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(values))
    data[f"{name}-{INITIAL_FORM_COUNT}"] = str(initial_forms)
    for index, value in enumerate(values):
        if value is not None:
            data[f"{name}-{index}"] = str(value)
    for index in deleted:
        data[f"{name}-{index}-{DELETION_FIELD_NAME}"] = "1"
    return data


HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
SMALL_INTEGERS = st.integers(min_value=-5, max_value=5)
SMALL_INTEGER_LISTS = st.lists(SMALL_INTEGERS, max_size=5)
JSON_SCALARS = st.none() | st.booleans() | st.integers(min_value=-5, max_value=5) | st.text(max_size=5)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=4), children, max_size=3),
    max_leaves=8,
)
DATETIME_ROWS = st.lists(
    st.datetimes(timezones=st.none()).map(lambda value: value.replace(microsecond=0)),
    max_size=4,
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

        form = Form(sequence_data("values", ["1", "2", "3"]))

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
                self.assertEqual(form.errors.as_data()["values"][0].code, "item_invalid")
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

        self.assertEqual(Form(initial={"values": range(3)})["values"].value(), [0, 1, 2])
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

    def test_overlapping_spellings_use_normal_overwrite_semantics(self):
        """It lets later overlapping spellings overwrite earlier ones."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            ({"values-1": "2", "values.1": "3"}, [3], "later canonical row wins"),
            ({"values": ["1"], "values-0": "2"}, [1], "direct value wins over indexed convenience"),
            ({"values-01": "2", "values-1": "3"}, [3], "later normalized index wins"),
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

        form = Form(sequence_data("values", ["1", "bad", "also-bad"]))

        self.assertFalse(form.is_valid())
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.code for error in errors], ["item_invalid", "item_invalid"])
        self.assertEqual([error.params["index"] for error in errors], [1, 2])
        self.assertEqual(list(form["values"].errors), [])

        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertInHTML(
            '<input type="number" name="values-1" value="bad" id="id_values_1" aria-invalid="true">',
            html,
        )
        self.assertInHTML("<li>Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 1: Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 2: Enter a whole number.</li>", html)

    def test_item_errors_do_not_promote_to_field_errors(self):
        """It keeps child validation errors out of the field-level error list."""
        class Form(forms.Form):
            emails = nestingdolls.ListField(forms.EmailField(), min_length=4)

        form = Form(sequence_data("emails", ["", "", "", "", ""]))

        self.assertFalse(form.is_valid())
        self.assertEqual(
            [error.code for error in form.errors.as_data()["emails"]],
            ["item_invalid"] * 5,
        )
        self.assertEqual(list(form["emails"].errors), [])

        html = form.as_p()
        self.assertNotInHTML("<li>Item 0: This field is required.</li>", html)
        self.assertInHTML("<li>This field is required.</li>", html)

    def test_deletion_preserves_initial_indices(self):
        """It deletes rows without renumbering initial items."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            sequence_data("values", ["1", "2"], deleted=[1]), initial={"values": [1, 2]}
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
                data = sequence_data("values", ["1"], initial_forms=1)
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

        empty = OptionalForm(sequence_data("values"))
        short = OptionalForm(sequence_data("values", ["1"]))

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

        form = Form(sequence_data("values", ["1", None], deleted=[1]))

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
            initial_missing.errors.as_data()["values"][0].params["index"], 0
        )

    def test_leading_zero_indexes_normalize_once(self):
        """It normalizes leading-zero indexes to one row key."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form({"values-01": "2"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [2])

    def test_rejects_unhashable_cleaned_values(self):
        """It rejects unhashable cleaned values for sets."""
        field = nestingdolls.SetField(forms.JSONField())

        self.assertNotIn("unhashable", nestingdolls.ListField(forms.JSONField()).error_messages)

        with self.assertRaises(ValidationError) as context:
            field.clean([{"answer": 42}])
        self.assertEqual(context.exception.code, "unhashable")

    def test_has_changed_uses_child_field_semantics(self):
        """It delegates change detection to the child field."""
        field = nestingdolls.ListField(forms.JSONField())
        set_field = nestingdolls.SetField(forms.IntegerField())

        self.assertTrue(field.has_changed([True], ["1"]))
        self.assertFalse(set_field.has_changed({1, 2}, ["2", "1", "1"]))

    def test_has_changed_detects_added_and_removed_integer_rows(self):
        """It treats added and removed integer rows as changes."""
        field = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertFalse(field.has_changed([], []))
        self.assertTrue(field.has_changed([], [0]))
        self.assertTrue(field.has_changed([0], []))
        self.assertFalse(field.has_changed([0, 1], [0, 1]))

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
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.clean([])
        self.assertEqual(context.exception.code, "required")

    def test_to_python_rejects_errors_as_values(self):
        """It rejects validation errors passed in as raw values."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.to_python(ValidationError("not submitted data"))
        self.assertEqual(context.exception.code, "invalid")

    def test_widget_value_from_datadict_accepts_each_single_row_spelling(self):
        """It extracts one row from each supported indexed spelling."""
        field = nestingdolls.ListField(forms.CharField(required=False), required=False)

        self.assertEqual(field.widget.value_from_datadict({"values-0": "x"}, {}, "values"), ["x"])
        self.assertEqual(field.widget.value_from_datadict({"values.0": "x"}, {}, "values"), ["x"])
        self.assertEqual(field.widget.value_from_datadict({"values[0]": "x"}, {}, "values"), ["x"])

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

        data = sequence_data("values", ["1"])
        data.setlist("initial-values", ["1"])
        form = Form(data)

        self.assertFalse(form.has_changed())
        self.assertInHTML(
            '<input type="hidden" name="initial-values" value="1" id="initial-id_values_0">',
            form.as_p(),
        )

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

        form = Form(sequence_data("values", ["x"]))
        self.assertFalse(form.is_valid())
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.message for error in errors], ["first", "second"])
        self.assertEqual([error.params["child_code"] for error in errors], ["first_code", "second_code"])


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
                    datetime(2024, 1, 2, 3, 4, 5),
                    datetime(2024, 6, 7, 8, 9, 10),
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
        self.assertEqual(form.errors.as_data()["values"][0].params["child_code"], "max_length")

    def test_list_field_accepts_deeply_nested_list_children(self):
        """It cleans nested list children from flat nested keys."""
        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    nestingdolls.ListField(forms.IntegerField())
                )
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

        self.assertFalse(field.has_changed([[[2], [0]]], [[[2], [0]]]))
        self.assertTrue(field.has_changed([[[2], [0]]], [[[2], [1]]]))
        self.assertEqual(
            field.has_changed([[[2], [0]]], [[[2], [1]]]),
            child.has_changed([[2], [0]], [[2], [1]]),
        )
        self.assertEqual(
            field.has_changed([[[2], [0]]], [[[2], [0]]]),
            child.has_changed([[2], [0]], [[2], [0]]),
        )


class _HypothesisTestCase(SimpleTestCase):
    _row_spelling_names = ("direct", "dash", "dot", "bracket")
    _multiwidget_spelling_names = ("dash", "dot", "bracket")

    @staticmethod
    def _spelled_sequence_data(name, values, style, formatter=str):
        if style == "direct":
            return {name: [formatter(value) for value in values]}
        if style == "dash":
            return {f"{name}-{index}": formatter(value) for index, value in enumerate(values)}
        if style == "dot":
            return {f"{name}.{index}": formatter(value) for index, value in enumerate(values)}
        if style == "bracket":
            return {f"{name}[{index}]": formatter(value) for index, value in enumerate(values)}
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
        row_values = ["on" if value else None for value in values]
        return sequence_data(name, row_values)

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
                    ("error", tuple(error.code for error in form.errors.as_data()["values"]))
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

        form = Form(sequence_data("values", values))
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

        form = Form(
            sequence_data(
                "values",
                values,
                deleted=sorted(deleted),
                initial_forms=initial_forms,
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], self._undeleted_rows(values, deleted))

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

        form = Form(sequence_data("values", values, deleted=sorted(deleted)))
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
            values = nestingdolls.ListField(forms.BooleanField(required=False), required=False)

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

        form = Form(self._json_row_data("values", values, style), initial={"values": values})
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
        self.assertEqual(cleaned_results, [values] * len(self._multiwidget_spelling_names))


class SetFieldPropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(values=[1, 1])
    @given(values=SMALL_INTEGER_LISTS)
    def test_set_field_cleans_to_the_semantic_set(self, values):
        """It deduplicates rows exactly as a set would."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        form = Form(sequence_data("values", values))
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
            sequence_data("values", list(submitted)),
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
            sequence_data("values", submitted_values),
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
        form = Form(self._nested_tuple_data("values", submitted_rows), initial={"values": rows})
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


class WidgetIntegrationTestCase(SimpleTestCase):
    def test_custom_child_choices_are_rendered(self):
        """It renders child choice widgets normally."""
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.ChoiceField(choices=(("a", "A"),))
            )

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

        data = sequence_data("values", [None, "on"])
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

    def test_multiwidget_child_uses_indexed_row_name(self):
        """It passes indexed row names into child multiwidgets."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        data = {"values-0_0": "2024-01-02", "values-0_1": "03:04:05"}
        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["values"][0]
        self.assertEqual(cleaned.replace(tzinfo=None), datetime(2024, 1, 2, 3, 4, 5))

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
                    cleaned.replace(tzinfo=None), datetime(2024, 1, 2, 3, 4, 5)
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
            values = nestingdolls.ListField(forms.FileField(required=False), required=False)

        kept = Form(sequence_data("values", [None]), initial={"values": [initial]})
        self.assertTrue(kept.is_valid(), kept.errors)
        self.assertIs(kept.cleaned_data["values"][0], initial)

        clear_data = sequence_data("values", [None])
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
            sequence_data("values", [None], deleted=[0]), initial={"values": [initial]}
        )
        self.assertTrue(deleted.is_valid(), deleted.errors)
        self.assertEqual(deleted.cleaned_data["values"], [])

    def test_file_uploads_use_child_widget_extraction(self):
        """It reads file uploads through the child widget."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.FileField())

        upload = SimpleUploadedFile("one.txt", b"one")
        form = Form(sequence_data("values", [None]), files={"values-0": upload})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"][0].name, "one.txt")

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
        field = nestingdolls.ListField(forms.DecimalField(), localize=True)

        self.assertTrue(field.child_field.localize)
        with translation.override("de"):
            self.assertEqual(field.clean(["1,5"]), [Decimal("1.5")])

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
        self.assertIn("data-sequence-empty-row", html)
        self.assertIn("data-sequence-add-button", html)
        self.assertIn("data-sequence-remove-button", html)
        self.assertEqual(html.count("data-sequence-add>"), 1)
        self.assertEqual(html.count("data-sequence-remove>"), 1)
        self.assertIn("nestingdolls/sequence.js", str(form.media))

    def test_widget_hides_add_button_when_initial_reaches_maximum(self):
        """It keeps only the add template when initial rows fill the limit."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": [1, 2]}).as_p()

        self.assertIn("data-sequence-add-button", html)
        self.assertEqual(html.count("data-sequence-add>"), 1)

    def test_widget_hides_add_button_when_initial_exceeds_maximum(self):
        """It keeps only the add template when initial rows exceed the limit."""
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": [1, 2, 3]}).as_p()

        self.assertIn("data-sequence-add-button", html)
        self.assertEqual(html.count("data-sequence-add>"), 1)


class PublicApiTestCase(SimpleTestCase):
    def test_public_aliases_and_bounds(self):
        """It keeps the public aliases and constructor bounds intact."""
        self.assertIs(nestingdolls.SequenceField, nestingdolls.ListField)
        self.assertIs(nestingdolls.FrozenSequenceField, nestingdolls.TupleField)
        self.assertTrue(issubclass(nestingdolls.FrozenSetField, nestingdolls.SetField))
        self.assertTrue(issubclass(nestingdolls.InvalidInitialValueError, ValueError))
        self.assertEqual(
            nestingdolls.ListField(forms.IntegerField(), initial=range(2)).initial,
            range(2),
        )

        with self.assertRaises(nestingdolls.InvalidInitialValueError):
            nestingdolls.ListField(forms.IntegerField(), initial="not a collection")
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=1, initial=[1, 2])

        for kwargs in (
            {"min_length": -1},
            {"max_length": -1},
            {"min_length": 2, "max_length": 1},
            {"min_length": False},
            {"max_length": None},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    nestingdolls.ListField(forms.IntegerField(), **kwargs)

    def test_rejects_non_fields_and_legacy_widget_usage(self):
        """It rejects invalid child fields and legacy widget arguments."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)

    def test_custom_bound_field_keeps_sequence_error_integration(self):
        """It lets custom bound fields keep sequence error rendering."""
        class CustomBoundField(nestingdolls.SequenceBoundField):
            pass

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=CustomBoundField
            )

        form = Form(sequence_data("values", ["bad"]))

        self.assertFalse(form.is_valid())
        self.assertIsInstance(form["values"], CustomBoundField)
        self.assertIn("Enter a whole number.", form.as_p())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
