"""Test support module."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

import django
from django import forms
from django.apps import apps
from django.conf import settings
from django.forms import BaseForm
from django.forms.renderers import DjangoTemplates, TemplatesSetting
from django.template import TemplateDoesNotExist
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
from .support.forms.composite import (
    CompositePointAndSequenceForm,
)
from .support.forms.mapping import (
    RequiredMappingPointForm,
)
from .support.forms.sequence import (
    MinimumOneIntegerSequenceForm,
    MinimumTwoIntegerSequenceForm,
)


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


class FormLayoutPatchInstallationTestCase(SimpleTestCase):
    """Test the safety of the form-rendering patch.

    The patch installs one time only. It keeps render wrappers from other
    libraries. It does not change forms that have no composite fields.
    """

    def test_installation_is_idempotent(self) -> None:
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

    def test_patch_wraps_an_existing_render_customization(self) -> None:
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

    def test_patch_is_a_pass_through_for_forms_without_composite_fields(self) -> None:
        """The patch does not change HTML for a form without composite fields."""

        class PlainForm(forms.Form):
            name = forms.CharField()
            count = forms.IntegerField()

        patched_html = PlainForm().as_p()
        with without_form_rendering_patch():
            unpatched_html = PlainForm().as_p()

        self.assertEqual(patched_html, unpatched_html)


class FormLayoutPatchStateTestCase(SimpleTestCase):
    """Test that the patch records the active form layout.

    Each render gives its layout to its nested widgets. An error or nested render
    does not change a different render.
    """

    def test_patch_resets_layout_after_render_error(self) -> None:
        """A render error restores the default layout for the next render."""

        class ExplodingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("boom")

        class Form(forms.Form):
            value = forms.CharField(widget=ExplodingWidget)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            Form().as_p()
        self.assertEqual(FormLayout.current(), FormLayout.div)

    def assertRendererPassesLayoutToNestedWidget(self, renderer: object) -> None:  # noqa: D102
        widget_layouts = []

        class LayoutWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                widget_layouts.append(FormLayout.current())
                return super().render(*args, **kwargs)

        class ChildForm(forms.Form):
            value = forms.CharField(widget=LayoutWidget)

        class Form(forms.Form):
            child = nestingdolls.MappingField(ChildForm)

        form = Form(renderer=renderer)
        html = form.as_p()

        self.assertIs(form.renderer, renderer)
        self.assertIs(bool(widget_layouts), True)
        self.assertEqual(set(widget_layouts), {FormLayout.p})
        self.assertIn('data-widget="mapping"', html)
        self.assertIn('name="child-value"', html)

    @override_settings(INSTALLED_APPS=("django.forms", "nestingdolls"))
    def test_django_templates_renderer_passes_layout_to_nested_widget(self) -> None:
        """The Django templates renderer passes the paragraph layout to its child."""
        self.assertRendererPassesLayoutToNestedWidget(DjangoTemplates())

    @override_settings(INSTALLED_APPS=("django.forms", "nestingdolls"))
    def test_template_settings_renderer_passes_layout_to_nested_widget(self) -> None:
        """The template settings renderer passes the paragraph layout to its child."""
        self.assertRendererPassesLayoutToNestedWidget(TemplatesSetting())

    def test_default_render_uses_the_renderer_form_template_layout(self) -> None:
        """``{{ form }}`` picks the layout of the renderer's own form template."""

        class PRenderer(DjangoTemplates):
            form_template_name = "django/forms/p.html"

        html = squashed(str(MinimumOneIntegerSequenceForm(renderer=PRenderer())))

        self.assertIn('<span data-widget="sequence"', html)
        self.assertNotIn('<div data-widget="sequence"', html)

    def test_nested_default_render_does_not_inherit_the_outer_layout(self) -> None:
        """A ``{{ inner_form }}`` inside ``as_table()`` renders its own div layout."""
        inner_form = MinimumOneIntegerSequenceForm()

        class EmbeddingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                return str(inner_form)

        class OuterForm(forms.Form):
            embedded = forms.CharField(widget=EmbeddingWidget)

        html = squashed(OuterForm().as_table())

        self.assertIn('<div data-widget="sequence"', html)
        self.assertNotIn('<table role="presentation">', html)

    def test_custom_template_render_keeps_the_active_layout(self) -> None:
        """``form.render("custom.html")`` inside ``as_p()`` uses the ``p`` layout.

        A custom template can contain a form in any layout.
        Keep the active layout during this render.
        Do not reset the layout to ``div``.
        """

        class CustomTemplateRenderer(DjangoTemplates):
            def get_template(self, template_name: str) -> object:
                if template_name == "example/detail.html":
                    return self.engine.from_string("{{ form.values }}")
                return super().get_template(template_name)

        inner_form = MinimumOneIntegerSequenceForm(renderer=CustomTemplateRenderer())

        class EmbeddingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                return inner_form.render("example/detail.html")

        class OuterForm(forms.Form):
            embedded = forms.CharField(widget=EmbeddingWidget)

        html = squashed(OuterForm().as_p())

        self.assertIn('<span data-widget="sequence"', html)
        self.assertNotIn('<div data-widget="sequence"', html)


