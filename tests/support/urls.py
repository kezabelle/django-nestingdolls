"""URL patterns for functional test probes."""

from __future__ import annotations

from django.urls import path

from .forms.hostile import (
    AggregateNestedTextSequenceForm,
    ManySiblingNestedTextSequenceForm,
    ManySiblingSequencesValueForm,
    NarrowIntegerSequenceForm,
    NestedTypedIntegerSequenceForm,
    OptionalChoiceMappingValueForm,
    OptionalIntegerSequenceMappingValueForm,
    OptionalJSONSetForm,
    OptionalPointValueForm,
    OptionalTripleMappingValueForm,
    PrefixedIntegerValueMappingForm,
    TripleMappingValueForm,
    TriplyNestedTextSequenceForm,
)
from .forms.mapping import (
    DisabledMappingPointForm,
    MappingHookForm,
    ValidatedMappingPointForm,
)
from .forms.sequence import (
    AbsoluteMaximumSequenceForm,
    DisabledSequenceForm,
    ExactNestedSequenceSubmissionForm,
    JSONSequenceSubmissionForm,
    MaximumOneSequenceForm,
    NestedIntegerValuesSequenceForm,
    NestedSequenceDeletionForm,
    OptionalRequiredTextSequenceForm,
    OptionalSplitDateTimeSequenceForm,
    SequenceOfPointsForm,
    SequenceSubmissionForm,
    SparseAssetSequenceForm,
)
from .views import (
    HostileSubmissionProbeView,
    MappingAssetInitialProbeView,
    MappingAssetProbeView,
    MappingFileChangeProbeView,
    MappingInitialProbeView,
    MappingNonFieldProbeView,
    MappingOptionalProbeView,
    MappingPrefixedProbeView,
    MappingRepeatedFileProbeView,
    MappingRootSubmissionLimitProbeView,
    ProbeView,
    RedisplayProbeView,
    SequenceMappingSequenceSubmissionProbeView,
    SequenceRootSubmissionLimitProbeView,
    SetProbeView,
    SparseAssetProbeView,
)

