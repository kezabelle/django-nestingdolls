import json
import unittest
from collections import deque
from datetime import datetime
from urllib.parse import urlencode

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
from django.http import JsonResponse, QueryDict
from django.test import SimpleTestCase, override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import path
from django.utils import translation
from django.utils.datastructures import MultiValueDict
from django.views import View

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


def setUpModule():
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule():
    # Undo the global template instrumentation after these unittest-based tests.
    teardown_test_environment()


class FormBindingUnitTestCase(SimpleTestCase):
    """Binds forms directly when tests need form internals."""

    def build_querydict_form(self, form_class, pairs, *, initial=None, prefix=None):
        """Bind form_class the way a browser <form> submit does: prefixed keys.

        `pairs` is a dict of prefixed keys (e.g. {"values-0": "1"}) or an
        already-encoded query string.
        """
        body = pairs if isinstance(pairs, str) else urlencode(pairs, doseq=True)
        return form_class(QueryDict(body), initial=initial, prefix=prefix)

    def build_whole_value_form(
        self, form_class, field_name, value, *, initial=None, prefix=None
    ):
        """Bind form_class the way application code hands over a decoded value.

        `value` is the Python value (list for ListField, dict for DictField)
        exactly as JSON- or CSV-inflated data would supply it, under the
        field's own name, with no prefixed row keys.
        """
        return form_class({field_name: value}, initial=initial, prefix=prefix)


class SubmissionLimitProbeFixtures(SimpleTestCase):
    class SequenceRootForm(forms.Form):
        outer = nestingdolls.ListField(
            nestingdolls.ListField(
                forms.BooleanField(required=False),
                max_length=10,
                absolute_max=10,
            ),
            max_length=10,
            absolute_max=10,
        )

    class MappingRootForm(forms.Form):
        class ValuesForm(forms.Form):
            first = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )
            second = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )

        values = nestingdolls.DictField(ValuesForm)

    class SequenceMappingSequenceForm(forms.Form):
        class ItemForm(forms.Form):
            tags = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )

        items = nestingdolls.ListField(
            nestingdolls.DictField(ItemForm),
            required=False,
            max_length=10,
            absolute_max=10,
        )


class ProbeView(View):
    form_class = None
    field_name = "values"

    def post(self, request):
        form = self.form_class(request.POST, request.FILES)
        valid = form.is_valid()
        return JsonResponse(self.response_data(form, valid, form.errors.as_data()))

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "values": form.cleaned_data.get(self.field_name) if valid else None,
            "errors": self.error_codes(errors),
        }

    def error_codes(self, errors):
        return {
            name: [error.code for error in field_errors]
            for name, field_errors in errors.items()
        }


class SequenceRootSubmissionLimitProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.SequenceRootForm

    def response_data(self, form, valid, errors):
        return {"valid": valid, "errors": self.error_codes(errors)}


class MappingRootSubmissionLimitProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.MappingRootForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "lengths": (
                {name: len(rows) for name, rows in form.cleaned_data["values"].items()}
                if valid
                else {}
            ),
        }


class SequenceMappingSequenceSubmissionProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.SequenceMappingSequenceForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "errors": self.error_codes(errors),
            "tag_counts": (
                [len(item["tags"]) for item in form.cleaned_data["items"]]
                if valid
                else []
            ),
        }


class ListProbeFixtures(SimpleTestCase):
    class SubmissionForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), required=False)

    class NestedForm(forms.Form):
        values = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

    class DisabledForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), disabled=True, initial=[1]
        )

    class MaxDeletionForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class JSONSubmissionForm(forms.Form):
        values = nestingdolls.ListField(forms.JSONField(), required=False)

    class DefaultAbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class AbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), max_length=1, absolute_max=2
        )

    class PointsForm(forms.Form):
        class PointForm(forms.Form):
            a = forms.IntegerField()
            b = forms.IntegerField()
            c = forms.IntegerField()

        values = nestingdolls.ListField(
            nestingdolls.DictField(PointForm), max_length=5, absolute_max=10
        )

    class SetForm(forms.Form):
        values = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)


class NestedListProbeFixtures(SimpleTestCase):
    class ExactSubmissionForm(forms.Form):
        outer = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), max_length=1999),
            required=False,
        )

    class SparseAssetForm(forms.Form):
        class RowForm(forms.Form):
            label = forms.CharField(required=False)
            upload = forms.FileField(required=False)

        values = nestingdolls.ListField(
            nestingdolls.MappingField(RowForm), required=False
        )

    class NestedDeletionForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )


class SparseAssetProbeView(ProbeView):
    form_class = NestedListProbeFixtures.SparseAssetForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "rows": [
                [row.get("label"), getattr(row.get("upload"), "name", None)]
                for row in form.cleaned_data["values"]
            ]
            if valid
            else None,
            "errors": self.error_codes(errors),
        }


class SetProbeView(ProbeView):
    form_class = ListProbeFixtures.SetForm

    def response_data(self, form, valid, errors):
        data = super().response_data(form, valid, errors)
        if valid:
            data["values"] = sorted(data["values"])
        return data


class RedisplayProbeView(ProbeView):
    def response_data(self, form, valid, errors):
        data = super().response_data(form, valid, errors)
        # The browser gets this HTML back when a submission fails, so the
        # redisplayed page is part of the submitted-state contract.
        data["html"] = form.as_p()
        return data


urlpatterns = [
    path(
        "list-submission-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.SubmissionForm),
    ),
    path("set-submission-probe/", SetProbeView.as_view()),
    path(
        "disabled-list-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DisabledForm),
    ),
    path(
        "list-max-deletion-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.MaxDeletionForm),
    ),
    path(
        "list-json-submission-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.JSONSubmissionForm),
    ),
    path(
        "list-default-absolute-maximum-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DefaultAbsoluteMaximumForm),
    ),
    path(
        "list-absolute-maximum-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.AbsoluteMaximumForm),
    ),
    path(
        "list-of-points-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.PointsForm),
    ),
    path(
        "exact-nested-submission-probe/",
        ProbeView.as_view(
            form_class=NestedListProbeFixtures.ExactSubmissionForm,
            field_name="outer",
        ),
    ),
    path(
        "sequence-root-submission-limit/",
        SequenceRootSubmissionLimitProbeView.as_view(),
    ),
    path(
        "mapping-root-submission-limit/",
        MappingRootSubmissionLimitProbeView.as_view(),
    ),
    path(
        "sequence-mapping-sequence-submission-limit/",
        SequenceMappingSequenceSubmissionProbeView.as_view(),
    ),
    path("sparse-asset-probe/", SparseAssetProbeView.as_view()),
    path(
        "nested-deletion-redisplay-probe/",
        RedisplayProbeView.as_view(
            form_class=NestedListProbeFixtures.NestedDeletionForm
        ),
    ),
    path(
        "nested-row-error-redisplay-probe/",
        RedisplayProbeView.as_view(form_class=ListProbeFixtures.NestedForm),
    ),
]


