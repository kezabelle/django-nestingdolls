"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from urllib.parse import urlencode

from django.conf import settings
from django.forms.formsets import (
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment

from .support.forms.mapping import (
    MappingRootSubmissionLimitForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support.urls", DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
class SequenceFieldRequestLimitTestCase(CompositeFieldTestCase):
    """Test request and per-level row limits.

    Post submissions through Django's request limits.
    """

    def assertSequenceRootSubmission(  # noqa: D102
        self, inner_total: object, expected_valid: object, expected_errors: object
    ) -> None:
        # The outer row is declared initial, so Django's own formset rule
        # keeps it: only an extra row may clean away as blank. Its inner
        # checkboxes are all unchecked, so the row carries no data key.
        response = self.client.post(
            "/sequence-root-submission-limit/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "1",
                f"outer-0-{TOTAL_FORM_COUNT}": str(inner_total),
                f"outer-0-{INITIAL_FORM_COUNT}": str(inner_total),
            },
        )
        self.assertJSONResponse(
            response, {"valid": expected_valid, "errors": expected_errors}
        )

    def test_sequence_root_rejects_total_above_shared_cap(self) -> None:
        """A sequence root rejects an inner total above its shared cap."""
        self.assertSequenceRootSubmission(10, False, {"outer": ["too_many_forms"]})

    def test_sequence_root_accepts_total_at_shared_cap(self) -> None:
        """A sequence root accepts an inner total at its shared cap."""
        self.assertSequenceRootSubmission(9, True, {})

    def test_request_rejects_more_urlencoded_keys_than_django_allows(self) -> None:
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
    def test_request_rejects_body_larger_than_django_limit(self) -> None:
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

    def test_mapping_sibling_lists_keep_independent_per_level_allowances(
        self,
    ) -> None:
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

        self.assertJSONResponse(
            response, {"valid": True, "lengths": {"first": 10, "second": 10}}
        )

    def assertMappingSiblingRendersRows(self, child: object) -> None:  # noqa: D102
        form = MappingRootSubmissionLimitForm(
            initial={"values": {"first": [True] * 10, "second": [True] * 10}}
        )
        html = form.as_p()
        self.assertEqual(
            sum(html.count(f'name="values-{child}-{index}"') for index in range(10)),
            10,
        )

    def test_mapping_root_renders_first_sibling_rows_within_its_allowance(
        self,
    ) -> None:
        """A mapping root renders the first sibling rows within its allowance."""
        self.assertMappingSiblingRendersRows("first")

    def test_mapping_root_renders_second_sibling_rows_within_its_allowance(
        self,
    ) -> None:
        """A mapping root renders the second sibling rows within its allowance."""
        self.assertMappingSiblingRendersRows("second")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=100)
    def test_per_level_total_above_absolute_max_is_a_nested_form_error_after_parsing(
        self,
    ) -> None:
        """A parser-accepted child total above its own absolute maximum returns item_invalid."""
        response = self.client.post(
            "/sequence-root-submission-limit/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "1",
                f"outer-0-{TOTAL_FORM_COUNT}": "11",
                f"outer-0-{INITIAL_FORM_COUNT}": "0",
            },
        )

        self.assertJSONResponse(
            response, {"valid": False, "errors": {"outer": ["item_invalid"]}}
        )

    def assertSequenceMappingSequenceSubmission(  # noqa: D102
        self,
        inner_total: object,
        expected_valid: object,
        expected_errors: object,
        expected_tag_counts: object,
    ) -> None:
        response = self.client.post(
            "/sequence-mapping-sequence-submission-limit/",
            {
                f"items-{TOTAL_FORM_COUNT}": "1",
                f"items-{INITIAL_FORM_COUNT}": "1",
                f"items-0-tags-{TOTAL_FORM_COUNT}": str(inner_total),
                f"items-0-tags-{INITIAL_FORM_COUNT}": str(inner_total),
            },
        )
        self.assertJSONResponse(
            response,
            {
                "valid": expected_valid,
                "errors": expected_errors,
                "tag_counts": expected_tag_counts,
            },
        )

    def test_sequence_mapping_sequence_rejects_total_above_outer_cap(self) -> None:
        """A nested sequence rejects a total above the outer cap."""
        self.assertSequenceMappingSequenceSubmission(
            10, False, {"items": ["too_many_forms"]}, []
        )

    def test_sequence_mapping_sequence_accepts_total_at_outer_cap(self) -> None:
        """A nested sequence accepts a total at the outer cap."""
        self.assertSequenceMappingSequenceSubmission(9, True, {}, [9])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
