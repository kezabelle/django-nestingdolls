"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class SequenceFieldRowFormClassTestCase(CompositeFieldTestCase):
    """What a deep copy of a nested sequence field shares, and what it does not.

    ``SequenceField.__deepcopy__`` keeps the row formset class that the
    source widget cached, instead of a rebuild of two classes for each
    row. These tests hold the lines that make that sharing safe.
    """

    def test_row_field_copies_share_one_row_formset_class(self) -> None:
        """Every row's field copy shares one cached row formset class.

        The shared class is the performance contract: without it, each
        nested row form builds two new classes. The row fields and their
        widgets must stay distinct objects, so no row shares mutable
        state with another row.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        form = Form(
            {
                "values-TOTAL_FORMS": "2",
                "values-INITIAL_FORMS": "0",
                "values-0-TOTAL_FORMS": "1",
                "values-0-INITIAL_FORMS": "0",
                "values-0-0": "a",
                "values-1-TOTAL_FORMS": "1",
                "values-1-INITIAL_FORMS": "0",
                "values-1-0": "b",
            }
        )
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [["a"], ["b"]])

        first, second = (row.fields["value"] for row in form["values"].formset.forms)
        self.assertIsNot(first, second)
        self.assertIsNot(first.widget, second.widget)
        self.assertIsNot(first.child_field, second.child_field)
        self.assertIs(first.widget.formset_class, second.widget.formset_class)

    def test_a_new_child_field_assignment_rebuilds_the_class(self) -> None:
        """A widget assigned a new child field builds a new class.

        The deep-copy path keeps the cached class only because its new
        child is a copy of the field that the class names. A
        ``child_field`` assignment brings a child with no such relation,
        so the setter must remove the cache, or the widget builds rows
        from the old child field.
        """
        field = nestingdolls.ListField(forms.CharField(), required=False)
        widget = field.widget
        old_class = widget.formset_class
        self.assertIs(old_class.form.base_fields["value"], field.child_field)

        new_child = forms.IntegerField()
        widget.child_field = new_child

        self.assertIsNot(widget.formset_class, old_class)
        self.assertIs(widget.formset_class.form.base_fields["value"], new_child)

    def test_a_child_field_change_on_one_form_reaches_its_rows(self) -> None:
        """A change to one form's child field changes that form's own rows.

        The shared class must not cross form instances. Each form's rows
        must come from that form's own child field chain, so a per-form
        change stays visible, and one form cannot leak configuration
        into another form of the same class.

        The form class is local to this test. The scope of the sharing is
        what this test measures, so no other test may touch this class.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        payload = {
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
            "values-0-TOTAL_FORMS": "1",
            "values-0-INITIAL_FORMS": "0",
            "values-0-0": "  padded  ",
        }
        # Complete one form lifecycle first. Sharing that crossed form
        # instances would then be observable in the second form.
        first = Form(payload)
        self.assertFormValid(first)
        self.assertEqual(first.cleaned_data["values"], [["padded"]])

        second = Form(payload)
        second.fields["values"].child_field.child_field.strip = False
        self.assertFormValid(second)
        self.assertEqual(second.cleaned_data["values"], [["  padded  "]])


class SequenceFieldConfigurationTestCase(SimpleTestCase):
    """Tests public constructor contracts.

    Invalid limits, child fields, widgets, and bound field classes are refused.
    """

    def test_constructor_bounds_are_enforced(self) -> None:
        """It refuses limit and initial combinations the field cannot satisfy."""
        self.assertEqual(
            nestingdolls.ListField(forms.IntegerField(), initial=range(2)).initial,
            range(2),
        )
        with self.assertRaises(nestingdolls.SequenceInputValidationError):
            nestingdolls.ListField(forms.IntegerField()).clean("not a list")

        with self.assertRaisesMessage(
            ValueError, "max_length=0 requires required=False"
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=0)
        with self.assertRaisesMessage(
            ValueError, "max_length must be greater than or equal to min_length"
        ):
            nestingdolls.ListField(forms.IntegerField(), min_length=5, max_length=2)
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=1, initial=[1, 2])
        with self.assertRaisesMessage(
            ValueError, "'absolute_max' must be greater or equal to 'max_length'."
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=2, absolute_max=1)

    def test_constructor_rejects_negative_min_length(self) -> None:
        """The constructor rejects a negative minimum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=-1)

    def test_constructor_rejects_negative_max_length(self) -> None:
        """The constructor rejects a negative maximum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=-1)

    def test_constructor_rejects_max_length_below_min_length(self) -> None:
        """The constructor rejects a maximum length below the minimum."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=2, max_length=1)

    def test_scalar_initial_becomes_one_row(self) -> None:
        """A scalar initial wraps into one row instead of raising."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), initial=5)

        constructor_html = Form().as_p()
        keyword_html = Form(initial={"values": 5}).as_p()

        self.assertIn('value="5"', constructor_html)
        self.assertIn('name="values-TOTAL_FORMS" value="1"', constructor_html)
        self.assertEqual(constructor_html, keyword_html)

    def test_rejects_non_fields_and_legacy_widget_usage(self) -> None:
        """It rejects invalid child fields and legacy widget configuration."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)
        with self.assertRaises(TypeError):
            nestingdolls.SequenceWidget(child_field=forms.IntegerField())
        with self.assertRaises(TypeError):
            nestingdolls.MappingWidget(form_class=forms.Form)

    def test_constructor_rejects_a_foreign_bound_field_class(self) -> None:
        """The constructor rejects a bound field class with a wrong base class."""
        with self.assertRaises(TypeError):
            nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=forms.BoundField
            )

    def test_widget_instance_is_copied_and_rebound_to_field_configuration(
        self,
    ) -> None:
        """Django copies a supplied widget before the field configures it."""
        widget = nestingdolls.SequenceWidget()

        field = nestingdolls.ListField(
            forms.IntegerField(),
            min_length=1,
            max_length=2,
            absolute_max=3,
            widget=widget,
        )

        self.assertIsNot(field.widget, widget)
        self.assertIs(field.widget.child_field, field.child_field)
        self.assertEqual(field.widget.limits.min_length, 1)
        self.assertEqual(field.widget.limits.max_length, 2)
        self.assertEqual(field.limits.absolute_max, 3)
        self.assertIs(field.widget.limits, field.limits)

    def test_a_reused_widget_rebuilds_for_its_new_field(self) -> None:
        """A reused widget's new field builds a class from its own child."""
        first = nestingdolls.ListField(forms.CharField(), required=False)
        stale = first.widget.formset_class

        second = nestingdolls.ListField(
            forms.IntegerField(), required=False, widget=first.widget
        )

        self.assertIsNot(second.widget.formset_class, stale)
        self.assertIs(
            second.widget.formset_class.form.base_fields["value"], second.child_field
        )
        self.assertIs(first.widget.formset_class, stale)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
