"""Shared Django fixtures, probe views, and form-binding helpers for tests."""

from __future__ import annotations

import dataclasses
import json
import unittest
from collections import deque
from datetime import datetime
from types import MappingProxyType
from typing import ClassVar, NamedTuple
from urllib.parse import urlencode

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import JsonResponse, QueryDict
from django.test import SimpleTestCase, override_settings
from django.test.html import Element, parse_html
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import path
from django.utils import translation
from django.utils.datastructures import MultiValueDict
from django.views import View

import nestingdolls

from .testcases import (
    CompositeErrorDisplayAssertions,
    CompositeRenderingAssertions,
    MarkedErrorList,
    MarkedRenderer,
)

__all__ = (
    "DEFAULT_MAX_NUM",
    "DELETION_FIELD_NAME",
    "INITIAL_FORM_COUNT",
    "MAX_NUM_FORM_COUNT",
    "MIN_NUM_FORM_COUNT",
    "TOTAL_FORM_COUNT",
    "ClassVar",
    "CompositeErrorDisplayAssertions",
    "CompositeRenderingAssertions",
    "DataclassPoint",
    "DataclassPointForm",
    "Element",
    "ImproperlyConfigured",
    "JsonResponse",
    "ListFormBindingUnitTestCase",
    "ListProbeFixtures",
    "MappingAssetInitialProbeView",
    "MappingAssetProbeFixtures",
    "MappingAssetProbeView",
    "MappingDisabledProbeFixtures",
    "MappingFileChangeProbeFixtures",
    "MappingFileChangeProbeView",
    "MappingFormBindingUnitTestCase",
    "MappingHookProbeFixtures",
    "MappingInitialProbeFixtures",
    "MappingInitialProbeView",
    "MappingNonFieldProbeFixtures",
    "MappingNonFieldProbeView",
    "MappingOptionalProbeFixtures",
    "MappingOptionalProbeView",
    "MappingPointForm",
    "MappingPrefixedProbeFixtures",
    "MappingPrefixedProbeView",
    "MappingProbeFixtures",
    "MappingProbeView",
    "MappingProxyType",
    "MappingRepeatedFileProbeFixtures",
    "MappingRepeatedFileProbeView",
    "MappingRootSubmissionLimitProbeView",
    "MappingValidatedProbeFixtures",
    "MappingValueForm",
    "MarkedErrorList",
    "MarkedRenderer",
    "MultiValueDict",
    "MultipleFileField",
    "MultipleFileInput",
    "NamedTuple",
    "NamedTuplePoint",
    "NamedTuplePointForm",
    "NestedListProbeFixtures",
    "OptionalMappingValueForm",
    "OptionalSequenceForm",
    "ProbeView",
    "QueryDict",
    "RedisplayProbeView",
    "SequenceForm",
    "SequenceMappingSequenceSubmissionProbeView",
    "SequenceRootSubmissionLimitProbeView",
    "SetProbeView",
    "SimpleTestCase",
    "SimpleUploadedFile",
    "SparseAssetProbeView",
    "SubmissionLimitProbeFixtures",
    "UploadedFile",
    "ValidationError",
    "View",
    "annotations",
    "dataclasses",
    "datetime",
    "deque",
    "django",
    "forms",
    "json",
    "nestingdolls",
    "override_settings",
    "parse_html",
    "path",
    "settings",
    "setup_test_environment",
    "teardown_test_environment",
    "translation",
    "unittest",
    "urlencode",
    "urlpatterns",
)


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


