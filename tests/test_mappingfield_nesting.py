"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.test.utils import setup_test_environment, teardown_test_environment

from .support.forms.mapping import (
    MappingIntegerTagsForm,
    MappingRecordPayloadForm,
)
from .support.testcases import (
    CompositeFieldTestCase,
    TestQueryDict,
    rendered_elements,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class MappingFieldNestedSequenceChildTestCase(CompositeFieldTestCase):
    """A mapping's nested sequence child validates the same in either input style.

    A sequence nested one level inside a mapping must still render its row error
    inline when the mapping binds to one whole Python value, as a prefixed
    submission does.
    """

    def assertNestedSequenceChildError(self, form: object) -> None:  # noqa: D102
        self.assertFormInvalid(form)
        self.assertBoundFieldErrors(form, "point", [])
        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertRenderedMessageCount(html, "Enter a whole number.")
        self.assertErrorReferenceResolves(html, "id_point-tags_1_error")
        self.assertErrorElementIsAbsent(html, "id_point_error")

    def assertNestedSequenceChildValid(self, form: object) -> None:  # noqa: D102
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"tags": [1, 2, 3]})
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        for index, value in enumerate((1, 2, 3)):
            self.assertIn(f'name="point-tags-{index}-value" value="{value}"', html)

    def test_nested_sequence_child_error_via_whole_value(self) -> None:
        """A bad row in a mapping's whole-value nested list shows its own error."""
        self.assertNestedSequenceChildError(
            MappingIntegerTagsForm({"point": {"tags": [1, "bad", 3]}})
        )

    def test_nested_sequence_child_error_via_querydict(self) -> None:
        """A bad row in a mapping's prefixed-row nested list shows its own error."""
        self.assertNestedSequenceChildError(
            MappingIntegerTagsForm(
                TestQueryDict.from_dict(
                    {
                        f"point-tags-{TOTAL_FORM_COUNT}": "3",
                        f"point-tags-{INITIAL_FORM_COUNT}": "3",
                        "point-tags-0-value": "1",
                        "point-tags-1-value": "bad",
                        "point-tags-2-value": "3",
                    }
                )
            )
        )

    def test_nested_sequence_child_valid_via_whole_value(self) -> None:
        """A valid whole-value nested list renders every row with no error markup."""
        self.assertNestedSequenceChildValid(
            MappingIntegerTagsForm({"point": {"tags": [1, 2, 3]}})
        )

    def test_nested_sequence_child_valid_via_querydict(self) -> None:
        """A valid prefixed-row nested list renders every row with no error markup."""
        self.assertNestedSequenceChildValid(
            MappingIntegerTagsForm(
                TestQueryDict.from_dict(
                    {
                        f"point-tags-{TOTAL_FORM_COUNT}": "3",
                        f"point-tags-{INITIAL_FORM_COUNT}": "3",
                        "point-tags-0-value": "1",
                        "point-tags-1-value": "2",
                        "point-tags-2-value": "3",
                    }
                )
            )
        )

    def test_nested_sequence_group_name_resolves_to_the_label_in_paragraph_layout(
        self,
    ) -> None:
        """Every group name of a mapping with a nested sequence points at an element.

        A nested field renders its label as a ``<span>``. Its ``aria-labelledby``
        target must be that span's id, not a missing element.
        """
        html = MappingIntegerTagsForm().as_p()

        elements = [dict(element.attributes) for element in rendered_elements(html)]
        referenced = {
            attributes["aria-labelledby"]
            for attributes in elements
            if "aria-labelledby" in attributes
        }
        existing = {attributes["id"] for attributes in elements if "id" in attributes}

        self.assertEqual(referenced, {"id_point_label", "id_point-tags_label"})
        self.assertEqual(referenced - existing, set())


class MappingFieldNestedRecordsTestCase(CompositeFieldTestCase):
    """A CSV- or JSON-shaped list of row mappings validates the same in either style.

    ``records`` stands in for one decoded JSON array of objects, or one CSV
    file's rows: a list of mappings nested inside a mapping field, three
    nesting levels deep - ``DictField`` around ``ListField`` around
    ``DictField``.
    """

    def assertRecordsLeafError(self, form: object) -> None:  # noqa: D102
        self.assertFormInvalid(form)
        self.assertBoundFieldErrors(form, "payload", [])
        html = form.as_p()
        self.assertRenderedMessageCount(html, "This field is required.")
        self.assertErrorReferenceResolves(html, "id_payload-records-1-value-name_error")
        self.assertErrorElementIsAbsent(html, "id_payload-records_1_error")
        self.assertErrorElementIsAbsent(html, "id_payload_error")

    def assertRecordsAllValid(self, form: object) -> None:  # noqa: D102
        self.assertFormValid(form)
        self.assertEqual(
            form.cleaned_data["payload"],
            {"records": [{"name": "ok"}, {"name": "ok2"}]},
        )
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        self.assertIn('name="payload-records-0-value-name" value="ok"', html)
        self.assertIn('name="payload-records-1-value-name" value="ok2"', html)

    def test_records_leaf_error_via_whole_value(self) -> None:
        """A CSV- or JSON-shaped list of row mappings shows a bad leaf inline."""
        self.assertRecordsLeafError(
            MappingRecordPayloadForm(
                {"payload": {"records": [{"name": "ok"}, {"name": ""}]}}
            )
        )

    def test_records_leaf_error_via_querydict(self) -> None:
        """A CSV- or JSON-shaped list of row mappings shows a bad leaf inline, prefixed-row style."""
        self.assertRecordsLeafError(
            MappingRecordPayloadForm(
                TestQueryDict.from_dict(
                    {
                        f"payload-records-{TOTAL_FORM_COUNT}": "2",
                        f"payload-records-{INITIAL_FORM_COUNT}": "2",
                        "payload-records-0-value-name": "ok",
                        "payload-records-1-value-name": "",
                    }
                )
            )
        )

    def test_records_all_valid_via_whole_value(self) -> None:
        """A valid CSV- or JSON-shaped record list cleans and renders every row."""
        self.assertRecordsAllValid(
            MappingRecordPayloadForm(
                {"payload": {"records": [{"name": "ok"}, {"name": "ok2"}]}}
            )
        )

    def test_records_all_valid_via_querydict(self) -> None:
        """A valid prefixed-row CSV- or JSON-shaped record list cleans and renders every row."""
        self.assertRecordsAllValid(
            MappingRecordPayloadForm(
                TestQueryDict.from_dict(
                    {
                        f"payload-records-{TOTAL_FORM_COUNT}": "2",
                        f"payload-records-{INITIAL_FORM_COUNT}": "2",
                        "payload-records-0-value-name": "ok",
                        "payload-records-1-value-name": "ok2",
                    }
                )
            )
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
