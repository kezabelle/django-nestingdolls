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
from .support.forms.mapping import (
    MappingPointForm,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class CompositeWidgetBaseContractTestCase(SimpleTestCase):
    """These tests check shared composite widget state and media."""

    def test_child_widgets_are_not_shared_between_form_instances(self) -> None:
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

    def test_the_base_widget_defers_keys_and_media_to_subclasses(self) -> None:
        """The base widget has no key test and no child media of its own."""
        widget = CompositeWidget()
        with self.assertRaises(NotImplementedError):
            widget.value_omitted_from_data({"point": "1"}, {}, "point")
        with self.assertRaises(NotImplementedError):
            str(widget.media)

    def test_widget_media_merges_every_declaration_in_the_mro(self) -> None:
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
            point = nestingdolls.DictField(MappingPointForm, widget=ExtraMappingWidget)

        media = str(Form().media)
        self.assertIn("nestingdolls/sequence.js", media)
        self.assertIn("extra-sequence.js", media)
        self.assertIn("extra-mapping.js", media)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
