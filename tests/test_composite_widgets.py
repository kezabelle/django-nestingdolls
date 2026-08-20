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
from nestingdolls.widgets import CompositeWidget

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


def setUpModule():
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class PointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


class CompositeWidgetSharedBehaviorTestCase(SimpleTestCase):
    """These tests check shared composite widget state and media."""

    def test_child_widgets_are_not_shared_between_form_instances(self):
        """One form does not share cached child widgets with another form.

        ``Widget.__deepcopy__`` is shallow. A shared cached widget can retain
        request state.
        """

        class ItemForm(forms.Form):
            f = forms.CharField()

        class Form(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.DictField(ItemForm))

        first, second = Form(), Form()
        for form in (first, second):
            # Warm the child cache the way a render does.
            self.assertIs(form.fields["rows"].widget.is_hidden, False)

        self.assertIsNot(
            first.fields["rows"].widget.child_field.widget.fields["f"].widget,
            second.fields["rows"].widget.child_field.widget.fields["f"].widget,
        )

    def test_the_base_widget_defers_keys_and_media_to_subclasses(self):
        """The base widget has no key test and no child media of its own."""
        widget = CompositeWidget()
        with self.assertRaises(NotImplementedError):
            widget.value_omitted_from_data({"point": "1"}, {}, "point")
        with self.assertRaises(NotImplementedError):
            str(widget.media)

    def test_widget_media_merges_every_declaration_in_the_mro(self):
        """A widget subclass adds media without removing inherited media.

        Both composite widgets define ``media``. They must merge subclass media
        themselves.
        """

        class ExtraSequenceWidget(nestingdolls.SequenceWidget):
            class Media:
                js = ("extra-sequence.js",)

        class ExtraMappingWidget(nestingdolls.MappingWidget):
            class Media:
                js = ("extra-mapping.js",)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), widget=ExtraSequenceWidget
            )
            point = nestingdolls.DictField(PointForm, widget=ExtraMappingWidget)

        media = str(Form().media)
        self.assertIn("nestingdolls/sequence.js", media)
        self.assertIn("extra-sequence.js", media)
        self.assertIn("extra-mapping.js", media)


class CompositeBoundFieldTestCase(SimpleTestCase):
    """Make sure composite bound fields prepare supplied widgets correctly."""

    def test_a_mapping_bound_field_accepts_a_normal_widget(self):
        """A mapping bound field accepts a normal widget."""

        class Form(forms.Form):
            point = nestingdolls.DictField(PointForm)

        html = Form()["point"].as_widget(forms.TextInput())

        self.assertIn('name="point"', html)

    def test_the_base_bound_field_does_not_change_a_disabled_field(self):
        """The base bound field does not change a disabled field."""

        class Form(forms.Form):
            point = nestingdolls.DictField(
                PointForm, disabled=True, show_hidden_initial=True
            )

        form = Form({"initial-point-a": "bad"})

        self.assertIs(
            CompositeBoundField(form, form.fields["point"], "point")._has_changed(),
            False,
        )

    def test_a_mapping_bound_field_clears_a_sequence_widget_state(self):
        """A mapping bound field clears a sequence widget state."""

        class Form(forms.Form):
            point = nestingdolls.DictField(PointForm)
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form()
        widget = form.fields["values"].widget
        widget.render_state = widget.RenderState(submission_overflow=True)
        form["point"].prepare_widget(widget)

        self.assertEqual(widget.render_state, widget.RenderState())

    def test_a_sequence_bound_field_clears_a_mapping_widget_state(self):
        """A sequence bound field clears a mapping widget state."""

        class Form(forms.Form):
            point = nestingdolls.DictField(PointForm)
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form()
        widget = form.fields["point"].widget
        widget.render_state = widget.RenderState(initial_error="bad")
        form["values"].prepare_widget(widget)

        self.assertEqual(widget.render_state, widget.RenderState())


class PublicApiTestCase(SimpleTestCase):
    """Make sure the public interface of ``nestingdolls`` is complete."""

    def test_every_exported_name_is_importable(self):
        """Every name in ``__all__`` is importable."""
        missing = {
            name for name in nestingdolls.__all__ if not hasattr(nestingdolls, name)
        }
        self.assertEqual(missing, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
