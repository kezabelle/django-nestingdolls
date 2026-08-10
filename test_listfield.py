import json
import tracemalloc
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

    def post_urlencoded_form(self, form_class, pairs, *, initial=None, prefix=None):
        body = pairs if isinstance(pairs, str) else urlencode(pairs, doseq=True)
        return form_class(QueryDict(body), initial=initial, prefix=prefix)


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

    class CardinalityForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), min_length=2, max_length=2
        )

    class NestedForm(forms.Form):
        values = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

    class CardinalityMatrixForm(forms.Form):
        optional_min = nestingdolls.ListField(
            forms.IntegerField(), required=False, min_length=2
        )
        required = nestingdolls.ListField(forms.IntegerField())
        maximum = nestingdolls.ListField(
            forms.IntegerField(), required=False, max_length=1
        )
        exact = nestingdolls.ListField(
            forms.IntegerField(), required=False, min_length=2, max_length=2
        )

    class DisabledForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), disabled=True, initial=[1]
        )

    class MaxDeletionForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class JSONSubmissionForm(forms.Form):
        values = nestingdolls.ListField(forms.JSONField(), required=False)

    class InitialManagementForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), initial=[1])

    class OptionalInitialManagementForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), required=False, initial=[10]
        )

    class DisabledChildForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(disabled=True), initial=[7])

    class DefaultAbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class AbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), max_length=1, absolute_max=2
        )

    class OptionalBooleanForm(forms.Form):
        values = nestingdolls.ListField(
            forms.BooleanField(required=False), required=False
        )

    class PointsForm(forms.Form):
        class PointForm(forms.Form):
            a = forms.IntegerField()
            b = forms.IntegerField()
            c = forms.IntegerField()

        values = nestingdolls.ListField(
            nestingdolls.DictField(PointForm), max_length=5, absolute_max=10
        )


class ListCardinalityMatrixProbeView(ProbeView):
    form_class = ListProbeFixtures.CardinalityMatrixForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "values": form.cleaned_data if valid else None,
            "errors": self.error_codes(errors),
        }


class NestedListProbeFixtures(SimpleTestCase):
    class PairForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.TupleField(forms.IntegerField(), min_length=2, max_length=2)
        )

    class DeepListForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))
        )

    class AlternatingForm(forms.Form):
        class SectionForm(forms.Form):
            class EntryForm(forms.Form):
                class PointForm(forms.Form):
                    a = forms.IntegerField()
                    label = forms.CharField(required=False)

                point = nestingdolls.MappingField(PointForm)
                title = forms.CharField()

            name = forms.CharField()
            entries = nestingdolls.ListField(nestingdolls.MappingField(EntryForm))

        values = nestingdolls.ListField(nestingdolls.MappingField(SectionForm))

    class BlankRowForm(forms.Form):
        class CheckboxRowForm(forms.Form):
            active = forms.BooleanField(required=False)

        values = nestingdolls.ListField(
            nestingdolls.MappingField(CheckboxRowForm), required=False
        )

    class RaisedSubmissionForm(forms.Form):
        outer = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False)), required=False
        )

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


