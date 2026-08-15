from __future__ import annotations

import unittest
from types import MappingProxyType
from urllib.parse import urlencode

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import JsonResponse, QueryDict
from django.test import SimpleTestCase, override_settings
from django.test.html import Element, parse_html
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import path
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


class MappingProbeView(View):
    form_class = None
    response_field = None

    def error_codes(self, form):
        return {
            name: [error.code for error in errors]
            for name, errors in form.errors.as_data().items()
        }

    def child_error_codes(self, form):
        return {
            name: [error.params.get("child_code") for error in errors if error.params]
            for name, errors in form.errors.as_data().items()
        }

    def get_form_kwargs(self):
        return {}

    def response_data(self, form, valid):
        response = {"valid": valid}
        if self.response_field is not None:
            response[self.response_field] = (
                form.cleaned_data.get(self.response_field) if valid else None
            )
        response["errors"] = self.error_codes(form)
        return response

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST, request.FILES, **self.get_form_kwargs())
        valid = form.is_valid()
        return JsonResponse(self.response_data(form, valid))


class FormBindingUnitTestCase(SimpleTestCase):
    """Provides a focused home for in-process form and field assertions."""

    def build_querydict_form(self, form_class, pairs, *, initial=None, prefix=None):
        """Bind form_class the way a browser <form> submit does: prefixed keys.

        `pairs` is a dict of prefixed keys (e.g. {"point-a": "1"}) or an
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


class MappingProbeFixtures(SimpleTestCase):
    class PointForm(forms.Form):
        a = forms.IntegerField()
        label = forms.CharField(required=False)


class MappingAssetProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField(required=False)

        asset = nestingdolls.MappingField(ChildForm)


class MappingAssetProbeView(MappingProbeView):
    form_class = MappingAssetProbeFixtures.ProbeForm

    def response_data(self, form, valid):
        asset = form.cleaned_data["asset"] if valid else None
        serialized_asset = None
        if asset is not None:
            upload = asset["upload"]
            if upload is None or upload is False:
                serialized_upload = upload
            elif isinstance(upload, UploadedFile):
                serialized_upload = upload.name
            else:
                serialized_upload = upload
            serialized_asset = {"title": asset["title"], "upload": serialized_upload}
        return {
            "valid": valid,
            "asset": serialized_asset,
            "errors": self.error_codes(form),
        }


class MappingOptionalProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        required_point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)
        optional_point = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, required=False
        )


class MappingOptionalProbeView(MappingProbeView):
    form_class = MappingOptionalProbeFixtures.ProbeForm

    def response_data(self, form, valid):
        return {
            "valid": valid,
            "value": form.cleaned_data if valid else None,
            "errors": self.error_codes(form),
        }


class MappingValidatedProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        @staticmethod
        def reject_two(value):
            if value["a"] == 2:
                raise ValidationError("No two.", code="no_two")

        point = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, required=False, validators=[reject_two]
        )


class MappingPrefixedProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)


class MappingPrefixedProbeView(MappingProbeView):
    form_class = MappingPrefixedProbeFixtures.ProbeForm
    response_field = "point"

    def get_form_kwargs(self):
        return {"prefix": "outer"}


class MappingDisabledProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm,
            disabled=True,
            initial={"a": 8, "label": "initial"},
        )


class MappingInitialProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, required=False
        )


class MappingInitialProbeView(MappingProbeView):
    form_class = MappingInitialProbeFixtures.ProbeForm
    response_field = "point"

    def get_form_kwargs(self):
        return {"initial": {"point": {"a": 8, "label": "saved"}}}


class MappingFileChangeProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            document = forms.FileField(required=False)

        asset = nestingdolls.MappingField(
            ChildForm,
            required=False,
            initial={"document": "saved.txt"},
            show_hidden_initial=True,
        )


class MappingFileChangeProbeView(MappingProbeView):
    form_class = MappingFileChangeProbeFixtures.ProbeForm

    def response_data(self, form, valid):
        asset = form.cleaned_data["asset"] if valid else None
        document = asset.get("document") if asset else None
        if document is None or document is False:
            serialized_document = document
        elif isinstance(document, UploadedFile):
            serialized_document = document.name
        else:
            serialized_document = document
        return {
            "valid": valid,
            "document": serialized_document,
            "errors": self.error_codes(form),
            "changed": form.has_changed(),
        }


class MappingAssetInitialProbeView(MappingProbeView):
    form_class = MappingAssetProbeFixtures.ProbeForm

    def get_form_kwargs(self):
        return {
            "initial": {
                "asset": {
                    "title": "old",
                    "upload": SimpleUploadedFile("old.txt", b"old"),
                }
            }
        }

    def response_data(self, form, valid):
        asset = form.cleaned_data["asset"] if valid else None
        serialized_asset = None
        if asset is not None:
            upload = asset["upload"]
            if upload is None or upload is False:
                serialized_upload = upload
            elif isinstance(upload, UploadedFile):
                serialized_upload = upload.name
            else:
                serialized_upload = upload
            serialized_asset = {"title": asset["title"], "upload": serialized_upload}
        return {
            "valid": valid,
            "asset": serialized_asset,
            "errors": self.error_codes(form),
            "child_errors": self.child_error_codes(form),
        }


class MultipleFileInput(forms.ClearableFileInput):
    """Read all files for one child input.

    ``FileInput`` uses ``getlist`` when available. Normalized mapping files must
    keep the ``request.FILES`` shape so a child receives every file.
    """

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Clean each file of a child that accepts more than one file."""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class MappingRepeatedFileProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            upload = MultipleFileField(required=False)

        asset = nestingdolls.MappingField(ChildForm, required=False)