@override_settings(ROOT_URLCONF=__name__)
class SequenceFieldTestCase(FormBindingUnitTestCase):
    field_class = nestingdolls.ListField
    collection_class = list

    def assert_cleaned_values(self, cleaned_data, values):
        self.assertIsInstance(cleaned_data, self.collection_class)
        self.assertEqual(cleaned_data, self.collection_class(values))

    def test_client_accepts_repeated_key_list_rows(self):
        """A repeated exact-name key submits scalar list rows without management controls."""
        response = self.client.post(
            "/list-submission-probe/", {"values": ["1", "2", "3"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"valid": True, "values": [1, 2, 3], "errors": {}}
        )

    def test_client_accepts_prefixed_row_list_rows(self):
        """Django-managed prefixed rows submit the same scalar list."""
        response = self.client.post(
            "/list-submission-probe/",
            {
                "values-0": "1",
                "values-1": "2",
                "values-2": "3",
                f"values-{TOTAL_FORM_COUNT}": "3",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"valid": True, "values": [1, 2, 3], "errors": {}}
        )

    def test_client_accepts_a_repeated_key_json_row(self):
        """A repeated exact-name key submits one JSON-encoded scalar row."""
        value = {"answer": 42, "nested": [1, 2]}
        response = self.client.post(
            "/list-json-submission-probe/", {"values": [json.dumps(value)]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"valid": True, "values": [value], "errors": {}}
        )

    def test_client_accepts_a_prefixed_row_json_row(self):
        """A Django-managed prefixed row submits the same JSON-encoded scalar row."""
        value = {"answer": 42, "nested": [1, 2]}
        response = self.client.post(
            "/list-json-submission-probe/",
            {
                "values-0": json.dumps(value),
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"valid": True, "values": [value], "errors": {}}
        )

    def test_json_child_change_detection_uses_cleaned_values(self):
        """Managed change detection compares JSON rows after normalization."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        value = {"answer": 42, "nested": [1, 2]}
        form = Form(
            {
                "values-0": json.dumps(value),
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
            initial={"values": [value]},
        )
        self.assertIs(form.has_changed(), False)

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

    def test_client_treats_an_exact_name_scalar_as_one_list_row(self):
        """Client returns one list row for an exact-name scalar control."""
        response = self.client.post("/list-submission-probe/", {"values": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"valid": True, "values": [1], "errors": {}}
        )

    def test_exact_name_scalar_rendering_normalizes_bound_and_initial_values(self):
        """Whole-value rendering exposes the scalar row as one indexed input."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        bound = Form({"values": "1"})
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            bound.as_p(),
        )
        unbound = Form(initial={"values": 1})
        self.assertEqual(unbound["values"].value(), [1])

    def assertMissingManagementFormResponse(self, query):
        response = self.client.post(
            "/list-submission-probe/",
            data=query,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["missing_management_form"]},
            },
        )

    def test_client_reports_missing_management_form_without_total_forms(self):
        """A prefixed row without total forms reports a management error."""
        self.assertMissingManagementFormResponse("values-INITIAL_FORMS=0&values-0=1")

    def test_client_reports_missing_management_form_without_initial_forms(self):
        """A prefixed row without initial forms reports a management error."""
        self.assertMissingManagementFormResponse("values-TOTAL_FORMS=1&values-0=1")

    def test_client_reports_missing_management_form_for_an_out_of_range_row_key(self):
        """An out-of-range row key without controls reports a management error."""
        self.assertMissingManagementFormResponse("values-999999=1")

    def assertInvalidManagementRedisplay(
        self, form_class, data, initial, management_input
    ):
        form = self.build_querydict_form(form_class, data, initial=initial)
        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertInHTML(management_input, html)
        return form, html

    def test_invalid_total_management_data_redisplays_submitted_rows(self):
        """An invalid total control stays in the rendered sequence form."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertInvalidManagementRedisplay(
            Form,
            f"values-{TOTAL_FORM_COUNT}=2&values-0=1&values-1=bad",
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" id="id_values-INITIAL_FORMS">',
        )

    def test_invalid_initial_management_data_redisplays_submitted_rows(self):
        """An invalid initial control stays in the rendered sequence form."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertInvalidManagementRedisplay(
            Form,
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=bad&values-0=1&values-1=bad",
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="bad" id="id_values-INITIAL_FORMS">',
        )

    def test_client_uses_the_last_duplicate_list_management_value(self):
        """Client uses the final submitted list management value."""
        pairs = (
            (f"values-{TOTAL_FORM_COUNT}", "1"),
            (f"values-{TOTAL_FORM_COUNT}", "2"),
            (f"values-{INITIAL_FORM_COUNT}", "0"),
            ("values-0", "1"),
            ("values-1", "2"),
        )
        response = self.client.post(
            "/list-submission-probe/",
            data=urlencode(pairs),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "values": [1, 2], "errors": {}},
        )

    def test_plain_mapping_does_not_invent_duplicate_management_values(self):
        """A list from ``dict.get()`` stays one invalid management value."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": ["1", "2"],
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
            }
        )

        self.assertIs(form.is_valid(), False)
        self.assertEqual(
            form.errors.as_data()["values"][0].code, "missing_management_form"
        )

    def test_rows_above_maximum_redisplay_management_state(self):
        """Rows above the maximum keep their submitted management controls."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        class MaximumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        _, html = self.assertInvalidManagementRedisplay(
            MaximumForm,
            submitted,
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
        )
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total id="id_values-TOTAL_FORMS">',
            html,
        )

    def test_rows_below_minimum_redisplay_management_state(self):
        """Rows below the minimum keep their submitted initial count."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        class MinimumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=3)

        form, _ = self.assertInvalidManagementRedisplay(
            MinimumForm,
            submitted,
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
        )
        self.assertEqual(form.errors.as_data()["values"][0].code, "min_length")

    def test_invalid_original_row_with_deleted_added_row_redisplays_management_state(
        self,
    ):
        """An invalid saved row keeps the deleted added row state."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        class PlainForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        _, html = self.assertInvalidManagementRedisplay(
            PlainForm,
            submitted + f"&values-0=bad&values-1=2&values-1-{DELETION_FIELD_NAME}=on",
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
        )
        self.assertInHTML(
            '<input type="hidden" name="values-1-DELETE" value="1" data-sequence-deleted-row data-sequence-field="values">',
            html,
        )
        self.assertNotInHTML(
            '<input type="number" name="values-1" value="2" id="id_values_1">',
            html,
        )

    def test_client_removes_a_deleted_list_row(self):
        """Client returns the surviving list rows after deletion."""
        response = self.client.post(
            "/list-submission-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
                f"values-1-{DELETION_FIELD_NAME}": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "values": [1], "errors": {}},
        )

        response = self.client.post(
            "/list-max-deletion-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                f"values-1-{DELETION_FIELD_NAME}": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "values": [1], "errors": {}},
        )

    def assertDeletionValueRemovesRow(self, delete_value):
        response = self.client.post(
            "/list-submission-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                f"values-0-{DELETION_FIELD_NAME}": delete_value,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "values": [], "errors": {}},
        )

    def test_client_treats_delete_value_1_as_deletion(self):
        """The delete value one removes a submitted row."""
        self.assertDeletionValueRemovesRow("1")

    def test_client_treats_delete_value_on_as_deletion(self):
        """The delete value on removes a submitted row."""
        self.assertDeletionValueRemovesRow("on")

    def test_client_treats_delete_value_true_as_deletion(self):
        """The delete value true removes a submitted row."""
        self.assertDeletionValueRemovesRow("true")

    def test_client_ignores_submitted_disabled_list_rows(self):
        """Client returns the initial value for a disabled list."""
        response = self.client.post(
            "/disabled-list-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "9",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "values": [1], "errors": {}},
        )

    def test_disabled_list_units_preserve_child_and_change_detection_behavior(self):
        """Field-level checks cover disabled child and change-detection internals."""

        class ChildForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(disabled=True))

        submitted = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=99"
        )
        valid = ChildForm(submitted, initial={"values": ["7"]})
        self.assertIs(valid.is_valid(), True, valid.errors)
        self.assertEqual(valid.cleaned_data["values"], [7])

        invalid = ChildForm(submitted, initial={"values": ["bad"]})
        self.assertIs(invalid.is_valid(), False)
        error = invalid.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "invalid")

    def assertOversizedDisabledFieldSkipsChildComparison(self, field_class):
        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("disabled child value was compared")

        OversizedForm = type(
            "OversizedForm",
            (forms.Form,),
            {
                "values": field_class(
                    UnreachableField(),
                    max_length=0,
                    required=False,
                    disabled=True,
                )
            },
        )
        absolute_max = OversizedForm.base_fields["values"].absolute_max
        oversized = OversizedForm({"values": ["1"] * (absolute_max + 1)})
        self.assertIs(oversized.has_changed(), False)

    def test_disabled_list_field_skips_child_comparison_for_oversized_whole_value(self):
        """An oversized disabled list does not compare its child values."""
        self.assertOversizedDisabledFieldSkipsChildComparison(nestingdolls.ListField)

    def test_disabled_set_field_skips_child_comparison_for_oversized_whole_value(self):
        """An oversized disabled set does not compare its child values."""
        self.assertOversizedDisabledFieldSkipsChildComparison(nestingdolls.SetField)

        class PointForm(forms.Form):
            a = forms.IntegerField()

        class TamperedForm(forms.Form):
            point = nestingdolls.MappingField(
                PointForm,
                initial={"a": 1},
                disabled=True,
                show_hidden_initial=True,
            )
            values = nestingdolls.ListField(
                forms.IntegerField(),
                initial=[1],
                disabled=True,
                show_hidden_initial=True,
            )

        tampered = TamperedForm(
            QueryDict(
                "point-a=9&initial-point=malformed&"
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=1&values-0=9&"
                "initial-values-TOTAL_FORMS=malformed&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=8"
            )
        )
        self.assertIs(tampered.has_changed(), False)
        self.assertIs(tampered.is_valid(), True, tampered.errors)
        self.assertEqual(tampered.cleaned_data["point"], {"a": 1})
        self.assertEqual(tampered.cleaned_data["values"], [1])

    def assertTooManyFormsResponse(self, url, total):
        response = self.client.post(
            url,
            {
                f"values-{TOTAL_FORM_COUNT}": str(total),
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["too_many_forms"]},
            },
        )

    def test_client_rejects_total_beyond_default_absolute_maximum(self):
        """The client rejects a total beyond the default absolute maximum."""
        self.assertTooManyFormsResponse(
            "/list-default-absolute-maximum-probe/", DEFAULT_MAX_NUM + 2
        )

    def test_client_rejects_total_beyond_configured_absolute_maximum(self):
        """The client rejects a total beyond the configured absolute maximum."""
        self.assertTooManyFormsResponse("/list-absolute-maximum-probe/", 3)

    def test_client_requires_management_for_an_out_of_range_row_key(self):
        """A discarded index still makes a row-key-only request malformed."""
        response = self.client.post(
            "/list-default-absolute-maximum-probe/",
            {f"values-{DEFAULT_MAX_NUM + 1}": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["missing_management_form"]},
            },
        )

    def test_client_reports_an_error_code_for_each_invalid_list_item(self):
        """Client returns one item-invalid code for each invalid submitted row."""
        response = self.client.post(
            "/list-submission-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "3",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "bad",
                "values-2": "also-bad",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["item_invalid", "item_invalid"]},
            },
        )

    def test_item_error_markup_stays_inline_and_out_of_the_field_error_list(self):
        """In-process rendering keeps each list item error beside its input."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=bad&values-2=also-bad"
            )
        )

        self.assertIs(form.is_valid(), False)
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

        class EmailForm(forms.Form):
            emails = nestingdolls.ListField(forms.EmailField(), min_length=4)

        blanks = EmailForm(
            QueryDict(
                f"emails-{TOTAL_FORM_COUNT}=5&"
                f"emails-{INITIAL_FORM_COUNT}=0&"
                "emails-0=&emails-1=&emails-2=&emails-3=&emails-4="
            )
        )

        self.assertIs(blanks.is_valid(), False)
        # Row 4 sits past ``min_length``/``min_num``. Django's own formset
        # machinery already forces rows 0-3 to validate (index < min_num), so
        # each of those four reports its own blank-email error. Row 4 has no
        # submitted content anywhere in the request, so it is a genuine
        # untouched extra row and is silently omitted, matching a vanilla
        # Django formset's own "add row, leave it blank" behavior.
        self.assertEqual(
            [error.code for error in blanks.errors.as_data()["emails"]],
            ["item_invalid"] * 4,
        )
        self.assertEqual(list(blanks["emails"].errors), [])

        blank_html = blanks.as_p()
        self.assertNotInHTML("<li>Item 0: This field is required.</li>", blank_html)
        self.assertInHTML("<li>This field is required.</li>", blank_html)

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
        self.assertIs(form.is_valid(), False)
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.message for error in errors], ["first", "second"])
        self.assertEqual(
            [error.params["child_code"] for error in errors],
            ["first_code", "second_code"],
        )

    def assertPercentMessageRendersLiterally(self, child_field):
        Form = type(
            "Form",
            (forms.Form,),
            {"values": nestingdolls.ListField(child_field)},
        )
        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=x"
            )
        )
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.messages, ["50% off is required"])
        self.assertEqual(error.child_message, "50% off is required")
        self.assertEqual(error.params["message"], "50% off is required")
        self.assertEqual(
            dict(form["values"].formset.forms[0].errors),
            {"value": ["50% off is required"]},
        )
        html = form.as_p()
        self.assertIn("50% off is required", html)
        self.assertNotIn("50%% off", html)

    def test_eager_percent_error_message_renders_literally(self):
        """An eager child error keeps one literal percent sign."""

        class PercentField(forms.Field):
            def clean(self, value):
                raise ValidationError("50% off is required", code="required")

        self.assertPercentMessageRendersLiterally(PercentField())

    def test_lazy_percent_error_message_renders_literally(self):
        """A lazy child error keeps one literal percent sign."""

        class LazyPercentField(forms.Field):
            def clean(self, value):
                raise ValidationError(
                    translation.gettext_lazy("%(pct)s%% off is required"),
                    code="required",
                    params={"pct": 50},
                )

        self.assertPercentMessageRendersLiterally(LazyPercentField())

    def test_nested_mapping_rows_are_partitioned_before_extraction(self):
        """It gives each nested mapping only its own normalized row inputs."""

        class RowForm(forms.Form):
            value = forms.IntegerField()

        class CountingWidget(nestingdolls.MappingWidget):
            normalized_keys = 0

            def read_input(self, data, files, name):
                form_input = super().read_input(data, files, name)
                CountingWidget.normalized_keys += len(form_input.data) + len(
                    form_input.files
                )
                return form_input

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(RowForm, widget=CountingWidget),
                required=False,
            )

        row_count = 50
        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": str(row_count),
                f"values-{INITIAL_FORM_COUNT}": "0",
                **{f"values-{index}-value": str(index) for index in range(row_count)},
            }
        )

        self.assertIs(form.is_valid(), True, form.errors)
        # Each nested mapping receives only its own normalized child values.
        # The exact number of values is an implementation detail.
        self.assertLess(CountingWidget.normalized_keys, row_count * row_count)

    def test_added_removed_and_failing_rows_drive_has_changed(self):
        """Row cardinality changes and child comparison errors both mean "changed"."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertIs(Form({"values": []}, initial={"values": []}).has_changed(), False)
        self.assertIs(Form({"values": [0]}, initial={"values": []}).has_changed(), True)
        self.assertIs(Form({"values": []}, initial={"values": [0]}).has_changed(), True)
        self.assertIs(
            Form({"values": [0, 1]}, initial={"values": [0, 1]}).has_changed(), False
        )

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise ValidationError("comparison failed")

        class ErrorForm(forms.Form):
            values = nestingdolls.ListField(ErrorField(), required=False)

        self.assertIs(ErrorForm({"values": ["1"]}).has_changed(), True)

    def test_deleting_an_initial_row_is_a_change(self):
        """A delete mark on an initial row reports a change on its own.

        The resubmitted values match the initial values, so value
        comparison reports no change. Only ``formset.deleted_forms`` can
        report the deletion, and ``SequenceBoundField._has_changed``
        reads it only when initial rows exist, because that read
        validates every row form. This test holds the boundary of that
        skip: a deletion missed here would skip the save that removes
        the row.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        data = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "2",
            "values-0": "1",
            "values-1": "2",
        }
        initial = {"values": [1, 2]}
        self.assertIs(Form(data, initial=initial).has_changed(), False)

        deleted = dict(data)
        deleted[f"values-1-{DELETION_FIELD_NAME}"] = "1"
        self.assertIs(Form(deleted, initial=initial).has_changed(), True)

    def test_to_python_rejects_errors_as_values(self):
        """It rejects validation errors passed in as raw values."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.to_python(ValidationError("not submitted data"))
        self.assertEqual(context.exception.code, "invalid")

    def test_rejects_unhashable_cleaned_values(self):
        """It rejects unhashable cleaned values for sets."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.JSONField())

        form = Form({"values": [{"answer": 42}]})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["values"][0].code, "unhashable")

    def test_client_counts_composite_list_rows_not_their_child_keys(self):
        """Client accepts four mapping rows that each submit three child controls."""
        response = self.client.post(
            "/list-of-points-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "4",
                f"values-{INITIAL_FORM_COUNT}": "0",
                **{
                    f"values-{index}-{child}": "1"
                    for index in range(4)
                    for child in ("a", "b", "c")
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": True,
                "values": [{"a": 1, "b": 1, "c": 1}] * 4,
                "errors": {},
            },
        )

    def assertDisabledSequenceUsesInitialRows(self, data):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, initial=[1, 2]
            )

        form = Form(data)
        html = form.as_p()

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [1, 2])
        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)

    def test_disabled_sequence_ignores_deleted_submitted_state(self):
        """A disabled sequence ignores a submitted deleted row."""
        self.assertDisabledSequenceUsesInitialRows(
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
                f"values-0-{DELETION_FIELD_NAME}": "on",
            }
        )

    def test_disabled_sequence_ignores_invalid_management_state(self):
        """A disabled sequence ignores invalid submitted management data."""
        self.assertDisabledSequenceUsesInitialRows(
            {
                f"values-{TOTAL_FORM_COUNT}": "bad",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )

    def test_untouched_added_row_does_not_block_an_optional_list(self):
        """An unfilled extra row must not fail a required child on an optional list.

        A browser's "add row" control raises ``TOTAL_FORMS`` and renders a
        blank input before the user types anything; that blank input still
        submits its own key. A vanilla Django formset treats an unedited row
        beyond ``INITIAL_FORMS``/``min_num`` as unchanged and silently omits
        it. This field must match that, even though the row's own key is
        present in the request.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0="
            )
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [])

    def test_untouched_added_row_beside_a_filled_initial_row(self):
        """An added-but-blank row is dropped while the filled initial row survives."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=1&"
                "values-0=kept&values-1="
            )
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], ["kept"])

    def test_optional_child_blank_added_row_is_dropped_like_a_formset(self):
        """A blank added row is dropped even when the child accepts blank.

        A vanilla Django formset treats an unedited extra row as
        unchanged and omits it, whether or not its fields accept blank.
        This field matches that: an added-but-blank row never becomes an
        explicit empty value.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(required=False), required=False
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=1&"
                "values-0=kept&values-1="
            )
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], ["kept"])


