"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.sequence import (
    BoundedNestedIntegerSequenceForm,
    NestedIntegerSequenceForm,
    OptionalBCSequenceForm,
    OptionalRequiredTextSequenceForm,
    RequiredBCSequenceForm,
    RequiredBSequenceForm,
    SequenceForm,
)
from .support.testcases import CompositeFieldTestCase, TestQueryDict


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support.urls")
class SequenceFieldNestingTestCase(CompositeFieldTestCase):
    """Tests sequences nested in sequences and mappings.

    The tests cover nested change detection, the shared row cap, sparse file
    rows, nested deletion, and nested row errors.
    """

    def test_nested_exact_rows_respect_the_child_absolute_max(self) -> None:
        """Nested exact rows cap construction without losing the rejected total."""

        class Child(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, max_length=1, absolute_max=2
            )

        class Outer(forms.Form):
            rows = nestingdolls.SequenceField(nestingdolls.MappingField(Child))

        form = Outer({"rows": [{"values": ["1", "2", "3"]}]})
        nested = form["rows"].formset.forms[0]["value"].subform["values"]
        self.assertEqual(len(nested.formset.forms), 2)
        self.assertFormInvalid(form)
        error = form.errors.as_data()["rows"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "too_many_forms")

    def test_nested_change_detection_uses_child_semantics(self) -> None:
        """Nested change detection delegates to the child field's comparison."""
        tuple_field = nestingdolls.ListField(
            nestingdolls.TupleField(
                forms.IntegerField(),
                min_length=2,
                max_length=2,
            ),
            required=False,
        )

        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 0]]), False)
        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 1]]), True)
        self.assertIs(tuple_field.has_changed([(2, 0)], []), True)
        self.assertIs(tuple_field.has_changed([], [[2, 0]]), True)

        child = nestingdolls.ListField(
            nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False),
                required=False,
            ),
            required=False,
        )
        field = nestingdolls.ListField(child, required=False)

        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]), False)
        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]), True)
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]),
            child.has_changed([[[2], [0]]], [[[2], [1]]]),
        )
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]),
            child.has_changed([[[2], [0]]], [[[2], [0]]]),
        )

    def test_nested_sequence_deletion_is_a_change(self) -> None:
        """A row deleted in a nested sequence changes the outer sequence.

        The outer rows still equal the initial rows. Only the nested row
        formset knows about the deletion.
        """

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False)
            )

        data = {
            f"outer-{TOTAL_FORM_COUNT}": "1",
            f"outer-{INITIAL_FORM_COUNT}": "1",
            f"outer-0-value-{TOTAL_FORM_COUNT}": "1",
            f"outer-0-value-{INITIAL_FORM_COUNT}": "1",
            "outer-0-value-0-value": "1",
        }
        initial = {"outer": [[1]]}
        self.assertIs(Form(data, initial=initial).has_changed(), False)

        deleted = Form(
            {**data, f"outer-0-value-0-{DELETION_FIELD_NAME}": "on"}, initial=initial
        )
        self.assertFormValid(deleted)
        self.assertEqual(deleted.cleaned_data["outer"], [[]])
        self.assertEqual(deleted.changed_data, ["outer"])

    def test_mapping_child_named_delete_does_not_delete_sequence_row(self) -> None:
        """A child value named DELETE is distinct from its row's deletion flag."""

        class Child(forms.Form):
            DELETE = forms.CharField()

        class Outer(forms.Form):
            rows = nestingdolls.SequenceField(
                nestingdolls.MappingField(Child), required=False
            )

        data = {
            "rows-TOTAL_FORMS": "1",
            "rows-INITIAL_FORMS": "0",
            "rows-0-value-DELETE": "keep",
        }
        retained = Outer(data)
        self.assertFormValid(retained)
        self.assertEqual(retained.cleaned_data["rows"], [{"DELETE": "keep"}])

        deleted = Outer({**data, "rows-0-DELETE": "1"})
        self.assertFormValid(deleted)
        self.assertEqual(deleted.cleaned_data["rows"], [])

    def test_disabled_composite_row_with_unusable_initial_is_unchanged(self) -> None:
        """A disabled mapping or sequence row reports no change, even for a bad initial.

        A disabled field ignores its input, so it has no change to report.
        The outer sequence asks each row for row changes, with the row's
        initial value ``42``, which is neither a mapping nor a sequence.
        """

        class PointForm(forms.Form):
            a = forms.IntegerField(required=False)

        for child in (
            nestingdolls.MappingField(PointForm, disabled=True),
            nestingdolls.ListField(forms.IntegerField(), disabled=True),
        ):
            with self.subTest(child=type(child).__name__):
                form_class = type(
                    "Form",
                    (forms.Form,),
                    {"values": nestingdolls.ListField(child, required=False)},
                )
                form = form_class(
                    {
                        f"values-{TOTAL_FORM_COUNT}": "1",
                        f"values-{INITIAL_FORM_COUNT}": "1",
                        "values-0-value-a": "1",
                    },
                    initial={"values": [42]},
                )

                self.assertIs(form.has_changed(), False)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_initial_rendering_reserves_rows_before_leaf_preparation(
        self,
    ) -> None:
        """Rendering clips nested initials before preparing excess leaf values."""

        class CountingField(forms.IntegerField):
            preparations = 0

            def prepare_value(self, value: object) -> object:
                CountingField.preparations += 1
                return super().prepare_value(value)

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    CountingField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        large_initial = [list(range(10)), list(range(10, 20))]
        CountingField.preparations = 0
        large_html = Form(initial={"outer": large_initial}).as_p()
        large_leaf_names = (
            f"outer-{outer_index}-value-{inner_index}-value"
            for outer_index in range(2)
            for inner_index in range(10)
        )
        rendered_large_leaves = sum(
            large_html.count(f'name="{name}"') for name in large_leaf_names
        )

        self.assertLessEqual(rendered_large_leaves, 10)
        self.assertLessEqual(CountingField.preparations, 10)

        small_initial = [list(range(4)), list(range(4, 8))]
        CountingField.preparations = 0
        small_html = Form(initial={"outer": small_initial}).as_p()
        small_leaf_names = (
            f"outer-{outer_index}-value-{inner_index}-value"
            for outer_index in range(2)
            for inner_index in range(4)
        )
        rendered_small_leaves = sum(
            small_html.count(f'name="{name}"') for name in small_leaf_names
        )

        self.assertEqual(rendered_small_leaves, 8)
        self.assertEqual(CountingField.preparations, 8)

    def test_prepare_value_keeps_a_row_the_nested_child_refuses(self) -> None:
        """A row that the nested child cannot read stays in the prepared rows."""
        field = nestingdolls.ListField(
            nestingdolls.ListField(forms.CharField(), required=False),
            required=False,
        )
        self.assertEqual(field.prepare_value([["a"], "scalar"]), [["a"], "scalar"])

    def test_client_accepts_an_exact_nested_submission_total(self) -> None:
        """Client accepts a nested submission that uses the shared cap exactly.

        Both the outer row and the inner rows are declared initial, so they
        survive extraction the way a stock formset keeps its initial forms.
        An extra outer row carrying no data key of its own would clean away
        as blank before the budget mattered.
        """
        response = self.client.post(
            "/exact-nested-submission-probe/",
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "1",
                f"outer-0-value-{TOTAL_FORM_COUNT}": "1999",
                f"outer-0-value-{INITIAL_FORM_COUNT}": "1999",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["valid"], True)
        self.assertEqual(payload["errors"], {})
        self.assertEqual([len(rows) for rows in payload["values"]], [1999])

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_whole_values_share_one_row_limit(self) -> None:
        """A decoded nested value can spend the shared cap exactly."""
        form = BoundedNestedIntegerSequenceForm({"outer": [list(range(9))]})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["outer"], [list(range(9))])

    def assertNestedRowBlankness(  # noqa: D102
        self, inner_required: object, extra_data: object, expected: object
    ) -> None:

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(), required=inner_required),
                required=False,
            )

        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-value-{TOTAL_FORM_COUNT}": "1",
                f"values-0-value-{INITIAL_FORM_COUNT}": "0",
                **extra_data,
            }
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], expected)

    def test_untouched_nested_row_cleans_away_as_blank(self) -> None:
        """An untouched nested row is blank, so its required child never runs.

        A rendered row submits its nested formset's management keys, and
        those are structure rather than content.
        """
        self.assertNestedRowBlankness(True, {"values-0-value-0-value": ""}, [])

    def test_untouched_nested_row_builds_no_phantom_element(self) -> None:
        """An untouched nested row with an optional child adds no empty list."""
        self.assertNestedRowBlankness(False, {"values-0-value-0-value": ""}, [])

    def test_nested_row_with_a_value_still_cleans_through(self) -> None:
        """A nested row carrying a value is not blank."""
        self.assertNestedRowBlankness(
            True, {"values-0-value-0-value": "abc"}, [["abc"]]
        )

    def test_nested_delete_key_alone_leaves_the_outer_row_blank(self) -> None:
        """A checked nested delete box is structure, not outer-row content."""
        self.assertNestedRowBlankness(
            True,
            {
                "values-0-value-0-value": "",
                f"values-0-value-0-{DELETION_FIELD_NAME}": "on",
            },
            [],
        )

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_whole_values_reject_shared_row_limit_overflow(self) -> None:
        """A decoded child list cannot overdraw its parent sequence budget."""

        class CountingField(forms.IntegerField):
            cleans = 0

            def clean(self, value: object) -> object:
                type(self).cleans += 1
                return super().clean(value)

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    CountingField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        form = Form({"outer": [list(range(10))]})

        self.assertFormInvalid(form)
        error = form.errors.as_data()["outer"][0]
        self.assertEqual(error.code, "too_many_forms")
        self.assertEqual(CountingField.cleans, 0)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_mapping_values_reject_shared_row_limit_overflow(self) -> None:
        """A mapping row discovers its nested sequence under the parent cap."""

        class CountingField(forms.IntegerField):
            cleans = 0

            def clean(self, value: object) -> object:
                type(self).cleans += 1
                return super().clean(value)

        class MappingForm(forms.Form):
            values = nestingdolls.ListField(
                CountingField(),
                max_length=10,
                absolute_max=10,
            )

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.MappingField(MappingForm),
                max_length=10,
                absolute_max=10,
            )

        form = Form({"outer": [{"values": list(range(10))}]})

        self.assertFormInvalid(form)
        error = form.errors.as_data()["outer"][0]
        self.assertEqual(error.code, "too_many_forms")
        self.assertEqual(CountingField.cleans, 0)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_unbound_nested_initial_rendering_counts_parent_rows_before_children(
        self,
    ) -> None:
        """An unbound form renders nine inner inputs because its outer row spends one cap slot."""
        html = BoundedNestedIntegerSequenceForm(
            initial={"outer": [list(range(10))]}
        ).as_p()

        self.assertIn('name="outer-0-value-8-value"', html)
        self.assertNotIn('name="outer-0-value-9-value"', html)

    def test_client_pairs_managed_sparse_data_and_file_rows_by_index(self) -> None:
        """Managed sparse data and file indexes identify the same row.

        The management total owns each row index. A gap does not change the
        data-file pair.
        """
        response = self.client.post(
            "/sparse-asset-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "6",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0-value-label": "row0-label",
                "values-5-value-label": "row5-label",
                "values-0-value-upload": SimpleUploadedFile("row0.txt", b"row0-file"),
                "values-3-value-upload": SimpleUploadedFile("row3.txt", b"row3-file"),
            },
        )

        self.assertJSONResponse(
            response,
            {
                "valid": True,
                "rows": [
                    ["row0-label", "row0.txt"],
                    ["", "row3.txt"],
                    ["row5-label", None],
                ],
                "errors": {},
            },
        )

    def test_client_deletes_a_nested_row_and_redisplays_it_as_deleted(self) -> None:
        """Deleting a nested row removes it and renders it deleted.

        A nested sequence has no bound field of its own to read its rows'
        delete marks. Deleting one of its rows must still remove that row
        from the cleaned value, and the redisplayed form must still show
        that row as deleted.
        """
        response = self.client.post(
            "/nested-deletion-redisplay-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-value-{TOTAL_FORM_COUNT}": "2",
                f"values-0-value-{INITIAL_FORM_COUNT}": "0",
                "values-0-value-0-value": "kept",
                "values-0-value-1-value": "deleted-me",
                f"values-0-value-1-{DELETION_FIELD_NAME}": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["values"], [["kept"]])
        self.assertInHTML(
            '<input type="hidden" name="values-0-value-1-DELETE" value="1"'
            ' data-sequence-deleted-row data-sequence-field="values-0-value">',
            payload["html"],
        )
        self.assertNotIn('value="deleted-me"', payload["html"])

    def test_client_attaches_a_nested_row_error_to_that_nested_row(self) -> None:
        """A nested row error appears at its failing input.

        An error inside a nested row belongs to that row, not to the row
        that holds the nested sequence. The redisplayed form must attach
        the error to the actual failing input, several levels deep.
        """
        response = self.client.post(
            "/nested-row-error-redisplay-probe/",
            {
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
                f"values-0-value-{TOTAL_FORM_COUNT}": "2",
                f"values-0-value-{INITIAL_FORM_COUNT}": "0",
                "values-0-value-0-value": "1",
                "values-0-value-1-value": "abc",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn('<span class="errorlist" id="id_values_0_1_error">', html)
        self.assertErrorReferenceResolves(html, "id_values_0_1_error")

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_field_clean_of_nested_values_pays_each_level_cap(self) -> None:
        """Nested ``clean()`` calls use each level's own cap.

        A ``clean()`` call has no request keys. It does not open the shared
        countdown, but each level still applies ``absolute_max``.
        """

        class CountingField(forms.CharField):
            cleans = 0

            def clean(self, value: object) -> object:
                CountingField.cleans += 1
                return super().clean(value)

        field = nestingdolls.ListField(
            nestingdolls.ListField(
                CountingField(required=False),
                required=False,
                max_length=10,
                absolute_max=10,
            ),
            required=False,
            max_length=10,
            absolute_max=10,
        )

        CountingField.cleans = 0
        cleaned = field.clean([[None] * 10 for _ in range(10)])

        self.assertEqual(len(cleaned), 10)
        self.assertEqual(CountingField.cleans, 100)
        self.assertGreater(CountingField.cleans, field.limits.submission_max)

        with self.assertRaises(ValidationError) as context:
            field.clean([[None] * 11])
        error = context.exception.error_list[0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "too_many_forms")


@override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
class SequenceFieldDecodedCollectionNestingTestCase(CompositeFieldTestCase):
    """Test the shared row cap against decoded Python collections.

    A Python value never meets the request parser, so these tests bind
    ``Form(data=...)`` directly. Both levels allow ten rows, and the outer
    field shares a cap of ten across its whole nested tree.
    """

    def test_nested_tuples_and_ranges_above_the_shared_cap_report_too_many_forms(
        self,
    ) -> None:
        """Three inner collections of three use twelve rows, above the cap of ten."""
        values = {
            "tuples": ((1, 2, 3), (4, 5, 6), (7, 8, 9)),
            "inner ranges": [range(3), range(3), range(3)],
        }
        for name, value in values.items():
            with self.subTest(name):
                form = BoundedNestedIntegerSequenceForm({"outer": value})
                self.assertFormInvalid(form)
                self.assertFormErrorCode(form, "outer", "too_many_forms")

    def test_nested_tuples_within_the_shared_cap_clean_to_lists(self) -> None:
        """A tuple tree inside the cap cleans like the equivalent list tree."""
        form = BoundedNestedIntegerSequenceForm({"outer": ((1, 2), (3, 4))})

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["outer"], [[1, 2], [3, 4]])


class SequenceFieldMappingRowTestCase(CompositeFieldTestCase):
    """A mapping row's own validation outcome is the same in either input style.

    Rendering an invalid redisplay once built an unbound row formset and
    dropped the row error silently. These tests guard that fix for a row
    whose child is a ``MappingField``, including the edge case where
    a row carries no submitted keys at all yet must still validate as
    real, present data rather than an untouched placeholder.
    """

    def assertMappingRowError(self, form: object) -> None:  # noqa: D102
        self.assertFormInvalid(form)
        error = form.errors.as_data()["a"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["item"], 1)
        self.assertEqual(error.params["child_code"], "required")
        self.assertBoundFieldErrors(form, "a", [])
        html = form.as_p()
        self.assertRenderedMessageCount(html, "This field is required.")
        self.assertErrorReferenceResolves(html, "id_a-1-value-b_error")
        self.assertErrorElementIsAbsent(html, "id_a_1_error")
        self.assertIn('name="a-0-value-b" value="2"', html)
        self.assertIn('name="a-1-value-c" value="3"', html)

    def assertMappingRowsValid(self, form: object) -> None:  # noqa: D102
        self.assertFormValid(form)
        self.assertEqual(
            form.cleaned_data["a"], [{"b": 2, "c": None}, {"b": None, "c": 3}]
        )
        html = form.as_p()
        self.assertNotIn("errorlist", html)
        self.assertIn('name="a-0-value-b" value="2"', html)
        self.assertIn('name="a-1-value-c" value="3"', html)

    def assertKeylessRowIsRequired(self, form: object) -> None:  # noqa: D102
        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "a", "item_invalid")
        html = form.as_p()
        self.assertRenderedMessageCount(html, "This field is required.")
        self.assertRegex(html, r'id="id_a(?:_0|-0-value-b)_error"')

    def test_mapping_row_error_via_whole_value(self) -> None:
        """A missing required child in a whole-value mapping row shows its error."""
        self.assertMappingRowError(RequiredBCSequenceForm({"a": [{"b": 2}, {"c": 3}]}))

    def test_mapping_row_error_via_querydict(self) -> None:
        """A missing required child in a prefixed-row mapping row shows its error."""
        self.assertMappingRowError(
            RequiredBCSequenceForm(
                TestQueryDict.from_dict(
                    {
                        f"a-{TOTAL_FORM_COUNT}": "2",
                        f"a-{INITIAL_FORM_COUNT}": "2",
                        "a-0-value-b": "2",
                        "a-1-value-c": "3",
                    }
                )
            )
        )

    def test_mapping_rows_valid_via_whole_value(self) -> None:
        """A valid whole-value mapping row list renders and cleans every child."""
        self.assertMappingRowsValid(OptionalBCSequenceForm({"a": [{"b": 2}, {"c": 3}]}))

    def test_mapping_rows_valid_via_querydict(self) -> None:
        """A valid prefixed-row mapping row list renders and cleans every child."""
        self.assertMappingRowsValid(
            OptionalBCSequenceForm(
                TestQueryDict.from_dict(
                    {
                        f"a-{TOTAL_FORM_COUNT}": "2",
                        f"a-{INITIAL_FORM_COUNT}": "2",
                        "a-0-value-b": "2",
                        "a-1-value-c": "3",
                    }
                )
            )
        )

    def test_mapping_row_with_no_keys_via_whole_value(self) -> None:
        """An empty-dict whole-value row is real data, not an untouched placeholder."""
        self.assertKeylessRowIsRequired(RequiredBSequenceForm({"a": [{}]}))

    def test_mapping_row_with_no_keys_via_querydict(self) -> None:
        """A declared row with no submitted keys is real data too, not skippable."""
        self.assertKeylessRowIsRequired(
            RequiredBSequenceForm(
                TestQueryDict.from_dict(
                    {
                        f"a-{TOTAL_FORM_COUNT}": "1",
                        f"a-{INITIAL_FORM_COUNT}": "1",
                    }
                )
            )
        )


