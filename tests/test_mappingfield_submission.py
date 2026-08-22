"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from typing import ClassVar

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils.datastructures import MultiValueDict

import nestingdolls

from .support.forms.mapping import (
    MappingHookForm,
    MappingNonFieldErrorForm,
    MappingOptionalPointsForm,
    MappingPointForm,
    OptionalMappingPointForm,
    RequiredMappingPointForm,
    ValidatedMappingPointForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support.urls")
class MappingFieldSubmissionFunctionalTestCase(CompositeFieldTestCase):
    """Tests the ``MappingField`` contract through posted HTTP submissions.

    The tests cover omissions, child errors, prefixes, disabled state, and file
    transport.
    """

    def test_client_reports_mapping_omissions_and_partial_child_errors(self) -> None:
        """Client reports required mapping omissions and partial child failures."""
        response = self.client.post("/mapping-optional-probe/", {})
        self.assertJSONResponse(
            response,
            {"valid": False, "value": None, "errors": {"required_point": ["required"]}},
        )
        response = self.client.post(
            "/mapping-optional-probe/",
            {"required_point-a": "1", "optional_point-label": "missing a"},
        )
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "value": None,
                "errors": {"optional_point": ["item_invalid"]},
            },
        )

    def test_client_returns_child_cleaning_and_validator_error_codes(self) -> None:
        """Client exposes cleaned child values and outer validator codes."""
        response = self.client.post("/mapping-hook-probe/", {"value-a": "2"})
        self.assertJSONResponse(
            response,
            {"valid": True, "value": {"a": 3, "double": 6}, "errors": {}},
        )
        response = self.client.post("/mapping-validated-probe/", {"point-a": "2"})
        self.assertJSONResponse(
            response,
            {"valid": False, "point": None, "errors": {"point": ["no_two"]}},
        )

    def test_client_preserves_non_field_child_error_codes(self) -> None:
        """Client keeps a child non-field error code at the mapping boundary."""
        response = self.client.post("/mapping-nonfield-probe/", {"value-a": "2"})
        self.assertJSONResponse(
            response,
            {
                "valid": False,
                "errors": {"value": ["item_invalid"]},
                "child_errors": {"value": ["unavailable"]},
            },
        )

    def test_client_applies_prefix_disabled_and_initial_omission_behavior(
        self,
    ) -> None:
        """Client binds prefixed controls, ignores disabled values, and clears omitted optional mappings."""
        response = self.client.post("/mapping-prefixed-probe/", {"outer-point-a": "5"})
        self.assertJSONResponse(
            response,
            {"valid": True, "point": {"a": 5, "label": ""}, "errors": {}},
        )
        response = self.client.post("/mapping-disabled-probe/", {"point-a": "99"})
        self.assertJSONResponse(
            response,
            {"valid": True, "point": {"a": 8, "label": "initial"}, "errors": {}},
        )
        response = self.client.post("/mapping-initial-probe/", {})
        self.assertJSONResponse(response, {"valid": True, "point": {}, "errors": {}})

    def test_client_transports_mapping_upload_clear_and_file_changes(self) -> None:
        """Client transports mapping uploads, clear conflicts, retained initials, and file changes."""
        response = self.client.post(
            "/mapping-asset-probe/",
            {
                "asset-title": "report",
                "asset-upload": SimpleUploadedFile("report.txt", b"data"),
            },
        )
        self.assertJSONResponse(
            response,
            {
                "valid": True,
                "asset": {"title": "report", "upload": "report.txt"},
                "errors": {},
            },
        )
        response = self.client.post(
            "/mapping-asset-initial-probe/", {"asset-title": "old"}
        )
        self.assertJSONResponseContains(
            response, {"asset": {"title": "old", "upload": "old.txt"}}
        )
        response = self.client.post(
            "/mapping-asset-initial-probe/",
            {"asset-title": "old", "asset-upload-clear": "1"},
        )
        self.assertJSONResponseContains(
            response, {"asset": {"title": "old", "upload": False}}
        )
        response = self.client.post(
            "/mapping-asset-initial-probe/",
            {
                "asset-title": "old",
                "asset-upload-clear": "1",
                "asset-upload": SimpleUploadedFile("new.txt", b"new"),
            },
        )
        self.assertJSONResponseContains(
            response, {"errors": {"asset": ["item_invalid"]}}
        )
        self.assertEqual(response.json()["child_errors"], {"asset": ["contradiction"]})
        response = self.client.post(
            "/mapping-file-change-probe/", {"initial-asset-document": "saved.txt"}
        )
        self.assertJSONResponseContains(response, {"changed": False})
        response = self.client.post(
            "/mapping-file-change-probe/",
            {
                "initial-asset-document": "saved.txt",
                "asset-document": SimpleUploadedFile("replacement.txt", b"new"),
            },
        )
        self.assertJSONResponseContains(response, {"changed": True})

    def test_client_gives_a_mapping_child_widget_every_repeated_file(self) -> None:
        """A mapping child widget receives every file for its input.

        Normalized files must keep the ``request.FILES`` shape. A child widget can
        then read every value with ``getlist``.
        """
        response = self.client.post(
            "/mapping-repeated-file-probe/",
            {
                "asset-upload": [
                    SimpleUploadedFile("first.txt", b"first"),
                    SimpleUploadedFile("second.txt", b"second"),
                ]
            },
        )

        self.assertJSONResponse(
            response,
            {"valid": True, "uploads": ["first.txt", "second.txt"], "errors": {}},
        )