class MappingRepeatedFileProbeView(MappingProbeView):
    form_class = MappingRepeatedFileProbeFixtures.ProbeForm

    def response_data(self, form, valid):
        asset = form.cleaned_data["asset"] if valid else None
        uploads = asset.get("upload") if asset else []
        return {
            "valid": valid,
            "uploads": [upload.name for upload in uploads],
            "errors": self.error_codes(form),
        }


class MappingHookProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean_a(self):
                return self.cleaned_data["a"] + 1

            def clean(self):
                cleaned_data = super().clean()
                cleaned_data["double"] = cleaned_data["a"] * 2
                return cleaned_data

        value = nestingdolls.MappingField(ChildForm)


class MappingNonFieldProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self):
                cleaned_data = super().clean()
                if cleaned_data.get("a") == 2:
                    raise ValidationError("Two is unavailable.", code="unavailable")
                return cleaned_data

        value = nestingdolls.MappingField(ChildForm)


class MappingNonFieldProbeView(MappingProbeView):
    form_class = MappingNonFieldProbeFixtures.ProbeForm

    def response_data(self, form, valid):
        return {
            "valid": valid,
            "errors": self.error_codes(form),
            "child_errors": self.child_error_codes(form),
        }


urlpatterns = [
    path(
        "mapping-hook-probe/",
        MappingProbeView.as_view(
            form_class=MappingHookProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path("mapping-nonfield-probe/", MappingNonFieldProbeView.as_view()),
    path("mapping-asset-probe/", MappingAssetProbeView.as_view()),
    path("mapping-asset-initial-probe/", MappingAssetInitialProbeView.as_view()),
    path("mapping-optional-probe/", MappingOptionalProbeView.as_view()),
    path(
        "mapping-validated-probe/",
        MappingProbeView.as_view(
            form_class=MappingValidatedProbeFixtures.ProbeForm, response_field="point"
        ),
    ),
    path("mapping-prefixed-probe/", MappingPrefixedProbeView.as_view()),
    path(
        "mapping-disabled-probe/",
        MappingProbeView.as_view(
            form_class=MappingDisabledProbeFixtures.ProbeForm, response_field="point"
        ),
    ),
    path("mapping-initial-probe/", MappingInitialProbeView.as_view()),
    path("mapping-file-change-probe/", MappingFileChangeProbeView.as_view()),
    path("mapping-repeated-file-probe/", MappingRepeatedFileProbeView.as_view()),
]


@override_settings(ROOT_URLCONF=__name__)
class MappingSubmissionFunctionalTestCase(SimpleTestCase):
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


class MappingChildValidationTestCase(FormBindingUnitTestCase):
    """A mapping child's own validation outcome is the same in either input style.

    ``MappingSubmissionFunctionalTestCase`` proves this over HTTP. A whole
    Python value never reaches the request parser, so its counterpart binds
    ``Form(data=...)`` in-process instead of posting to a view.
    """

    def test_required_mapping_omission_is_required_via_whole_value(self):
        """A required mapping with no whole value reports 'required'."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(PointForm)
            optional_point = nestingdolls.MappingField(PointForm, required=False)

        form = Form(data={})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["required_point"][0].code, "required")

    def test_partial_optional_mapping_child_is_item_invalid_via_whole_value(self):
        """An optional mapping present with a missing required child is item_invalid."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(PointForm)
            optional_point = nestingdolls.MappingField(PointForm, required=False)

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

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class ValidatedForm(forms.Form):
            point = nestingdolls.MappingField(
                PointForm, required=False, validators=[reject_two]
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

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        form = Form(data={})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {})


class MappingFieldUnitTestCase(FormBindingUnitTestCase):
    """Exercises mapping APIs, construction, and rendering that HTTP cannot expose."""

    def test_uploaded_file_named_after_the_field_keeps_the_child_input(self):
        """A file named after the field cannot replace its mapped child inputs."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)

        form = Form(
            data=QueryDict("point-a=1&point-label=kept"),
            files=MultiValueDict(
                {"point": [SimpleUploadedFile("forged.txt", b"forged")]}
            ),
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_invalid_mapping_shapes_stay_in_djangos_bound_data_path(self):
        """It redisplays hostile submitted data and disabled hostile initials."""
        enabled = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, required=False
        )
        disabled = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, required=False, disabled=True
        )

        submitted = ["hostile"]
        initial = ["initial"]
        self.assertIs(enabled.bound_data(submitted, initial), submitted)
        self.assertIs(disabled.bound_data(submitted, initial), initial)

    def test_to_python_only_checks_the_container_shape(self):
        """Shape conversion does not run child Form cleaning hooks."""
        cleaned = False

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self):
                nonlocal cleaned
                cleaned = True
                return super().clean()

        field = nestingdolls.MappingField(ChildForm)

        self.assertEqual(field.to_python({"a": "2"}), {"a": "2"})
        self.assertIs(cleaned, False)
        self.assertEqual(field.clean({"a": "2"}), {"a": 2})
        self.assertIs(cleaned, True)

    def test_output_builds_another_mapping_type(self):
        class ChildForm(forms.Form):
            value = forms.IntegerField()

        cleaned = nestingdolls.MappingField(ChildForm, output=MappingProxyType).clean(
            {"value": "2"}
        )

        self.assertIsInstance(cleaned, MappingProxyType)
        self.assertEqual(cleaned, {"value": 2})

    def test_dynamic_child_fields_use_instantiated_form_fields(self):
        """Rendering and cleaning use fields added by the child Form instance."""

        class DynamicForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["number"] = forms.IntegerField()
                self.fields["upload"] = forms.FileField(required=False)
                self.fields["nested"] = nestingdolls.MappingField(
                    MappingProbeFixtures.PointForm
                )

        class Form(forms.Form):
            point = nestingdolls.MappingField(DynamicForm)

        unbound = Form(
            initial={
                "point": {
                    "number": 3,
                    "nested": {"a": 4, "label": "inside"},
                }
            }
        )
        html = unbound.as_div()
        self.assertIn('type="number" name="point-number"', html)
        self.assertIn('type="file" name="point-upload"', html)
        self.assertIn('name="point-nested-a"', html)
        self.assertIs(unbound["point"].field.widget.is_hidden, False)
        self.assertIs(unbound["point"].field.widget.needs_multipart_form, True)

        upload = SimpleUploadedFile("dynamic.txt", b"dynamic")
        bound = Form(
            data={
                "point": {
                    "number": "5",
                    "nested": {"a": "6", "label": "submitted"},
                }
            },
            files={"point": {"upload": upload}},
        )
        self.assertIs(bound.is_valid(), True, bound.errors)
        self.assertEqual(
            bound.cleaned_data["point"],
            {
                "number": 5,
                "upload": upload,
                "nested": {"a": 6, "label": "submitted"},
            },
        )

    def test_rejects_non_mapping_input(self):
        """It rejects an exact scalar value."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)

        form = Form({"point": "not a mapping"})

        self.assertIs(form.is_valid(), False)
        self.assertIsInstance(
            form.errors.as_data()["point"][0],
            nestingdolls.MappingInputValidationError,
        )
        self.assertEqual(form.errors.as_data()["point"][0].code, "invalid")

    def test_as_hidden_uses_child_hidden_widgets(self):
        """A hidden mapping renders every child through its hidden widget."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)

        form = Form(initial={"point": {"a": 8, "label": "saved"}})

        html = form["point"].as_hidden()

        self.assertIn('type="hidden" name="point-a" value="8"', html)
        self.assertIn('type="hidden" name="point-label" value="saved"', html)
        self.assertNotIn('type="number"', html)
        self.assertNotIn('type="text"', html)

    def test_show_hidden_initial_uses_child_hidden_widgets(self):
        """Django can compare hidden mapping initial values by child name."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, show_hidden_initial=True
            )

        initial = {"point": {"a": 8, "label": "saved"}}
        unbound = Form(initial=initial)
        html = unbound.as_div()
        self.assertIn('type="hidden" name="initial-point-a" value="8"', html)
        self.assertIn('type="hidden" name="initial-point-label" value="saved"', html)

        bound = Form(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "8",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertIs(bound.is_valid(), True, bound.errors)
        self.assertIs(bound.has_changed(), False)

        malformed_initial = Form(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "not-an-integer",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertIs(malformed_initial.has_changed(), True)

    def test_rejects_wrong_form_widget_and_bound_field_types(self):
        """Constructor extension points require compatible Django types."""

        class NeedsArgForm(forms.Form):
            def __init__(self, token, *args, **kwargs):
                super().__init__(*args, **kwargs)

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(forms.IntegerField)  # type: ignore[arg-type]
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(NeedsArgForm)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, widget=forms.TextInput
            )
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, bound_field_class=forms.BoundField
            )

    def test_widget_extensions_are_copied_and_rebound_to_the_child_form(self):
        """Django copies widget instances and the field supplies its Form class."""

        class CustomWidget(nestingdolls.MappingWidget):
            pass

        widget = CustomWidget()
        instance_field = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, widget=widget
        )
        class_field = nestingdolls.MappingField(
            MappingProbeFixtures.PointForm, widget=CustomWidget
        )

        self.assertIsNot(instance_field.widget, widget)
        self.assertIs(instance_field.widget.form_class, MappingProbeFixtures.PointForm)
        self.assertIsInstance(class_field.widget, CustomWidget)
        self.assertIs(class_field.widget.form_class, MappingProbeFixtures.PointForm)


