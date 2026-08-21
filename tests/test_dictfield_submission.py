"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from typing import ClassVar

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    MappingFormBindingUnitTestCase,
    MappingProbeFixtures,
    MappingValueForm,
    MultiValueDict,
    OptionalMappingValueForm,
    QueryDict,
    SimpleTestCase,
    SimpleUploadedFile,
    ValidationError,
    forms,
    nestingdolls,
    override_settings,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support")
class MappingSubmissionFunctionalTestCase(SimpleTestCase):
    """Tests the ``MappingField`` contract through posted HTTP submissions.

    The tests cover omissions, child errors, prefixes, disabled state, and file
    transport."""

    def test_client_reports_mapping_omissions_and_partial_child_errors(self):
        """Client reports required mapping omissions and partial child failures."""
        response = self.client.post("/mapping-optional-probe/", {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": False, "value": None, "errors": {"required_point": ["required"]}},
        )
        response = self.client.post(
            "/mapping-optional-probe/",
            {"required_point-a": "1", "optional_point-label": "missing a"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "valid": False,
                "value": None,
                "errors": {"optional_point": ["item_invalid"]},
            },
        )

    def test_client_returns_child_cleaning_and_validator_error_codes(self):
        """Client exposes cleaned child values and outer validator codes."""
        response = self.client.post("/mapping-hook-probe/", {"value-a": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": True, "value": {"a": 3, "double": 6}, "errors": {}},
        )
        response = self.client.post("/mapping-validated-probe/", {"point-a": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": False, "point": None, "errors": {"point": ["no_two"]}},
        )

    def test_client_preserves_non_field_child_error_codes(self):
        """Client keeps a child non-field error code at the mapping boundary."""
        response = self.client.post("/mapping-nonfield-probe/", {"value-a": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "valid": False,
                "errors": {"value": ["item_invalid"]},
                "child_errors": {"value": ["unavailable"]},
            },
        )

    def test_client_applies_prefix_disabled_and_initial_omission_behavior(self):
        """Client binds prefixed controls, ignores disabled values, and clears omitted optional mappings."""
        response = self.client.post("/mapping-prefixed-probe/", {"outer-point-a": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": True, "point": {"a": 5, "label": ""}, "errors": {}},
        )
        response = self.client.post("/mapping-disabled-probe/", {"point-a": "99"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": True, "point": {"a": 8, "label": "initial"}, "errors": {}},
        )
        response = self.client.post("/mapping-initial-probe/", {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"valid": True, "point": {}, "errors": {}})

    def test_client_transports_mapping_upload_clear_and_file_changes(self):
        """Client transports mapping uploads, clear conflicts, retained initials, and file changes."""
        response = self.client.post(
            "/mapping-asset-probe/",
            {
                "asset-title": "report",
                "asset-upload": SimpleUploadedFile("report.txt", b"data"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "valid": True,
                "asset": {"title": "report", "upload": "report.txt"},
                "errors": {},
            },
        )
        response = self.client.post(
            "/mapping-asset-initial-probe/", {"asset-title": "old"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["asset"], {"title": "old", "upload": "old.txt"}
        )
        response = self.client.post(
            "/mapping-asset-initial-probe/",
            {"asset-title": "old", "asset-upload-clear": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["asset"], {"title": "old", "upload": False})
        response = self.client.post(
            "/mapping-asset-initial-probe/",
            {
                "asset-title": "old",
                "asset-upload-clear": "1",
                "asset-upload": SimpleUploadedFile("new.txt", b"new"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["errors"], {"asset": ["item_invalid"]})
        self.assertEqual(response.json()["child_errors"], {"asset": ["contradiction"]})
        response = self.client.post(
            "/mapping-file-change-probe/", {"initial-asset-document": "saved.txt"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changed"], False)
        response = self.client.post(
            "/mapping-file-change-probe/",
            {
                "initial-asset-document": "saved.txt",
                "asset-document": SimpleUploadedFile("replacement.txt", b"new"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changed"], True)

    def test_client_gives_a_mapping_child_widget_every_repeated_file(self):
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"valid": True, "uploads": ["first.txt", "second.txt"], "errors": {}},
        )


class MappingChildValidationTestCase(MappingFormBindingUnitTestCase):
    """A mapping child's own validation outcome is the same in either input style.

    ``MappingSubmissionFunctionalTestCase`` proves this over HTTP. A whole
    Python value never reaches the request parser, so its counterpart binds
    ``Form(data=...)`` in-process instead of posting to a view.
    """

    def test_item_error_params_carry_the_documented_locator(self):
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

        self.assertIs(form.is_valid(), False)
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
        self.assertEqual(list(form["point"].errors), [])
        self.assertEqual(list(form.errors["point"]), ["This field is required."])

    def test_required_mapping_omission_is_required_via_whole_value(self):
        """A required mapping with no whole value reports 'required'."""

        class MappingPointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(MappingPointForm)
            optional_point = nestingdolls.MappingField(MappingPointForm, required=False)

        form = Form(data={})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["required_point"][0].code, "required")

    def test_partial_optional_mapping_child_is_item_invalid_via_whole_value(self):
        """An optional mapping present with a missing required child is item_invalid."""

        class MappingPointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(MappingPointForm)
            optional_point = nestingdolls.MappingField(MappingPointForm, required=False)

        form = Form(
            data={"required_point": {"a": 1}, "optional_point": {"label": "missing a"}}
        )

        self.assertIs(form.is_valid(), False)
        self.assertEqual(
            form.errors.as_data()["optional_point"][0].code, "item_invalid"
        )

    def test_child_clean_hooks_and_validator_codes_apply_via_whole_value(self):
        """Whole-value data still reaches child clean hooks and an outer validator."""

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean_a(self):
                return self.cleaned_data["a"] + 1

            def clean(self):
                cleaned_data = super().clean()
                cleaned_data["double"] = cleaned_data["a"] * 2
                return cleaned_data

        class HookForm(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        hook_form = self.build_whole_value_form(HookForm, "value", {"a": 2})
        self.assertIs(hook_form.is_valid(), True, hook_form.errors)
        self.assertEqual(hook_form.cleaned_data["value"], {"a": 3, "double": 6})

        def reject_two(value):
            if value["a"] == 2:
                raise ValidationError("No two.", code="no_two")

        class MappingPointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class ValidatedForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingPointForm, required=False, validators=[reject_two]
            )

        validated_form = self.build_whole_value_form(ValidatedForm, "point", {"a": 2})
        self.assertIs(validated_form.is_valid(), False)
        self.assertEqual(validated_form.errors.as_data()["point"][0].code, "no_two")

    def test_non_field_child_error_code_survives_via_whole_value(self):
        """A child non-field error keeps its own code at the mapping boundary."""

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self):
                cleaned_data = super().clean()
                if cleaned_data.get("a") == 2:
                    raise ValidationError("Two is unavailable.", code="unavailable")
                return cleaned_data

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = self.build_whole_value_form(Form, "value", {"a": 2})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["value"][0].code, "item_invalid")
        self.assertEqual(
            form.errors.as_data()["value"][0].params["child_code"], "unavailable"
        )

    def test_optional_mapping_omission_cleans_to_an_empty_dict_via_whole_value(self):
        """An omitted optional mapping cleans to {} the same as an HTTP omission."""

        class MappingPointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingPointForm, required=False)

        form = Form(data={})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {})


class MappingDeveloperInputUnitTestCase(MappingFormBindingUnitTestCase):
    """Exercises Python-only nested values and field APIs called without a form."""

    def test_whole_value_children_reach_the_child_field_unchanged(self):
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
        self.assertIs(repeated.is_valid(), True, repeated.errors)
        self.assertEqual(repeated.cleaned_data["point"], {"tags": ["one", "two"]})

        # A nested list stays one JSON value instead of becoming repeated input.
        class JSONChildForm(forms.Form):
            payload = forms.JSONField()

        class JSONOuter(forms.Form):
            value = nestingdolls.MappingField(JSONChildForm)

        encoded = JSONOuter({"value": {"payload": [1, {"answer": 42}]}})
        self.assertIs(encoded.is_valid(), True, encoded.errors)
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

    def test_exact_name_and_child_keys_count_as_input(self):
        """An exact or child key counts as input. A non-string key does not."""
        widget = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm).widget

        self.assertIs(
            widget.value_omitted_from_data({"point": "x"}, {}, "point"), False
        )
        self.assertIs(
            widget.value_omitted_from_data({"point-a": "1"}, {}, "point"), False
        )
        self.assertIs(widget.value_omitted_from_data({0: "1"}, {}, "point"), True)

    def test_an_exact_multivaluedict_binds_only_the_keys_it_holds(self):
        """An exact MultiValueDict binds only the child keys it holds."""

        class PairForm(forms.Form):
            first = forms.CharField(required=False)
            second = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(PairForm, required=False)

        nested = MultiValueDict[str, object]()
        nested.setlist("first", ["one", "two"])
        form = Form({"point": nested})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"first": "two", "second": ""})


class DictFieldCleaningTestCase(SimpleTestCase):
    """Make sure ``DictField`` cleans each input shape correctly.

    Each test sends one input shape. Each test examines the cleaned mapping or
    the error codes."""

    def test_exact_name_empty_string_cleans_empty(self):
        """A lone empty ``point`` key cleans as an empty mapping."""
        form = OptionalMappingValueForm(QueryDict("point="))
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {})

    def test_accepts_declared_prefixed_children_only(self):
        """Dot, bracket, and undeclared keys cannot enter a child form."""
        form = OptionalMappingValueForm(
            {
                "point-a": "1",
                "point-label": "kept",
                "point-undeclared": "ignored",
                "point.a": "ignored",
                "point[a]": "ignored",
            }
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_preserves_getlist_values_for_child_widgets(self):
        """Canonicalization copies every repeated value through Django's protocol."""

        class RepeatedInput(dict[str, object]):
            def getlist(self, key: str) -> list[object]:
                return self.lists.get(key, [])

            def __init__(self) -> None:
                super().__init__({"point-a": "second"})
                self.lists = {"point-a": ["first", "second"]}

        class CaptureWidget(forms.TextInput):
            values: ClassVar[list[object]] = []

            def value_from_datadict(self, data, files, name):
                type(self).values = data.getlist(name)
                return super().value_from_datadict(data, files, name)

        class CaptureForm(forms.Form):
            a = forms.CharField(widget=CaptureWidget)

        class Form(forms.Form):
            point = nestingdolls.DictField(CaptureForm)

        form = Form(RepeatedInput())
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(CaptureWidget.values, ["first", "second"])

    def test_optional_direct_mapping_cleans_every_child(self):
        """A direct mapping in a dict cleans every child."""
        form = OptionalMappingValueForm({"point": {"a": "3", "label": "whole"}})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_exact_request_mapping_cleans(self):
        """A request exact mapping still cleans every child."""
        form = OptionalMappingValueForm(
            MultiValueDict({"point": [{"a": "3", "label": "whole"}]})
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_prefixed_data_cleans(self):
        """A prefixed mapping submission cleans its child."""
        form = MappingValueForm({"point-a": "1"})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": ""})

    def test_required_direct_mapping_cleans_every_child(self):
        """A direct mapping cleans every child."""
        form = MappingValueForm({"point": {"a": "3", "label": "whole"}})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_direct_mapping_scalar_child_sequence_is_invalid(self):
        """A direct mapping retains an invalid scalar sequence child."""

        class Child(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        class Form(forms.Form):
            point = nestingdolls.DictField(Child, required=False)

        form = Form({"point": {"values": "3"}})
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "invalid")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