urlpatterns = [
    path(
        "list-submission-probe/",
        ProbeView.as_view(form_class=SequenceSubmissionForm),
    ),
    path("set-submission-probe/", SetProbeView.as_view()),
    path(
        "disabled-list-probe/",
        ProbeView.as_view(form_class=DisabledSequenceForm),
    ),
    path(
        "list-max-deletion-probe/",
        ProbeView.as_view(form_class=MaximumOneSequenceForm),
    ),
    path(
        "list-json-submission-probe/",
        ProbeView.as_view(form_class=JSONSequenceSubmissionForm),
    ),
    path(
        "list-default-absolute-maximum-probe/",
        ProbeView.as_view(form_class=MaximumOneSequenceForm),
    ),
    path(
        "list-absolute-maximum-probe/",
        ProbeView.as_view(form_class=AbsoluteMaximumSequenceForm),
    ),
    path(
        "list-of-points-probe/",
        ProbeView.as_view(form_class=SequenceOfPointsForm),
    ),
    path(
        "exact-nested-submission-probe/",
        ProbeView.as_view(
            form_class=ExactNestedSequenceSubmissionForm,
            cleaned_data_field_name="outer",
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
        RedisplayProbeView.as_view(form_class=NestedSequenceDeletionForm),
    ),
    path(
        "nested-row-error-redisplay-probe/",
        RedisplayProbeView.as_view(form_class=NestedIntegerValuesSequenceForm),
    ),
    path(
        "mapping-hook-probe/",
        ProbeView.as_view(
            form_class=MappingHookForm,
            response_field="value",
            cleaned_data_field_name="value",
        ),
    ),
    path("mapping-nonfield-probe/", MappingNonFieldProbeView.as_view()),
    path("mapping-asset-probe/", MappingAssetProbeView.as_view()),
    path("mapping-asset-initial-probe/", MappingAssetInitialProbeView.as_view()),
    path("mapping-optional-probe/", MappingOptionalProbeView.as_view()),
    path(
        "mapping-validated-probe/",
        ProbeView.as_view(
            form_class=ValidatedMappingPointForm,
            response_field="point",
            cleaned_data_field_name="point",
        ),
    ),
    path("mapping-prefixed-probe/", MappingPrefixedProbeView.as_view()),
    path(
        "mapping-disabled-probe/",
        ProbeView.as_view(
            form_class=DisabledMappingPointForm,
            response_field="point",
            cleaned_data_field_name="point",
        ),
    ),
    path("mapping-initial-probe/", MappingInitialProbeView.as_view()),
    path("mapping-file-change-probe/", MappingFileChangeProbeView.as_view()),
    path("mapping-repeated-file-probe/", MappingRepeatedFileProbeView.as_view()),
    path(
        "hostile-split-datetime-list/",
        HostileSubmissionProbeView.as_view(
            form_class=OptionalSplitDateTimeSequenceForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-integer-list/",
        HostileSubmissionProbeView.as_view(form_class=SequenceSubmissionForm),
    ),
    path(
        "hostile-narrow-list/",
        HostileSubmissionProbeView.as_view(form_class=NarrowIntegerSequenceForm),
    ),
    path(
        "hostile-nested-text-list/",
        HostileSubmissionProbeView.as_view(
            form_class=NestedSequenceDeletionForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-changed-first-nested-list/",
        HostileSubmissionProbeView.as_view(
            form_class=NestedSequenceDeletionForm,
            change_detection_first=True,
            show_html=True,
        ),
    ),
    path(
        "hostile-empty-permitted-nested-list/",
        HostileSubmissionProbeView.as_view(
            form_class=NestedSequenceDeletionForm,
            form_kwargs={"empty_permitted": True, "use_required_attribute": False},
        ),
    ),
    path(
        "hostile-triply-nested-list/",
        HostileSubmissionProbeView.as_view(
            form_class=TriplyNestedTextSequenceForm,
        ),
    ),
    path(
        "hostile-many-sibling-list-fields/",
        HostileSubmissionProbeView.as_view(
            form_class=ManySiblingNestedTextSequenceForm,
        ),
    ),
    path(
        "hostile-nested-typed-list/",
        HostileSubmissionProbeView.as_view(form_class=NestedTypedIntegerSequenceForm),
    ),
    path(
        "hostile-aggregate-cap-list/",
        HostileSubmissionProbeView.as_view(
            form_class=AggregateNestedTextSequenceForm,
            show_html=True,
        ),
    ),
    path(
        "hostile-deep-bracket-list/",
        HostileSubmissionProbeView.as_view(form_class=OptionalRequiredTextSequenceForm),
    ),
    path(
        "hostile-row-upload-list/",
        HostileSubmissionProbeView.as_view(form_class=SparseAssetSequenceForm),
    ),
    path(
        "hostile-json-set/",
        HostileSubmissionProbeView.as_view(form_class=OptionalJSONSetForm),
    ),
    path(
        "hostile-triple-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=TripleMappingValueForm, field_name="value"
        ),
    ),
    path(
        "hostile-optional-triple-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=OptionalTripleMappingValueForm,
            field_name="value",
        ),
    ),
    path(
        "hostile-mapping-list/",
        HostileSubmissionProbeView.as_view(
            form_class=OptionalIntegerSequenceMappingValueForm, field_name="value"
        ),
    ),
    path(
        "hostile-choices-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=OptionalChoiceMappingValueForm, field_name="value"
        ),
    ),
    path(
        "hostile-prefixed-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=PrefixedIntegerValueMappingForm,
            field_name="value",
            form_kwargs={"prefix": "outer"},
        ),
    ),
    path(
        "hostile-plain-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=OptionalPointValueForm, field_name="value"
        ),
    ),
    path(
        "hostile-many-sibling-sequences-mapping/",
        HostileSubmissionProbeView.as_view(
            form_class=ManySiblingSequencesValueForm,
            field_name="value",
        ),
    ),
]