class DictFieldRenderingTestCase(SimpleTestCase):
    def assertChildErrorReferencesResolve(self, renderer):
        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                "point-label": "missing a",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
                "values-0": "bad",
            }
        )
        self.assertIs(form.is_valid(), False)

        # The outer field owns no error; the subform renders it exactly once.
        self.assertEqual(list(form["point"].errors), [])
        rendered = str(form["point"])
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertIn('aria-invalid="true"', rendered)

        paragraphs = form.as_p()
        self.assertIn('aria-describedby="id_point-a_error"', paragraphs)
        self.assertInHTML(
            '<span class="errorlist" id="id_point-a_error">'
            "This field is required."
            "</span>",
            paragraphs,
        )

        elements = [parse_html(getattr(form, renderer)())]
        for element in elements:
            elements.extend(
                child for child in element.children if isinstance(child, Element)
            )

        element_attributes = [dict(element.attributes) for element in elements]
        ids = [
            attributes["id"] for attributes in element_attributes if "id" in attributes
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("id_point-a_error", ids)
        self.assertIn("id_values_0_error", ids)
        for attributes in element_attributes:
            for reference in attributes.get("aria-describedby", "").split():
                self.assertIn(reference, ids)

    def test_div_layout_resolves_child_error_references(self):
        """The div layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_div")

    def test_p_layout_resolves_child_error_references(self):
        """The paragraph layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_p")

    def test_ul_layout_resolves_child_error_references(self):
        """The list layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_ul")

    def test_table_layout_resolves_child_error_references(self):
        """The table layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_table")

    def assertMappingChildFormAndWrapperRender(self, renderer):
        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, show_hidden_initial=True
            )

        form = Form(initial={"point": {"a": 9, "label": "layout"}})
        html = getattr(form, renderer)()
        self.assertIn('data-widget="mapping"', html)
        self.assertIn('data-mapping-field="point"', html)
        self.assertIn('id="id_point_widget"', html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="point-label"', html)
        self.assertEqual(html.count('name="initial-point-a"'), 1)
        self.assertInHTML(
            '<input type="number" name="point-a" value="9" required id="id_point-a">',
            html,
        )

    def test_div_layout_renders_mapping_child_form_and_wrapper(self):
        """The div layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_div")

    def test_p_layout_renders_mapping_child_form_and_wrapper(self):
        """The paragraph layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_p")

    def test_ul_layout_renders_mapping_child_form_and_wrapper(self):
        """The list layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_ul")

    def test_table_layout_renders_mapping_child_form_and_wrapper(self):
        """The table layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_table")

    def test_widget_exposes_child_media_and_multipart_requirement(self):
        """The outer widget reports child widget integration requirements."""

        class MediaWidget(forms.TextInput):
            class Media:
                js = ("child.js",)

        class ChildForm(forms.Form):
            title = forms.CharField(widget=MediaWidget)
            upload = forms.FileField(required=False)

        field = nestingdolls.MappingField(ChildForm)

        self.assertIs(field.widget.needs_multipart_form, True)
        self.assertIn("child.js", str(field.widget.media))


class MappingDeveloperInputUnitTestCase(FormBindingUnitTestCase):
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


class MappingNestedSequenceChildTestCase(FormBindingUnitTestCase):
    """A mapping's nested sequence child validates the same in either input style.

    Same regression guard as ``test_listfield.py``'s
    ``SequenceScalarRowTestCase``, for a sequence nested one level inside
    a mapping: the nested list's own row error must still render inline
    when the mapping binds to one whole Python value.
    """

    def assertNestedSequenceChildError(self, form):
        """Assert row 1 of the nested int list shows its own inline error."""
        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertIn('name="point-tags-1" value="bad"', html)
        self.assertIn('aria-describedby="id_point-tags_1_error"', html)
        self.assertInHTML("<li>Enter a whole number.</li>", html)

    def assertNestedSequenceChildValid(self, form):
        """Assert a valid nested int list cleans and renders every row."""
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"tags": [1, 2, 3]})
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        for index, value in enumerate((1, 2, 3)):
            self.assertIn(f'name="point-tags-{index}" value="{value}"', html)

    def test_nested_sequence_child_error_via_whole_value(self):
        """A bad row in a mapping's whole-value nested list shows its own error."""

        class ChildForm(forms.Form):
            tags = nestingdolls.ListField(forms.IntegerField())

        class Form(forms.Form):
            point = nestingdolls.DictField(ChildForm)

        self.assertNestedSequenceChildError(
            self.build_whole_value_form(Form, "point", {"tags": [1, "bad", 3]})
        )

    def test_nested_sequence_child_error_via_querydict(self):
        """A bad row in a mapping's prefixed-row nested list shows its own error."""

        class ChildForm(forms.Form):
            tags = nestingdolls.ListField(forms.IntegerField())

        class Form(forms.Form):
            point = nestingdolls.DictField(ChildForm)

        self.assertNestedSequenceChildError(
            self.build_querydict_form(
                Form,
                {
                    f"point-tags-{TOTAL_FORM_COUNT}": "3",
                    f"point-tags-{INITIAL_FORM_COUNT}": "3",
                    "point-tags-0": "1",
                    "point-tags-1": "bad",
                    "point-tags-2": "3",
                },
            )
        )

    def test_nested_sequence_child_valid_via_whole_value(self):
        """A valid whole-value nested list renders every row with no error markup."""

        class ChildForm(forms.Form):
            tags = nestingdolls.ListField(forms.IntegerField())

        class Form(forms.Form):
            point = nestingdolls.DictField(ChildForm)

        self.assertNestedSequenceChildValid(
            self.build_whole_value_form(Form, "point", {"tags": [1, 2, 3]})
        )

    def test_nested_sequence_child_valid_via_querydict(self):
        """A valid prefixed-row nested list renders every row with no error markup."""

        class ChildForm(forms.Form):
            tags = nestingdolls.ListField(forms.IntegerField())

        class Form(forms.Form):
            point = nestingdolls.DictField(ChildForm)

        self.assertNestedSequenceChildValid(
            self.build_querydict_form(
                Form,
                {
                    f"point-tags-{TOTAL_FORM_COUNT}": "3",
                    f"point-tags-{INITIAL_FORM_COUNT}": "3",
                    "point-tags-0": "1",
                    "point-tags-1": "2",
                    "point-tags-2": "3",
                },
            )
        )