class TupleFieldTestCase(SimpleTestCase):
    """`TupleField` is `SequenceField` with one line changed: ``compress``.

    These tests cover that difference and nothing else.
    """

    def test_clean_returns_an_immutable_tuple(self):
        """It collects cleaned rows into a tuple, through clean() and a bound form."""
        field = nestingdolls.TupleField(forms.IntegerField())

        cleaned = field.clean(["1", "2"])

        self.assertIsInstance(cleaned, tuple)
        self.assertEqual(cleaned, (1, 2))
        with self.assertRaises(TypeError):
            cleaned[0] = 3  # type: ignore[index]

        class Form(forms.Form):
            values = nestingdolls.TupleField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2"
            )
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], (1, 2))
        self.assertIsInstance(form.cleaned_data["values"], tuple)

    def test_has_changed_compares_a_tuple_initial(self):
        """A tuple initial compares against submitted rows, order included."""
        field = nestingdolls.TupleField(forms.IntegerField(), required=False)

        self.assertIs(field.has_changed((1, 2), ["1", "2"]), False)
        self.assertIs(field.has_changed((1, 2), ["2", "1"]), True)
        self.assertIs(field.has_changed((1, 2), ["1"]), True)

    def test_cardinality_limits_apply_to_the_tuple(self):
        """Length limits are checked on the compressed value."""
        field = nestingdolls.TupleField(
            forms.IntegerField(), min_length=2, max_length=2
        )

        with self.assertRaises(ValidationError) as context:
            field.clean(["1"])
        self.assertEqual(context.exception.code, "min_length")
        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "2", "3"])
        self.assertEqual(context.exception.code, "max_length")