class ListFormBindingUnitTestCase(SimpleTestCase):
    """Binds forms directly when tests need form internals."""

    def build_querydict_form(self, form_class, pairs, *, initial=None, prefix=None):
        """Bind form_class the way a browser <form> submit does: prefixed keys.

        `pairs` is a dict of prefixed keys (e.g. {"values-0": "1"}) or an
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


class SubmissionLimitProbeFixtures(SimpleTestCase):
    class SequenceRootForm(forms.Form):
        outer = nestingdolls.ListField(
            nestingdolls.ListField(
                forms.BooleanField(required=False),
                max_length=10,
                absolute_max=10,
            ),
            max_length=10,
            absolute_max=10,
        )

    class MappingRootForm(forms.Form):
        class ValuesForm(forms.Form):
            first = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )
            second = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )

        values = nestingdolls.DictField(ValuesForm)

    class SequenceMappingSequenceForm(forms.Form):
        class ItemForm(forms.Form):
            tags = nestingdolls.ListField(
                forms.BooleanField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            )

        items = nestingdolls.ListField(
            nestingdolls.DictField(ItemForm),
            required=False,
            max_length=10,
            absolute_max=10,
        )


class ProbeView(View):
    form_class = None
    field_name = "values"

    def post(self, request):
        form = self.form_class(request.POST, request.FILES)
        valid = form.is_valid()
        return JsonResponse(self.response_data(form, valid, form.errors.as_data()))

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "values": form.cleaned_data.get(self.field_name) if valid else None,
            "errors": self.error_codes(errors),
        }

    def error_codes(self, errors):
        return {
            name: [error.code for error in field_errors]
            for name, field_errors in errors.items()
        }


class SequenceRootSubmissionLimitProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.SequenceRootForm

    def response_data(self, form, valid, errors):
        return {"valid": valid, "errors": self.error_codes(errors)}


class MappingRootSubmissionLimitProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.MappingRootForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "lengths": (
                {name: len(rows) for name, rows in form.cleaned_data["values"].items()}
                if valid
                else {}
            ),
        }


class SequenceMappingSequenceSubmissionProbeView(ProbeView):
    form_class = SubmissionLimitProbeFixtures.SequenceMappingSequenceForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "errors": self.error_codes(errors),
            "tag_counts": (
                [len(item["tags"]) for item in form.cleaned_data["items"]]
                if valid
                else []
            ),
        }


class ListProbeFixtures(SimpleTestCase):
    class SubmissionForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), required=False)

    class NestedForm(forms.Form):
        values = nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))

    class DisabledForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), disabled=True, initial=[1]
        )

    class MaxDeletionForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class JSONSubmissionForm(forms.Form):
        values = nestingdolls.ListField(forms.JSONField(), required=False)

    class DefaultAbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

    class AbsoluteMaximumForm(forms.Form):
        values = nestingdolls.ListField(
            forms.IntegerField(), max_length=1, absolute_max=2
        )

    class PointsForm(forms.Form):
        class PointForm(forms.Form):
            a = forms.IntegerField()
            b = forms.IntegerField()
            c = forms.IntegerField()

        values = nestingdolls.ListField(
            nestingdolls.DictField(PointForm), max_length=5, absolute_max=10
        )

    class SetForm(forms.Form):
        values = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)


class NestedListProbeFixtures(SimpleTestCase):
    class ExactSubmissionForm(forms.Form):
        outer = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), max_length=1999),
            required=False,
        )

    class SparseAssetForm(forms.Form):
        class RowForm(forms.Form):
            label = forms.CharField(required=False)
            upload = forms.FileField(required=False)

        values = nestingdolls.ListField(
            nestingdolls.MappingField(RowForm), required=False
        )

    class NestedDeletionForm(forms.Form):
        values = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(required=False), required=False),
            required=False,
        )


class SparseAssetProbeView(ProbeView):
    form_class = NestedListProbeFixtures.SparseAssetForm

    def response_data(self, form, valid, errors):
        return {
            "valid": valid,
            "rows": [
                [row.get("label"), getattr(row.get("upload"), "name", None)]
                for row in form.cleaned_data["values"]
            ]
            if valid
            else None,
            "errors": self.error_codes(errors),
        }


class SetProbeView(ProbeView):
    form_class = ListProbeFixtures.SetForm

    def response_data(self, form, valid, errors):
        data = super().response_data(form, valid, errors)
        if valid:
            data["values"] = sorted(data["values"])
        return data


class RedisplayProbeView(ProbeView):
    def response_data(self, form, valid, errors):
        data = super().response_data(form, valid, errors)
        # The browser gets this HTML back when a submission fails, so the
        # redisplayed page is part of the submitted-state contract.
        data["html"] = form.as_p()
        return data


urlpatterns = [
    path(
        "list-submission-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.SubmissionForm),
    ),
    path("set-submission-probe/", SetProbeView.as_view()),
    path(
        "disabled-list-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DisabledForm),
    ),
    path(
        "list-max-deletion-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.MaxDeletionForm),
    ),
    path(
        "list-json-submission-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.JSONSubmissionForm),
    ),
    path(
        "list-default-absolute-maximum-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.DefaultAbsoluteMaximumForm),
    ),
    path(
        "list-absolute-maximum-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.AbsoluteMaximumForm),
    ),
    path(
        "list-of-points-probe/",
        ProbeView.as_view(form_class=ListProbeFixtures.PointsForm),
    ),
    path(
        "exact-nested-submission-probe/",
        ProbeView.as_view(
            form_class=NestedListProbeFixtures.ExactSubmissionForm,
            field_name="outer",
        ),
    ),
    path(
        "sequence-root-submission-limit/",
        SequenceRootSubmissionLimitProbeView.as_view(),
    ),
    path(
        "mapping-root-submission-limit/",
        MappingRootSubmissionLimitProbeView.as_view(),
    ),
    path(
        "sequence-mapping-sequence-submission-limit/",
        SequenceMappingSequenceSubmissionProbeView.as_view(),
    ),
    path("sparse-asset-probe/", SparseAssetProbeView.as_view()),
    path(
        "nested-deletion-redisplay-probe/",
        RedisplayProbeView.as_view(
            form_class=NestedListProbeFixtures.NestedDeletionForm
        ),
    ),
    path(
        "nested-row-error-redisplay-probe/",
        RedisplayProbeView.as_view(form_class=ListProbeFixtures.NestedForm),
    ),
]


class SequenceForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField())


class OptionalSequenceForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField(), required=False)


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


class MappingFormBindingUnitTestCase(SimpleTestCase):
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
    class MappingPointForm(forms.Form):
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
        required_point = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm
        )
        optional_point = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, required=False
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
            MappingProbeFixtures.MappingPointForm,
            required=False,
            validators=[reject_two],
        )


class MappingPrefixedProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)


class MappingPrefixedProbeView(MappingProbeView):
    form_class = MappingPrefixedProbeFixtures.ProbeForm
    response_field = "point"

    def get_form_kwargs(self):
        return {"prefix": "outer"}


class MappingDisabledProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm,
            disabled=True,
            initial={"a": 8, "label": "initial"},
        )


class MappingInitialProbeFixtures(SimpleTestCase):
    class ProbeForm(forms.Form):
        point = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, required=False
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


urlpatterns += [
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


class MappingPointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


class MappingValueForm(forms.Form):
    point = nestingdolls.DictField(MappingPointForm)


class OptionalMappingValueForm(forms.Form):
    point = nestingdolls.DictField(MappingPointForm, required=False)


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


@dataclasses.dataclass
class DataclassPoint:
    x: int
    y: int


class DataclassPointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()


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


class NamedTuplePoint(NamedTuple):
    x: int
    y: int


class NamedTuplePointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()
