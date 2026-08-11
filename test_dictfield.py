from __future__ import annotations

import unittest

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
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
    """Provides a focused home for direct form and field assertions."""


class MappingProbeFixtures(SimpleTestCase):
    class PointForm(forms.Form):
        a = forms.IntegerField()
        label = forms.CharField(required=False)


class MappingSubmissionProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)


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


class NestedMappingProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)

        rows = nestingdolls.ListField(nestingdolls.MappingField(ChildForm))


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


class NestedAssetProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField(required=False)
            happened_at = forms.SplitDateTimeField()

        assets = nestingdolls.ListField(nestingdolls.MappingField(ChildForm))


class NestedAssetProbeView(MappingProbeView):
    form_class = NestedAssetProbeFixtures.ProbeForm

    def get_form_kwargs(self):
        return {
            "initial": {"assets": [{"upload": SimpleUploadedFile("old.txt", b"old")}]}
        }

    def response_data(self, form, valid):
        assets = form.cleaned_data["assets"] if valid else None
        serialized_assets = None
        if assets is not None:
            serialized_assets = []
            for asset in assets:
                upload = asset["upload"]
                if upload is None or upload is False:
                    serialized_upload = upload
                elif isinstance(upload, UploadedFile):
                    serialized_upload = upload.name
                else:
                    serialized_upload = upload
                serialized_assets.append(
                    {
                        "title": asset["title"],
                        "upload": serialized_upload,
                        "happened_at": asset["happened_at"]
                        .replace(tzinfo=None)
                        .isoformat(),
                    }
                )
        return {
            "valid": valid,
            "assets": serialized_assets,
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


class TripleMMMProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class OuterChildForm(forms.Form):
            class InnerForm(forms.Form):
                class LeafForm(forms.Form):
                    child = forms.IntegerField()

                child = nestingdolls.MappingField(LeafForm)

            child = nestingdolls.MappingField(InnerForm)

        value = nestingdolls.MappingField(OuterChildForm)


class TripleMMLProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class OuterChildForm(forms.Form):
            class InnerForm(forms.Form):
                child = nestingdolls.ListField(forms.IntegerField())

            child = nestingdolls.MappingField(InnerForm)

        value = nestingdolls.MappingField(OuterChildForm)


class TripleMLMProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class InnerForm(forms.Form):
            class LeafForm(forms.Form):
                child = forms.IntegerField()

            child = nestingdolls.ListField(nestingdolls.MappingField(LeafForm))

        value = nestingdolls.MappingField(InnerForm)


class TripleMLLProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class InnerForm(forms.Form):
            child = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

        value = nestingdolls.MappingField(InnerForm)


class TripleLMMProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class InnerForm(forms.Form):
            class LeafForm(forms.Form):
                child = forms.IntegerField()

            child = nestingdolls.MappingField(LeafForm)

        value = nestingdolls.ListField(nestingdolls.MappingField(InnerForm))


class TripleLMLProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class InnerForm(forms.Form):
            child = nestingdolls.ListField(forms.IntegerField())

        value = nestingdolls.ListField(nestingdolls.MappingField(InnerForm))


class TripleLLMProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class LeafForm(forms.Form):
            child = forms.IntegerField()

        value = nestingdolls.ListField(
            nestingdolls.ListField(nestingdolls.MappingField(LeafForm))
        )


class TripleLLLProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        value = nestingdolls.ListField(
            nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))
        )


class DeepPayloadProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            class SectionForm(forms.Form):
                class EntryForm(forms.Form):
                    point = nestingdolls.MappingField(MappingProbeFixtures.PointForm)
                    title = forms.CharField()

                heading = forms.CharField()
                entries = nestingdolls.ListField(nestingdolls.MappingField(EntryForm))

            rows = nestingdolls.ListField(nestingdolls.MappingField(SectionForm))

        payload = nestingdolls.MappingField(ChildForm)


class NestedRowErrorProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.MappingField(MappingProbeFixtures.PointForm)
        )


class NumericMappingProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        class ChildForm(forms.Form):
            locals()["0"] = forms.IntegerField()

        point = nestingdolls.MappingField(ChildForm, required=False)


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
        "mapping-submission-probe/",
        MappingProbeView.as_view(
            form_class=MappingSubmissionProbeFixtures.ProbeForm, response_field="point"
        ),
    ),
    path(
        "numeric-mapping-probe/",
        MappingProbeView.as_view(
            form_class=NumericMappingProbeFixtures.ProbeForm, response_field="point"
        ),
    ),
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
    path(
        "nested-mapping-probe/",
        MappingProbeView.as_view(
            form_class=NestedMappingProbeFixtures.ProbeForm, response_field="rows"
        ),
    ),
    path("nested-asset-probe/", NestedAssetProbeView.as_view()),
    path(
        "nested-row-error-probe/",
        MappingProbeView.as_view(form_class=NestedRowErrorProbeFixtures.ProbeForm),
    ),
    path(
        "triple-mmm-probe/",
        MappingProbeView.as_view(
            form_class=TripleMMMProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-mml-probe/",
        MappingProbeView.as_view(
            form_class=TripleMMLProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-mlm-probe/",
        MappingProbeView.as_view(
            form_class=TripleMLMProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-mll-probe/",
        MappingProbeView.as_view(
            form_class=TripleMLLProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-lmm-probe/",
        MappingProbeView.as_view(
            form_class=TripleLMMProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-lml-probe/",
        MappingProbeView.as_view(
            form_class=TripleLMLProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-llm-probe/",
        MappingProbeView.as_view(
            form_class=TripleLLMProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "triple-lll-probe/",
        MappingProbeView.as_view(
            form_class=TripleLLLProbeFixtures.ProbeForm, response_field="value"
        ),
    ),
    path(
        "deep-payload-probe/",
        MappingProbeView.as_view(
            form_class=DeepPayloadProbeFixtures.ProbeForm, response_field="payload"
        ),
    ),
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


@override_settings(ROOT_URLCONF=__name__)
class NestedMappingSubmissionFunctionalTestCase(SimpleTestCase):
    """Retain the URL fixture namespace after alias-contract removal."""


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

    def test_flattened_initial_mapping_uses_child_widget_values(self):
        """It reconstructs raw widget values from flat child names."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False
            )

        self.assertEqual(Form(initial={"point-a": "2"})["point"].initial, {"a": "2"})

    def test_unrecognized_flattened_initial_uses_the_field_initial(self):
        """It leaves Django's configured mapping initial value intact."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False, initial={"a": 3}
            )

        self.assertEqual(
            Form(initial={"point-junk": "value"})["point"].initial, {"a": 3}
        )

    def test_invalid_mapping_shapes_stay_in_djangos_bound_data_channel(self):
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
    def test_child_errors_render_once_with_resolvable_references(self):
        """A child error renders beside its own input, with resolvable ids."""

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

        for renderer in (form.as_div, form.as_p, form.as_ul, form.as_table):
            with self.subTest(renderer=renderer.__name__):
                elements = [parse_html(renderer())]
                for element in elements:
                    elements.extend(
                        child
                        for child in element.children
                        if isinstance(child, Element)
                    )

                element_attributes = [dict(element.attributes) for element in elements]
                ids = [
                    attributes["id"]
                    for attributes in element_attributes
                    if "id" in attributes
                ]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertIn("id_point-a_error", ids)
                self.assertIn("id_values_0_error", ids)
                for attributes in element_attributes:
                    for reference in attributes.get("aria-describedby", "").split():
                        self.assertIn(reference, ids)

    def test_every_helper_layout_renders_the_child_form_and_wrapper(self):
        """Each helper renders the child inputs, the wrapper, and one hidden initial."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, show_hidden_initial=True
            )

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        for renderer in (form.as_div, form.as_p, form.as_table, form.as_ul):
            with self.subTest(renderer=renderer.__name__):
                html = renderer()
                self.assertIn('data-widget="mapping"', html)
                self.assertIn('data-mapping-field="point"', html)
                self.assertIn('id="id_point_widget"', html)
                self.assertIn('name="point-a"', html)
                self.assertIn('name="point-label"', html)
                self.assertEqual(html.count('name="initial-point-a"'), 1)
                self.assertInHTML(
                    '<input type="number" name="point-a" value="9" required'
                    ' id="id_point-a">',
                    html,
                )

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
    """Exercises Python-only nested values and direct field APIs."""

    def test_direct_child_values_reach_the_child_field_unchanged(self):
        """Direct mapping input keeps repeated, JSON, compound, and file values."""

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

        # A direct list stays one JSON value instead of becoming repeated input.
        class JSONChildForm(forms.Form):
            payload = forms.JSONField()

        class JSONOuter(forms.Form):
            value = nestingdolls.MappingField(JSONChildForm)

        encoded = JSONOuter({"value": {"payload": [1, {"answer": 42}]}})
        self.assertIs(encoded.is_valid(), True, encoded.errors)
        self.assertEqual(encoded.cleaned_data["value"]["payload"], [1, {"answer": 42}])

        # Direct cleaning hands already-extracted compound and file values over.
        class CompoundForm(forms.Form):
            happened_at = forms.SplitDateTimeField()
            upload = forms.FileField()

        upload = SimpleUploadedFile("direct.txt", b"direct")
        cleaned = nestingdolls.MappingField(CompoundForm).clean(
            {"happened_at": ["2026-08-01", "10:30:00"], "upload": upload}
        )
        self.assertEqual(
            cleaned["happened_at"].replace(tzinfo=None).isoformat(),
            "2026-08-01T10:30:00",
        )
        self.assertIs(cleaned["upload"], upload)


class NestedMappingRenderingUnitTestCase(FormBindingUnitTestCase):
    """Exercises nested mapping row markup that an HTTP response cannot expose."""


class DictFieldRegressionTestCase(SimpleTestCase):
    def test_hostile_initials_and_payloads_stay_renderable_errors(self):
        """Malformed initials and payloads stay in Django's error channel."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False
            )

        class CallableInitialForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False, initial=lambda: ["bad"]
            )

        class DisabledForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.PointForm, required=False, disabled=True
            )

        for form in (Form(initial={"point": ["bad"]}), CallableInitialForm()):
            with self.subTest(form=form.__class__.__name__):
                self.assertEqual(form["point"].value(), ["bad"])
                str(form["point"])

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

        class NestedForm(forms.Form):
            rows = nestingdolls.ListField(
                nestingdolls.MappingField(MappingProbeFixtures.PointForm),
                required=False,
            )

        class HiddenInitialForm(forms.Form):
            payload = nestingdolls.MappingField(
                NestedForm, required=False, show_hidden_initial=True
            )

        initial = {"payload": {"rows": [{"a": 1, "label": "saved"}]}}
        for data in ({"payload": "hostile"}, {"payload": {"rows": ["hostile"]}}):
            with self.subTest(data=data):
                hidden = HiddenInitialForm(data, initial=initial)
                self.assertIs(hidden.is_valid(), False)
                self.assertIn("Enter a mapping of values.", hidden.as_p())

    def test_child_rebinding_rejections_use_mapping_fallbacks(self):
        """A child rejection returns a mapping through Django's base contract."""

        class RejectingField(forms.CharField):
            def bound_data(self, data, initial):
                raise ValidationError("Cannot bind this value.")

            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class ChildForm(forms.Form):
            value = RejectingField()

        field = nestingdolls.MappingField(ChildForm)
        value = {"value": "hostile"}

        operations = (
            ("bound_data", lambda: field.bound_data(value, {})),
            ("prepare_value", lambda: field.prepare_value(value)),
        )
        for operation_name, operation in operations:
            with self.subTest(operation=operation_name):
                self.assertEqual(operation(), value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