@override_settings(ROOT_URLCONF=__name__)
class SetFieldTestCase(SimpleTestCase):
    def test_cardinality_is_checked_after_deduplication(self):
        """It checks set cardinality after removing duplicates."""
        field = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)

        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "1"])
        self.assertEqual(context.exception.code, "min_length")

        field = nestingdolls.SetField(forms.IntegerField(), max_length=1)
        self.assertEqual(field.clean(["1", "1"]), {1})

    def test_client_deduplicates_before_cardinality_validation(self):
        def submit(*values):
            return self.client.post(
                "/set-submission-probe/",
                {
                    f"values-{TOTAL_FORM_COUNT}": str(len(values)),
                    f"values-{INITIAL_FORM_COUNT}": "0",
                    **{f"values-{index}": value for index, value in enumerate(values)},
                },
            )

        duplicate = submit("1", "1")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(
            duplicate.json(),
            {"valid": False, "values": None, "errors": {"values": ["min_length"]}},
        )

        deduplicated = submit("1", "1", "2")
        self.assertEqual(deduplicated.status_code, 200)
        self.assertEqual(
            deduplicated.json(),
            {"valid": True, "values": [1, 2], "errors": {}},
        )

        too_many = submit("1", "2", "3")
        self.assertEqual(too_many.status_code, 200)
        self.assertEqual(
            too_many.json(),
            {"valid": False, "values": None, "errors": {"values": ["max_length"]}},
        )

    def test_frozen_set_field_is_an_immutable_set_variant(self):
        """It exposes a frozenset variant of the set field."""
        field = nestingdolls.FrozenSetField(forms.IntegerField())

        cleaned = field.clean(["2", "1", "1"])
        self.assertIsInstance(cleaned, frozenset)
        self.assertEqual(cleaned, frozenset({1, 2}))
        self.assertIs(field.has_changed(frozenset({1, 2}), ["2", "1", "1"]), False)
        with self.assertRaises(ValidationError) as context:
            nestingdolls.FrozenSetField(forms.JSONField()).clean([{"answer": 42}])
        self.assertEqual(context.exception.code, "unhashable")
        parent = nestingdolls.ListField(
            nestingdolls.FrozenSetField(forms.IntegerField(), required=False),
            required=False,
        )
        self.assertIs(parent.has_changed([frozenset({1, 2})], [["2", "1", "1"]]), False)

    def assertOversizedWholeValueMarksChanged(self, field_class, expected_initial):
        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        field = field_class(UnreachableField(), max_length=0, required=False)
        values = ["1"] * (field.absolute_max + 1)
        self.assertIs(field.has_changed(expected_initial, values), True)

    def test_oversized_whole_value_marks_set_changed_without_child_comparison(self):
        """An oversized set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(nestingdolls.SetField, set())

    def test_oversized_whole_value_marks_frozen_set_changed_without_child_comparison(
        self,
    ):
        """An oversized frozen set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(
            nestingdolls.FrozenSetField, frozenset()
        )

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

        self.assertIs(
            field.has_changed(
                set(range(size)), [str(value) for value in reversed(range(size))]
            ),
            False,
        )
        self.assertLessEqual(field.child_field.comparisons, size * 3)

    def test_has_changed_bounds_comparisons_for_non_matching_rows(self):
        """A hostile submission cannot make set comparison quadratic.

        Submitted rows can reach ``absolute_max``. Budget exhaustion reports a
        change, which is safer than a missed change.
        """

        class CountingCharField(forms.CharField):
            comparisons = 0

            def has_changed(self, initial, data):
                self.comparisons += 1
                return super().has_changed(initial, data)

        members = 1000
        rows = 2000
        field = nestingdolls.SetField(
            CountingCharField(required=False),
            max_length=rows,
            absolute_max=rows,
            required=False,
        )

        # An empty row matches no member. It is itself unchanged
        # against None. So nothing short-circuits the scan.
        changed = field.has_changed(
            {f"m{index}" for index in range(members)}, [""] * rows
        )

        self.assertIs(changed, True)
        self.assertLess(field.child_field.comparisons, 5 * (members + rows))

    def test_has_changed_reports_unhashable_rows_as_changed(self):
        """A compound child's unhashable rows count as a change, never a miss."""
        field = nestingdolls.SetField(
            forms.MultipleChoiceField(
                choices=[("first", "First"), ("second", "Second")]
            ),
            required=False,
        )

        self.assertIs(
            field.has_changed({("first", "second")}, [["second", "first"]]), True
        )
        self.assertIs(field.has_changed({("first", "second")}, [["first"]]), True)

    def test_has_changed_keeps_duplicate_blank_invalid_and_json_semantics(self):
        """Indexed matching preserves the child field's semantic edge cases."""
        integer_field = nestingdolls.SetField(
            forms.IntegerField(required=False), required=False
        )
        json_field = nestingdolls.SetField(forms.JSONField(), required=False)

        self.assertIs(integer_field.has_changed({1}, ["1", "1", ""]), False)
        self.assertIs(integer_field.has_changed({1}, ["invalid"]), True)
        self.assertIs(json_field.has_changed({True}, ["1"]), True)


