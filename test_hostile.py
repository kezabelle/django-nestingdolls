"""Hostile request tests for mapping and sequence fields.

Each test sends a request with ``self.client``. A request is the user-facing
input channel.

A request must not crash a view, report a false cause, create too many rows,
or erase valid values.

All defects that these tests found are fixed. Each test states the
behavior it defends.
"""

import time
import unittest
from urllib.parse import urlencode

import django
from django import forms
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import JsonResponse
from django.test import SimpleTestCase, override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import path
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
    # The client tests render bound forms.
    # Use Django's instrumented template environment.
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


# One marker appears in the rendered HTML for each sequence row, and one more
# for the inert template row of each sequence level.
ROW_MARKER = "data-sequence-index="


class HostileProbeView(View):
    """Bind one static form to the request and report what a user can see."""

    form_class = None
    field_name = "values"
    show_html = False
    form_kwargs = None
    # Django itself calls has_changed() before _clean_fields() whenever a form
    # is empty_permitted, so change detection is a real entry point into row
    # extraction and not only an application's own call.
    change_detection_first = False

    def post(self, request):
        form = self.form_class(request.POST, request.FILES, **(self.form_kwargs or {}))
        if self.change_detection_first:
            form.has_changed()
        valid = form.is_valid()
        stored = form.errors.as_data()
        data = {
            "valid": valid,
            "value": form.cleaned_data.get(self.field_name) if valid else None,
            "errors": {
                name: [error.code for error in errors]
                for name, errors in stored.items()
            },
            "child_codes": {
                name: [
                    error.params.get("child_code") for error in errors if error.params
                ]
                for name, errors in stored.items()
            },
            "messages": {name: list(errors) for name, errors in form.errors.items()},
        }
        if self.show_html:
            # A failed submission comes back to the browser as HTML, so the
            # size and the row count of that page are part of the contract.
            html = form.as_p()
            data["rendered_rows"] = html.count(ROW_MARKER)
            data["rendered_bytes"] = len(html)
            data["html"] = html
        return JsonResponse(data)


class SequenceHostileFixtures(SimpleTestCase):
    """Hold the sequence forms that the hostile routes bind."""

    class SplitDateTimeListForm(forms.Form):
        values = nestingdolls.ListField(forms.SplitDateTimeField(), required=False)

    class IntegerListForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), required=False)

    class NarrowListForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), required=False, max_length=3, absolute_max=5
        )

    class NestedTextListForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )

    class TriplyNestedListForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            ),
            required=False,
        )

    class ManySiblingListFieldsForm(forms.Form):
        a = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        b = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        c = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        d = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        e = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        f = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        g = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )
        h = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )

    class NestedTypedListForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(
                forms.IntegerField(), required=False, min_length=2, max_length=4
            ),
            required=False,
        )

    class AggregateCapForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(
                forms.CharField(required=False), max_length=50, absolute_max=50
            ),
            required=False,
            max_length=50,
            absolute_max=50,
        )

    class DeepBracketForm(forms.Form):
        values = nestingdolls.ListField(forms.CharField(), required=False)

    class RowUploadForm(forms.Form):
        class RowForm(forms.Form):
            label = forms.CharField(required=False)
            upload = forms.FileField(required=False)

        values = nestingdolls.ListField(nestingdolls.DictField(RowForm), required=False)

    class JsonSetForm(forms.Form):
        values = nestingdolls.SetField(forms.JSONField(), required=False)


class MappingHostileFixtures(SimpleTestCase):
    """Hold the mapping forms that the hostile routes bind."""

    class TripleMappingForm(forms.Form):
        class Level1Form(forms.Form):
            class Level2Form(forms.Form):
                leaf = forms.IntegerField()

            child = nestingdolls.DictField(Level2Form)

        value = nestingdolls.DictField(Level1Form)

    class OptionalTripleMappingForm(forms.Form):
        class Level1Form(forms.Form):
            class Level2Form(forms.Form):
                leaf = forms.IntegerField(required=False)

            child = nestingdolls.DictField(Level2Form, required=False)

        value = nestingdolls.DictField(Level1Form, required=False)

    class MappingListForm(forms.Form):
        class InnerForm(forms.Form):
            rows = nestingdolls.ListField(forms.IntegerField(), required=False)

        value = nestingdolls.DictField(InnerForm, required=False)

    class ChoicesMappingForm(forms.Form):
        class ChoicesForm(forms.Form):
            choices = forms.MultipleChoiceField(
                choices=[("a", "a"), ("b", "b")], required=False
            )

        value = nestingdolls.DictField(ChoicesForm, required=False)

    class PrefixedMappingForm(forms.Form):
        class PointForm(forms.Form):
            a = forms.IntegerField()

        value = nestingdolls.DictField(PointForm)

    class PlainMappingForm(forms.Form):
        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        value = nestingdolls.DictField(PointForm, required=False)

    class ManySiblingSequencesForm(forms.Form):
        class InnerForm(forms.Form):
            a = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            b = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            c = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            d = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            e = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            f = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            g = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )
            h = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False), required=False),
                required=False,
            )

        value = nestingdolls.DictField(InnerForm, required=False)


