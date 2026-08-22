"""HTTP probe views shared by functional test cohorts."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.http import JsonResponse
from django.views import View

from .forms.mapping import (
    MappingAssetForm,
    MappingFileChangeForm,
    MappingNonFieldErrorForm,
    MappingOptionalPointsForm,
    MappingRootSubmissionLimitForm,
    OptionalMappingPointForm,
    PrefixedMappingPointForm,
    RepeatedFileMappingForm,
)
from .forms.sequence import (
    SequenceMappingSequenceSubmissionLimitForm,
    SequenceRootSubmissionLimitForm,
    SetSubmissionForm,
    SparseAssetSequenceForm,
)


def _serialize_uploaded_value(value: object) -> object:
    if value is None or value is False:
        return value
    if isinstance(value, UploadedFile):
        return value.name
    return value


def _serialize_asset(asset: object) -> object:
    if asset is None:
        return None
    return {
        "title": asset["title"],
        "upload": _serialize_uploaded_value(asset["upload"]),
    }


class ProbeView(View):  # noqa: D101
    form_class = None
    response_field = "values"
    cleaned_data_field_name = "values"

    def get_form_kwargs(self) -> object:  # noqa: D102
        return {}

    def post(self, request: object, *args: object, **kwargs: object) -> object:  # noqa: D102
        form = self.form_class(
            request.POST,
            request.FILES,
            **self.get_form_kwargs(),
        )
        valid = form.is_valid()
        return JsonResponse(self.response_data(form, valid))

    def error_codes(self, form: object) -> object:  # noqa: D102
        return {
            name: [error.code for error in errors]
            for name, errors in form.errors.as_data().items()
        }

    def child_error_codes(self, form: object) -> object:  # noqa: D102
        return {
            name: [error.params.get("child_code") for error in errors if error.params]
            for name, errors in form.errors.as_data().items()
        }

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = {"valid": valid}
        if self.response_field is not None:
            data[self.response_field] = (
                form.cleaned_data.get(self.cleaned_data_field_name) if valid else None
            )
        data["errors"] = self.error_codes(form)
        return data


class SequenceRootSubmissionLimitProbeView(ProbeView):  # noqa: D101
    form_class = SequenceRootSubmissionLimitForm
    response_field = None


class MappingRootSubmissionLimitProbeView(ProbeView):  # noqa: D101
    form_class = MappingRootSubmissionLimitForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        return {
            "valid": valid,
            "lengths": (
                {name: len(rows) for name, rows in form.cleaned_data["values"].items()}
                if valid
                else {}
            ),
        }


class SequenceMappingSequenceSubmissionProbeView(ProbeView):  # noqa: D101
    form_class = SequenceMappingSequenceSubmissionLimitForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        return {
            "valid": valid,
            "errors": self.error_codes(form),
            "tag_counts": (
                [len(item["tags"]) for item in form.cleaned_data["items"]]
                if valid
                else []
            ),
        }


class SparseAssetProbeView(ProbeView):  # noqa: D101
    form_class = SparseAssetSequenceForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        return {
            "valid": valid,
            "rows": (
                [
                    [row.get("label"), _serialize_uploaded_value(row.get("upload"))]
                    for row in form.cleaned_data["values"]
                ]
                if valid
                else None
            ),
            "errors": self.error_codes(form),
        }


class SetProbeView(ProbeView):  # noqa: D101
    form_class = SetSubmissionForm

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        if valid:
            data["values"] = sorted(data["values"])
        return data


class RedisplayProbeView(ProbeView):  # noqa: D101
    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        data["html"] = form.as_p()
        return data


class MappingAssetProbeView(ProbeView):  # noqa: D101
    form_class = MappingAssetForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        data["asset"] = _serialize_asset(form.cleaned_data["asset"] if valid else None)
        return data


class MappingOptionalProbeView(ProbeView):  # noqa: D101
    form_class = MappingOptionalPointsForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        data["value"] = form.cleaned_data if valid else None
        return data


class MappingPrefixedProbeView(ProbeView):  # noqa: D101
    form_class = PrefixedMappingPointForm
    response_field = "point"
    cleaned_data_field_name = "point"

    def get_form_kwargs(self) -> object:  # noqa: D102
        return {"prefix": "outer"}


class MappingInitialProbeView(ProbeView):  # noqa: D101
    form_class = OptionalMappingPointForm
    response_field = "point"
    cleaned_data_field_name = "point"

    def get_form_kwargs(self) -> object:  # noqa: D102
        return {"initial": {"point": {"a": 8, "label": "saved"}}}


class MappingFileChangeProbeView(ProbeView):  # noqa: D101
    form_class = MappingFileChangeForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        asset = form.cleaned_data["asset"] if valid else None
        document = asset.get("document") if asset else None
        data.update(
            document=_serialize_uploaded_value(document),
            changed=form.has_changed(),
        )
        return data


class MappingAssetInitialProbeView(MappingAssetProbeView):  # noqa: D101
    def get_form_kwargs(self) -> object:  # noqa: D102
        return {
            "initial": {
                "asset": {
                    "title": "old",
                    "upload": SimpleUploadedFile("old.txt", b"old"),
                }
            }
        }

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        data["child_errors"] = self.child_error_codes(form)
        return data


class MappingRepeatedFileProbeView(ProbeView):  # noqa: D101
    form_class = RepeatedFileMappingForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        asset = form.cleaned_data["asset"] if valid else None
        uploads = asset.get("upload") if asset else []
        data["uploads"] = [upload.name for upload in uploads]
        return data


class MappingNonFieldProbeView(ProbeView):  # noqa: D101
    form_class = MappingNonFieldErrorForm
    response_field = None

    def response_data(self, form: object, valid: object) -> object:  # noqa: D102
        data = super().response_data(form, valid)
        data["child_errors"] = self.child_error_codes(form)
        return data


ROW_MARKER = "data-sequence-index="


class HostileSubmissionProbeView(View):
    """Bind one static form to the request and report what a user can see."""

    form_class = None
    field_name = "values"
    show_html = False
    form_kwargs = None
    # Django itself calls has_changed() before _clean_fields() whenever a form
    # is empty_permitted, so change detection is a real entry point into row
    # extraction and not only an application's own call.
    change_detection_first = False

    def post(self, request: object) -> object:  # noqa: D102
        form = self.form_class(request.POST, request.FILES, **(self.form_kwargs or {}))
        if self.change_detection_first:
            form.has_changed()
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