class MappingSequenceOfRecordsTestCase(FormBindingUnitTestCase):
    """A CSV- or JSON-shaped list of row mappings validates the same in either style.

    ``records`` stands in for one decoded JSON array of objects, or one CSV
    file's rows: a list of mappings nested inside a mapping field, three
    nesting levels deep - ``DictField`` around ``ListField`` around
    ``DictField``.
    """

    def assertRecordsLeafError(self, form):
        """Assert row 1's blank required ``name`` shows its own inline error."""
        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertIn('name="payload-records-0-name" value="ok"', html)
        self.assertIn('aria-describedby="id_payload-records-1-name_error"', html)
        self.assertInHTML("<li>This field is required.</li>", html)

    def assertRecordsAllValid(self, form):
        """Assert both valid records clean and render correctly."""
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(
            form.cleaned_data["payload"],
            {"records": [{"name": "ok"}, {"name": "ok2"}]},
        )
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        self.assertIn('name="payload-records-0-name" value="ok"', html)
        self.assertIn('name="payload-records-1-name" value="ok2"', html)

    def test_records_leaf_error_via_whole_value(self):
        """A CSV- or JSON-shaped list of row mappings shows a bad leaf inline."""

        class RowForm(forms.Form):
            name = forms.CharField()

        class PayloadForm(forms.Form):
            records = nestingdolls.ListField(nestingdolls.DictField(RowForm))

        class Form(forms.Form):
            payload = nestingdolls.DictField(PayloadForm)

        self.assertRecordsLeafError(
            self.build_whole_value_form(
                Form, "payload", {"records": [{"name": "ok"}, {"name": ""}]}
            )
        )

    def test_records_leaf_error_via_querydict(self):
        """A CSV- or JSON-shaped list of row mappings shows a bad leaf inline, prefixed-row style."""

        class RowForm(forms.Form):
            name = forms.CharField()

        class PayloadForm(forms.Form):
            records = nestingdolls.ListField(nestingdolls.DictField(RowForm))

        class Form(forms.Form):
            payload = nestingdolls.DictField(PayloadForm)

        self.assertRecordsLeafError(
            self.build_querydict_form(
                Form,
                {
                    f"payload-records-{TOTAL_FORM_COUNT}": "2",
                    f"payload-records-{INITIAL_FORM_COUNT}": "2",
                    "payload-records-0-name": "ok",
                    "payload-records-1-name": "",
                },
            )
        )

    def test_records_all_valid_via_whole_value(self):
        """A valid CSV- or JSON-shaped record list cleans and renders every row."""

        class RowForm(forms.Form):
            name = forms.CharField()

        class PayloadForm(forms.Form):
            records = nestingdolls.ListField(nestingdolls.DictField(RowForm))

        class Form(forms.Form):
            payload = nestingdolls.DictField(PayloadForm)

        self.assertRecordsAllValid(
            self.build_whole_value_form(
                Form, "payload", {"records": [{"name": "ok"}, {"name": "ok2"}]}
            )
        )

    def test_records_all_valid_via_querydict(self):
        """A valid prefixed-row CSV- or JSON-shaped record list cleans and renders every row."""

        class RowForm(forms.Form):
            name = forms.CharField()

        class PayloadForm(forms.Form):
            records = nestingdolls.ListField(nestingdolls.DictField(RowForm))

        class Form(forms.Form):
            payload = nestingdolls.DictField(PayloadForm)

        self.assertRecordsAllValid(
            self.build_querydict_form(
                Form,
                {
                    f"payload-records-{TOTAL_FORM_COUNT}": "2",
                    f"payload-records-{INITIAL_FORM_COUNT}": "2",
                    "payload-records-0-name": "ok",
                    "payload-records-1-name": "ok2",
                },
            )
        )