class UnpatchedCompositeWidgetRenderingTestCase(SimpleTestCase):
    """Test that composite widgets render without the patch.

    The mapping widget and sequence widget show their wrappers and child inputs
    when Django uses its original renderer.
    """

    def test_mapping_widget_renders_without_patch(self) -> None:
        """A mapping widget renders its wrapper and child inputs without the patch."""
        form = RequiredMappingPointForm(initial={"point": {"a": 9, "label": "layout"}})

        with without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="mapping"', html)
        self.assertIn("<div", html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="point-label"', html)

    def test_sequence_widget_renders_without_patch(self) -> None:
        """A sequence widget renders its wrapper and row inputs without the patch."""
        form = MinimumTwoIntegerSequenceForm()

        with without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="sequence"', html)
        self.assertIn("<div", html)
        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)


class FormLayoutTemplateDiscoveryTestCase(SimpleTestCase):
    """Test how project settings control template discovery.

    The default renderer finds widget templates only when the project installs
    the app. The template-settings renderer finds templates through project
    template directories.
    """

    @override_settings(INSTALLED_APPS=("nestingdolls",))
    def test_installing_the_app_resolves_templates_and_tracks_paragraph_layout(
        self,
    ) -> None:
        """The default renderer finds templates and the patch selects paragraph widgets."""
        html = squashed(CompositePointAndSequenceForm().as_p())

        self.assertIn('<span data-widget="mapping"', html)
        self.assertIn('<span data-widget="sequence"', html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)

    @override_settings(
        INSTALLED_APPS=("django.forms",),
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [Path(nestingdolls.__file__).parent / "templates"],
                "APP_DIRS": True,
            }
        ],
    )
    def test_default_renderer_ignores_template_dirs_without_the_app(self) -> None:
        """The default form renderer does not load project template settings."""
        with (
            without_form_rendering_patch(),
            self.assertRaisesRegex(
                TemplateDoesNotExist, "nestingdolls/mapping/div.html"
            ),
        ):
            CompositePointAndSequenceForm().as_p()

    @override_settings(
        INSTALLED_APPS=("django.forms",),
        FORM_RENDERER="django.forms.renderers.TemplatesSetting",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [Path(nestingdolls.__file__).parent / "templates"],
                "APP_DIRS": True,
            }
        ],
    )
    def test_template_settings_renderer_uses_template_dirs_without_the_app(
        self,
    ) -> None:
        """The template-settings renderer finds widgets, but cannot track helpers."""
        with without_form_rendering_patch():
            html = squashed(CompositePointAndSequenceForm().as_p())

        self.assertIn('<div data-widget="mapping"', html)
        self.assertIn('<div data-widget="sequence"', html)
        self.assertNotIn('<span data-widget="mapping"', html)
        self.assertNotIn('<span data-widget="sequence"', html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)
