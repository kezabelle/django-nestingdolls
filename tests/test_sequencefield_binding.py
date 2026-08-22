"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import json
import unittest
from collections import deque
from urllib.parse import urlencode

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import QueryDict
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils import translation
from django.utils.datastructures import MultiValueDict

import nestingdolls

from .support.forms.sequence import (
    JSONSequenceSubmissionForm,
    MaximumOneSequenceForm,
    OptionalFileSequenceForm,
    OptionalRequiredTextSequenceForm,
    SequenceForm,
    SequenceSubmissionForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support.urls")
class SequenceFieldBindingTestCase(CompositeFieldTestCase):
    """These tests check core ListField behavior."""

    field_class = nestingdolls.ListField
    collection_class = list

    def assertCleanedValues(self, cleaned_data: object, values: object) -> None:  # noqa: D102
        self.assertIsInstance(cleaned_data, self.collection_class)
        self.assertEqual(cleaned_data, self.collection_class(values))

    def test_client_accepts_repeated_key_list_rows(self) -> None:
        """A repeated exact-name key submits scalar list rows without management controls."""
        response = self.client.post(
            "/list-submission-probe/", {"values": ["1", "2", "3"]}
        )
        self.assertJSONResponse(
            response, {"valid": True, "values": [1, 2, 3], "errors": {}}
        )

    def test_exact_sequence_input_accepts_a_legacy_widget_override(self) -> None:
        """Exact input keeps Django's three-argument widget extraction hook."""

        class LegacyWidget(nestingdolls.SequenceWidget):
            def value_from_datadict(
                self, data: object, files: object, name: object
            ) -> object:
                return super().value_from_datadict(data, files, name)

        class Form(forms.Form):
            values = nestingdolls.SequenceField(
                forms.IntegerField(), widget=LegacyWidget
            )

        form = Form({"values": ["1", "2"]})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_client_accepts_prefixed_row_list_rows(self) -> None:
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
        self.assertJSONResponse(
            response, {"valid": True, "values": [1, 2, 3], "errors": {}}
        )

    def test_client_accepts_a_repeated_key_json_row(self) -> None:
        """A repeated exact-name key submits one JSON-encoded scalar row."""
        value = {"answer": 42, "nested": [1, 2]}
        response = self.client.post(
            "/list-json-submission-probe/", {"values": [json.dumps(value)]}
        )
        self.assertJSONResponse(
            response, {"valid": True, "values": [value], "errors": {}}
        )

    def test_client_accepts_a_prefixed_row_json_row(self) -> None:
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
        self.assertJSONResponse(
            response, {"valid": True, "values": [value], "errors": {}}
        )

    def test_json_child_change_detection_uses_cleaned_values(self) -> None:
        """Managed change detection compares JSON rows after normalization."""
        value = {"answer": 42, "nested": [1, 2]}
        form = JSONSequenceSubmissionForm(
            {
                "values-0": json.dumps(value),
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
            initial={"values": [value]},
        )
        self.assertIs(form.has_changed(), False)

    def test_initial_accepts_generic_sequence_and_collection_types(self) -> None:
        """It accepts non-string collection-shaped initial values beyond builtins."""

        class FieldInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, initial=range(1, 3)
            )

        self.assertEqual(
            SequenceSubmissionForm(initial={"values": range(3)})["values"].value(),
            [0, 1, 2],
        )
        self.assertEqual(
            SequenceSubmissionForm(initial={"values": deque([4, 5])})["values"].value(),
            [4, 5],
        )
        self.assertEqual(FieldInitialForm()["values"].value(), [1, 2])

    def test_client_treats_an_exact_name_request_value_as_one_list_row(self) -> None:
        """A browser request value is one list row through ``getlist``."""
        response = self.client.post("/list-submission-probe/", {"values": "1"})
        self.assertJSONResponse(response, {"valid": True, "values": [1], "errors": {}})

    def test_exact_name_non_collections_are_invalid_sequence_input(self) -> None:
        """A direct exact sequence input must be a non-string collection."""
        for value in (None, "", "value", b"value", {"value": "value"}):
            with self.subTest(value=value):
                form = OptionalRequiredTextSequenceForm({"values": value})
                self.assertFormInvalid(form)
                self.assertFormErrorCode(form, "values", "invalid")

        field = nestingdolls.ListField(forms.CharField(), required=False)
        # ``None`` is the one non-collection input ``clean`` accepts directly:
        # it is the field's own default initial, and ``MappingField.clean``
        # already treats it as empty.
        self.assertEqual(field.clean(None), [])
        with self.assertRaises(ValidationError) as error:
            field.clean("")
        self.assertEqual(error.exception.code, "invalid")
        # Any other non-string collection binds, so the field can clean the
        # tuple or the set that a sibling variant produced.
        self.assertEqual(field.clean(("a", "b")), ["a", "b"])
        self.assertEqual(field.clean(field.clean(["a", "b"])), ["a", "b"])

    def test_exact_name_mapping_is_invalid_sequence_input(self) -> None:
        """A direct mapping under a sequence name is not one row."""

        class Row(forms.Form):
            value = forms.IntegerField()

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.DictField(Row), required=False)

        form = Form({"values": {}})
        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "invalid")

    def test_exact_name_file_list_binds_rows(self) -> None:
        """A files-only exact-name list supplies rows, as data does."""
        upload = SimpleUploadedFile("a.txt", b"a")
        form = OptionalFileSequenceForm(
            data={}, files=MultiValueDict({"uploads": [upload]})
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["uploads"], [upload])

    def test_exact_empty_data_list_masks_files(self) -> None:
        """An exact data key wins over files even when its list is empty."""
        data = MultiValueDict()
        data.setlist("uploads", [])
        upload = SimpleUploadedFile("a.txt", b"a")
        form = OptionalFileSequenceForm(
            data=data, files=MultiValueDict({"uploads": [upload]})
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["uploads"], [])

    def test_omitted_file_input_keeps_the_initial_file_rows(self) -> None:
        """A bound form with no file input keeps the initial file rows."""
        upload = SimpleUploadedFile("a.txt", b"a")
        form = OptionalFileSequenceForm(data={}, initial={"uploads": [upload]})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["uploads"], [upload])

    def test_exact_name_list_wins_over_management_keys(self) -> None:
        """A direct list under the exact name outranks management keys alone."""
        form = SequenceSubmissionForm(
            {
                "values": ["1", "2"],
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_invalid_exact_scalar_is_not_redisplayed_as_a_row(self) -> None:
        """An invalid direct scalar is not converted into a row."""
        bound = SequenceForm({"values": "1"})
        self.assertFormInvalid(bound)
        self.assertFormErrorCode(bound, "values", "invalid")
        self.assertNotIn('name="values-0" value="1"', bound.as_p())
        unbound = SequenceForm(initial={"values": 1})
        self.assertEqual(unbound["values"].value(), [1])

    def assertMissingManagementFormResponse(self, query: object) -> None:  # noqa: D102
        response = self.client.post(
            "/list-submission-probe/",
            data=query,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["missing_management_form"]},
            },
        )

    def test_client_reports_missing_management_form_without_total_forms(self) -> None:
        """A prefixed row without total forms reports a management error."""
        self.assertMissingManagementFormResponse("values-INITIAL_FORMS=0&values-0=1")

    def test_client_reports_missing_management_form_without_initial_forms(
        self,
    ) -> None:
        """A prefixed row without initial forms reports a management error."""
        self.assertMissingManagementFormResponse("values-TOTAL_FORMS=1&values-0=1")

    def test_client_reports_missing_management_form_for_an_out_of_range_row_key(
        self,
    ) -> None:
        """An out-of-range row key without controls reports a management error."""
        self.assertMissingManagementFormResponse("values-999999=1")

    def assertInvalidManagementRedisplay(  # noqa: D102
        self,
        form_class: object,
        data: object,
        initial: object,
        management_input: object,
    ) -> None:
        form = form_class(QueryDict(data), initial=initial)
        self.assertFormInvalid(form)
        html = form.as_p()
        self.assertInHTML(management_input, html)
        return form, html

    def test_invalid_total_management_data_redisplays_submitted_rows(self) -> None:
        """An invalid total control stays in the rendered sequence form."""
        self.assertInvalidManagementRedisplay(
            SequenceForm,
            f"values-{TOTAL_FORM_COUNT}=2&values-0=1&values-1=bad",
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" id="id_values-INITIAL_FORMS">',
        )

    def test_invalid_initial_management_data_redisplays_submitted_rows(self) -> None:
        """An invalid initial control stays in the rendered sequence form."""
        self.assertInvalidManagementRedisplay(
            SequenceForm,
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=bad&values-0=1&values-1=bad",
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="bad" id="id_values-INITIAL_FORMS">',
        )

    def test_client_uses_the_last_duplicate_list_management_value(self) -> None:
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
        self.assertJSONResponse(
            response, {"valid": True, "values": [1, 2], "errors": {}}
        )

    def test_list_valued_total_forms_in_plain_dict_data_is_missing_management(
        self,
    ) -> None:
        """A management key that binds to a Python list stays missing management data."""
        """A list from ``dict.get()`` stays one invalid management value."""

        form = SequenceForm(
            {
                f"values-{TOTAL_FORM_COUNT}": ["1", "2"],
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                "values-1": "2",
            }
        )

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "missing_management_form")

    def test_rows_above_maximum_redisplay_management_state(self) -> None:
        """Rows above the maximum keep their submitted management controls."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        _, html = self.assertInvalidManagementRedisplay(
            MaximumOneSequenceForm,
            submitted,
            {"values": [1]},
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
        )
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total id="id_values-TOTAL_FORMS">',
            html,
        )

    def test_rows_below_minimum_redisplay_management_state(self) -> None:
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
        self.assertFormErrorCode(form, "values", "min_length")

    def test_invalid_original_row_with_deleted_added_row_redisplays_management_state(
        self,
    ) -> None:
        """An invalid saved row keeps the deleted added row state."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        _, html = self.assertInvalidManagementRedisplay(
            SequenceForm,
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

    def test_client_removes_a_deleted_list_row(self) -> None:
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
        self.assertJSONResponse(response, {"valid": True, "values": [1], "errors": {}})

        response = self.client.post(
            "/list-max-deletion-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                f"values-1-{DELETION_FIELD_NAME}": "1",
            },
        )
        self.assertJSONResponse(response, {"valid": True, "values": [1], "errors": {}})

    def assertDeletionValueRemovesRow(self, delete_value: object) -> None:  # noqa: D102
        response = self.client.post(
            "/list-submission-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "1",
                f"values-0-{DELETION_FIELD_NAME}": delete_value,
            },
        )
        self.assertJSONResponse(response, {"valid": True, "values": [], "errors": {}})

    def test_client_treats_delete_value_1_as_deletion(self) -> None:
        """The delete value one removes a submitted row."""
        self.assertDeletionValueRemovesRow("1")

    def test_client_treats_delete_value_on_as_deletion(self) -> None:
        """The delete value on removes a submitted row."""
        self.assertDeletionValueRemovesRow("on")

    def test_client_treats_delete_value_true_as_deletion(self) -> None:
        """The delete value true removes a submitted row."""
        self.assertDeletionValueRemovesRow("true")

    def test_client_ignores_submitted_disabled_list_rows(self) -> None:
        """Client returns the initial value for a disabled list."""
        response = self.client.post(
            "/disabled-list-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "9",
            },
        )
        self.assertJSONResponse(response, {"valid": True, "values": [1], "errors": {}})

    def test_disabled_list_units_preserve_child_and_change_detection_behavior(
        self,
    ) -> None:
        """Field-level checks cover disabled child and change-detection internals."""

        class ChildForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(disabled=True))

        submitted = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=99"
        )
        valid = ChildForm(submitted, initial={"values": ["7"]})
        self.assertFormValid(valid)
        self.assertEqual(valid.cleaned_data["values"], [7])

        invalid = ChildForm(submitted, initial={"values": ["bad"]})
        self.assertFormInvalid(invalid)
        error = invalid.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "invalid")

    def test_direct_clean_of_a_disabled_child_ignores_submitted_rows(self) -> None:
        """A disabled child cleans each direct row from an empty initial."""
        field = nestingdolls.ListField(
            forms.IntegerField(disabled=True, required=False), required=False
        )
        self.assertEqual(field.clean(["9", "8"]), [None, None])

    def assertOversizedDisabledFieldSkipsChildComparison(  # noqa: D102
        self, field_class: object
    ) -> None:

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial: object, data: object) -> object:
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
        absolute_max = OversizedForm.base_fields["values"].limits.absolute_max
        oversized = OversizedForm({"values": ["1"] * (absolute_max + 1)})
        self.assertIs(oversized.has_changed(), False)

    def test_disabled_list_field_skips_child_comparison_for_oversized_whole_value(
        self,
    ) -> None:
        """An oversized disabled list does not compare its child values."""
        self.assertOversizedDisabledFieldSkipsChildComparison(nestingdolls.ListField)

    def test_disabled_set_field_skips_child_comparison_for_oversized_whole_value(
        self,
    ) -> None:
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
        self.assertFormValid(tampered)
        self.assertEqual(tampered.cleaned_data["point"], {"a": 1})
        self.assertEqual(tampered.cleaned_data["values"], [1])

    def test_direct_disabled_and_oversized_values_skip_child_comparison(self) -> None:
        """A disabled or oversized direct value gets its answer without child comparison."""

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial: object, data: object) -> object:
                raise AssertionError("child value was compared")

        disabled = nestingdolls.ListField(
            UnreachableField(), required=False, disabled=True
        )
        oversized = nestingdolls.ListField(
            UnreachableField(), max_length=0, required=False
        )

        self.assertIs(disabled.has_changed([1], ["2"]), False)
        self.assertIs(
            oversized.has_changed([], ["1"] * (oversized.limits.absolute_max + 1)),
            True,
        )

    def assertTooManyFormsResponse(self, url: object, total: object) -> None:  # noqa: D102
        response = self.client.post(
            url,
            {
                f"values-{TOTAL_FORM_COUNT}": str(total),
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["too_many_forms"]},
            },
        )

    def test_client_rejects_total_beyond_default_absolute_maximum(self) -> None:
        """The client rejects a total beyond the default absolute maximum."""
        self.assertTooManyFormsResponse(
            "/list-default-absolute-maximum-probe/", DEFAULT_MAX_NUM + 2
        )

    def test_client_rejects_total_beyond_configured_absolute_maximum(self) -> None:
        """The client rejects a total beyond the configured absolute maximum."""
        self.assertTooManyFormsResponse("/list-absolute-maximum-probe/", 3)

    def test_client_requires_management_for_an_out_of_range_row_key(self) -> None:
        """A discarded index still makes a row-key-only request malformed."""
        response = self.client.post(
            "/list-default-absolute-maximum-probe/",
            {f"values-{DEFAULT_MAX_NUM + 1}": "1"},
        )
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["missing_management_form"]},
            },
        )

    def test_client_reports_an_error_code_for_each_invalid_list_item(self) -> None:
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
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "values": None,
                "errors": {"values": ["item_invalid", "item_invalid"]},
            },
        )

    def test_item_error_markup_stays_inline_and_out_of_the_field_error_list(
        self,
    ) -> None:
        """In-process rendering keeps each list item error beside its input."""
        form = SequenceForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=bad&values-2=also-bad"
            )
        )

        self.assertFormInvalid(form)
        errors = form.errors.as_data()["values"]
        self.assertEqual(
            [error.code for error in errors], ["item_invalid", "item_invalid"]
        )
        self.assertEqual([error.params["item"] for error in errors], [1, 2])
        self.assertBoundFieldErrors(form, "values", [])

        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertInHTML(
            '<input type="number" name="values-1" value="bad" id="id_values_1" aria-invalid="true" aria-describedby="id_values_1_error">',
            html,
        )
        self.assertInHTML(
            '<span class="errorlist" id="id_values_1_error">Enter a whole number.</span>',
            html,
        )
        self.assertInHTML(
            '<span class="errorlist" id="id_values_2_error">Enter a whole number.</span>',
            html,
        )
        self.assertNotIn("Item 1: Enter a whole number.", html)
        self.assertNotIn("Item 2: Enter a whole number.", html)

        class EmailForm(forms.Form):
            emails = nestingdolls.ListField(forms.EmailField(), min_length=4)

        blanks = EmailForm(
            QueryDict(
                f"emails-{TOTAL_FORM_COUNT}=5&"
                f"emails-{INITIAL_FORM_COUNT}=0&"
                "emails-0=&emails-1=&emails-2=&emails-3=&emails-4="
            )
        )

        self.assertFormInvalid(blanks)
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
        self.assertBoundFieldErrors(blanks, "emails", [])

        blank_html = blanks.as_p()
        self.assertNotIn("Item 0: This field is required.", blank_html)
        self.assertInHTML(
            '<span class="errorlist" id="id_emails_0_error">This field is required.</span>',
            blank_html,
        )

    def test_item_invalid_errors_preserve_child_codes(self) -> None:
        """It preserves child error codes inside item errors."""

        class MultiErrorField(forms.Field):
            def clean(self, value: object) -> object:
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
        self.assertFormInvalid(form)
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.message for error in errors], ["first", "second"])
        self.assertEqual(
            [error.params["child_code"] for error in errors],
            ["first_code", "second_code"],
        )

    def assertPercentMessageRendersLiterally(self, child_field: object) -> None:  # noqa: D102
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
        self.assertFormInvalid(form)
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

    def test_eager_percent_error_message_renders_literally(self) -> None:
        """An eager child error keeps one literal percent sign."""

        class PercentField(forms.Field):
            def clean(self, value: object) -> object:
                raise ValidationError("50% off is required", code="required")

        self.assertPercentMessageRendersLiterally(PercentField())

    def test_lazy_percent_error_message_renders_literally(self) -> None:
        """A lazy child error keeps one literal percent sign."""

        class LazyPercentField(forms.Field):
            def clean(self, value: object) -> object:
                raise ValidationError(
                    translation.gettext_lazy("%(pct)s%% off is required"),
                    code="required",
                    params={"pct": 50},
                )

        self.assertPercentMessageRendersLiterally(LazyPercentField())

    def test_nested_mapping_rows_are_partitioned_before_extraction(self) -> None:
        """It gives each nested mapping only its own normalized row inputs."""

        class RowForm(forms.Form):
            value = forms.IntegerField()

        class CountingWidget(nestingdolls.MappingWidget):
            normalized_keys = 0

            def read_input(self, data: object, files: object, name: object) -> object:
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

        self.assertFormValid(form)
        # Each nested mapping receives only its own normalized child values.
        # The exact number of values is an implementation detail.
        self.assertLess(CountingWidget.normalized_keys, row_count * row_count)

    def test_added_removed_and_failing_rows_drive_has_changed(self) -> None:
        """Row cardinality changes and child comparison errors both mean "changed"."""
        self.assertIs(
            SequenceSubmissionForm(
                {"values": []}, initial={"values": []}
            ).has_changed(),
            False,
        )
        self.assertIs(
            SequenceSubmissionForm(
                {"values": [0]}, initial={"values": []}
            ).has_changed(),
            True,
        )
        self.assertIs(
            SequenceSubmissionForm(
                {"values": []}, initial={"values": [0]}
            ).has_changed(),
            True,
        )
        self.assertIs(
            SequenceSubmissionForm(
                {"values": [0, 1]}, initial={"values": [0, 1]}
            ).has_changed(),
            False,
        )

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial: object, data: object) -> object:
                raise ValidationError("comparison failed")

        class ErrorForm(forms.Form):
            values = nestingdolls.ListField(ErrorField(), required=False)

        self.assertIs(ErrorForm({"values": ["1"]}).has_changed(), True)

    def test_deleting_an_initial_row_is_a_change(self) -> None:
        """A delete mark on an initial row reports a change on its own.

        The resubmitted values match the initial values, so value
        comparison reports no change. Only ``formset.deleted_forms`` can
        report the deletion, and ``SequenceBoundField._has_changed``
        reads it only when initial rows exist, because that read
        validates every row form. This test holds the boundary of that
        skip: a deletion missed here would skip the save that removes
        the row.
        """
        data = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "2",
            "values-0": "1",
            "values-1": "2",
        }
        initial = {"values": [1, 2]}
        self.assertIs(SequenceForm(data, initial=initial).has_changed(), False)

        deleted = dict(data)
        deleted[f"values-1-{DELETION_FIELD_NAME}"] = "1"
        self.assertIs(SequenceForm(deleted, initial=initial).has_changed(), True)

    def test_bound_form_without_sequence_keys_reports_no_change(self) -> None:
        """Answer change detection for a bound field that never extracted rows.

        This field's extraction returns its initial rows without opening a
        budget, so the overflow reader must answer for a bound field that has
        no extraction at all. An earlier version stored that answer only
        inside the countdown scope, so this raised ``AttributeError``.
        """
        self.assertIs(SequenceSubmissionForm({}).has_changed(), False)

    def test_to_python_rejects_errors_as_values(self) -> None:
        """It rejects validation errors passed in as raw values."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.to_python(ValidationError("not submitted data"))
        self.assertEqual(context.exception.code, "invalid")

    def test_rejects_unhashable_cleaned_values(self) -> None:
        """It rejects unhashable cleaned values for sets."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.JSONField())

        form = Form({"values": [{"answer": 42}]})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "unhashable")

    def test_client_counts_composite_list_rows_not_their_child_keys(self) -> None:
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
        self.assertJSONResponse(
            response,
            {
                "valid": True,
                "values": [{"a": 1, "b": 1, "c": 1}] * 4,
                "errors": {},
            },
        )

    def assertDisabledSequenceUsesInitialRows(self, data: object) -> None:  # noqa: D102

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, initial=[1, 2]
            )

        form = Form(data)
        html = form.as_p()

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [1, 2])
        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)

    def test_disabled_sequence_ignores_deleted_submitted_state(self) -> None:
        """A disabled sequence ignores a submitted deleted row."""
        self.assertDisabledSequenceUsesInitialRows(
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
                f"values-0-{DELETION_FIELD_NAME}": "on",
            }
        )

    def test_disabled_sequence_ignores_invalid_management_state(self) -> None:
        """A disabled sequence ignores invalid submitted management data."""
        self.assertDisabledSequenceUsesInitialRows(
            {
                f"values-{TOTAL_FORM_COUNT}": "bad",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )

    def test_untouched_added_row_does_not_block_an_optional_list(self) -> None:
        """An unfilled extra row must not fail a required child on an optional list.

        A browser's "add row" control raises ``TOTAL_FORMS`` and renders a
        blank input before the user types anything; that blank input still
        submits its own key. A vanilla Django formset treats an unedited row
        beyond ``INITIAL_FORMS``/``min_num`` as unchanged and silently omits
        it. This field must match that, even though the row's own key is
        present in the request.
        """
        form = OptionalRequiredTextSequenceForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0="
            )
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [])

    def test_untouched_added_row_beside_a_filled_initial_row(self) -> None:
        """An added-but-blank row is dropped while the filled initial row survives."""
        form = OptionalRequiredTextSequenceForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=1&"
                "values-0=kept&values-1="
            )
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], ["kept"])

    def test_optional_child_blank_added_row_is_dropped_like_a_formset(self) -> None:
        """A blank added row is dropped even when the child accepts blank.

        A vanilla Django formset treats an unedited extra row as
        unchanged and omits it, whether or not its fields accept blank.
        This field matches that: an added-but-blank row never becomes an
        explicit empty value.
        """
        form = OptionalRequiredTextSequenceForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=1&"
                "values-0=kept&values-1="
            )
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], ["kept"])

    def test_row_equal_to_the_child_initial_is_kept(self) -> None:
        """A submitted row is kept even when it equals the child's own initial.

        Django alone would drop it: an extra row stays ``empty_permitted``
        and ``Form.has_changed()`` compares the row against the child
        field's ``initial``. ``RowFormSet.get_form_kwargs`` exists for this.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(required=False, initial="x")
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0&"
                "values-0=x&values-1=y"
            )
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], ["x", "y"])

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_bound_whole_value_above_the_shared_cap_reports_too_many_forms(
        self,
    ) -> None:
        """A clipped whole value reports overflow instead of losing rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, max_length=10, absolute_max=10
            )

        form = Form({"values": list(range(11))})

        self.assertFormInvalid(form)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "too_many_forms")
        self.assertEqual(error.params["num"], 10)

    def test_item_error_params_carry_the_documented_row_index(self) -> None:
        """A row failure keeps its row index in ``params``.

        README.md documents this exact dict; a sequence records the row index
        where a mapping records the child field name.
        """
        form = SequenceForm(
            {
                "values-0": "1",
                "values-1": "bad",
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
            }
        )

        self.assertFormInvalid(form)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(
            error.params,
            {
                "item": 1,
                "message": "Enter a whole number.",
                "child_code": "invalid",
            },
        )
        self.assertBoundFieldErrors(form, "values", [])
        self.assertFormError(form, "values", ["Enter a whole number."])

    def test_deleted_row_errors_stay_out_of_item_errors(self) -> None:
        """A deleted row's errors do not become item errors of the field."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad0",
                f"values-0-{DELETION_FIELD_NAME}": "on",
                "values-1": "bad1",
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )

        self.assertFormInvalid(form)
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.params["item"] for error in errors], [1])


class SequenceFieldDirectCleaningTestCase(CompositeFieldTestCase):
    """Make sure ``ListField`` cleans each input shape correctly.

    Each test sends one input shape. Each test examines the cleaned list or the
    error codes.
    """

    def test_exact_name_blank_is_one_row(self) -> None:
        """A blank request value is one submitted sequence row."""
        form = SequenceSubmissionForm(QueryDict("values="))
        self.assertFormInvalid(form)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "required")

    def test_optional_direct_list_cleans_every_row(self) -> None:
        """A direct Python list in a dict cleans every row."""
        form = SequenceSubmissionForm({"values": ["3", "4"]})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_request_list_payload_is_one_row(self) -> None:
        """A request list payload is one row, not the outer sequence."""
        form = SequenceSubmissionForm(MultiValueDict({"values": [["3", "4"]]}))
        self.assertFormInvalid(form)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "invalid")

    def test_direct_non_collections_are_invalid_sequence_input(self) -> None:
        """A direct exact sequence input must be a non-string collection."""
        for value in (None, "", "3", b"3", {"number": "3"}):
            with self.subTest(value=value):
                form = SequenceSubmissionForm({"values": value})
                self.assertFormInvalid(form)
                self.assertFormErrorCode(form, "values", "invalid")

    def test_direct_tuple_input_binds_as_rows(self) -> None:
        """A tuple binds, so a sibling variant's output cleans again."""
        form = SequenceSubmissionForm({"values": ("3", "4")})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_direct_none_cleans_empty_when_optional(self) -> None:
        """An optional field treats ``clean(None)`` as an empty submission.

        ``MappingField.clean(None)`` returns ``{}``.
        The sequence field has the same direct-call behavior.
        Only ``clean`` makes this conversion.
        Bound ``{"values": None}`` input remains invalid.
        """
        field = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertEqual(field.clean(None), [])

    def test_direct_none_reports_required(self) -> None:
        """A required field reports ``required`` for ``clean(None)``."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as caught:
            field.clean(None)

        self.assertEqual(caught.exception.code, "required")

    def test_prefixed_data_cleans(self) -> None:
        """A prefixed sequence submission cleans its row."""
        form = SequenceForm(
            {
                "values-0": "1",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [1])

    def test_required_direct_list_cleans_every_row(self) -> None:
        """A direct sequence list cleans every row."""
        form = SequenceForm({"values": ["3", "4"]})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_exact_list_blank_and_none_are_rows(self) -> None:
        """A list entry remains a row regardless of its value."""
        for submitted in ({"values": [""]}, {"values": [None]}, QueryDict("values=")):
            with self.subTest(submitted=submitted):
                form = SequenceSubmissionForm(submitted)
                self.assertFormInvalid(form)
                error = form.errors.as_data()["values"][0]
                self.assertEqual(error.code, "item_invalid")
                self.assertEqual(error.child_code, "required")

    def test_direct_empty_list_cleans_empty(self) -> None:
        """An empty direct list is an empty submitted sequence."""
        form = SequenceSubmissionForm({"values": []})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [])

    def test_direct_list_keeps_a_multiple_choice_row(self) -> None:
        """A direct row list reaches Django's list-aware child widget."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.MultipleChoiceField(choices=(("a", "A"), ("b", "B"))),
                required=False,
            )

        form = Form({"values": [["a", "b"]]})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [["a", "b"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
