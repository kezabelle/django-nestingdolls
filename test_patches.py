from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import TYPE_CHECKING

import django
from django import forms
from django.apps import apps
from django.conf import settings
from django.forms import BaseForm
from django.forms.renderers import DjangoTemplates, TemplatesSetting
from django.test import SimpleTestCase, override_settings

import nestingdolls
from nestingdolls.patches import FormLayout, install_form_rendering_patch

if TYPE_CHECKING:
    from collections.abc import Iterator

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


@contextmanager
def without_form_rendering_patch() -> Iterator[None]:
    """Run code with Django's original ``BaseForm`` renderer."""
    original_render = BaseForm.render
    original_str = BaseForm.__str__
    original_html = BaseForm.__html__
    original_patch_target = BaseForm.nestingdolls_original_render
    original_flag = bool(
        getattr(BaseForm, "nestingdolls_render_patch_installed", False)
    )
    BaseForm.render = original_patch_target
    BaseForm.__str__ = original_patch_target
    BaseForm.__html__ = original_patch_target
    BaseForm.nestingdolls_render_patch_installed = False
    try:
        yield
    finally:
        BaseForm.render = original_render
        BaseForm.__str__ = original_str
        BaseForm.__html__ = original_html
        BaseForm.nestingdolls_original_render = original_patch_target
        BaseForm.nestingdolls_render_patch_installed = original_flag


def squashed(html: str) -> str:
    """Collapse runs of whitespace so multi-line attributes compare as one line."""
    return " ".join(html.split())


class FormRenderingPatchTestCase(SimpleTestCase):
    def test_installation_is_idempotent(self):
        """Repeated installation keeps one wrapper around the original renderer.

        ``AppConfig.ready()`` can run more than once in one process. It calls
        ``install_form_rendering_patch()``, so both entry points must preserve
        the same wrapper.
        """
        app_config = apps.get_app_config("nestingdolls")
        installed_render = BaseForm.render
        original_render = BaseForm.nestingdolls_original_render

        app_config.ready()
        install_form_rendering_patch()

        self.assertIs(BaseForm.render, installed_render)
        self.assertIs(BaseForm.__str__, installed_render)
        self.assertIs(BaseForm.__html__, installed_render)
        self.assertIs(BaseForm.nestingdolls_render_patch_installed, True)
        self.assertIs(BaseForm.nestingdolls_original_render, original_render)
        self.assertIs(getattr(BaseForm.render, "__wrapped__", None), original_render)

    def test_patch_wraps_an_existing_render_customization(self):
        """The patch preserves an existing render wrapper and its layout."""
        wrapper_layouts = []
        widget_layouts = []
        render_results = []
        original_render = BaseForm.nestingdolls_original_render

        class LayoutWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                widget_layouts.append(FormLayout.current())
                return super().render(*args, **kwargs)

        class ChildForm(forms.Form):
            value = forms.CharField(widget=LayoutWidget)

        class Form(forms.Form):
            child = nestingdolls.MappingField(ChildForm)

        @wraps(original_render)
        def customized_render(
            self: BaseForm,
            template_name: str | None = None,
            context: dict[str, object] | None = None,
            renderer: object = None,
        ) -> str:
            wrapper_layouts.append(FormLayout.current())
            result = original_render(self, template_name, context, renderer)
            render_results.append(result)
            return result

        # Install the patch after another library replaces ``BaseForm.render``.
        with without_form_rendering_patch():
            BaseForm.render = customized_render
            install_form_rendering_patch()
            html = Form().as_p()

        self.assertIs(bool(wrapper_layouts), True)
        self.assertEqual(set(wrapper_layouts), {FormLayout.p})
        self.assertIs(bool(widget_layouts), True)
        self.assertEqual(set(widget_layouts), {FormLayout.p})
        self.assertIs(html, render_results[-1])
        self.assertIs(BaseForm.nestingdolls_original_render, original_render)

    def test_patch_resets_layout_after_render_error(self):
        """A render error restores the default layout for the next render."""

        class ExplodingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("boom")

        class Form(forms.Form):
            value = forms.CharField(widget=ExplodingWidget)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            Form().as_p()
        self.assertEqual(FormLayout.current(), FormLayout.div)

    @override_settings(INSTALLED_APPS=("django.forms", "nestingdolls"))
    def test_patch_supports_django_template_renderers(self):
        """Both Django template renderers pass the selected layout to child widgets."""
        widget_layouts = []

        class LayoutWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                widget_layouts.append(FormLayout.current())
                return super().render(*args, **kwargs)

        class ChildForm(forms.Form):
            value = forms.CharField(widget=LayoutWidget)

        class Form(forms.Form):
            child = nestingdolls.MappingField(ChildForm)

        for renderer in (DjangoTemplates(), TemplatesSetting()):
            with self.subTest(renderer=type(renderer).__name__):
                widget_layouts.clear()
                form = Form(renderer=renderer)

                html = form.as_p()

                self.assertIs(form.renderer, renderer)
                self.assertIs(bool(widget_layouts), True)
                self.assertEqual(set(widget_layouts), {FormLayout.p})
                self.assertIn('data-widget="mapping"', html)
                self.assertIn('name="child-value"', html)

    def test_mapping_widget_renders_without_patch(self):
        """A mapping widget renders its wrapper and child inputs without the patch."""

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
        """A sequence widget renders its wrapper and row inputs without the patch."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()

        with without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="sequence"', html)
        self.assertIn("<div", html)
        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)

    def test_default_render_uses_the_renderer_form_template(self):
        """``{{ form }}`` picks the layout of the renderer's own form template."""

        class PRenderer(DjangoTemplates):
            form_template_name = "django/forms/p.html"

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=1)

        html = squashed(str(Form(renderer=PRenderer())))

        self.assertIn('<span data-widget="sequence"', html)
        self.assertNotIn('<div data-widget="sequence"', html)

    def test_nested_default_render_does_not_inherit_the_outer_layout(self):
        """A ``{{ inner_form }}`` inside ``as_table()`` renders its own div layout."""

        class InnerForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=1)

        inner_form = InnerForm()

        class EmbeddingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                return str(inner_form)

        class OuterForm(forms.Form):
            embedded = forms.CharField(widget=EmbeddingWidget)

        html = squashed(OuterForm().as_table())

        self.assertIn('<div data-widget="sequence"', html)
        self.assertNotIn('<table role="presentation">', html)
