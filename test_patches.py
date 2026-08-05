from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager

import django
from django import forms
from django.conf import settings
from django.forms import BaseForm
from django.test import SimpleTestCase

import nestingdolls
from nestingdolls.patches import install_form_rendering_patch
from nestingdolls.rendering import FormLayout

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=("nestingdolls",),
        USE_I18N=False,
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()


@contextmanager
def without_form_rendering_patch() -> Iterator[None]:
    original_render = BaseForm.render
    original_flag = bool(
        getattr(BaseForm, "nestingdolls_render_patch_installed", False)
    )
    BaseForm.render = BaseForm.nestingdolls_original_render
    BaseForm.nestingdolls_render_patch_installed = False
    try:
        yield
    finally:
        BaseForm.render = original_render
        BaseForm.nestingdolls_render_patch_installed = original_flag


class FormRenderingPatchTestCase(SimpleTestCase):
    def test_installation_is_idempotent(self):
        original_render = BaseForm.nestingdolls_original_render

        install_form_rendering_patch()
        install_form_rendering_patch()

        self.assertTrue(BaseForm.nestingdolls_render_patch_installed)
        self.assertIs(BaseForm.nestingdolls_original_render, original_render)

    def test_patch_preserves_wrapped_method(self):
        original_render = BaseForm.nestingdolls_original_render

        self.assertIs(getattr(BaseForm.render, "__wrapped__", None), original_render)
        self.assertEqual(
            inspect.signature(BaseForm.render), inspect.signature(original_render)
        )

    def test_patch_resets_layout_after_render_error(self):
        class ExplodingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("boom")

        class Form(forms.Form):
            value = forms.CharField(widget=ExplodingWidget)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            Form().as_p()
        self.assertEqual(FormLayout.current(), FormLayout.div)

    def test_mapping_widget_renders_without_patch(self):
        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        with without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="mapping"', html)
        self.assertIn("<div", html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="point-label"', html)

    def test_sequence_widget_renders_without_patch(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()

        with without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="sequence"', html)
        self.assertIn("<div", html)
        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)
