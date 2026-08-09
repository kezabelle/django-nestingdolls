"""Hostile request tests for mapping and sequence fields.

Every test in this module sends a request through Django with
``self.client``. A request is the only channel a user has. So a request is
the only channel these tests use.

The contract is short. A user must not crash a view. A user must not get an
error message that names the wrong cause. A user must not make the server
build more rows than the row limits allow, and a user must not destroy the
values of a good submission with one extra key.

A test that proves a defect carries ``@unittest.expectedFailure`` and a
docstring that states the defect. Remove the marker when the defect is fixed.
"""

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
    # The client tests below render bound forms, so use the same instrumented
    # environment that the other test modules use.
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

    def post(self, request):
        form = self.form_class(request.POST, request.FILES, **(self.form_kwargs or {}))
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
        """A forged scalar under the field name crashes the redisplay of a
        SplitDateTimeField row.

        DEFECT. ``SequenceWidget.Keys.whole_value_rows`` returns the raw
        submitted string as a row, and ``SequenceWidget.get_context`` gives
        that string to ``MultiWidget.decompress``. The widget expects a
        datetime, so the render raises ``AttributeError`` and the user gets
        HTTP 500 from one POST key.
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
        """A JSON array in a set row gives a validation error, not a crash.

        ``SetField.compress`` raises when a cleaned row cannot go into a
        Python ``set``. A request reaches that path with an ordinary JSON
        array, which ``JSONField`` accepts but ``set()`` cannot hash.
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
        """A total of ``2.0`` destroys both submitted rows without a word.

        DEFECT. ``SequenceWidget.Keys.total_forms`` calls ``int()``, which
        refuses ``"2.0"``. Django's ``ManagementForm`` uses ``IntegerField``,
        which accepts it as 2. The two readers disagree, so extraction returns
        no rows while the management form reports two. The optional field then
        cleans to an empty list and the response reports success, so the two
        submitted values disappear with no error at all.
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

    def test_client_accepts_a_row_beside_a_junk_unused_management_control(self):
        """A junk ``MIN_NUM_FORMS`` value rejects a correct submission.

        DEFECT. ``SequenceWidget.Keys.management_names`` counts
        ``MIN_NUM_FORMS`` and ``MAX_NUM_FORMS`` as management input, and
        ``SequenceField._clean_bound_field`` refuses the field when the
        management form is invalid. Neither value is read for validation
        anywhere in the package, so one extra key rejects a good submission
        and disables the add and remove controls on the page.
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
                self.assertEqual(response.json()["value"], [5])

    def test_management_error_does_not_call_a_submitted_control_missing(self):
        """The management error names a control that the request did send.

        DEFECT. ``MissingManagementFormValidationError`` lists every control
        that failed ``ManagementForm`` validation under the words "Missing
        fields". A control with a bad value is present, not missing, so the
        message states the wrong cause.
        """
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-{MIN_NUM_FORM_COUNT}": "not a number",
                "values-0": "5",
            },
        )
        self.assertEqual(response.status_code, 200)
        message = " ".join(response.json()["messages"].get("values", []))
        self.assertNotIn(f"Missing fields: values-{MIN_NUM_FORM_COUNT}", message)

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
        """A direct row key cannot replace unambiguous inner row keys."""
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
        """A forged row-name key destroys typed rows and blames their values.

        DEFECT. Same inverted rule as the test above, with a typed child. The
        forged text replaces both submitted rows, the child field cannot read
        it, and the user reads "Enter a whole number." about two rows that
        were whole numbers. The reported cause is the opposite of the truth.
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
        """A direct mapping key cannot replace an unambiguous nested leaf."""
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
        """An empty forged key silently drops a nested leaf and reports success.

        DEFECT. ``value-child=`` becomes the whole value of the optional
        nested mapping. ``MappingField.to_python`` turns the empty string into
        an empty mapping, the field is optional, and cleaning succeeds. The
        submitted leaf is gone with no error at all.
        """
        response = self.post_raw(
            "/hostile-optional-triple-mapping/",
            (("value-child", ""), ("value-child-leaf", "1")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], {"child": {"leaf": 1}})

    def test_client_keeps_flat_list_rows_beside_a_forged_field_name_key(self):
        """A direct field-name key cannot replace unambiguous flat row keys."""
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

    def test_client_ignores_a_forged_file_upload_beside_flat_list_rows(self):
        """A forged file upload under the field name cannot replace flat row keys."""
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

    def test_client_keeps_flat_mapping_children_beside_a_forged_field_name_key(self):
        """A direct field-name key cannot replace unambiguous flat mapping children."""
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
        """A three-letter forged value renders three inner rows.

        DEFECT. ``SequenceField.initial_values`` refuses a string, because a
        string is not a collection of rows. ``SequenceWidget.get_context``
        applies ``islice`` to the same value with no such guard, and
        ``prepare_value`` hands the raw string back after the refusal. So the
        render walks the string one character at a time.
        """
        response = self.client.post("/hostile-nested-text-list/", {"values": "abc"})
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        for letter in ("a", "b", "c"):
            with self.subTest(letter=letter):
                self.assertNotIn(f'value="{letter}"', html)

    def test_client_cannot_expand_one_text_key_into_thousands_of_rendered_rows(self):
        """One 3 KB key builds about 2000 nested rows and a very large page.

        DEFECT. The same missing string guard turns one submitted key into one
        rendered row for each character, up to ``absolute_max``. The request
        is small, the response is not.
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
        """The aggregate refusal quotes a per-level limit that every level met.

        DEFECT. ``SequenceField._clean_bound_field`` raises
        ``TooManyFormsValidationError`` with ``num=self.limits.max_length``
        when the shared row budget runs out. No level exceeded ``max_length``
        here, so the message "Please submit at most 50 forms." names a limit
        the user respected instead of the aggregate budget that stopped the
        request.
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
        """The page that reports "too many forms" still renders those rows.

        DEFECT. Cleaning and rendering each open their own
        ``SubmissionCountdown``. Cleaning refuses the submission, and the
        render then spends a whole fresh budget on the rows it just refused.
        The user gets a large page that contradicts its own error.
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
        """A few nested totals cannot claim more rows than the default cap allows.

        Three outer rows each claiming 900 inner rows ask for 3 + 2700 = 2703
        rows, past the default 2000-row ``submission_max``, from 8 management
        keys. No per-level ``max_length``/``absolute_max`` override is set, so
        this is the cap every undecorated ``ListField`` ships with.
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