class CompositeHiddenInitialTestCase(SimpleTestCase):
    def test_hidden_initial_markup_and_change_detection(self):
        """Hidden initial rows drive change detection and survive an invalid redisplay."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&"
            f"initial-values-{MIN_NUM_FORM_COUNT}=0&"
            f"initial-values-{MAX_NUM_FORM_COUNT}=1000&initial-values-0=1"
        )
        form = Form(data)

        self.assertIs(form.has_changed(), False)
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-TOTAL_FORMS" value="1" id="id_initial-values-TOTAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-INITIAL_FORMS" value="1" id="id_initial-values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MIN_NUM_FORMS" value="0" id="id_initial-values-MIN_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MAX_NUM_FORMS" value="1000" id="id_initial-values-MAX_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0" value="1" id="initial-id_values_0">',
            html,
        )

        malformed_initial = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&initial-values-0=not-an-integer"
        )
        self.assertIs(Form(malformed_initial).has_changed(), True)

        changed = data.copy()
        changed["values-0"] = "2"
        self.assertIs(Form(changed).has_changed(), True)

        legacy = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        legacy.setlist("initial-values", ["1"])
        self.assertIs(Form(legacy).has_changed(), False)

        invalid = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=bad&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=7"
            )
        )
        self.assertIs(invalid.is_valid(), False)
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0" value="7" id="initial-id_values_0">',
            invalid.as_p(),
        )

    def assertSequenceCollectionHiddenInitialIsUnchanged(self, field_class, initial):
        class Form(forms.Form):
            values = field_class(
                forms.IntegerField(),
                initial=initial,
                show_hidden_initial=True,
            )

        form = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=1&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=1"
            )
        )
        self.assertIs(form.has_changed(), False)

    def test_list_hidden_initial_round_trips_integer_child(self):
        """A list hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.ListField, [1]
        )

    def test_tuple_hidden_initial_round_trips_integer_child(self):
        """A tuple hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.TupleField, (1,)
        )

    def test_set_hidden_initial_round_trips_integer_child(self):
        """A set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.SetField, {1}
        )

    def test_frozen_set_hidden_initial_round_trips_integer_child(self):
        """A frozen set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.FrozenSetField, frozenset({1})
        )

    def test_compound_and_file_children_use_their_own_hidden_widgets(self):
        """A compound child hides every subwidget; a file child hides no filename."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(),
                initial=[datetime(2024, 1, 2, 3, 4, 5)],  # noqa: DTZ001
                show_hidden_initial=True,
            )

        html = CompoundForm().as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_0" value="2024-01-02" id="initial-id_values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_1" value="03:04:05" id="initial-id_values_0_1">',
            html,
        )

        compound = CompoundForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&"
                "values-0_0=2024-01-02&values-0_1=03%3A04%3A05&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&"
                "initial-values-0_0=2024-01-02&"
                "initial-values-0_1=03%3A04%3A05"
            )
        )
        self.assertIs(compound.has_changed(), False)

        class FileForm(forms.Form):
            files = nestingdolls.ListField(
                forms.FileField(required=False),
                initial=["saved.txt"],
                required=False,
                show_hidden_initial=True,
            )

        data = QueryDict(
            "files-TOTAL_FORMS=1&files-INITIAL_FORMS=1&"
            "initial-files-TOTAL_FORMS=1&initial-files-INITIAL_FORMS=1&"
            "initial-files-0=saved.txt"
        )
        self.assertIs(FileForm(data).has_changed(), False)

        upload = SimpleUploadedFile("replacement.txt", b"replacement")
        uploaded = FileForm(data, files=MultiValueDict({"files-0": [upload]}))
        self.assertIs(uploaded.has_changed(), True)

    def test_hidden_initial_recurses_through_nested_composites(self):
        """Hidden initial parsing recurses through alternating composites."""

        class PointForm(forms.Form):
            a = forms.IntegerField()

        class SequenceOfMappingsForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                initial=[{"a": 1}],
                show_hidden_initial=True,
            )

        html = SequenceOfMappingsForm().as_p()
        self.assertNotIn("{&#x27;a&#x27;: 1}", html)
        self.assertIn('name="initial-values-TOTAL_FORMS"', html)
        self.assertIn('name="initial-values-0-a"', html)

        rows = SequenceOfMappingsForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-a=1&"
                "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
                "initial-values-MIN_NUM_FORMS=0&initial-values-MAX_NUM_FORMS=1000&"
                "initial-values-0-a=1"
            )
        )
        self.assertIs(rows.has_changed(), False)

        class ContainerForm(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        class MappingOfSequenceForm(forms.Form):
            container = nestingdolls.MappingField(
                ContainerForm,
                initial={"rows": [{"a": 1}]},
                show_hidden_initial=True,
            )

        container_html = MappingOfSequenceForm().as_p()
        self.assertIn('name="initial-container-rows-TOTAL_FORMS"', container_html)
        self.assertIn('name="initial-container-rows-0-a"', container_html)

        container = MappingOfSequenceForm(
            QueryDict(
                "container-rows-TOTAL_FORMS=1&"
                "container-rows-INITIAL_FORMS=0&container-rows-0-a=1&"
                "initial-container-rows-TOTAL_FORMS=1&"
                "initial-container-rows-INITIAL_FORMS=1&"
                "initial-container-rows-0-a=1"
            )
        )
        self.assertIs(container.has_changed(), False)

    def assertHiddenSequenceMarkupIsMinimal(self, html):
        self.assertEqual(html.count('name="initial-values-0"'), 1)
        self.assertEqual(html.count('id="initial-id_values_0"'), 1)
        for name in (
            TOTAL_FORM_COUNT,
            INITIAL_FORM_COUNT,
            MIN_NUM_FORM_COUNT,
            MAX_NUM_FORM_COUNT,
        ):
            self.assertEqual(html.count(f'name="initial-values-{name}"'), 1)
        self.assertNotIn('name="initial-values-0-DELETE"', html)
        self.assertNotIn('name="initial-values-__prefix__"', html)
        self.assertNotIn('data-sequence-field="initial-values"', html)

    def test_hidden_initial_markup_is_minimal_with_as_p(self):
        """The paragraph helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_p())

    def test_hidden_initial_markup_is_minimal_with_as_div(self):
        """The div helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_div())

    def test_hidden_initial_markup_is_minimal_with_as_ul(self):
        """The list helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_ul())

    def test_hidden_initial_markup_is_minimal_with_as_table(self):
        """The table helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_table())