class NestedPairProbeView(ProbeView):
    form_class = NestedListProbeFixtures.PairForm

    def response_data(self, form, valid, errors):
        value_errors = errors.get("values", [])
        return {
            "valid": valid,
            "values": form.cleaned_data.get("values") if valid else None,
            "errors": (
                {"values": [error.code for error in value_errors]}
                if value_errors
                else {}
            ),
            **(
                {
                    "child_codes": [
                        error.params.get("child_code") for error in value_errors
                    ]
                }
                if value_errors
                else {}
            ),
        }


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
    path(
        "disabled-list-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DisabledForm),
    ),
    path(
        "list-max-deletion-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.MaxDeletionForm),
    ),
    path("list-cardinality-matrix-probe/", ListCardinalityMatrixProbeView.as_view()),
    path(
        "list-cardinality-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.CardinalityForm),
    ),
    path(
        "nested-list-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.NestedForm),
    ),
    path(
        "list-json-submission-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.JSONSubmissionForm),
    ),
    path(
        "list-initial-management-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.InitialManagementForm),
    ),
    path(
        "optional-list-initial-management-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.OptionalInitialManagementForm),
    ),
    path(
        "disabled-list-child-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DisabledChildForm),
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
        "optional-boolean-list-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.OptionalBooleanForm),
    ),
    path(
        "list-of-points-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.PointsForm),
    ),
    path("nested-pair-probe/", NestedPairProbeView.as_view()),
    path(
        "nested-deep-list-probe/",
        ProbeView.as_view(form_class=NestedListProbeFixtures.DeepListForm),
    ),
    path(
        "nested-alternating-probe/",
        ProbeView.as_view(form_class=NestedListProbeFixtures.AlternatingForm),
    ),
    path(
        "nested-blank-row-probe/",
        ProbeView.as_view(form_class=NestedListProbeFixtures.BlankRowForm),
    ),
    path(
        "raised-nested-submission-probe/",
        ProbeView.as_view(
            form_class=NestedListProbeFixtures.RaisedSubmissionForm,
            field_name="outer",
        ),
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

    def test_client_posts_direct_and_managed_dash_list_rows(self):
        """Direct values and Django-managed dash rows are the accepted contracts."""
        cases = (
            ({"values": ["1", "2", "3"]}, [1, 2, 3]),
            (
                {
                    "values-0": "1",
                    "values-1": "2",
                    "values-2": "3",
                    f"values-{TOTAL_FORM_COUNT}": "3",
                    f"values-{INITIAL_FORM_COUNT}": "0",
                },
                [1, 2, 3],
            ),
        )
        for data, expected in cases:
            with self.subTest(data=data):
                response = self.client.post("/list-submission-probe/", data)
                self.assertEqual(response.status_code, 200)
                self.assertJSONEqual(
                    response.content, {"valid": True, "values": expected, "errors": {}}
                )

    def test_client_returns_cleaned_json_direct_and_managed_dash_rows(self):
        """JSON rows retain the same direct and managed wire contracts."""
        value = {"answer": 42, "nested": [1, 2]}
        encoded = json.dumps(value)
        for data in (
            {"values": [encoded]},
            {
                "values-0": encoded,
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        ):
            with self.subTest(data=data):
                response = self.client.post("/list-json-submission-probe/", data)
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
        """Direct rendering exposes the scalar row as one indexed input."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        bound = Form({"values": "1"})
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            bound.as_p(),
        )
        unbound = Form(initial={"values": 1})
        self.assertEqual(unbound["values"].value(), [1])

    def test_client_returns_management_errors_for_missing_list_controls(self):
        """Every dash-indexed request requires Django's two management controls."""
        for query in (
            "values-TOTAL_FORMS=1&values-0=1",
            "values-INITIAL_FORMS=0&values-0=1",
            "values-999999=1",
        ):
            with self.subTest(query=query):
                response = self.client.generic(
                    "POST",
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

    def test_invalid_management_data_redisplays_the_submitted_rows(self):
        """Form rendering keeps invalid management controls and submitted rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            (
                f"values-{TOTAL_FORM_COUNT}=2&values-0=1&values-1=bad",
                '<input type="hidden" name="values-INITIAL_FORMS" id="id_values-INITIAL_FORMS">',
            ),
            (
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=bad&values-0=1&values-1=bad",
                '<input type="hidden" name="values-INITIAL_FORMS" value="bad" id="id_values-INITIAL_FORMS">',
            ),
        )
        for data, management_input in cases:
            with self.subTest(data=data):
                form = self.post_urlencoded_form(Form, data, initial={"values": [1]})
                self.assertIs(form.is_valid(), False)
                self.assertInHTML(management_input, form.as_p())

    def test_client_uses_the_last_duplicate_list_management_value(self):
        """Client uses the final submitted list management value."""
        pairs = (
            (f"values-{TOTAL_FORM_COUNT}", "1"),
            (f"values-{TOTAL_FORM_COUNT}", "2"),
            (f"values-{INITIAL_FORM_COUNT}", "0"),
            ("values-0", "1"),
            ("values-1", "2"),
        )
        response = self.client.generic(
            "POST",
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

    def test_invalid_rows_redisplay_the_submitted_management_state(self):
        """An invalid submission redisplays its own counts, rows, and delete flags."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        class MaximumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        with self.subTest(case="added row over the maximum"):
            form = self.post_urlencoded_form(
                MaximumForm, submitted, initial={"values": [1]}
            )
            self.assertIs(form.is_valid(), False)
            html = form.as_p()
            self.assertInHTML(
                '<input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total id="id_values-TOTAL_FORMS">',
                html,
            )
            self.assertInHTML(
                '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
                html,
            )

        class MinimumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=3)

        with self.subTest(case="rows below the minimum"):
            form = self.post_urlencoded_form(
                MinimumForm, submitted, initial={"values": [1]}
            )
            self.assertIs(form.is_valid(), False)
            self.assertEqual(form.errors.as_data()["values"][0].code, "min_length")
            self.assertInHTML(
                '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
                form.as_p(),
            )

        class PlainForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        with self.subTest(case="invalid original row beside a deleted added row"):
            form = self.post_urlencoded_form(
                PlainForm,
                submitted
                + f"&values-0=bad&values-1=2&values-1-{DELETION_FIELD_NAME}=on",
                initial={"values": [1]},
            )

            self.assertIs(form.is_valid(), False)
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

        for delete_value in ("1", "on", "true"):
            with self.subTest(delete_value=delete_value):
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
        """Direct field checks cover disabled child and change-detection internals."""

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

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("disabled child value was compared")

        for field_class in (nestingdolls.ListField, nestingdolls.SetField):
            with self.subTest(field_class=field_class.__name__):
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

    def test_client_rejects_management_totals_past_each_absolute_maximum(self):
        """Client returns a too-many-forms error past each configured hard limit."""
        cases = (
            ("/list-default-absolute-maximum-probe/", DEFAULT_MAX_NUM + 2),
            ("/list-absolute-maximum-probe/", 3),
        )
        for url, total in cases:
            with self.subTest(url=url, total=total):
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
        """Direct rendering keeps each list item error beside its input."""

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
        self.assertEqual(
            [error.code for error in blanks.errors.as_data()["emails"]],
            ["item_invalid"] * 5,
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

    def test_item_error_messages_with_percent_signs_render_literally(self):
        """A child message keeps its percent sign, eager or lazy."""

        class PercentField(forms.Field):
            def clean(self, value):
                raise ValidationError("50% off is required", code="required")

        class LazyPercentField(forms.Field):
            def clean(self, value):
                raise ValidationError(
                    translation.gettext_lazy("%(pct)s%% off is required"),
                    code="required",
                    params={"pct": 50},
                )

        for child_field in (PercentField(), LazyPercentField()):
            with self.subTest(child_field=type(child_field).__name__):
                Form = type(
                    "Form",
                    (forms.Form,),
                    {"values": nestingdolls.ListField(child_field)},
                )
                form = Form(
                    QueryDict(
                        f"values-{TOTAL_FORM_COUNT}=1&"
                        f"values-{INITIAL_FORM_COUNT}=0&values-0=x"
                    )
                )
                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertEqual(error.messages, ["50% off is required"])
                self.assertEqual(error.child_message, "50% off is required")
                self.assertEqual(error.params["message"], "50% off is required")
                self.assertEqual(
                    dict(form["values"].submission.errors),
                    {0: ["50% off is required"]},
                )
                html = form.as_p()
                self.assertIn("50% off is required", html)
                self.assertNotIn("50%% off", html)

    def test_nested_mapping_rows_are_partitioned_before_extraction(self):
        """It gives each nested mapping only its own normalized row inputs."""

        class RowForm(forms.Form):
            value = forms.IntegerField()

        class CountingWidget(nestingdolls.MappingWidget):
            key_visits = 0

            class Keys(nestingdolls.MappingWidget.Keys):
                def normalized(self, data, name):
                    CountingWidget.key_visits += len(data)
                    return super().normalized(data, name)

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
        # The bound must stay sub-quadratic in the row count. A per-row
        # rescan of the whole input visits row_count * row_count keys.
        # The exact figure is an implementation detail. Do not pin it
        # here.
        self.assertLess(CountingWidget.key_visits, row_count * row_count)

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

    def test_absolute_max_must_stay_addressable_by_a_row_index(self):
        """``max_index_digits`` is an invariant, so a limit past it is refused."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.CharField(), absolute_max=10_000_000)

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

    def test_disabled_sequence_renders_the_initial_rows_it_cleans(self):
        """A disabled field ignores submitted render state, as it ignores data."""
        cases = (
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
                f"values-0-{DELETION_FIELD_NAME}": "on",
            },
            {
                f"values-{TOTAL_FORM_COUNT}": "bad",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        for data in cases:
            with self.subTest(data=data):

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
        self.assertIs(field.has_changed(frozenset({1, 2}), ["2", "1", "1"]), False)
        with self.assertRaises(ValidationError) as context:
            nestingdolls.FrozenSetField(forms.JSONField()).clean([{"answer": 42}])
        self.assertEqual(context.exception.code, "unhashable")
        parent = nestingdolls.ListField(
            nestingdolls.FrozenSetField(forms.IntegerField(), required=False),
            required=False,
        )
        self.assertIs(parent.has_changed([frozenset({1, 2})], [["2", "1", "1"]]), False)

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
                self.assertIs(field.has_changed(expected_initial, values), True)

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

    def test_member_order_does_not_build_one_index_per_member_per_row(self):
        """A matched row checks only its matching member.

        Building an order for every candidate creates quadratic writes.
        ``members_left`` prevents this work.
        """
        size = 100_000
        members = [f"m{index}" for index in range(size)]
        match = nestingdolls.SetField.Match(
            forms.CharField(), members, members_left=size
        )
        rows = members[:100]

        tracemalloc.start()
        try:
            for row in rows:
                self.assertIs(match.claim(row, match.candidate(row)), True)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        self.assertEqual(size - match.members_left, len(rows))
        # An eager order builds one tuple of `size` indexes for each row.
        self.assertLess(peak, size)

    def test_has_changed_uses_fallback_for_multiple_choice_lists(self):
        """It compares multiple-choice lists without hashing them."""
        field = nestingdolls.SetField(
            forms.MultipleChoiceField(
                choices=[("first", "First"), ("second", "Second")]
            ),
            required=False,
        )

        self.assertIs(
            field.has_changed({("first", "second")}, [["second", "first"]]), False
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

    def test_each_sequence_collection_round_trips_an_integer_child(self):
        """Each sequence collection reads one indexed hidden integer."""
        for field_class, initial in (
            (nestingdolls.ListField, [1]),
            (nestingdolls.TupleField, (1,)),
            (nestingdolls.SetField, {1}),
            (nestingdolls.FrozenSetField, frozenset({1})),
        ):
            with self.subTest(field_class=field_class.__name__):

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

    def test_hidden_sequence_markup_is_minimal_in_each_form_layout(self):
        """Each helper emits one hidden child and no hidden sequence controls."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        for helper, html in (
            ("as_p", Form().as_p()),
            ("as_div", Form().as_div()),
            ("as_ul", Form().as_ul()),
            ("as_table", Form().as_table()),
        ):
            with self.subTest(helper=helper):
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

    def test_submission_limit_follows_the_django_request_limit(self):
        """Use Django's key limit and the per-level cap for the shared cap.

        A populated row needs a key. One level can still request
        ``absolute_max`` empty rows with one ``TOTAL_FORMS`` key. The shared cap
        is the larger value.
        """
        limits = nestingdolls.ListField(forms.CharField()).limits
        self.assertEqual(limits.absolute_max, 2000)

        cases = (
            # (Django key limit, expected shared cap)
            (1000, 2000),  # The per-level cap is larger.
            (5000, 5000),  # More accepted keys allow more populated rows.
            (10, 2000),  # The field still permits its empty rows.
            (None, 2000),  # The key limit is off, so the per-level cap applies.
        )
        for keys, expected in cases:
            with (
                self.subTest(keys=keys),
                override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=keys),
            ):
                self.assertEqual(limits.submission_max, expected)

    def test_submission_max_reads_a_zero_django_key_limit_as_no_limit(self):
        """A zero key limit uses the default shared cap.

        Django rejects a zero key limit before form binding. Zero and ``None`` are
        not supported row budgets.
        """
        limits = nestingdolls.ListField(
            forms.CharField(), max_length=10, absolute_max=10
        ).limits

        for keys in (0, None):
            with (
                self.subTest(keys=keys),
                override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=keys),
            ):
                self.assertEqual(limits.submission_max, DEFAULT_MAX_NUM)
        with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=5):
            self.assertEqual(limits.submission_max, limits.absolute_max)

    def test_client_accepts_an_exact_nested_submission_total(self):
        """Client accepts a nested submission that uses the shared cap exactly."""
        response = self.client.post(
            "/exact-nested-submission-probe/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                f"outer-0-{TOTAL_FORM_COUNT}": "1999",
                f"outer-0-{INITIAL_FORM_COUNT}": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["valid"], True)
        self.assertEqual(payload["errors"], {})
        self.assertEqual([len(rows) for rows in payload["values"]], [1999])

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_direct_nested_values_keep_only_per_level_row_limits(self):
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
    def test_direct_nested_values_reject_an_oversized_child_list(self):
        """A direct nested value still gets the child list's user-visible hard-cap error."""

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

    @unittest.expectedFailure
    def test_client_pairs_unmanaged_sparse_data_and_file_rows_by_index(self):
        """Unmanaged sparse data and file indexes must identify the same row.

        DEFECT. Separate normalization creates separate maps. Text row 5 pairs with
        file row 3, then the submission succeeds.
        """
        response = self.client.post(
            "/sparse-asset-probe/",
            {
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

    @unittest.expectedFailure
    def test_client_deletes_a_nested_row_and_redisplays_it_as_deleted(self):
        """Deleting a nested row removes it and renders it deleted.

        DEFECT. A nested sequence has no bound field to read its delete control. The
        value remains and the row renders as live.
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

    @unittest.expectedFailure
    def test_client_attaches_a_nested_row_error_to_that_nested_row(self):
        """A nested row error appears at its failing input.

        DEFECT. The nested widget receives no row errors. An inner error appears on
        the outer row instead.
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

            class Keys(nestingdolls.SequenceWidget.Keys):
                def rows(self, data, name, form_count):
                    CountingWidget.key_visits += len(data)
                    return super().rows(data, name, form_count)

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
    def test_direct_clean_of_nested_values_pays_each_level_cap(self):
        """Direct nested cleaning uses each level's own cap.

        Direct ``clean()`` has no request keys. It does not open the shared
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


class SyntheticSubmissionCountdownContractTestCase(FormBindingUnitTestCase):
    """Define behavior for manually nested private countdown scopes.

    ``SequenceWidget.SubmissionCountdown`` is not public API. This test 
    manufactures an unsupported situation anyway, by opening the scope by hand 
    around ``is_valid()`` to demonstrate a synthetic issue.

    No request path opens a second ``SubmissionCountdown``. This test does so to
    record that a joined scope does not receive overflow state. This unsupported
    call can truncate and accept data.

    Do not change this behavior, do not try and fix this because it is beyond the
    scope of a Field and moves towards either an owning form, or an owning view.
    """

    @unittest.expectedFailure
    def test_a_hand_opened_shared_scope_silently_truncates_instead_of_rejecting(
        self,
    ):
        """Demonstrate the synthetic misuse. See the class docstring first."""

        class Form(forms.Form):
            a = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            b = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )

        pairs = [
            (f"a-{TOTAL_FORM_COUNT}", "1"),
            (f"a-{INITIAL_FORM_COUNT}", "0"),
            (f"a-0-{TOTAL_FORM_COUNT}", "20"),
            (f"a-0-{INITIAL_FORM_COUNT}", "0"),
            (f"b-{TOTAL_FORM_COUNT}", "1"),
            (f"b-{INITIAL_FORM_COUNT}", "0"),
            (f"b-0-{TOTAL_FORM_COUNT}", "1"),
            (f"b-0-{INITIAL_FORM_COUNT}", "0"),
            ("b-0-0", "hello"),
        ]
        form = self.post_urlencoded_form(Form, pairs)

        # Synthetic only: no shipped code path opens this scope by hand.
        with nestingdolls.SequenceWidget.SubmissionCountdown(10):
            valid = form.is_valid()

        # A real (fixed) implementation would reject the whole submission
        # once the hand-opened shared allowance of 10 ran out, instead of
        # reporting success with field "a" truncated and field "b" dropped.
        self.assertIs(valid, False)
        errors = form.errors.as_data()
        for field_name in ("a", "b"):
            with self.subTest(field=field_name):
                self.assertEqual(len(errors[field_name]), 1)
                error = errors[field_name][0]
                self.assertEqual(error.code, "too_many_forms")
                self.assertIn("across nested sequences", error.messages[0])


@override_settings(ROOT_URLCONF=__name__, DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
class DjangoRequestLimitFunctionalTestCase(SimpleTestCase):
    def test_sequence_root_request_cap_boundaries(self):
        """Django parses four management keys before nested row work is capped."""

        for inner_total, expected_valid, expected_errors in (
            (10, False, {"outer": ["too_many_forms"]}),
            (9, True, {}),
        ):
            with self.subTest(inner_total=inner_total):
                response = self.client.post(
                    "/sequence-root-submission-limit/",
                    {
                        f"outer-{TOTAL_FORM_COUNT}": "1",
                        f"outer-{INITIAL_FORM_COUNT}": "0",
                        f"outer-0-{TOTAL_FORM_COUNT}": str(inner_total),
                        f"outer-0-{INITIAL_FORM_COUNT}": "0",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertJSONEqual(
                    response.content,
                    {"valid": expected_valid, "errors": expected_errors},
                )

    def test_request_rejects_more_urlencoded_keys_than_django_allows(self):
        """Django rejects URL-encoded keys above its request limit."""
        limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        body = urlencode([(f"unused-{index}", "1") for index in range(limit + 1)])

        response = self.client.generic(
            "POST",
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

        response = self.client.generic(
            "POST",
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
                "values-first-INITIAL_FORMS": "0",
                "values-second-TOTAL_FORMS": "10",
                "values-second-INITIAL_FORMS": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"valid": True, "lengths": {"first": 10, "second": 10}},
        )

    def test_mapping_root_renders_each_sibling_list_within_its_own_allowance(self):
        """A mapping root renders two capped lists, because it opens no row scope.

        This is the render half of the rule that the submitted half above
        states. Rendering clips the rows that do not fit. It does not raise.
        """
        form = SubmissionLimitProbeFixtures.MappingRootForm(
            initial={"values": {"first": [True] * 10, "second": [True] * 10}}
        )

        html = form.as_p()

        for child in ("first", "second"):
            with self.subTest(child=child):
                self.assertEqual(
                    sum(
                        html.count(f'name="values-{child}-{index}"')
                        for index in range(10)
                    ),
                    10,
                )

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

    def test_sequence_mapping_sequence_submission_shares_the_outer_sequence_cap(self):
        """A mapping between sequence levels remains transparent to the outer form error."""

        for inner_total, expected_valid, expected_errors, expected_tag_counts in (
            (10, False, {"items": ["too_many_forms"]}, []),
            (9, True, {}, [9]),
        ):
            with self.subTest(inner_total=inner_total):
                response = self.client.post(
                    "/sequence-mapping-sequence-submission-limit/",
                    {
                        f"items-{TOTAL_FORM_COUNT}": "1",
                        f"items-{INITIAL_FORM_COUNT}": "0",
                        f"items-0-tags-{TOTAL_FORM_COUNT}": str(inner_total),
                        f"items-0-tags-{INITIAL_FORM_COUNT}": "0",
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


class NestedParserRegressionTestCase(SimpleTestCase):
    def test_unrecognized_mapping_initial_becomes_one_renderable_row(self):
        """A mapping that is not flattened sequence data remains one raw row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        value = {"unexpected": "saved"}
        form = Form(initial={"values": value})

        self.assertEqual(form["values"].initial, [value])
        self.assertIn("unexpected", str(form["values"]))

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
                self.assertIs(form.is_valid(), False)
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

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(self):
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget(forms.CharField())
        file_widget = nestingdolls.SequenceWidget(forms.FileField())

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

    def test_row_error_markup_describes_the_child_widgets(self):
        """A row error points every child subwidget at that row's error list."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        data = {
            "values-0": "bad",
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
        }
        cases = (
            (
                {},
                '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
                '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            ),
            (
                {"auto_id": False},
                '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
                '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
            ),
        )
        for kwargs, expected_input, expected_errors in cases:
            with self.subTest(kwargs=kwargs):
                form = Form(data, **kwargs)
                self.assertIs(form.is_valid(), False)
                html = form.as_div()
                self.assertInHTML(expected_input, html)
                self.assertInHTML(expected_errors, html)

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

    def test_add_button_survives_an_initial_at_or_over_the_maximum(self):
        """It keeps only the add template when initial rows fill or exceed the limit."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        for initial in ([1, 2], [1, 2, 3]):
            with self.subTest(initial=initial):
                html = Form(initial={"values": initial}).as_p()

                self.assertIn("data-sequence-add-button", html)
                self.assertInHTML(
                    '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
                    html,
                )

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

        for kwargs in (
            {"min_length": -1},
            {"max_length": -1},
            {"min_length": 2, "max_length": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                nestingdolls.ListField(forms.IntegerField(), **kwargs)

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
        self.assertEqual(field.widget.limits.min_length, 1)
        self.assertEqual(field.widget.limits.max_length, 2)
        self.assertEqual(field.absolute_max, 3)
        self.assertEqual(field.widget.limits.absolute_max, field.absolute_max)
        self.assertIs(widget.child_field, original_child)
        self.assertEqual(widget.limits.min_length, 4)
        self.assertEqual(widget.limits.max_length, 5)
        self.assertEqual(widget.limits.absolute_max, 6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