class SequenceFieldNestedListRowTestCase(CompositeFieldTestCase):
    """A leaf two levels deep inside a nested list validates the same in either style.

    The same regression guard as for a mapping row, one nesting level
    deeper: a whole ``SequenceField(SequenceField(...))`` value's inner
    row error must still render inline, not just clean correctly.
    """

    def assertNestedLeafError(self, form: object) -> None:  # noqa: D102
        self.assertFormInvalid(form)
        self.assertBoundFieldErrors(form, "outer", [])
        html = form.as_p()
        self.assertRenderedMessageCount(html, "Enter a whole number.")
        self.assertErrorReferenceResolves(html, "id_outer_0_1_error")
        self.assertErrorElementIsAbsent(html, "id_outer_0_error")
        self.assertIn('name="outer-0-value-1-value" value="bad"', html)

    def test_nested_list_leaf_error_via_whole_value(self) -> None:
        """A bad leaf two levels deep in a whole-value nested list still shows its error."""
        self.assertNestedLeafError(NestedIntegerSequenceForm({"outer": [[1, "bad"]]}))

    def test_nested_list_leaf_error_via_querydict(self) -> None:
        """A bad leaf two levels deep in a prefixed-row nested list still shows its error."""
        self.assertNestedLeafError(
            NestedIntegerSequenceForm(
                TestQueryDict.from_dict(
                    {
                        f"outer-{TOTAL_FORM_COUNT}": "1",
                        f"outer-{INITIAL_FORM_COUNT}": "1",
                        f"outer-0-value-{TOTAL_FORM_COUNT}": "2",
                        f"outer-0-value-{INITIAL_FORM_COUNT}": "2",
                        "outer-0-value-0-value": "1",
                        "outer-0-value-1-value": "bad",
                    }
                )
            )
        )

    def test_nested_list_direct_scalar_is_invalid_sequence_input(self) -> None:
        """A direct nested scalar is not coerced into one inner row."""
        form = NestedIntegerSequenceForm(
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                "outer-0-value": "1",
            }
        )
        self.assertFormInvalid(form)
        error = form.errors.as_data()["outer"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "invalid")


class SequenceFieldNestedParserRegressionTestCase(CompositeFieldTestCase):
    """Tests request parser edge cases.

    Text indexes do not bind rows. An unknown mapping initial stays one
    renderable row.
    """

    def test_unrecognized_mapping_initial_becomes_one_renderable_row(self) -> None:
        """A mapping that is not flattened sequence data remains one raw row."""
        value = {"unexpected": "saved"}
        form = OptionalRequiredTextSequenceForm(initial={"values": value})

        self.assertEqual(form["values"].initial, [value])
        self.assertIn("unexpected", str(form["values"]))

    def assertTextIndexDoesNotBind(self, data: object) -> None:  # noqa: D102

        form = SequenceForm(data)
        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "values", "required")

    def test_bracket_text_index_does_not_bind(self) -> None:
        """A bracket text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values[text]": "1"})

    def test_dot_text_index_does_not_bind(self) -> None:
        """A dot text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values.text": "1"})

    def test_nested_bracket_text_index_does_not_bind(self) -> None:
        """A nested bracket text index does not bind a sequence row."""
        self.assertTextIndexDoesNotBind({"values[text][a]": "1"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