@override_settings(ROOT_URLCONF=__name__)
class NestedSequenceFieldTestCase(FormBindingUnitTestCase):
    def test_nested_change_detection_uses_child_semantics(self):
        """Nested change detection delegates to the child field's comparison."""
        tuple_field = nestingdolls.ListField(
            nestingdolls.TupleField(
                forms.IntegerField(),
                min_length=2,
                max_length=2,
            ),
            required=False,
        )

        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 0]]), False)
        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 1]]), True)
        self.assertIs(tuple_field.has_changed([(2, 0)], []), True)
        self.assertIs(tuple_field.has_changed([], [[2, 0]]), True)

        child = nestingdolls.ListField(
            nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False),
                required=False,
            ),
            required=False,
        )
        field = nestingdolls.ListField(child, required=False)

        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]), False)
        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]), True)
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]),
            child.has_changed([[[2], [0]]], [[[2], [1]]]),
        )
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]),
            child.has_changed([[[2], [0]]], [[[2], [0]]]),
        )

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_initial_rendering_reserves_rows_before_leaf_preparation(self):
        """Rendering clips nested initials before preparing excess leaf values."""

        class CountingField(forms.IntegerField):
            preparations = 0

            def prepare_value(self, value):
                CountingField.preparations += 1
                return super().prepare_value(value)

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    CountingField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        large_initial = [list(range(10)), list(range(10, 20))]
        CountingField.preparations = 0
        large_html = Form(initial={"outer": large_initial}).as_p()
        large_leaf_names = (
            f"outer-{outer_index}-{inner_index}"
            for outer_index in range(2)
            for inner_index in range(10)
        )
        rendered_large_leaves = sum(
            large_html.count(f'name="{name}"') for name in large_leaf_names
        )

        self.assertLessEqual(rendered_large_leaves, 10)
        self.assertLessEqual(CountingField.preparations, 10)

        small_initial = [list(range(4)), list(range(4, 8))]
        CountingField.preparations = 0
        small_html = Form(initial={"outer": small_initial}).as_p()
        small_leaf_names = (
            f"outer-{outer_index}-{inner_index}"
            for outer_index in range(2)
            for inner_index in range(4)
        )
        rendered_small_leaves = sum(
            small_html.count(f'name="{name}"') for name in small_leaf_names
        )

        self.assertEqual(rendered_small_leaves, 8)
        self.assertEqual(CountingField.preparations, 8)

    def assertSubmissionMaximum(self, limits, keys, expected):
        with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=keys):
            self.assertEqual(limits.submission_max, expected)

    def test_submission_max_uses_absolute_maximum_at_django_key_limit_1000(self):
        """A Django key limit of 1000 uses the absolute maximum."""
        limits = nestingdolls.ListField(forms.CharField()).limits
        self.assertEqual(limits.absolute_max, 2000)
        self.assertSubmissionMaximum(limits, 1000, 2000)

    def test_submission_max_uses_django_key_limit_5000(self):
        """A Django key limit of 5000 sets the submission maximum."""
        self.assertSubmissionMaximum(
            nestingdolls.ListField(forms.CharField()).limits, 5000, 5000
        )

    def test_submission_max_uses_absolute_maximum_at_django_key_limit_10(self):
        """A Django key limit of 10 uses the absolute maximum."""
        self.assertSubmissionMaximum(
            nestingdolls.ListField(forms.CharField()).limits, 10, 2000
        )

    def test_submission_max_uses_absolute_maximum_when_django_key_limit_is_disabled(
        self,
    ):
        """A disabled Django key limit uses the absolute maximum."""
        self.assertSubmissionMaximum(
            nestingdolls.ListField(forms.CharField()).limits, None, 2000
        )

    def test_submission_max_uses_default_when_django_key_limit_is_zero(self):
        """A zero Django key limit uses the default submission maximum."""
        limits = nestingdolls.ListField(
            forms.CharField(), max_length=10, absolute_max=10
        ).limits
        self.assertSubmissionMaximum(limits, 0, DEFAULT_MAX_NUM)

    def test_submission_max_uses_default_when_django_key_limit_is_none(self):
        """A none Django key limit uses the default submission maximum."""
        limits = nestingdolls.ListField(
            forms.CharField(), max_length=10, absolute_max=10
        ).limits
        self.assertSubmissionMaximum(limits, None, DEFAULT_MAX_NUM)

    def test_submission_max_uses_absolute_maximum_when_django_key_limit_is_lower(self):
        """A lower Django key limit uses the absolute maximum."""
        limits = nestingdolls.ListField(
            forms.CharField(), max_length=10, absolute_max=10
        ).limits
        self.assertSubmissionMaximum(limits, 5, limits.absolute_max)

    def test_client_accepts_an_exact_nested_submission_total(self):
        """Client accepts a nested submission that uses the shared cap exactly.

        The inner rows are declared initial, so they survive extraction the
        way a stock formset keeps its initial forms.
        """
        response = self.client.post(
            "/exact-nested-submission-probe/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                f"outer-0-{TOTAL_FORM_COUNT}": "1999",
                f"outer-0-{INITIAL_FORM_COUNT}": "1999",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["valid"], True)
        self.assertEqual(payload["errors"], {})
        self.assertEqual([len(rows) for rows in payload["values"]], [1999])

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_whole_values_keep_only_per_level_row_limits(self):
        """A developer-supplied nested value bypasses request counting but each list caps itself."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        form = Form({"outer": [list(range(10))]})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["outer"], [list(range(10))])

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_whole_values_reject_an_oversized_child_list(self):
        """A nested whole value still gets the child list's user-visible hard-cap error."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        form = Form({"outer": [list(range(11))]})

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["outer"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "too_many_forms")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_unbound_nested_initial_rendering_counts_parent_rows_before_children(self):
        """An unbound form renders nine inner inputs because its outer row spends one cap slot."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        html = Form(initial={"outer": [list(range(10))]}).as_p()

        self.assertIn('name="outer-0-8"', html)
        self.assertNotIn('name="outer-0-9"', html)

    def test_client_pairs_managed_sparse_data_and_file_rows_by_index(self):
        """Managed sparse data and file indexes identify the same row.

        The management total owns each row index. A gap does not change the
        data-file pair.
        """
        response = self.client.post(
            "/sparse-asset-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "6",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0-label": "row0-label",
                "values-5-label": "row5-label",
                "values-0-upload": SimpleUploadedFile("row0.txt", b"row0-file"),
                "values-3-upload": SimpleUploadedFile("row3.txt", b"row3-file"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": True,
                "rows": [
                    ["row0-label", "row0.txt"],
                    ["", "row3.txt"],
                    ["row5-label", None],
                ],
                "errors": {},
            },
        )

    def test_client_deletes_a_nested_row_and_redisplays_it_as_deleted(self):
        """Deleting a nested row removes it and renders it deleted.

        A nested sequence has no bound field of its own to read its rows'
        delete marks. Deleting one of its rows must still remove that row
        from the cleaned value, and the redisplayed form must still show
        that row as deleted.
        """
        response = self.client.post(
            "/nested-deletion-redisplay-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "2",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "kept",
                "values-0-1": "deleted-me",
                f"values-0-1-{DELETION_FIELD_NAME}": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["values"], [["kept"]])
        self.assertInHTML(
            '<input type="hidden" name="values-0-1-DELETE" value="1"'
            ' data-sequence-deleted-row data-sequence-field="values-0">',
            payload["html"],
        )
        self.assertNotIn('value="deleted-me"', payload["html"])

    def test_client_attaches_a_nested_row_error_to_that_nested_row(self):
        """A nested row error appears at its failing input.

        An error inside a nested row belongs to that row, not to the row
        that holds the nested sequence. The redisplayed form must attach
        the error to the actual failing input, several levels deep.
        """
        response = self.client.post(
            "/nested-row-error-redisplay-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "2",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "1",
                "values-0-1": "abc",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn('<ul class="errorlist" id="id_values_0_1_error">', html)
        self.assertIn('aria-describedby="id_values_0_1_error"', html)

    def test_row_bucketing_runs_once_for_each_input_source(self):
        """The parsed input cohort owns row bucketing for its full request lifetime."""

        class CountingWidget(nestingdolls.SequenceWidget):
            key_visits = 0

            def read_input(self, data, files, name):
                CountingWidget.key_visits += len(data) + len(files)
                return super().read_input(data, files, name)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, widget=CountingWidget
            )

        row_count = 50
        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": str(row_count),
                f"values-{INITIAL_FORM_COUNT}": "0",
                **{f"values-{index}": str(index) for index in range(row_count)},
            }
        )

        self.assertEqual(len(form["values"].data), row_count)
        extraction_visits = CountingWidget.key_visits
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(CountingWidget.key_visits, extraction_visits)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_field_clean_of_nested_values_pays_each_level_cap(self):
        """Nested ``clean()`` calls use each level's own cap.

        A ``clean()`` call has no request keys. It does not open the shared
        countdown, but each level still applies ``absolute_max``.
        """

        class CountingField(forms.CharField):
            cleans = 0

            def clean(self, value):
                CountingField.cleans += 1
                return super().clean(value)

        field = nestingdolls.ListField(
            nestingdolls.ListField(
                CountingField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            ),
            required=False,
            max_length=10,
            absolute_max=10,
        )

        CountingField.cleans = 0
        cleaned = field.clean([[None] * 10 for _ in range(10)])

        self.assertEqual(len(cleaned), 10)
        self.assertEqual(CountingField.cleans, 100)
        self.assertGreater(CountingField.cleans, field.limits.submission_max)

        with self.assertRaises(ValidationError) as context:
            field.clean([[None] * 11])
        error = context.exception.error_list[0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "too_many_forms")


class SequenceFieldCopyTestCase(SimpleTestCase):
    """What a deep copy of a nested sequence field shares, and what it does not.

    ``SequenceField.__deepcopy__`` keeps the row formset class that the
    source widget cached, instead of a rebuild of two classes for each
    row. These tests hold the lines that make that sharing safe.
    """

    def test_row_field_copies_share_one_row_formset_class(self):
        """Every row's field copy shares one cached row formset class.

        The shared class is the performance contract: without it, each
        nested row form builds two new classes. The row fields and their
        widgets must stay distinct objects, so no row shares mutable
        state with another row.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        form = Form(
            {
                "values-TOTAL_FORMS": "2",
                "values-INITIAL_FORMS": "0",
                "values-0-TOTAL_FORMS": "1",
                "values-0-INITIAL_FORMS": "0",
                "values-0-0": "a",
                "values-1-TOTAL_FORMS": "1",
                "values-1-INITIAL_FORMS": "0",
                "values-1-0": "b",
            }
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [["a"], ["b"]])

        first, second = (row.fields["value"] for row in form["values"].formset.forms)
        self.assertIsNot(first, second)
        self.assertIsNot(first.widget, second.widget)
        self.assertIsNot(first.child_field, second.child_field)
        self.assertIs(first.widget.formset_class, second.widget.formset_class)

    def test_configure_with_a_new_child_field_rebuilds_the_class(self):
        """A widget configured with a new child field builds a new class.

        The deep-copy path keeps the cached class only because its new
        child is a copy of the field that the class names. ``configure()``
        gets a child with no such relation, so it must remove the cache,
        or the widget builds rows from the old child field.
        """
        field = nestingdolls.ListField(forms.CharField(), required=False)
        widget = field.widget
        old_class = widget.formset_class
        self.assertIs(old_class.form.base_fields["value"], field.child_field)

        new_child = forms.IntegerField()
        widget.configure(new_child, field.limits)

        self.assertIsNot(widget.formset_class, old_class)
        self.assertIs(widget.formset_class.form.base_fields["value"], new_child)

    def test_a_child_field_change_on_one_form_reaches_its_rows(self):
        """A change to one form's child field changes that form's own rows.

        The shared class must not cross form instances. Each form's rows
        must come from that form's own child field chain, so a per-form
        change stays visible, and one form cannot leak configuration
        into another form of the same class.

        The form class is local to this test. The scope of the sharing is
        what this test measures, so no other test may touch this class.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        payload = {
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
            "values-0-TOTAL_FORMS": "1",
            "values-0-INITIAL_FORMS": "0",
            "values-0-0": "  padded  ",
        }
        # Complete one form lifecycle first. Sharing that crossed form
        # instances would then be observable in the second form.
        first = Form(payload)
        self.assertIs(first.is_valid(), True, first.errors)
        self.assertEqual(first.cleaned_data["values"], [["padded"]])

        second = Form(payload)
        second.fields["values"].child_field.child_field.strip = False
        self.assertIs(second.is_valid(), True, second.errors)
        self.assertEqual(second.cleaned_data["values"], [["  padded  "]])


class SequenceScalarRowTestCase(FormBindingUnitTestCase):
    """A scalar row's own validation outcome is the same in either input style.

    Cleaning a whole value already uses a fast path that reports each
    row's own error correctly. Rendering an invalid redisplay once built
    an unbound row formset and dropped that error silently instead of
    showing it inline. These tests are the regression guard for that fix,
    proven against both input styles.
    """

    def assertScalarRowError(self, form):
        """Assert row 1 of a 3-row int list shows its own inline error."""
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["item"], 1)
        html = form.as_p()
        self.assertEqual(html.count("errorlist"), 1)
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertIn('name="values-1" value="bad"', html)
        self.assertIn('aria-describedby="id_values_1_error"', html)
        self.assertInHTML("<li>Enter a whole number.</li>", html)

    def assertScalarRowsValid(self, form):
        """Assert a valid 3-row int list renders every row with no error markup."""
        self.assertIs(form.is_valid(), True, form.errors)
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        for index, value in enumerate((1, 2, 3)):
            self.assertIn(f'name="values-{index}" value="{value}"', html)

    def test_scalar_row_error_via_whole_value(self):
        """A bad row in a whole-value scalar list shows its own error, not silence."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertScalarRowError(
            self.build_whole_value_form(Form, "values", [1, "bad", 3])
        )

    def test_scalar_row_error_via_querydict(self):
        """A bad row in a prefixed-row scalar list shows its own error, not silence."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertScalarRowError(
            self.build_querydict_form(
                Form,
                {
                    f"values-{TOTAL_FORM_COUNT}": "3",
                    f"values-{INITIAL_FORM_COUNT}": "3",
                    "values-0": "1",
                    "values-1": "bad",
                    "values-2": "3",
                },
            )
        )

    def test_scalar_rows_valid_via_whole_value(self):
        """A valid whole-value scalar list renders every row with no error markup."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertScalarRowsValid(
            self.build_whole_value_form(Form, "values", [1, 2, 3])
        )

    def test_scalar_rows_valid_via_querydict(self):
        """A valid prefixed-row scalar list renders every row with no error markup."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertScalarRowsValid(
            self.build_querydict_form(
                Form,
                {
                    f"values-{TOTAL_FORM_COUNT}": "3",
                    f"values-{INITIAL_FORM_COUNT}": "3",
                    "values-0": "1",
                    "values-1": "2",
                    "values-2": "3",
                },
            )
        )


class SequenceMappingRowTestCase(FormBindingUnitTestCase):
    """A mapping row's own validation outcome is the same in either input style.

    Same regression guard as ``SequenceScalarRowTestCase``, for a row
    whose child is itself a ``DictField``, including the edge case where
    a row carries no submitted keys at all yet must still validate as
    real, present data rather than an untouched placeholder.
    """

    def assertMappingRowError(self, form):
        """Assert row 1's missing required child shows its own inline error."""
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["a"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["item"], 1)
        self.assertEqual(error.params["child_code"], "required")
        html = form.as_p()
        self.assertInHTML("<li>This field is required.</li>", html)
        self.assertIn('name="a-0-b" value="2"', html)
        self.assertIn('aria-describedby="id_a-1-b_error"', html)
        self.assertIn('name="a-1-c" value="3"', html)

    def assertMappingRowsValid(self, form):
        """Assert a valid mapping row list cleans and renders every child."""
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(
            form.cleaned_data["a"], [{"b": 2, "c": None}, {"b": None, "c": 3}]
        )
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        self.assertIn('name="a-0-b" value="2"', html)
        self.assertIn('name="a-1-c" value="3"', html)

    def assertKeylessRowIsRequired(self, form):
        """Assert an empty-dict/keyless row is real data, not skippable.

        A whole-value list has no prefixed row keys to leave blank. Every entry
        in the list is data the caller gave, even an empty mapping.
        Cleaning already validates every row unconditionally; rendering
        must not silently skip this row the way it skips an unfilled
        extra formset row from a browser.
        """
        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["a"][0].code, "item_invalid")
        self.assertInHTML("<li>This field is required.</li>", form.as_p())

    def test_mapping_row_error_via_whole_value(self):
        """A missing required child in a whole-value mapping row shows its error."""

        class Row(forms.Form):
            b = forms.IntegerField()
            c = forms.IntegerField(required=False)

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertMappingRowError(
            self.build_whole_value_form(Form, "a", [{"b": 2}, {"c": 3}])
        )

    def test_mapping_row_error_via_querydict(self):
        """A missing required child in a prefixed-row mapping row shows its error."""

        class Row(forms.Form):
            b = forms.IntegerField()
            c = forms.IntegerField(required=False)

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertMappingRowError(
            self.build_querydict_form(
                Form,
                {
                    f"a-{TOTAL_FORM_COUNT}": "2",
                    f"a-{INITIAL_FORM_COUNT}": "2",
                    "a-0-b": "2",
                    "a-1-c": "3",
                },
            )
        )

    def test_mapping_rows_valid_via_whole_value(self):
        """A valid whole-value mapping row list renders and cleans every child."""

        class Row(forms.Form):
            b = forms.IntegerField(required=False)
            c = forms.IntegerField(required=False)

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertMappingRowsValid(
            self.build_whole_value_form(Form, "a", [{"b": 2}, {"c": 3}])
        )

    def test_mapping_rows_valid_via_querydict(self):
        """A valid prefixed-row mapping row list renders and cleans every child."""

        class Row(forms.Form):
            b = forms.IntegerField(required=False)
            c = forms.IntegerField(required=False)

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertMappingRowsValid(
            self.build_querydict_form(
                Form,
                {
                    f"a-{TOTAL_FORM_COUNT}": "2",
                    f"a-{INITIAL_FORM_COUNT}": "2",
                    "a-0-b": "2",
                    "a-1-c": "3",
                },
            )
        )

    def test_mapping_row_with_no_keys_via_whole_value(self):
        """An empty-dict whole-value row is real data, not an untouched placeholder."""

        class Row(forms.Form):
            b = forms.IntegerField()

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertKeylessRowIsRequired(self.build_whole_value_form(Form, "a", [{}]))

    def test_mapping_row_with_no_keys_via_querydict(self):
        """A declared row with no submitted keys is real data too, not skippable."""

        class Row(forms.Form):
            b = forms.IntegerField()

        class Form(forms.Form):
            a = nestingdolls.ListField(nestingdolls.DictField(Row))

        self.assertKeylessRowIsRequired(
            self.build_querydict_form(
                Form, {f"a-{TOTAL_FORM_COUNT}": "1", f"a-{INITIAL_FORM_COUNT}": "1"}
            )
        )