urlpatterns = [
    path(
        "hostile-split-datetime-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.SplitDateTimeListForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-integer-list/",
        HostileProbeView.as_view(form_class=SequenceHostileFixtures.IntegerListForm),
    ),
    path(
        "hostile-narrow-list/",
        HostileProbeView.as_view(form_class=SequenceHostileFixtures.NarrowListForm),
    ),
    path(
        "hostile-nested-text-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.NestedTextListForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-changed-first-nested-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.NestedTextListForm,
            change_detection_first=True,
            show_html=True,
        ),
    ),
    path(
        "hostile-empty-permitted-nested-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.NestedTextListForm,
            form_kwargs={"empty_permitted": True, "use_required_attribute": False},
        ),
    ),
    path(
        "hostile-triply-nested-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.TriplyNestedListForm,
        ),
    ),
    path(
        "hostile-many-sibling-list-fields/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.ManySiblingListFieldsForm,
        ),
    ),
    path(
        "hostile-nested-typed-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.NestedTypedListForm
        ),
    ),
    path(
        "hostile-aggregate-cap-list/",
        HostileProbeView.as_view(
            form_class=SequenceHostileFixtures.AggregateCapForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-deep-bracket-list/",
        HostileProbeView.as_view(form_class=SequenceHostileFixtures.DeepBracketForm),
    ),
    path(
        "hostile-row-upload-list/",
        HostileProbeView.as_view(form_class=SequenceHostileFixtures.RowUploadForm),
    ),
    path(
        "hostile-json-set/",
        HostileProbeView.as_view(form_class=SequenceHostileFixtures.JsonSetForm),
    ),
    path(
        "hostile-triple-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.TripleMappingForm, field_name="value"
        ),
    ),
    path(
        "hostile-optional-triple-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.OptionalTripleMappingForm,
            field_name="value",
        ),
    ),
    path(
        "hostile-mapping-list/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.MappingListForm, field_name="value"
        ),
    ),
    path(
        "hostile-choices-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.ChoicesMappingForm, field_name="value"
        ),
    ),
    path(
        "hostile-prefixed-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.PrefixedMappingForm,
            field_name="value",
            form_kwargs={"prefix": "outer"},
        ),
    ),
    path(
        "hostile-plain-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.PlainMappingForm, field_name="value"
        ),
    ),
    path(
        "hostile-many-sibling-sequences-mapping/",
        HostileProbeView.as_view(
            form_class=MappingHostileFixtures.ManySiblingSequencesForm,
            field_name="value",
        ),
    ),
]


