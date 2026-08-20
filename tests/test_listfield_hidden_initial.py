"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    MultiValueDict,
    QueryDict,
    SimpleTestCase,
    SimpleUploadedFile,
    datetime,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class CompositeHiddenInitialRenderingTestCase(SimpleTestCase):
    """These tests check composite hidden initial rendering."""

    def test_hidden_initial_markup_and_change_detection(self):
        """Hidden initial rows drive change detection and survive an invalid redisplay."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&"
            f"initial-values-{MIN_NUM_FORM_COUNT}=0&"
            f"initial-values-{MAX_NUM_FORM_COUNT}=1000&initial-values-0=1"
        )
        form = Form(data)

        self.assertIs(form.has_changed(), False)
        html = form.as_p()
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
            '<input type="hidden" name="initial-values-0" value="1" id="initial-id_values_0">',
            html,
        )

        malformed_initial = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&initial-values-0=not-an-integer"
        )
        self.assertIs(Form(malformed_initial).has_changed(), True)

        changed = data.copy()
        changed["values-0"] = "2"
        self.assertIs(Form(changed).has_changed(), True)

        legacy = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        legacy.setlist("initial-values", ["1"])
        self.assertIs(Form(legacy).has_changed(), False)

        invalid = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=bad&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=7"
            )
        )
        self.assertIs(invalid.is_valid(), False)
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0" value="7" id="initial-id_values_0">',
            invalid.as_p(),
        )

    def assertSequenceCollectionHiddenInitialIsUnchanged(self, field_class, initial):
        class Form(forms.Form):
            values = field_class(
                forms.IntegerField(),
                initial=initial,
                show_hidden_initial=True,
            )

        form = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=1&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=1"
            )
        )
        self.assertIs(form.has_changed(), False)

    def test_list_hidden_initial_round_trips_integer_child(self):
        """A list hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.ListField, [1]
        )

    def test_tuple_hidden_initial_round_trips_integer_child(self):
        """A tuple hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.TupleField, (1,)
        )

    def test_set_hidden_initial_round_trips_integer_child(self):
        """A set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.SetField, {1}
        )

    def test_frozen_set_hidden_initial_round_trips_integer_child(self):
        """A frozen set hidden initial keeps one integer child unchanged."""
        self.assertSequenceCollectionHiddenInitialIsUnchanged(
            nestingdolls.FrozenSetField, frozenset({1})
        )

    def test_compound_and_file_children_use_their_own_hidden_widgets(self):
        """A compound child hides every subwidget; a file child hides no filename."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(),
                initial=[datetime(2024, 1, 2, 3, 4, 5)],
                show_hidden_initial=True,
            )

        html = CompoundForm().as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_0" value="2024-01-02" id="initial-id_values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_1" value="03:04:05" id="initial-id_values_0_1">',
            html,
        )

        compound = CompoundForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&"
                "values-0_0=2024-01-02&values-0_1=03%3A04%3A05&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&"
                "initial-values-0_0=2024-01-02&"
                "initial-values-0_1=03%3A04%3A05"
            )
        )
        self.assertIs(compound.has_changed(), False)

        class FileForm(forms.Form):
            files = nestingdolls.ListField(
                forms.FileField(required=False),
                initial=["saved.txt"],
                required=False,
                show_hidden_initial=True,
            )

        data = QueryDict(
            "files-TOTAL_FORMS=1&files-INITIAL_FORMS=1&"
            "initial-files-TOTAL_FORMS=1&initial-files-INITIAL_FORMS=1&"
            "initial-files-0=saved.txt"
        )
        self.assertIs(FileForm(data).has_changed(), False)

        upload = SimpleUploadedFile("replacement.txt", b"replacement")
        uploaded = FileForm(data, files=MultiValueDict({"files-0": [upload]}))
        self.assertIs(uploaded.has_changed(), True)

    def test_hidden_initial_recurses_through_nested_composites(self):
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
        self.assertIn('name="initial-values-0-a"', html)

        rows = SequenceOfMappingsForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-a=1&"
                "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
                "initial-values-MIN_NUM_FORMS=0&initial-values-MAX_NUM_FORMS=1000&"
                "initial-values-0-a=1"
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
        self.assertIn('name="initial-container-rows-0-a"', container_html)

        container = MappingOfSequenceForm(
            QueryDict(
                "container-rows-TOTAL_FORMS=1&"
                "container-rows-INITIAL_FORMS=0&container-rows-0-a=1&"
                "initial-container-rows-TOTAL_FORMS=1&"
                "initial-container-rows-INITIAL_FORMS=1&"
                "initial-container-rows-0-a=1"
            )
        )
        self.assertIs(container.has_changed(), False)

    def assertHiddenSequenceMarkupIsMinimal(self, html):
        self.assertEqual(html.count('name="initial-values-0"'), 1)
        self.assertEqual(html.count('id="initial-id_values_0"'), 1)
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

    def test_hidden_initial_markup_is_minimal_with_as_p(self):
        """The paragraph helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_p())

    def test_hidden_initial_markup_is_minimal_with_as_div(self):
        """The div helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_div())

    def test_hidden_initial_markup_is_minimal_with_as_ul(self):
        """The list helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_ul())

    def test_hidden_initial_markup_is_minimal_with_as_table(self):
        """The table helper keeps hidden sequence markup minimal."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        self.assertHiddenSequenceMarkupIsMinimal(Form().as_table())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
