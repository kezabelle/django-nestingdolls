"""Tests shared by sequence and mapping fields.

Each test names the concrete ``ListField`` or ``DictField`` behavior it covers.
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


def setUpModule() -> None:
    """Set up the module test environment."""
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class CompositeBoundFieldPreparationTestCase(SimpleTestCase):
    """Make sure composite bound fields prepare supplied widgets correctly."""

    def test_a_mapping_bound_field_accepts_a_normal_widget(self) -> None:
        """A mapping bound field accepts a normal widget."""
        html = RequiredMappingPointForm()["point"].as_widget(forms.TextInput())

        self.assertIn('name="point"', html)

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