class SequenceNestedListRowTestCase(FormBindingUnitTestCase):
    """A leaf two levels deep inside a nested list validates the same in either style.

    Same regression guard as ``SequenceScalarRowTestCase``, one nesting
    level deeper: a whole ``ListField(ListField(...))`` value's inner
    row error must still render inline, not just clean correctly.
    """

    def assertNestedLeafError(self, form):
        """Assert the bad leaf at outer row 0, inner row 1 shows its own error."""
        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertInHTML("<li>Enter a whole number.</li>", html)
        self.assertIn('name="outer-0-1" value="bad"', html)

    def test_nested_list_leaf_error_via_whole_value(self):
        """A bad leaf two levels deep in a whole-value nested list still shows its error."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

        self.assertNestedLeafError(
            self.build_whole_value_form(Form, "outer", [[1, "bad"]])
        )

    def test_nested_list_leaf_error_via_querydict(self):
        """A bad leaf two levels deep in a prefixed-row nested list still shows its error."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

        self.assertNestedLeafError(
            self.build_querydict_form(
                Form,
                {
                    f"outer-{TOTAL_FORM_COUNT}": "1",
                    f"outer-{INITIAL_FORM_COUNT}": "1",
                    f"outer-0-{TOTAL_FORM_COUNT}": "2",
                    f"outer-0-{INITIAL_FORM_COUNT}": "2",
                    "outer-0-0": "1",
                    "outer-0-1": "bad",
                },
            )
        )


@override_settings(ROOT_URLCONF=__name__, DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
class DjangoRequestLimitFunctionalTestCase(SimpleTestCase):
    def assertSequenceRootSubmission(
        self, inner_total, expected_valid, expected_errors
    ):
        response = self.client.post(
            "/sequence-root-submission-limit/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                f"outer-0-{TOTAL_FORM_COUNT}": str(inner_total),
                f"outer-0-{INITIAL_FORM_COUNT}": str(inner_total),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": expected_valid, "errors": expected_errors},
        )

    def test_sequence_root_rejects_total_above_shared_cap(self):
        """A sequence root rejects an inner total above its shared cap."""
        self.assertSequenceRootSubmission(10, False, {"outer": ["too_many_forms"]})

    def test_sequence_root_accepts_total_at_shared_cap(self):
        """A sequence root accepts an inner total at its shared cap."""
        self.assertSequenceRootSubmission(9, True, {})

    def test_request_rejects_more_urlencoded_keys_than_django_allows(self):
        """Django rejects URL-encoded keys above its request limit."""
        limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        body = urlencode([(f"unused-{index}", "1") for index in range(limit + 1)])

        response = self.client.post(
            "/sequence-root-submission-limit/",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=64)
    def test_request_rejects_body_larger_than_django_limit(self):
        """Django rejects a URL-encoded body larger than its byte limit."""
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        body = urlencode([("unused", "x" * limit)])
        self.assertGreater(len(body.encode()), limit)

        response = self.client.post(
            "/sequence-root-submission-limit/",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 400)

    def test_mapping_sibling_lists_keep_independent_per_level_allowances(self):
        """A mapping root accepts two capped lists because it is not a recursive row scope."""

        response = self.client.post(
            "/mapping-root-submission-limit/",
            {
                "values-first-TOTAL_FORMS": "10",
                "values-first-INITIAL_FORMS": "10",
                "values-second-TOTAL_FORMS": "10",
                "values-second-INITIAL_FORMS": "10",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "lengths": {"first": 10, "second": 10}},
        )

    def assertMappingSiblingRendersRows(self, child):
        form = SubmissionLimitProbeFixtures.MappingRootForm(
            initial={"values": {"first": [True] * 10, "second": [True] * 10}}
        )
        html = form.as_p()
        self.assertEqual(
            sum(html.count(f'name="values-{child}-{index}"') for index in range(10)),
            10,
        )

    def test_mapping_root_renders_first_sibling_rows_within_its_allowance(self):
        """A mapping root renders the first sibling rows within its allowance."""
        self.assertMappingSiblingRendersRows("first")

    def test_mapping_root_renders_second_sibling_rows_within_its_allowance(self):
        """A mapping root renders the second sibling rows within its allowance."""
        self.assertMappingSiblingRendersRows("second")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=100)
    def test_per_level_total_above_absolute_max_is_a_nested_form_error_after_parsing(
        self,
    ):
        """A parser-accepted child total above its own absolute maximum returns item_invalid."""

        response = self.client.post(
            "/sequence-root-submission-limit/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                f"outer-0-{TOTAL_FORM_COUNT}": "11",
                f"outer-0-{INITIAL_FORM_COUNT}": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": False, "errors": {"outer": ["item_invalid"]}},
        )

    def assertSequenceMappingSequenceSubmission(
        self, inner_total, expected_valid, expected_errors, expected_tag_counts
    ):
        response = self.client.post(
            "/sequence-mapping-sequence-submission-limit/",
            {
                f"items-{TOTAL_FORM_COUNT}": "1",
                f"items-{INITIAL_FORM_COUNT}": "0",
                f"items-0-tags-{TOTAL_FORM_COUNT}": str(inner_total),
                f"items-0-tags-{INITIAL_FORM_COUNT}": str(inner_total),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "valid": expected_valid,
                "errors": expected_errors,
                "tag_counts": expected_tag_counts,
            },
        )

    def test_sequence_mapping_sequence_rejects_total_above_outer_cap(self):
        """A nested sequence rejects a total above the outer cap."""
        self.assertSequenceMappingSequenceSubmission(
            10, False, {"items": ["too_many_forms"]}, []
        )

    def test_sequence_mapping_sequence_accepts_total_at_outer_cap(self):
        """A nested sequence accepts a total at the outer cap."""
        self.assertSequenceMappingSequenceSubmission(9, True, {}, [9])