class MappingFieldSubmissionChildValidationTestCase(CompositeFieldTestCase):
    """A mapping child's own validation outcome is the same in either input style.

    ``MappingFieldSubmissionFunctionalTestCase`` proves this over HTTP. A whole
    Python value never reaches the request parser, so its counterpart binds
    ``Form(data=...)`` in-process instead of posting to a view.
    """

    def test_item_error_params_carry_the_documented_locator(self) -> None:
        """A child failure keeps its locator in ``params``.

        README.md documents this exact dict as the machine-readable route,
        because ``ErrorDict.as_json()`` keeps only ``message`` and ``code``.
        """

        class Point(forms.Form):
            x = forms.CharField()
            y = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(Point)

        form = Form({"point-x": ""})

        self.assertFormInvalid(form)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(
            error.params,
            {
                "item": "x",
                "message": "This field is required.",
                "child_code": "required",
            },
        )
        # The outer bound field hides it so the subform renders it once.
        self.assertBoundFieldErrors(form, "point", [])
        self.assertFormError(form, "point", ["This field is required."])

    def test_required_mapping_omission_is_required_via_whole_value(self) -> None:
        """A required mapping with no whole value reports 'required'."""
        form = MappingOptionalPointsForm(data={})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "required_point", "required")

    def test_partial_optional_mapping_child_is_item_invalid_via_whole_value(
        self,
    ) -> None:
        """An optional mapping present with a missing required child is item_invalid."""
        form = MappingOptionalPointsForm(
            data={"required_point": {"a": 1}, "optional_point": {"label": "missing a"}}
        )

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "optional_point", "item_invalid")

    def test_child_clean_hooks_and_validator_codes_apply_via_whole_value(
        self,
    ) -> None:
        """Whole-value data still reaches child clean hooks and an outer validator."""
        hook_form = MappingHookForm({"value": {"a": 2}})
        self.assertFormValid(hook_form)
        self.assertEqual(hook_form.cleaned_data["value"], {"a": 3, "double": 6})

        validated_form = ValidatedMappingPointForm({"point": {"a": 2}})
        self.assertFormInvalid(validated_form)
        self.assertFormErrorCode(validated_form, "point", "no_two")

    def test_non_field_child_error_code_survives_via_whole_value(self) -> None:
        """A child non-field error keeps its own code at the mapping boundary."""
        form = MappingNonFieldErrorForm({"value": {"a": 2}})

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "value", "item_invalid")
        self.assertEqual(
            form.errors.as_data()["value"][0].params["child_code"], "unavailable"
        )

    def test_optional_mapping_omission_cleans_to_an_empty_dict_via_whole_value(
        self,
    ) -> None:
        """An omitted optional mapping cleans to {} the same as an HTTP omission."""
        form = OptionalMappingPointForm(data={})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {})


