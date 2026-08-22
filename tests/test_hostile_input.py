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
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment

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
from .support.forms.hostile import (
    OptionalIntegerSequenceMappingValueForm,
)
from .support.forms.sequence import (
    NestedSequenceDeletionForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    # The client tests render bound forms.
    # Use Django's instrumented template environment.
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


# One marker appears in the rendered HTML for each sequence row, and one more
# for the inert template row of each sequence level.


class HostileRequestClientTestCase(CompositeFieldTestCase):
    """Give the hostile tests one way to send a raw, ordered request body."""

    def post_raw(self, url: object, pairs: object) -> object:
        """Send an ordered URL-encoded body, which a dict payload cannot spell."""
        return self.client.post(
            url,
            data=urlencode(pairs, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileRequestBodyTestCase(HostileRequestClientTestCase):
    """A hostile request body does not cause a server error.

    Each test sends a body that no browser form sends. The view returns a client
    error or an empty submission.
    """

    def test_client_survives_a_body_that_is_not_form_data(self) -> None:
        """A JSON body carries no form controls and gives an empty submission."""
        response = self.client.post(
            "/hostile-integer-list/",
            data='{"values": [1, 2]}',
            content_type="application/json",
        )
        self.assertJSONResponseContains(response, {"value": []})

    def test_client_survives_a_malformed_multipart_body(self) -> None:
        """A truncated multipart body gives a client error, never a server error."""
        response = self.client.post(
            "/hostile-row-upload-list/",
            data=b"--frontier\r\nContent-Disposition: form-data; name=",
            content_type="multipart/form-data; boundary=frontier",
        )
        self.assertLess(response.status_code, 500)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=2)
    def test_client_survives_more_uploads_than_the_request_allows(self) -> None:
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


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileRowKeyTestCase(HostileRequestClientTestCase):
    """A malformed row key binds no row.

    Each test sends a row key that managed spelling does not permit. The key
    binds no row, and valid rows stay in the value.
    """

    def test_client_ignores_a_deeply_nested_bracket_row_key(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": ["kept"]})

    def assertMalformedBracketKeyDoesNotBind(self, key: object) -> None:  # noqa: D102
        response = self.client.post(
            "/hostile-integer-list/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                key: "9",
                "values-0": "1",
            },
        )
        self.assertJSONResponseContains(response, {"value": [1]})

    def test_client_ignores_open_bracket_row_key(self) -> None:
        """An open bracket row key does not bind a row."""
        self.assertMalformedBracketKeyDoesNotBind("values[")

    def test_client_ignores_empty_bracket_row_key(self) -> None:
        """An empty bracket row key does not bind a row."""
        self.assertMalformedBracketKeyDoesNotBind("values[]")

    def test_client_ignores_bracket_then_text_row_key(self) -> None:
        """A bracket then text row key does not bind a row."""
        self.assertMalformedBracketKeyDoesNotBind("values[]0")

    def test_client_ignores_unbalanced_bracket_row_key(self) -> None:
        """An unbalanced bracket row key does not bind a row."""
        self.assertMalformedBracketKeyDoesNotBind("values]0[")

    def test_client_ignores_negative_bracket_row_key(self) -> None:
        """A negative bracket row key does not bind a row."""
        self.assertMalformedBracketKeyDoesNotBind("values[-1]")

    def test_client_ignores_a_row_index_longer_than_the_digit_limit(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [1]})

    def test_client_ignores_invisible_characters_in_row_keys_and_keeps_them_in_values(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": [["text\u200bwith marks"]]})

    def test_client_ignores_non_ascii_digit_row_indexes_at_every_level(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [["kept"]]})

    def test_client_ignores_row_indexes_that_cannot_name_a_form(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [5]})


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileRowValueTestCase(HostileRequestClientTestCase):
    """A hostile row value gets a validation error, not a crash.

    Each test sends a value that a field cannot clean. The view returns an
    ordinary response, and the error names the cause.
    """

    def test_client_accepts_a_managed_compound_child_row(self) -> None:
        """A managed compound child row returns a valid response."""
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

    def assertCompoundChildWholeValueDoesNotRaise(self, body: object) -> None:  # noqa: D102
        response = self.client.post("/hostile-split-datetime-list/", body)
        self.assertEqual(response.status_code, 200)

    def test_client_survives_a_scalar_whole_value_for_compound_child_rows(
        self,
    ) -> None:
        """A scalar whole value for a compound row does not return HTTP 500."""
        self.assertCompoundChildWholeValueDoesNotRaise({"values": "abc"})

    def test_client_survives_a_list_whole_value_for_compound_child_rows(self) -> None:
        """A list whole value for a compound row does not return HTTP 500."""
        self.assertCompoundChildWholeValueDoesNotRaise({"values": ["a", "b"]})

    def test_client_reports_an_unhashable_json_row_as_a_validation_error(
        self,
    ) -> None:
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

    def test_client_reports_a_null_byte_in_a_row_as_a_validation_error(self) -> None:
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


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileSequenceManagementTestCase(HostileRequestClientTestCase):
    """Send management controls that a browser never sends."""

    def test_client_keeps_rows_when_a_total_ends_in_a_decimal_zero(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [1, 2]})

    def test_client_keeps_a_negative_total_as_zero_rows_without_an_error(
        self,
    ) -> None:
        """A negative total buys no rows, and asking for none is not an overdraw.

        Django's bound ``total_form_count`` is ``min(TOTAL_FORMS,
        absolute_max)`` over a plain ``IntegerField`` with no lower clamp, so a
        negative total reaches the shared budget and builds no row, exactly as
        a total of zero does. The countdown must treat it the same way: refuse
        the claim, and do not record an overdraw. Reporting
        ``too_many_forms`` for a request that asked for fewer rows than the
        budget allows would reject a submission the budget never limited.
        """
        for total in ("0", "-5", "-1000000"):
            with self.subTest(total=total):
                response = self.client.post(
                    "/hostile-integer-list/",
                    {
                        f"values-{TOTAL_FORM_COUNT}": total,
                        f"values-{INITIAL_FORM_COUNT}": "0",
                    },
                )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertIs(body["valid"], True)
                self.assertEqual(body["value"], [])

    def assertJunkManagementControlIsRejected(self, name: object) -> None:  # noqa: D102
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
        self.assertEqual(body["errors"], {"values": ["missing_management_form"]})
        message = " ".join(body["messages"]["values"])
        self.assertIn(
            "ManagementForm data is missing or has been tampered with", message
        )

    def test_client_rejects_junk_minimum_forms_control(self) -> None:
        """A junk minimum forms control rejects the submission."""
        self.assertJunkManagementControlIsRejected(MIN_NUM_FORM_COUNT)

    def test_client_rejects_junk_maximum_forms_control(self) -> None:
        """A junk maximum forms control rejects the submission."""
        self.assertJunkManagementControlIsRejected(MAX_NUM_FORM_COUNT)

    def test_client_keeps_the_last_of_two_duplicate_row_values(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [2]})

    def test_client_ignores_a_deletion_control_named_after_the_field(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [1, 2]})


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileNestedForgeryTestCase(HostileRequestClientTestCase):
    """Send one extra key that is spelled like a nested composite child."""

    def test_client_keeps_inner_rows_beside_a_forged_row_name_key(self) -> None:
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
        self.assertJSONResponseContains(response, {"value": [["kept"]]})

    def test_client_does_not_blame_the_user_data_for_a_forged_row_name_key(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": [[1, 2]]})

    def test_client_keeps_the_leaf_of_a_nested_mapping_beside_a_forged_key(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": {"child": {"leaf": 1}}})

    def test_client_keeps_an_optional_nested_leaf_beside_an_empty_forged_key(
        self,
    ) -> None:
        """An empty forged key must not discard an optional nested leaf.

        An empty exact-name value does not become an empty mapping. The
        nested leaf key still supplies the value.
        """
        response = self.post_raw(
            "/hostile-optional-triple-mapping/",
            (("value-child", ""), ("value-child-leaf", "1")),
        )
        self.assertJSONResponseContains(response, {"value": {"child": {"leaf": 1}}})

    def test_client_keeps_prefixed_list_rows_beside_a_forged_field_name_key(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": [1, 2]})

    def test_client_ignores_a_forged_file_upload_beside_prefixed_list_rows(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": [1, 2]})

    def test_client_keeps_prefixed_mapping_children_beside_a_forged_field_name_key(
        self,
    ) -> None:
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
        self.assertJSONResponseContains(response, {"value": {"a": 1, "label": "kept"}})

    def test_client_validates_a_lone_forged_scalar_instead_of_an_empty_list(
        self,
    ) -> None:
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
        self.assertNotEqual(body["errors"]["values"], {})

    def test_client_validates_a_lone_forged_scalar_instead_of_an_empty_mapping(
        self,
    ) -> None:
        """An exact-name scalar with no children is validated, not silently dropped."""
        response = self.client.post("/hostile-plain-mapping/", {"value": "save"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body["valid"], False)
        self.assertNotEqual(body["errors"]["value"], {})


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileRenderCostTestCase(HostileRequestClientTestCase):
    """Measure the page that a hostile submission makes the server build."""

    def test_forged_text_row_does_not_render_scalar_characters(self) -> None:
        """A forged text row does not render any scalar character as a row."""
        response = self.client.post("/hostile-nested-text-list/", {"values": "abc"})
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertNotIn('value="a"', html)
        self.assertNotIn('value="b"', html)
        self.assertNotIn('value="c"', html)

    def test_client_cannot_expand_one_text_key_into_thousands_of_rendered_rows(
        self,
    ) -> None:
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

    def test_aggregate_row_rejection_does_not_quote_a_respected_per_level_limit(
        self,
    ) -> None:
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

    def test_a_rejected_oversized_submission_does_not_redisplay_its_rows(
        self,
    ) -> None:
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

    def test_client_cannot_multiply_default_row_caps_with_a_handful_of_keys(
        self,
    ) -> None:
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


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileRowBudgetTestCase(HostileRequestClientTestCase):
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
    ) -> None:
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
        self.assertJSONResponseContains(
            cheap_response, {"errors": {"values": ["too_many_forms"]}}
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
        self.assertJSONResponseContains(
            expensive_response, {"errors": {"values": ["too_many_forms"]}}
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

    def test_client_pays_at_most_linear_cost_for_sibling_mapping_children(
        self,
    ) -> None:
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

    def test_client_pays_at_most_linear_cost_for_sibling_list_fields(self) -> None:
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

    def test_client_pays_bounded_cost_three_sequence_levels_deep(self) -> None:
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

    def _count_rows_built(self) -> object:
        """Count row forms built while the returned counter is in scope.

        Wall-clock budgets catch a runaway cost but not a small regression.
        This counts the exact work an attacker's ``TOTAL_FORMS`` keys buy:
        one call per row form Django constructs, at every nesting level.
        """
        built = []
        formset_class = nestingdolls.SequenceWidget.RowFormSet
        original = formset_class._construct_form

        def counting(inner_self: object, index: object, **kwargs: object) -> object:
            built.append(index)
            return original(inner_self, index, **kwargs)

        formset_class._construct_form = counting
        self.addCleanup(setattr, formset_class, "_construct_form", original)
        return built

    def _count_formsets_built(self) -> object:
        """Count formsets built while the returned counter is in scope.

        Row counts do not detect empty child formsets built after the shared
        budget overflows. This counter detects that setup work.
        """
        built = []
        widget_class = nestingdolls.SequenceWidget
        original = widget_class.new_formset

        def counting(inner_self: object, *args: object, **kwargs: object) -> object:
            built.append(kwargs["prefix"])
            return original(inner_self, *args, **kwargs)

        widget_class.new_formset = counting
        self.addCleanup(setattr, widget_class, "new_formset", original)
        return built

    def test_overflow_skips_empty_later_child_formsets(self) -> None:
        """Reject overflow and skip child-formset setup that cannot admit a row.

        The first inner row's overdraw unwinds extraction, so the 19 outer
        rows after it never build their child formsets. The final ``values``
        entry is the owner's bound zero-row replacement: one constant build
        per rejected submission, never one per sibling.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=20, inner_total=2000
        )
        built = self._count_formsets_built()
        form = NestedSequenceDeletionForm(data=payload)

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "too_many_forms")
        self.assertEqual(built, ["values", "values-0", "values"])

    def test_overflow_keeps_no_row_a_forged_claim_bought(self) -> None:
        """Keep no row past the budget alive to the end of the response.

        Building a row is bounded work; keeping one is not. Every surviving
        row is read once by extraction, again by cleaning or a render, and
        stays alive until the response is finished, so a rejected submission
        must leave none behind. The first overdraw unwinds extraction, and
        the owner replaces the whole formset with a bound zero-row one, so
        the rows a forged claim already bought are unreferenced when
        extraction returns and no later reader needs to know they existed.
        Nested rows are only reachable through these outer rows, so dropping
        these drops the whole tree. Measured on the eight-sibling case in
        ``pathological.py``: 488 rows at 0.7 MB peak with the abort, against
        16,000 rows at 4.5 MB when extraction built every row and discarded
        them afterwards, for the same rejection.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=20, inner_total=2000
        )
        built = self._count_rows_built()
        form = NestedSequenceDeletionForm(data=payload)
        bound_field = form["values"]

        self.assertIs(bound_field.submission_overflow, True)
        self.assertEqual(list(bound_field.formset.forms), [])
        self.assertEqual(bound_field.data, [])
        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "too_many_forms")
        # The claim did buy row construction. Nothing may outlive it.
        self.assertGreater(len(built), 0)

    def test_claim_after_exact_budget_still_records_overflow(self) -> None:
        """Let the claim after exact budget use record overflow.

        Zero is not overflow. The next child must read its claim and be the
        one that overdraws. This prevents refusing a claim that
        the budget can still pay in full.
        """
        payload = {
            "values-TOTAL_FORMS": "2",
            "values-INITIAL_FORMS": "0",
            "values-0-TOTAL_FORMS": "1998",
            "values-0-INITIAL_FORMS": "0",
            "values-1-TOTAL_FORMS": "1",
            "values-1-INITIAL_FORMS": "0",
        }
        form = NestedSequenceDeletionForm(data=payload)

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "too_many_forms")

    def test_negative_total_forms_cannot_refund_the_shared_budget(self) -> None:
        """Refuse a negative claim instead of paying it back into the budget.

        Django's bound ``total_form_count`` is ``min(TOTAL_FORMS,
        absolute_max)`` over a plain ``IntegerField`` with no lower clamp, so
        a forged negative ``TOTAL_FORMS`` reaches ``take()``. An earlier
        version subtracted the full claim, so this payload's 42 keys refunded
        a million rows, built 8005 rows, and cleaned as valid. A claim of zero
        or less must buy nothing and refund nothing.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=5, inner_total=2000
        )
        payload[f"values-0-{TOTAL_FORM_COUNT}"] = "-1000000"
        built = self._count_rows_built()
        form = NestedSequenceDeletionForm(data=payload)

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "too_many_forms")
        self.assertLessEqual(len(built), 2010)

    def test_client_cannot_bypass_the_shared_budget_with_change_detection(
        self,
    ) -> None:
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

    def test_client_cannot_bypass_the_shared_budget_with_empty_permitted(
        self,
    ) -> None:
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

    def test_client_sees_a_reported_rejection_not_a_silent_truncation(self) -> None:
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

    def test_client_keeps_exact_budget_use_valid_after_change_detection(self) -> None:
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

    def test_client_keeps_a_legitimate_submission_whole_after_change_detection(
        self,
    ) -> None:
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

    def test_change_detection_without_initial_rows_validates_no_row_form(
        self,
    ) -> None:
        """Change detection answers from extracted values alone.

        ``SequenceBoundField._has_changed`` compares extracted values, and
        only the deletion of an initial row can report a change beyond
        that comparison. Django's ``deleted_forms`` validates every row
        form before it answers. With no initial rows that validation
        cannot change the answer, so the bound field returns before the
        read, partly for performance and efficiency: Django calls
        ``has_changed()`` itself for every ``empty_permitted`` form, and
        a hostile submission carries no initial rows, so the validation
        pass would be unread work on every rejection this class measures.
        ``test_sequencefield_binding`` holds the other side of the boundary: with
        initial rows, a delete mark must still report a change.
        """
        payload = self._amplified_sequence_payload(
            "values", outer_total=2, inner_total=3
        )
        form = NestedSequenceDeletionForm(payload)

        validations = []
        formset_class = nestingdolls.SequenceWidget.RowFormSet
        original = formset_class.full_clean

        def counting(inner_self: object, *args: object, **kwargs: object) -> object:
            validations.append(inner_self.prefix)
            return original(inner_self, *args, **kwargs)

        # full_clean is inherited, so remove the wrapper to restore it.
        formset_class.full_clean = counting
        self.addCleanup(delattr, formset_class, "full_clean")

        self.assertIs(form.has_changed(), False)
        self.assertEqual(validations, [])

    def test_rendering_a_bound_mapping_builds_no_second_row_formset(self) -> None:
        """Rendering a bound mapping reuses the rows that cleaning built.

        ``BoundField.as_widget`` always computes ``value()``, and the base
        behavior extracts the whole mapping to compute it, which builds a
        fresh row formset for each nested sequence.
        ``MappingWidget.get_context`` renders from the bound child Form
        and never reads that value, so ``MappingBoundField.value()``
        returns the initial value when the child Form owns the bound
        data, partly for performance and efficiency: the render of a
        rejected submission would otherwise pay a second full row budget,
        and ``pathological.py`` measures that page.
        """
        payload = {
            f"value-rows-{TOTAL_FORM_COUNT}": "2",
            f"value-rows-{INITIAL_FORM_COUNT}": "0",
            "value-rows-0": "1",
            "value-rows-1": "2",
        }
        form = OptionalIntegerSequenceMappingValueForm(payload)
        built = self._count_rows_built()

        self.assertFormValid(form)
        rows_from_cleaning = len(built)
        self.assertGreater(rows_from_cleaning, 0)

        form.as_p()

        self.assertEqual(len(built), rows_from_cleaning)


@override_settings(ROOT_URLCONF="tests.support.urls")
class HostileFormPrefixTestCase(HostileRequestClientTestCase):
    """Send the same mapping child under more than one accepted spelling."""

    def test_client_ignores_unprefixed_controls_on_a_prefixed_form(self) -> None:
        """A control without the form prefix reaches no field."""
        response = self.client.post("/hostile-prefixed-mapping/", {"value-a": "9"})
        self.assertJSONResponseContains(response, {"errors": {"value": ["required"]}})

    def test_client_prefers_the_prefixed_control_over_a_forged_bare_control(
        self,
    ) -> None:
        """A prefixed control wins when both spellings arrive."""
        response = self.post_raw(
            "/hostile-prefixed-mapping/",
            (("value-a", "9"), ("outer-value-a", "5")),
        )
        self.assertJSONResponseContains(response, {"value": {"a": 5}})

    def test_client_drops_an_undeclared_child_inside_a_sequence_row(self) -> None:
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
        self.assertJSONResponseContains(
            response, {"value": [{"label": "kept", "upload": None}]}
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
