"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
    MappingFormBindingUnitTestCase,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class MappingNestedSequenceChildTestCase(MappingFormBindingUnitTestCase):
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
        self.assertInHTML(
            '<span class="errorlist" id="id_point-tags_1_error">Enter a whole number.</span>',
            html,
        )

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


class MappingSequenceOfRecordsTestCase(MappingFormBindingUnitTestCase):
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
        self.assertInHTML(
            '<span class="errorlist" id="id_payload-records-1-name_error">This field is required.</span>',
            html,
        )
        self.assertInHTML(
            '<span class="errorlist" id="id_payload-records_1_error">This field is required.</span>',
            html,
        )

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