class DictFieldRegressionTestCase(SimpleTestCase):
    def assertPointValueRenders(self, form):
        self.assertEqual(form["point"].value(), ["bad"])
        str(form["point"])

    def test_list_initial_stays_renderable(self):
        """A list initial for a mapping field stays renderable."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False
            )

        self.assertPointValueRenders(Form(initial={"point": ["bad"]}))

    def test_callable_list_initial_stays_renderable(self):
        """A callable list initial for a mapping field stays renderable."""

        class CallableInitialForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False, initial=lambda: ["bad"]
            )

        self.assertPointValueRenders(CallableInitialForm())

    def test_disabled_and_scalar_file_hostile_values_stay_renderable_errors(self):
        """Disabled and scalar file hostile values stay Django form errors."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False
            )

        class DisabledForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False, disabled=True
            )

        disabled = DisabledForm({}, initial={"point": ["bad"]})
        self.assertIs(disabled.is_valid(), False)
        self.assertEqual(disabled.errors.as_data()["point"][0].code, "invalid")
        str(disabled["point"])

        # A hostile scalar in `files` is a form error, never a render crash.
        scalar_file = Form(data={}, files={"point": False})
        self.assertIs(scalar_file.is_valid(), False)
        self.assertEqual(scalar_file.errors.as_data()["point"][0].code, "invalid")
        self.assertIs(scalar_file["point"].value(), False)
        str(scalar_file["point"])

    def assertHostileHiddenInitialPayloadRendersError(self, data):
        class NestedForm(forms.Form):
            rows = nestingdolls.ListField(
                nestingdolls.MappingField(MappingProbeFixtures.PointForm),
                required=False,
            )

        class HiddenInitialForm(forms.Form):
            payload = nestingdolls.MappingField(
                NestedForm, required=False, show_hidden_initial=True
            )

        hidden = HiddenInitialForm(
            data,
            initial={"payload": {"rows": [{"a": 1, "label": "saved"}]}},
        )
        self.assertIs(hidden.is_valid(), False)
        self.assertIn("Enter a mapping of values.", hidden.as_p())

    def test_scalar_hidden_initial_payload_stays_a_renderable_error(self):
        """A scalar hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError({"payload": "hostile"})

    def test_nested_list_hidden_initial_payload_stays_a_renderable_error(self):
        """A nested list hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError(
            {"payload": {"rows": ["hostile"]}}
        )

    def test_bound_data_rejection_returns_the_mapping_initial_value(self):
        """A child bound data rejection returns the mapping initial value."""

        class RejectingField(forms.CharField):
            def bound_data(self, data, initial):
                raise ValidationError("Cannot bind this value.")

        class ChildForm(forms.Form):
            value = RejectingField()

        field = nestingdolls.MappingField(ChildForm)
        value = {"value": "hostile"}
        self.assertEqual(field.bound_data(value, {}), value)

    def test_prepare_value_rejection_returns_the_mapping_initial_value(self):
        """A child prepare value rejection returns the mapping initial value."""

        class RejectingField(forms.CharField):
            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class ChildForm(forms.Form):
            value = RejectingField()

        field = nestingdolls.MappingField(ChildForm)
        value = {"value": "hostile"}
        self.assertEqual(field.prepare_value(value), value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