class NestedParserRegressionTestCase(SimpleTestCase):
    def test_unrecognized_mapping_initial_becomes_one_renderable_row(self):
        """A mapping that is not flattened sequence data remains one raw row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        value = {"unexpected": "saved"}
        form = Form(initial={"values": value})

        self.assertEqual(form["values"].initial, [value])
        self.assertIn("unexpected", str(form["values"]))

    def assertTextIndexDoesNotBind(self, data):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(data)
        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["values"][0].code, "required")

    def test_bracket_text_index_does_not_bind(self):
        """A bracket text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values[text]": "1"})

    def test_dot_text_index_does_not_bind(self):
        """A dot text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values.text": "1"})

    def test_nested_bracket_text_index_does_not_bind(self):
        """A nested bracket text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values[text][a]": "1"})


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

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(self):
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget()
        file_widget = nestingdolls.SequenceWidget()

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), widget=text_widget)

        class TextForm(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), widget=file_widget)

        self.assertIs(UploadForm().is_multipart(), True)
        self.assertIs(TextForm().is_multipart(), False)

    def test_form_required_attribute_opt_out_is_preserved(self):
        """It respects the form-level required-attribute opt-out."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertNotIn(" required", Form(use_required_attribute=False).as_p())

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_widget_renders_management_inputs_controls_and_media(self):
        """It renders management inputs, row controls, and the enhancement media."""

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
        self.assertIn('data-sequence-minimum="2"', html)
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
            '<button type="button" data-sequence-remove data-sequence-field="values"'
            ' id="id_values___prefix___remove"'
            ' aria-label="Remove row __prefix__">Remove</button>',
            html,
        )
        self.assertIn("data-sequence-actions", html)
        self.assertIn("nestingdolls/sequence.js", str(form.media))

        # An invalid bound render keeps the sequence markup in the active layout.
        invalid = Form(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"}
        )
        self.assertIs(invalid.is_valid(), False)
        with self.assertTemplateUsed("nestingdolls/sequence/p.html"):
            invalid_html = invalid.as_p()

        self.assertIn('data-widget="sequence"', invalid_html)
        self.assertIn("<span", invalid_html)
        self.assertIn("Enter a whole number.", invalid_html)

    def assertRowErrorMarkup(self, form_kwargs, expected_input, expected_errors):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        form = Form(
            {
                "values-0": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            },
            **form_kwargs,
        )
        self.assertIs(form.is_valid(), False)
        html = form.as_div()
        self.assertInHTML(expected_input, html)
        self.assertInHTML(expected_errors, html)

    def test_row_error_markup_with_automatic_ids(self):
        """A row error describes its child input when Django creates ids."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
        )

    def test_row_error_markup_without_automatic_ids(self):
        """A row error keeps the existing description when Django omits ids."""
        self.assertRowErrorMarkup(
            {"auto_id": False},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
            '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
        )

    def test_compound_row_error_markup_describes_each_child_widget(self):
        """A compound row error describes each child input."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        compound = CompoundForm(
            {
                "values-0_0": "2026-08-05",
                "values-0_1": "not-a-time",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertIs(compound.is_valid(), False)
        compound_html = compound.as_div()
        self.assertInHTML(
            '<input type="text" name="values-0_0" value="2026-08-05" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_0">',
            compound_html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0_1" value="not-a-time" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_1">',
            compound_html,
        )

    def assertAddButtonSurvivesInitial(self, initial):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": initial}).as_p()
        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )

    def test_add_button_survives_initial_at_maximum(self):
        """The add button remains when initial rows reach the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2])

    def test_add_button_survives_initial_above_maximum(self):
        """The add button remains when initial rows exceed the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2, 3])

    def test_initial_reads_are_bounded_by_the_absolute_maximum(self):
        """It reads at most absolute_max items from a callable or nested initial."""

        class GuardedInitial(list[int]):
            def __iter__(self):
                for index, value in enumerate(super().__iter__()):
                    if index == 2:
                        raise AssertionError("read beyond absolute_max")
                    yield value

        class CallableInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                max_length=2,
                absolute_max=2,
                initial=lambda: GuardedInitial([1, 2, 3]),
            )

        html = CallableInitialForm().as_p()

        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)
        self.assertNotIn('name="values-2"', html)
        self.assertIn('name="values-TOTAL_FORMS" value="2"', html)
        self.assertIn('name="values-INITIAL_FORMS" value="2"', html)

        class NestedForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(), max_length=2, absolute_max=2
                ),
                max_length=1,
                absolute_max=1,
            )

        nested_html = NestedForm(initial={"values": [GuardedInitial([1, 2, 3])]}).as_p()

        self.assertIn('name="values-0-0"', nested_html)
        self.assertIn('name="values-0-1"', nested_html)
        self.assertNotIn('name="values-0-2"', nested_html)
        self.assertIn('name="values-0-TOTAL_FORMS" value="2"', nested_html)
        self.assertIn('name="values-0-INITIAL_FORMS" value="2"', nested_html)


class PublicApiTestCase(SimpleTestCase):
    def test_constructor_bounds_are_enforced(self):
        """It refuses limit and initial combinations the field cannot satisfy."""
        self.assertEqual(
            nestingdolls.ListField(forms.IntegerField(), initial=range(2)).initial,
            range(2),
        )
        with self.assertRaises(nestingdolls.SequenceInputValidationError):
            nestingdolls.ListField(forms.IntegerField()).clean("not a list")

        with self.assertRaisesMessage(
            ValueError, "max_length=0 requires required=False"
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=0)
        with self.assertRaisesMessage(
            ValueError, "max_length must be greater than or equal to min_length"
        ):
            nestingdolls.ListField(forms.IntegerField(), min_length=5, max_length=2)
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=1, initial=[1, 2])
        with self.assertRaisesMessage(
            ValueError, "'absolute_max' must be greater or equal to 'max_length'."
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=2, absolute_max=1)

    def test_constructor_rejects_negative_min_length(self):
        """The constructor rejects a negative minimum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=-1)

    def test_constructor_rejects_negative_max_length(self):
        """The constructor rejects a negative maximum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=-1)

    def test_constructor_rejects_max_length_below_min_length(self):
        """The constructor rejects a maximum length below the minimum."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=2, max_length=1)

    def test_scalar_initial_becomes_one_row(self):
        """A scalar initial wraps into one row instead of raising."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), initial=5)

        constructor_html = Form().as_p()
        keyword_html = Form(initial={"values": 5}).as_p()

        self.assertIn('value="5"', constructor_html)
        self.assertIn('name="values-TOTAL_FORMS" value="1"', constructor_html)
        self.assertEqual(constructor_html, keyword_html)

    def test_rejects_non_fields_and_legacy_widget_usage(self):
        """It rejects invalid child fields and legacy widget configuration."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)
        with self.assertRaises(TypeError):
            nestingdolls.SequenceWidget(child_field=forms.IntegerField())
        with self.assertRaises(TypeError):
            nestingdolls.MappingWidget(form_class=forms.Form)

    def test_widget_instance_is_copied_and_rebound_to_field_configuration(self):
        """Django copies a supplied widget before the field configures it."""
        widget = nestingdolls.SequenceWidget()

        field = nestingdolls.ListField(
            forms.IntegerField(),
            min_length=1,
            max_length=2,
            absolute_max=3,
            widget=widget,
        )

        self.assertIsNot(field.widget, widget)
        self.assertIs(field.widget.child_field, field.child_field)
        self.assertEqual(field.widget.limits.min_length, 1)
        self.assertEqual(field.widget.limits.max_length, 2)
        self.assertEqual(field.absolute_max, 3)
        self.assertEqual(field.widget.limits.absolute_max, field.absolute_max)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
