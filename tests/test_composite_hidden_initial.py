"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import QueryDict
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils.datastructures import MultiValueDict

import nestingdolls

from .support.forms.sequence import (
    HiddenInitialIntegerSequenceForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class CompositeHiddenInitialRenderingTestCase(CompositeFieldTestCase):
    """These tests check composite hidden initial rendering."""

    def matching_hidden_initial_data(self) -> QueryDict:
        """Return a submission whose row equals the hidden initial row."""
        return QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0-value=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&"
            f"initial-values-{MIN_NUM_FORM_COUNT}=0&"
            f"initial-values-{MAX_NUM_FORM_COUNT}=1000&initial-values-0-value=1"
        )

    def test_matching_hidden_initial_is_unchanged(self) -> None:
        """A submitted row equal to its hidden initial row is not a change."""
        form = HiddenInitialIntegerSequenceForm(self.matching_hidden_initial_data())

        self.assertIs(form.has_changed(), False)

    def test_hidden_initial_renders_management_and_row_inputs(self) -> None:
        """The hidden initial renders four management inputs and one row input."""
        html = HiddenInitialIntegerSequenceForm(
            self.matching_hidden_initial_data()
        ).as_p()

        self.assertInHTML(
            '<input type="hidden" name="initial-values-TOTAL_FORMS" value="1" id="id_initial-values-TOTAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-INITIAL_FORMS" value="1" id="id_initial-values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MIN_NUM_FORMS" value="0" id="id_initial-values-MIN_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MAX_NUM_FORMS" value="1000" id="id_initial-values-MAX_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0-value" value="1" id="id_initial-values_0">',
            html,
        )

    def test_malformed_hidden_initial_is_changed(self) -> None:
        """A hidden initial row that its child cannot read counts as a change."""
        malformed_initial = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0-value=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&initial-values-0-value=not-an-integer"
        )

        self.assertIs(
            HiddenInitialIntegerSequenceForm(malformed_initial).has_changed(), True
        )

    def test_changed_row_differs_from_hidden_initial(self) -> None:
        """A submitted row that differs from its hidden initial row is a change."""
        changed = self.matching_hidden_initial_data().copy()
        changed["values-0-value"] = "2"

        self.assertIs(HiddenInitialIntegerSequenceForm(changed).has_changed(), True)

    def test_legacy_exact_hidden_initial_round_trips(self) -> None:
        """A hidden initial sent as one repeated exact value still compares equal."""
        legacy = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0-value=1",
            mutable=True,
        )
        legacy.setlist("initial-values", ["1"])

        self.assertIs(HiddenInitialIntegerSequenceForm(legacy).has_changed(), False)

    def test_invalid_redisplay_preserves_hidden_initial(self) -> None:
        """An invalid redisplay keeps the hidden initial row the browser sent."""
        invalid = HiddenInitialIntegerSequenceForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-value=bad&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0-value=7"
            )
        )
        self.assertFormInvalid(invalid)
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0-value" value="7" id="id_initial-values_0">',
            invalid.as_p(),
        )

    def test_hidden_initial_ids_ignore_the_parent_auto_id(self) -> None:
        """Hidden initial rows and management inputs share the default ID scheme."""
        for auto_id in ("custom_%s", False):
            with self.subTest(auto_id=auto_id):
                html = HiddenInitialIntegerSequenceForm(auto_id=auto_id).as_p()
                self.assertInHTML(
                    '<input type="hidden" name="initial-values-TOTAL_FORMS" value="1" id="id_initial-values-TOTAL_FORMS">',
                    html,
                )
                self.assertInHTML(
                    '<input type="hidden" name="initial-values-0-value" value="1" id="id_initial-values_0">',
                    html,
                )

    def assertSequenceCollectionHiddenInitialIsUnchanged(  # noqa: D102
        self, field_class: object, initial: object
    ) -> None:

        class Form(forms.Form):
            values = field_class(
                forms.IntegerField(),
                initial=initial,
                show_hidden_initial=True,
            )

        form = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-value=1&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0-value=1"
            )
        )
        self.assertIs(form.has_changed(), False)

    def test_list_hidden_initial_round_trips_integer_child(self) -> None:
        """A list hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.ListField, [1]
        )

    def test_tuple_hidden_initial_round_trips_integer_child(self) -> None:
        """A tuple hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.TupleField, (1,)
        )

    def test_set_hidden_initial_round_trips_integer_child(self) -> None:
        """A set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.SetField, {1}
        )

    def test_frozen_set_hidden_initial_round_trips_integer_child(self) -> None:
        """A frozen set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.FrozenSetField, frozenset({1})
        )

    def test_compound_child_renders_every_subwidget_as_hidden_initial(self) -> None:
        """A compound child hides each subwidget of its hidden initial."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(),
                initial=[datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)],
                show_hidden_initial=True,
            )

        html = CompoundForm().as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0-value_0" value="2024-01-02" id="id_initial-values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0-value_1" value="03:04:05" id="id_initial-values_0_1">',
            html,
        )

    def test_compound_hidden_initial_is_unchanged_after_a_round_trip(self) -> None:
        """A compound row equal to its hidden initial parts is not a change."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(),
                initial=[datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)],
                show_hidden_initial=True,
            )

        compound = CompoundForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&"
                "values-0-value_0=2024-01-02&values-0-value_1=03%3A04%3A05&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&"
                "initial-values-0-value_0=2024-01-02&"
                "initial-values-0-value_1=03%3A04%3A05"
            )
        )

        self.assertIs(compound.has_changed(), False)

    def file_hidden_initial_form(
        self, data: object = None, files: object = None
    ) -> forms.Form:
        """Return a form whose file child holds the saved file ``saved.txt``."""

        class FileForm(forms.Form):
            files = nestingdolls.ListField(
                forms.FileField(required=False),
                initial=["saved.txt"],
                required=False,
                show_hidden_initial=True,
            )

        return FileForm(data, files)

    def test_file_child_hidden_initial_renders_the_filename_text(self) -> None:
        """A file child renders its saved filename as its hidden initial text."""
        html = self.file_hidden_initial_form().as_p()

        self.assertInHTML(
            '<input type="hidden" name="initial-files-0-value" value="saved.txt" id="id_initial-files_0">',
            html,
        )

    def test_file_child_upload_is_a_change_from_the_hidden_initial(self) -> None:
        """An uploaded replacement file differs from the saved hidden initial."""
        upload = SimpleUploadedFile("replacement.txt", b"replacement")
        form = self.file_hidden_initial_form(
            QueryDict(
                "files-TOTAL_FORMS=1&files-INITIAL_FORMS=1&"
                "initial-files-TOTAL_FORMS=1&initial-files-INITIAL_FORMS=1&"
                "initial-files-0-value=saved.txt"
            ),
            MultiValueDict({"files-0-value": [upload]}),
        )

        self.assertIs(form.has_changed(), True)

    def test_file_child_hidden_initial_reaches_the_child_comparison(self) -> None:
        """A file child compares its posted hidden filename, not ``None``.

        Django's ``FileField.has_changed`` ignores its initial value, so this
        child reads it.
        """

        class SavedNameFileField(forms.FileField):
            def has_changed(self, initial: object, data: object) -> bool:
                return initial != "saved.txt"

        class FileForm(forms.Form):
            files = nestingdolls.ListField(
                SavedNameFileField(required=False),
                initial=["saved.txt"],
                required=False,
                show_hidden_initial=True,
            )

        form = FileForm(
            QueryDict(
                "files-TOTAL_FORMS=1&files-INITIAL_FORMS=1&"
                "initial-files-TOTAL_FORMS=1&initial-files-INITIAL_FORMS=1&"
                "initial-files-0-value=saved.txt"
            )
        )

        self.assertIs(form.has_changed(), False)

    def test_hidden_initial_recurses_through_nested_composites(self) -> None:
        """Hidden initial parsing recurses through alternating composites."""

        class PointForm(forms.Form):
            a = forms.IntegerField()

        class SequenceOfMappingsForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                initial=[{"a": 1}],
                show_hidden_initial=True,
            )

        html = SequenceOfMappingsForm().as_p()
        self.assertNotIn("{&#x27;a&#x27;: 1}", html)
        self.assertIn('name="initial-values-TOTAL_FORMS"', html)
        self.assertIn('name="initial-values-0-value-a"', html)

        rows = SequenceOfMappingsForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-value-a=1&"
                "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
                "initial-values-MIN_NUM_FORMS=0&initial-values-MAX_NUM_FORMS=1000&"
                "initial-values-0-value-a=1"
            )
        )
        self.assertIs(rows.has_changed(), False)

        class ContainerForm(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        class MappingOfSequenceForm(forms.Form):
            container = nestingdolls.MappingField(
                ContainerForm,
                initial={"rows": [{"a": 1}]},
                show_hidden_initial=True,
            )

        container_html = MappingOfSequenceForm().as_p()
        self.assertIn('name="initial-container-rows-TOTAL_FORMS"', container_html)
        self.assertIn('name="initial-container-rows-0-value-a"', container_html)

        container = MappingOfSequenceForm(
            QueryDict(
                "container-rows-TOTAL_FORMS=1&"
                "container-rows-INITIAL_FORMS=0&container-rows-0-value-a=1&"
                "initial-container-rows-TOTAL_FORMS=1&"
                "initial-container-rows-INITIAL_FORMS=1&"
                "initial-container-rows-0-value-a=1"
            )
        )
        self.assertIs(container.has_changed(), False)

    def test_exact_input_compares_against_the_submitted_hidden_initial(self) -> None:
        """Exact input compares with the hidden initial that the browser sent.

        The page rendered ``[1]``, the user sent ``[1]`` back, and the server
        initial then became ``[2]``. The user changed nothing.
        """
        data = QueryDict(
            "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
            "initial-values-0-value=1",
            mutable=True,
        )
        data.setlist("values", ["1"])

        form = HiddenInitialIntegerSequenceForm(data, initial={"values": [2]})

        self.assertIs(form.has_changed(), False)

    def test_deleted_row_compares_against_the_submitted_hidden_initial(self) -> None:
        """A deleted row is a change when the hidden initial holds that row.

        The page rendered ``[1]``, the user deleted that row, and the server
        initial then became ``[]``.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, show_hidden_initial=True
            )

        form = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=1&values-0-value=1&"
                "values-0-DELETE=on&"
                "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
                "initial-values-0-value=1"
            ),
            initial={"values": []},
        )

        self.assertIs(form.has_changed(), True)
        self.assertEqual(form.changed_data, ["values"])

    def test_nested_sequence_deletion_changes_a_hidden_initial_mapping(self) -> None:
        """A row deleted in a nested sequence changes the outer mapping.

        The mapping values still equal the hidden initial. Only the nested
        row formset knows about the deletion.
        """

        class ChildForm(forms.Form):
            rows = nestingdolls.ListField(forms.IntegerField(), required=False)

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm, show_hidden_initial=True)

        form = Form(
            QueryDict(
                "value-rows-TOTAL_FORMS=1&value-rows-INITIAL_FORMS=1&"
                "value-rows-0-value=1&value-rows-0-DELETE=on&"
                "initial-value-rows-TOTAL_FORMS=1&"
                "initial-value-rows-INITIAL_FORMS=1&initial-value-rows-0-value=1"
            ),
            initial={"value": {"rows": [1]}},
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["value"], {"rows": []})
        self.assertEqual(form.changed_data, ["value"])

    def test_nested_sequence_deletion_changes_a_hidden_initial_sequence(
        self,
    ) -> None:
        """A row deleted in a nested sequence changes the outer sequence.

        The outer rows still equal the hidden initial. Only the nested row
        formset knows about the deletion.
        """

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False),
                show_hidden_initial=True,
            )

        form = Form(
            QueryDict(
                "outer-TOTAL_FORMS=1&outer-INITIAL_FORMS=1&"
                "outer-0-value-TOTAL_FORMS=1&outer-0-value-INITIAL_FORMS=1&outer-0-value-0-value=1&"
                "outer-0-value-0-DELETE=on&"
                "initial-outer-TOTAL_FORMS=1&initial-outer-INITIAL_FORMS=1&"
                "initial-outer-0-value-TOTAL_FORMS=1&initial-outer-0-value-INITIAL_FORMS=1&"
                "initial-outer-0-value-0-value=1"
            ),
            initial={"outer": [[1]]},
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["outer"], [[]])
        self.assertEqual(form.changed_data, ["outer"])

    def test_hidden_initial_markup_is_minimal_in_every_layout(self) -> None:
        """Every layout renders each hidden sequence input once and nothing else."""
        for layout in ("as_p", "as_div", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                html = getattr(HiddenInitialIntegerSequenceForm(), layout)()
                self.assertEqual(html.count('name="initial-values-0-value"'), 1)
                self.assertEqual(html.count('id="id_initial-values_0"'), 1)
                for name in (
                    TOTAL_FORM_COUNT,
                    INITIAL_FORM_COUNT,
                    MIN_NUM_FORM_COUNT,
                    MAX_NUM_FORM_COUNT,
                ):
                    self.assertEqual(html.count(f'name="initial-values-{name}"'), 1)
                self.assertNotIn('name="initial-values-0-DELETE"', html)
                self.assertNotIn('name="initial-values-__prefix__"', html)
                self.assertNotIn('data-sequence-field="initial-values"', html)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