class HostileClientTestCase(SimpleTestCase):
    """Give the hostile tests one way to send a raw, ordered request body."""

    def post_raw(self, url, pairs):
        """Send an ordered URL-encoded body, which a dict payload cannot spell."""
        return self.client.generic(
            "POST",
            url,
            data=urlencode(pairs, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )


@override_settings(ROOT_URLCONF=__name__)
class HostileSequenceCrashTestCase(HostileClientTestCase):
    """Prove that no submitted key makes a sequence view raise."""

    def test_client_survives_a_forged_whole_value_for_compound_child_rows(self):
        """A scalar in a compound row must not cause an HTTP 500.

        A compound child widget receives a decomposed value or ``None``,
        never a raw string, so ``MultiWidget.decompress`` does not raise.
        """
        managed = self.client.post(
            "/hostile-split-datetime-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0_0": "2026-08-01",
                "values-0_1": "10:30:00",
            },
        )
        self.assertEqual(managed.status_code, 200)
        self.assertIs(managed.json()["valid"], True)

        for body in ({"values": "abc"}, {"values": ["a", "b"]}):
            with self.subTest(body=body):
                response = self.client.post("/hostile-split-datetime-list/", body)
                self.assertEqual(response.status_code, 200)

    def test_client_survives_deeply_nested_bracket_row_keys(self):
        """A key with thousands of bracket groups gives an ordinary response."""
        response = self.post_raw(
            "/hostile-deep-bracket-list/",
            (
                (f"values-{TOTAL_FORM_COUNT}", "1"),
                (f"values-{INITIAL_FORM_COUNT}", "0"),
                ("values[0]" + "[0]" * 5000, "deep"),
                ("values-0", "kept"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], ["kept"])

    def test_client_survives_unbalanced_and_empty_bracket_row_keys(self):
        """A malformed bracket key names no row and raises nothing."""
        for key in ("values[", "values[]", "values[]0", "values]0[", "values[-1]"):
            with self.subTest(key=key):
                response = self.client.post(
                    "/hostile-integer-list/",
                    {
                        f"values-{TOTAL_FORM_COUNT}": "1",
                        f"values-{INITIAL_FORM_COUNT}": "0",
                        key: "9",
                        "values-0": "1",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["value"], [1])

    def test_client_survives_a_row_index_longer_than_the_digit_limit(self):
        """A row index with more digits than the limit names no row."""
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-99999999": "9",
                "values-0": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [1])

    def test_client_reports_an_unhashable_json_row_as_a_validation_error(self):
        """A JSON array in a set row returns a validation error.

        ``JSONField`` accepts an array, but a Python ``set`` cannot hash it.
        """
        response = self.client.post(
            "/hostile-json-set/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "[1, 2]",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["unhashable"]})

    def test_client_reports_a_null_byte_in_a_row_as_a_validation_error(self):
        """A null byte gives Django's field error, not a broken response."""
        response = self.client.post(
            "/hostile-nested-text-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "1",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "text\x00with a null",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["item_invalid"]})
        self.assertEqual(
            body["child_codes"], {"values": ["null_characters_not_allowed"]}
        )

    def test_client_survives_invisible_characters_in_row_keys_and_values(self):
        """A zero-width space stays in a value and names no row."""
        response = self.client.post(
            "/hostile-nested-text-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "1",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "text\u200bwith marks",
                "values-0-\u200b1": "ignored",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [["text\u200bwith marks"]])

    def test_client_survives_non_ascii_digit_row_indexes_at_every_level(self):
        """A Unicode digit names no row at an outer or an inner level."""
        response = self.client.post(
            "/hostile-nested-text-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "1",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "kept",
                "values-\u0661-0": "outer arabic index",
                "values-0-\u00b2": "inner superscript index",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [["kept"]])

    def test_client_discards_row_indexes_that_cannot_name_a_form(self):
        """Oversized and overlong indexes do not reach the formset."""
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "5",
                "values-9999999": "ignored",
                "values-12345678": "ignored",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [5])

    def test_client_survives_a_body_that_is_not_form_data(self):
        """A JSON body carries no form controls and gives an empty submission."""
        response = self.client.post(
            "/hostile-integer-list/",
            data='{"values": [1, 2]}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [])

    def test_client_survives_a_malformed_multipart_body(self):
        """A truncated multipart body gives a client error, never a server error."""
        response = self.client.generic(
            "POST",
            "/hostile-row-upload-list/",
            data=b"--frontier\r\nContent-Disposition: form-data; name=",
            content_type="multipart/form-data; boundary=frontier",
        )
        self.assertLess(response.status_code, 500)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=2)
    def test_client_survives_more_uploads_than_the_request_allows(self):
        """Django refuses the extra uploads, and the view does not fail."""
        response = self.client.post(
            "/hostile-row-upload-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "3",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0-upload": SimpleUploadedFile("a.txt", b"a"),
                "values-1-upload": SimpleUploadedFile("b.txt", b"b"),
                "values-2-upload": SimpleUploadedFile("c.txt", b"c"),
            },
        )
        self.assertEqual(response.status_code, 400)


@override_settings(ROOT_URLCONF=__name__)
class HostileSequenceManagementTestCase(HostileClientTestCase):
    """Send management controls that a browser never sends."""

    def test_client_keeps_rows_when_a_total_ends_in_a_decimal_zero(self):
        """A decimal total must retain its submitted rows.

        Django's ``IntegerField`` accepts a trailing decimal zero, so
        ``TOTAL_FORMS=2.0`` counts as 2 and keeps both rows.
        """
        control = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
            },
        )
        self.assertEqual(control.json()["value"], [1, 2])

        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2.0",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [1, 2])

    def test_client_rejects_a_junk_management_control_like_django(self):
        """A junk management control rejects the submission, as Django does.

        This package uses Django's own management-form validation. A
        tampered ``MIN_NUM_FORMS`` or ``MAX_NUM_FORMS`` value fails the
        ManagementForm and rejects the complete submission.
        """
        for name in (MIN_NUM_FORM_COUNT, MAX_NUM_FORM_COUNT):
            with self.subTest(name=name):
                response = self.client.post(
                    "/hostile-integer-list/",
                    {
                        f"values-{TOTAL_FORM_COUNT}": "1",
                        f"values-{INITIAL_FORM_COUNT}": "0",
                        f"values-{name}": "not a number",
                        "values-0": "5",
                    },
                )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertIs(body["valid"], False)
                self.assertEqual(
                    body["errors"], {"values": ["missing_management_form"]}
                )
                message = " ".join(body["messages"]["values"])
                self.assertIn(
                    "ManagementForm data is missing or has been tampered with",
                    message,
                )

    def test_client_keeps_the_last_of_two_duplicate_row_values(self):
        """Two values under one row key give the last value, as Django does."""
        response = self.post_raw(
            "/hostile-integer-list/",
            (
                (f"values-{TOTAL_FORM_COUNT}", "1"),
                (f"values-{INITIAL_FORM_COUNT}", "0"),
                ("values-0", "1"),
                ("values-0", "2"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [2])

    def test_client_ignores_a_deletion_control_named_after_the_field(self):
        """A ``DELETE`` control on the field itself removes no row."""
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-DELETE": "1",
                "values-0": "1",
                "values-1": "2",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [1, 2])


@override_settings(ROOT_URLCONF=__name__)
class HostileNestedForgeryTestCase(HostileClientTestCase):
    """Send one extra key that is spelled like a nested composite child."""

    def test_client_keeps_inner_rows_beside_a_forged_row_name_key(self):
        """A forged row-name key cannot replace unambiguous inner row keys."""
        control = self.client.post(
            "/hostile-nested-text-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "1",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "kept",
            },
        )
        self.assertEqual(control.json()["value"], [["kept"]])

        response = self.client.post(
            "/hostile-nested-text-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "1",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0": "forged",
                "values-0-0": "kept",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [["kept"]])

    def test_client_does_not_blame_the_user_data_for_a_forged_row_name_key(self):
        """A forged row-name key must not replace valid typed rows.

        The unambiguous typed row keys win over the forged whole-row text,
        so the rows clean as integers with no false error.
        """
        control = self.client.post(
            "/hostile-nested-typed-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "2",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0-0": "1",
                "values-0-1": "2",
            },
        )
        self.assertEqual(control.json()["value"], [[1, 2]])

        response = self.client.post(
            "/hostile-nested-typed-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-{TOTAL_FORM_COUNT}": "2",
                f"values-0-{INITIAL_FORM_COUNT}": "0",
                "values-0": "forged",
                "values-0-0": "1",
                "values-0-1": "2",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [[1, 2]])

    def test_client_keeps_the_leaf_of_a_nested_mapping_beside_a_forged_key(self):
        """A forged mapping key cannot replace an unambiguous nested leaf."""
        control = self.post_raw(
            "/hostile-triple-mapping/",
            (("value", "forged"), ("value-child-leaf", "1")),
        )
        self.assertEqual(control.json()["value"], {"child": {"leaf": 1}})

        response = self.post_raw(
            "/hostile-triple-mapping/",
            (("value-child", "forged"), ("value-child-leaf", "1")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], {"child": {"leaf": 1}})

    def test_client_keeps_an_optional_nested_leaf_beside_an_empty_forged_key(self):
        """An empty forged key must not discard an optional nested leaf.

        An empty exact-name value does not become an empty mapping. The
        nested leaf key still supplies the value.
        """
        response = self.post_raw(
            "/hostile-optional-triple-mapping/",
            (("value-child", ""), ("value-child-leaf", "1")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], {"child": {"leaf": 1}})

    def test_client_keeps_prefixed_list_rows_beside_a_forged_field_name_key(self):
        """A forged field-name key cannot replace unambiguous prefixed row keys."""
        control = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
            },
        )
        self.assertEqual(control.json()["value"], [1, 2])

        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values": "forged",
                "values-0": "1",
                "values-1": "2",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [1, 2])

    def test_client_ignores_a_forged_file_upload_beside_prefixed_list_rows(self):
        """A forged file upload under the field name cannot replace prefixed row keys."""
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
                "values": SimpleUploadedFile("forged.txt", b"forged"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [1, 2])

    def test_client_keeps_prefixed_mapping_children_beside_a_forged_field_name_key(
        self,
    ):
        """A forged field-name key cannot replace unambiguous prefixed mapping children."""
        control = self.post_raw(
            "/hostile-plain-mapping/",
            (("value-a", "1"), ("value-label", "kept")),
        )
        self.assertEqual(control.json()["value"], {"a": 1, "label": "kept"})

        response = self.post_raw(
            "/hostile-plain-mapping/",
            (("value", "forged"), ("value-a", "1"), ("value-label", "kept")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], {"a": 1, "label": "kept"})

    def test_client_validates_a_lone_forged_scalar_instead_of_an_empty_list(self):
        """An exact-name scalar with no rows is validated, not silently dropped."""
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "0",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertTrue(body["errors"]["values"])

    def test_client_validates_a_lone_forged_scalar_instead_of_an_empty_mapping(self):
        """An exact-name scalar with no children is validated, not silently dropped."""
        response = self.client.post("/hostile-plain-mapping/", {"value": "save"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertTrue(body["errors"]["value"])


@override_settings(ROOT_URLCONF=__name__)
class HostileRenderCostTestCase(HostileClientTestCase):
    """Measure the page that a hostile submission makes the server build."""

    def test_client_does_not_split_a_forged_text_row_into_one_row_per_letter(self):
        """A forged text row must not render one row per character.

        ``initial_values`` rejects text, so rendering shows the raw value
        as one row. It does not iterate the characters.
        """
        response = self.client.post("/hostile-nested-text-list/", {"values": "abc"})
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        for letter in ("a", "b", "c"):
            with self.subTest(letter=letter):
                self.assertNotIn(f'value="{letter}"', html)

    def test_client_cannot_expand_one_text_key_into_thousands_of_rendered_rows(self):
        """A single text key must not create thousands of rows.

        A text value renders as one row, so a small request cannot buy a
        large response.
        """
        response = self.client.post(
            "/hostile-nested-text-list/", {"values": "a" * 3000}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertLess(
            payload["rendered_rows"],
            50,
            f"one key rendered {payload['rendered_rows']} rows "
            f"and {payload['rendered_bytes']} bytes",
        )

    def test_aggregate_row_rejection_does_not_quote_a_respected_per_level_limit(self):
        """A shared-budget error must name the shared budget.

        When the shared budget runs out, cleaning reports ``too_many_forms``.
        It does not blame a per-level ``max_length`` that no level exceeded.
        """
        payload = {
            f"values-{TOTAL_FORM_COUNT}": "50",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        for index in range(50):
            payload[f"values-{index}-{TOTAL_FORM_COUNT}"] = "50"
            payload[f"values-{index}-{INITIAL_FORM_COUNT}"] = "0"
            payload[f"values-{index}-0"] = "x"

        response = self.client.post("/hostile-aggregate-cap-list/", payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})
        self.assertNotIn("at most 50 forms", " ".join(body["messages"]["values"]))

    def test_a_rejected_oversized_submission_does_not_redisplay_its_rows(self):
        """A rejected submission must not render rejected rows.

        Cleaning and rendering share the overflow decision, so a refused
        submission renders only the rows that fit the budget.
        """
        payload = {
            f"values-{TOTAL_FORM_COUNT}": "50",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        for index in range(50):
            payload[f"values-{index}-{TOTAL_FORM_COUNT}"] = "50"
            payload[f"values-{index}-{INITIAL_FORM_COUNT}"] = "0"
            payload[f"values-{index}-0"] = "x"

        response = self.client.post("/hostile-aggregate-cap-list/", payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})
        self.assertLess(
            body["rendered_rows"],
            60,
            f"a refused submission rendered {body['rendered_rows']} rows "
            f"and {body['rendered_bytes']} bytes",
        )

    def test_client_cannot_multiply_default_row_caps_with_a_handful_of_keys(self):
        """Nested totals cannot exceed the default shared cap.

        Three outer rows with 900 inner rows claim 2703 rows. The default
        ``submission_max`` is 2000 rows.
        """
        payload = {
            f"values-{TOTAL_FORM_COUNT}": "3",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        for index in range(3):
            payload[f"values-{index}-{TOTAL_FORM_COUNT}"] = "900"
            payload[f"values-{index}-{INITIAL_FORM_COUNT}"] = "0"
        self.assertEqual(len(payload), 8)

        response = self.client.post("/hostile-nested-text-list/", payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})


@override_settings(ROOT_URLCONF=__name__)
class HostileCleanCostTestCase(HostileClientTestCase):
    """Measure the cost to reject hostile nested submissions.

    ``submission_countdown`` stops nested totals from multiplying rows. Other
    tests check the rejection result. These tests check the server work required
    to reject it.
    """

    @staticmethod
    def _amplified_sequence_payload(
        prefix: str, *, outer_total: int, inner_total: int
    ) -> dict[str, str]:
        """Build a nested sequence claim under ``prefix``.

        The same claim also reaches a sequence inside a mapping.
        """
        payload = {
            f"{prefix}-{TOTAL_FORM_COUNT}": str(outer_total),
            f"{prefix}-{INITIAL_FORM_COUNT}": "0",
        }
        for index in range(outer_total):
            payload[f"{prefix}-{index}-{TOTAL_FORM_COUNT}"] = str(inner_total)
            payload[f"{prefix}-{index}-{INITIAL_FORM_COUNT}"] = "0"
        return payload

    def test_client_pays_similar_cost_for_a_concentrated_or_spread_out_claim(
        self,
    ):
        """A spread claim costs about the same as a concentrated claim.

        Each ``read_input`` call reserves rows from one shared budget. Both request
        shapes must reject with similar work.
        """
        # A single row asking for more than the shared budget allows is
        # rejected up front, without building a single child row.
        cheap_payload = {
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
            f"values-0-{TOTAL_FORM_COUNT}": "2000",
            f"values-0-{INITIAL_FORM_COUNT}": "0",
        }
        cheap_start = time.perf_counter()
        cheap_response = self.client.post("/hostile-nested-text-list/", cheap_payload)
        cheap_elapsed = time.perf_counter() - cheap_start
        self.assertEqual(cheap_response.status_code, 200)
        self.assertEqual(
            cheap_response.json()["errors"], {"values": ["too_many_forms"]}
        )

        # The same 2000-row claim, spread across 499 sibling rows instead of
        # one, stays under Django's default DATA_UPLOAD_MAX_NUMBER_FIELDS
        # (1000 POST keys) and under every per-level absolute_max.
        expensive_payload = {
            f"values-{TOTAL_FORM_COUNT}": "499",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        for index in range(499):
            expensive_payload[f"values-{index}-{TOTAL_FORM_COUNT}"] = "2000"
            expensive_payload[f"values-{index}-{INITIAL_FORM_COUNT}"] = "0"
        self.assertLessEqual(len(expensive_payload), 1000)

        expensive_start = time.perf_counter()
        expensive_response = self.client.post(
            "/hostile-nested-text-list/", expensive_payload
        )
        expensive_elapsed = time.perf_counter() - expensive_start
        self.assertEqual(expensive_response.status_code, 200)
        self.assertEqual(
            expensive_response.json()["errors"], {"values": ["too_many_forms"]}
        )

        # Both requests reach the same correct verdict from a similar number
        # of POST keys. A shared budget that gates child work keeps the
        # expensive shape within a small constant factor of the cheap
        # shape's time, instead of roughly two orders of magnitude past it.
        budget_seconds = max(0.5, cheap_elapsed * 20)
        self.assertLess(
            expensive_elapsed,
            budget_seconds,
            f"a {len(expensive_payload)}-key submission spread across rows "
            f"took {expensive_elapsed:.3f}s to correctly reject, versus "
            f"{cheap_elapsed:.3f}s for a single row claiming the same "
            "total -- the shared row budget did not bound the cost of "
            "reaching that rejection",
        )

    def _fastest_of(self, url: str, payload: dict[str, str], repeats: int = 5) -> float:
        """Return the quickest of several posts to ``url``, damping scheduling noise.

        Each post must still be rejected, so a broken payload cannot pass by
        cutting the work short.
        """
        best = float("inf")
        for _ in range(repeats):
            start = time.perf_counter()
            response = self.client.post(url, payload)
            best = min(best, time.perf_counter() - start)
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.json()["valid"], False)
        return best

    def test_client_cost_scales_with_sibling_mapping_children_not_worse(self):
        """Sibling sequences in a mapping have independent shared budgets.

        This matches Django formsets. The form author fixes the sibling count. This
        test rejects superlinear sibling cost.
        """
        amplify = self._amplified_sequence_payload
        one_child_payload = amplify("value-a", outer_total=1, inner_total=2000)
        all_children_payload: dict[str, str] = {}
        for child_name in "abcdefgh":
            all_children_payload.update(
                amplify(f"value-{child_name}", outer_total=1, inner_total=2000)
            )
        self.assertLessEqual(len(all_children_payload), 1000)

        url = "/hostile-many-sibling-sequences-mapping/"
        one_elapsed = self._fastest_of(url, one_child_payload)
        all_elapsed = self._fastest_of(url, all_children_payload)

        # Eight independent, individually-bounded siblings should cost on
        # the order of eight times one of them, not orders of magnitude
        # more, which is what a superlinear regression would look like.
        budget_seconds = max(0.3, one_elapsed * 8 * 5)
        self.assertLess(
            all_elapsed,
            budget_seconds,
            f"amplifying all eight sibling sequences took {all_elapsed:.3f}s, "
            f"versus {one_elapsed:.3f}s for one of them alone -- that is "
            "worse than the linear-in-sibling-count cost Django's own "
            "formsets accept",
        )

    def test_client_cost_scales_with_sibling_list_fields_not_worse(self):
        """Sibling ``ListField`` instances have independent shared budgets.

        This is the mapping test without ``DictField``. The form author fixes the
        sibling count. This test rejects superlinear sibling cost.
        """
        amplify = self._amplified_sequence_payload
        one_field_payload = amplify("a", outer_total=1, inner_total=2000)
        all_fields_payload: dict[str, str] = {}
        for field_name in "abcdefgh":
            all_fields_payload.update(
                amplify(field_name, outer_total=1, inner_total=2000)
            )
        self.assertLessEqual(len(all_fields_payload), 1000)

        url = "/hostile-many-sibling-list-fields/"
        one_elapsed = self._fastest_of(url, one_field_payload)
        all_elapsed = self._fastest_of(url, all_fields_payload)

        budget_seconds = max(0.3, one_elapsed * 8 * 5)
        self.assertLess(
            all_elapsed,
            budget_seconds,
            f"amplifying all eight sibling fields took {all_elapsed:.3f}s, "
            f"versus {one_elapsed:.3f}s for one of them alone -- that is "
            "worse than the linear-in-sibling-count cost Django's own "
            "formsets accept",
        )

    def test_client_stays_bounded_three_sequence_levels_deep(self):
        """The shared budget limits work at a third nesting level.

        Two outer rows, two middle rows, and 2000 inner rows claim up to 8000 rows.
        The same reservation rule must work at every depth.
        """
        payload = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        for outer in range(2):
            payload[f"values-{outer}-{TOTAL_FORM_COUNT}"] = "2"
            payload[f"values-{outer}-{INITIAL_FORM_COUNT}"] = "0"
            for middle in range(2):
                payload[f"values-{outer}-{middle}-{TOTAL_FORM_COUNT}"] = "2000"
                payload[f"values-{outer}-{middle}-{INITIAL_FORM_COUNT}"] = "0"
        self.assertEqual(len(payload), 14)

        start = time.perf_counter()
        response = self.client.post("/hostile-triply-nested-list/", payload)
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})
        self.assertLess(
            elapsed,
            0.5,
            f"a 14-key, three-level submission asking for 8000 rows took "
            f"{elapsed:.3f}s to correctly reject",
        )

    def _count_rows_built(self):
        """Count row forms built while the returned counter is in scope.

        Wall-clock budgets catch a runaway cost but not a small regression.
        This counts the exact work an attacker's ``TOTAL_FORMS`` keys buy:
        one call per row form Django constructs, at every nesting level.
        """
        built = []
        formset_class = nestingdolls.SequenceWidget.RowFormSet
        original = formset_class._construct_form

        def counting(inner_self, index, **kwargs):
            built.append(index)
            return original(inner_self, index, **kwargs)

        formset_class._construct_form = counting
        self.addCleanup(setattr, formset_class, "_construct_form", original)
        return built

    def test_client_cannot_bypass_the_shared_budget_with_change_detection(self):
        """Change detection reserves rows from the same budget cleaning uses.

        ``Form.has_changed()`` extracts every row before any field is cleaned,
        and Django itself calls it from ``full_clean()``. A submission that
        arrives through change detection first must reach the same rejection,
        for the same work, as one that reaches cleaning first.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=20, inner_total=2000
        )
        self.assertEqual(len(payload), 42)

        built = self._count_rows_built()
        response = self.client.post("/hostile-changed-first-nested-list/", payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})
        # Extraction and the error render each hold one budget, so the whole
        # request stays a small constant multiple of submission_max instead
        # of the 40000 rows these 42 keys asked for.
        self.assertLessEqual(
            len(built),
            4000,
            f"42 keys claiming 40000 rows built {len(built)} row forms once "
            "change detection ran before cleaning -- every nesting level got "
            "a fresh budget instead of sharing one",
        )

    def test_client_cannot_bypass_the_shared_budget_with_empty_permitted(self):
        """An ``empty_permitted`` form shares the budget too.

        ``BaseForm.full_clean`` calls ``has_changed()`` itself for such a form,
        so this path needs no unusual application code at all.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=20, inner_total=2000
        )

        built = self._count_rows_built()
        response = self.client.post("/hostile-empty-permitted-nested-list/", payload)

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(built),
            4000,
            f"an empty_permitted form built {len(built)} row forms from 42 "
            "keys claiming 40000 rows",
        )

    def test_client_sees_a_reported_rejection_not_a_silent_truncation(self):
        """A clipped submission is rejected, not quietly cut down to size.

        Extraction records that the budget ran out. Cleaning reads the already
        clipped formset, so it cannot rediscover the overflow itself and must
        honour what extraction recorded. Otherwise the user's oversized
        submission would appear to save with rows missing.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=20, inner_total=2000
        )
        payload["values-0-0"] = "real content"

        response = self.client.post("/hostile-empty-permitted-nested-list/", payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertEqual(body["errors"], {"values": ["too_many_forms"]})

    def test_client_keeps_exact_budget_use_valid_after_change_detection(self):
        """Spending the budget exactly still succeeds on the extraction path.

        The shared budget must bound hostile multiplication without rejecting a
        submission that fits.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=1, inner_total=1999
        )

        response = self.client.post("/hostile-changed-first-nested-list/", payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], True, body["errors"])

    def test_client_keeps_a_legitimate_submission_whole_after_change_detection(self):
        """Change detection must not consume the rows cleaning needs.

        A budget spent twice on the same rows would halve it and could reject or
        truncate an ordinary submission.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=2, inner_total=3
        )
        for outer in range(2):
            for inner in range(3):
                payload[f"values-{outer}-{inner}"] = f"r{outer}c{inner}"

        built = self._count_rows_built()
        response = self.client.post("/hostile-changed-first-nested-list/", payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], True, body["errors"])
        self.assertEqual(
            body["value"],
            [["r0c0", "r0c1", "r0c2"], ["r1c0", "r1c1", "r1c2"]],
        )
        # Two outer rows and three inner rows each: the request builds the
        # rows it was sent, and change detection does not double the work.
        self.assertLessEqual(len(built), 16, len(built))


@override_settings(ROOT_URLCONF=__name__)
class HostileMappingSpellingTestCase(HostileClientTestCase):
    """Send the same mapping child under more than one accepted spelling."""

    def test_client_ignores_unprefixed_controls_on_a_prefixed_form(self):
        """A control without the form prefix reaches no field."""
        response = self.client.post("/hostile-prefixed-mapping/", {"value-a": "9"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"], {"value": ["required"]})

    def test_client_prefers_the_prefixed_control_over_a_forged_bare_control(self):
        """A prefixed control wins when both spellings arrive."""
        response = self.post_raw(
            "/hostile-prefixed-mapping/",
            (("value-a", "9"), ("outer-value-a", "5")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], {"a": 5})

    def test_client_drops_an_undeclared_child_inside_a_sequence_row(self):
        """A child name that no row form declares stays out of the value."""
        response = self.client.post(
            "/hostile-row-upload-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0-label": "kept",
                "values-0-untrusted": "dropped",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], [{"label": "kept", "upload": None}])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