class MappingFieldSubmissionDeveloperInputTestCase(CompositeFieldTestCase):
    """Exercises Python-only nested values and field APIs called without a form."""

    def test_whole_value_children_reach_the_child_field_unchanged(self) -> None:
        """Whole mapping input keeps repeated, JSON, compound, and file values."""

        class TagsForm(forms.Form):
            tags = forms.MultipleChoiceField(
                choices=(("one", "One"), ("two", "Two")), required=False
            )

        class TagsOuter(forms.Form):
            point = nestingdolls.MappingField(TagsForm, required=False)

        # A nested MultiValueDict keeps Django's repeated-value shape.
        nested = MultiValueDict[str, object]()
        nested.setlist("tags", ["one", "two"])
        repeated = TagsOuter({"point": nested})
        self.assertFormValid(repeated)
        self.assertEqual(repeated.cleaned_data["point"], {"tags": ["one", "two"]})

        # A nested list stays one JSON value instead of becoming repeated input.
        class JSONChildForm(forms.Form):
            payload = forms.JSONField()

        class JSONOuter(forms.Form):
            value = nestingdolls.MappingField(JSONChildForm)

        encoded = JSONOuter({"value": {"payload": [1, {"answer": 42}]}})
        self.assertFormValid(encoded)
        self.assertEqual(encoded.cleaned_data["value"]["payload"], [1, {"answer": 42}])

        # A clean() call hands already-extracted compound and file values over.
        class CompoundForm(forms.Form):
            happened_at = forms.SplitDateTimeField()
            upload = forms.FileField()

        upload = SimpleUploadedFile("upload.txt", b"upload")
        cleaned = nestingdolls.MappingField(CompoundForm).clean(
            {"happened_at": ["2026-08-01", "10:30:00"], "upload": upload}
        )
        self.assertEqual(
            cleaned["happened_at"].replace(tzinfo=None).isoformat(),
            "2026-08-01T10:30:00",
        )
        self.assertIs(cleaned["upload"], upload)

    def test_exact_name_and_child_keys_count_as_input(self) -> None:
        """An exact or child key counts as input. A non-string key does not."""
        widget = nestingdolls.MappingField(MappingPointForm).widget

        self.assertIs(
            widget.value_omitted_from_data({"point": "x"}, {}, "point"), False
        )
        self.assertIs(
            widget.value_omitted_from_data({"point-a": "1"}, {}, "point"), False
        )
        self.assertIs(widget.value_omitted_from_data({0: "1"}, {}, "point"), True)

    def test_an_exact_multivaluedict_binds_only_the_keys_it_holds(self) -> None:
        """An exact MultiValueDict binds only the child keys it holds."""

        class PairForm(forms.Form):
            first = forms.CharField(required=False)
            second = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(PairForm, required=False)

        nested = MultiValueDict[str, object]()
        nested.setlist("first", ["one", "two"])
        form = Form({"point": nested})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"first": "two", "second": ""})


class MappingFieldSubmissionBindingTestCase(CompositeFieldTestCase):
    """Make sure ``DictField`` cleans each input shape correctly.

    Each test sends one input shape. Each test examines the cleaned mapping or
    the error codes.
    """

    def test_exact_name_empty_string_cleans_empty(self) -> None:
        """A lone empty ``point`` key cleans as an empty mapping."""
        form = OptionalMappingPointForm(QueryDict("point="))
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {})

    def test_accepts_declared_prefixed_children_only(self) -> None:
        """Dot, bracket, and undeclared keys cannot enter a child form."""
        form = OptionalMappingPointForm(
            {
                "point-a": "1",
                "point-label": "kept",
                "point-undeclared": "ignored",
                "point.a": "ignored",
                "point[a]": "ignored",
            }
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_preserves_getlist_values_for_child_widgets(self) -> None:
        """Canonicalization copies every repeated value through Django's protocol."""

        class RepeatedInput(dict[str, object]):
            def getlist(self, key: str) -> list[object]:
                return self.lists.get(key, [])

            def __init__(self) -> None:
                super().__init__({"point-a": "second"})
                self.lists = {"point-a": ["first", "second"]}

        class CaptureWidget(forms.TextInput):
            values: ClassVar[list[object]] = []

            def value_from_datadict(
                self, data: object, files: object, name: object
            ) -> object:
                type(self).values = data.getlist(name)
                return super().value_from_datadict(data, files, name)

        class CaptureForm(forms.Form):
            a = forms.CharField(widget=CaptureWidget)

        class Form(forms.Form):
            point = nestingdolls.DictField(CaptureForm)

        form = Form(RepeatedInput())
        self.assertFormValid(form)
        self.assertEqual(CaptureWidget.values, ["first", "second"])

    def test_optional_direct_mapping_cleans_every_child(self) -> None:
        """A direct mapping in a dict cleans every child."""
        form = OptionalMappingPointForm({"point": {"a": "3", "label": "whole"}})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_exact_request_mapping_cleans(self) -> None:
        """A request exact mapping still cleans every child."""
        form = OptionalMappingPointForm(
            MultiValueDict({"point": [{"a": "3", "label": "whole"}]})
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_prefixed_data_cleans(self) -> None:
        """A prefixed mapping submission cleans its child."""
        form = RequiredMappingPointForm({"point-a": "1"})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": ""})

    def test_required_direct_mapping_cleans_every_child(self) -> None:
        """A direct mapping cleans every child."""
        form = RequiredMappingPointForm({"point": {"a": "3", "label": "whole"}})
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_direct_mapping_scalar_child_sequence_is_invalid(self) -> None:
        """A direct mapping retains an invalid scalar sequence child."""

        class Child(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        class Form(forms.Form):
            point = nestingdolls.DictField(Child, required=False)

        form = Form({"point": {"values": "3"}})
        self.assertFormInvalid(form)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "invalid")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
