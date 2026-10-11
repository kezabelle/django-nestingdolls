"""Tests shared by sequence and mapping fields.

Each test names the concrete ``SequenceField`` or ``MappingField`` behavior.
Tests for one field family belong in its own test module.
"""

from __future__ import annotations

import unittest

import django
from django import forms
from django.conf import settings
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls
from nestingdolls.boundfield import CompositeBoundField

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
from .support.forms.composite import (
    CompositePointAndSequenceForm,
)
from .support.forms.mapping import (
    MappingPointForm,
    RequiredMappingPointForm,
)
from .support.forms.sequence import (
    SequenceForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class CompositeBoundFieldPreparationTestCase(SimpleTestCase):
    """Make sure composite bound fields prepare supplied widgets correctly."""

    def test_a_normal_widget_renders_the_submitted_mapping(self) -> None:
        """A normal widget shows the submitted mapping, not the initial one."""
        form = RequiredMappingPointForm(
            {"point-a": "9", "point-label": "new"},
            initial={"point": {"a": 1, "label": "old"}},
        )

        html = form["point"].as_widget(forms.TextInput())

        self.assertInHTML(
            '<input type="text" name="point" value="{&#x27;a&#x27;: &#x27;9&#x27;, &#x27;label&#x27;: &#x27;new&#x27;}" required id="id_point">',
            html,
        )

    def test_a_normal_widget_renders_the_submitted_rows(self) -> None:
        """A normal widget shows the submitted rows, not the initial rows."""
        form = SequenceForm(
            {
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "1",
                "values-0-value": "9",
            },
            initial={"values": [1]},
        )

        html = form["values"].as_widget(forms.TextInput())

        self.assertInHTML(
            '<input type="text" name="values" value="[&#x27;9&#x27;]" required id="id_values">',
            html,
        )

    def test_the_base_bound_field_does_not_change_a_disabled_field(self) -> None:
        """The base bound field does not change a disabled field."""

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm, disabled=True, show_hidden_initial=True
            )

        form = Form({"initial-point-a": "bad"})

        self.assertIs(
            CompositeBoundField(form, form.fields["point"], "point")._has_changed(),
            False,
        )

    def test_a_mapping_bound_field_clears_a_sequence_widget_state(self) -> None:
        """A mapping bound field clears a sequence widget state."""
        form = CompositePointAndSequenceForm()
        widget = form.fields["values"].widget
        widget.render_state = widget.RenderState(submission_overflow=True)
        form["point"].prepare_widget(widget)

        self.assertEqual(widget.render_state, widget.RenderState())

    def test_a_sequence_bound_field_clears_a_mapping_widget_state(self) -> None:
        """A sequence bound field clears a mapping widget state."""
        form = CompositePointAndSequenceForm()
        widget = form.fields["point"].widget
        widget.render_state = widget.RenderState(initial_error="bad")
        form["values"].prepare_widget(widget)

        self.assertEqual(widget.render_state, widget.RenderState())


class CompositeBoundFieldCssClassesTestCase(CompositeFieldTestCase):
    """Make sure composite bound fields apply CSS classes like ordinary fields."""

    def child_failure_forms(self) -> dict[str, tuple[forms.Form, str]]:
        """Return one form per composite family whose only failure is in a child."""

        class MappingForm(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            point = nestingdolls.DictField(MappingPointForm)
            plain = forms.CharField()

        class SequenceFieldForm(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            values = nestingdolls.ListField(forms.IntegerField())
            plain = forms.CharField()

        return {
            "mapping": (
                MappingForm({"point-label": "missing a", "plain": ""}),
                "point",
            ),
            "sequence": (
                SequenceFieldForm(
                    {
                        "values-TOTAL_FORMS": "1",
                        "values-INITIAL_FORMS": "0",
                        "values-0-value": "bad",
                        "plain": "",
                    }
                ),
                "values",
            ),
        }

    def test_string_extra_classes_match_an_ordinary_field(self) -> None:
        """A space-separated extra class string is applied once, as for any field."""
        for family, (form, name) in self.child_failure_forms().items():
            with self.subTest(family=family):
                self.assertFormInvalid(form)
                self.assertCssClassesMatchBaseline(
                    form[name], form["plain"], "mine yours"
                )

    def test_iterable_extra_classes_match_an_ordinary_field(self) -> None:
        """An iterable of extra classes is applied once each, as for any field."""
        for family, (form, name) in self.child_failure_forms().items():
            with self.subTest(family=family):
                self.assertFormInvalid(form)
                self.assertCssClassesMatchBaseline(
                    form[name], form["plain"], ["mine", "yours"]
                )

    def test_child_only_failure_renders_each_error_class_once(self) -> None:
        """A child-only failure marks the composite once, beside the failed plain field."""
        for family, (form, _name) in self.child_failure_forms().items():
            with self.subTest(family=family):
                self.assertFormInvalid(form)
                self.assertRenderedMessageCount(form.as_div(), "has-error", 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
