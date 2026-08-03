from __future__ import annotations

import json
import unittest

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import BaseForm
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment
from hypothesis import HealthCheck, example, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

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


HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def setUpModule():
    # `assertTemplateUsed()` relies on Django's instrumented template renderer.
    setup_test_environment()


def tearDownModule():
    # Undo the global template instrumentation after these unittest-based tests.
    teardown_test_environment()
SMALL_INTEGERS = st.integers(min_value=-10, max_value=10)
RAW_INTEGER_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=12),
    st.lists(st.integers(), max_size=3),
)
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | SMALL_INTEGERS | st.text(max_size=8),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=4), children, max_size=3),
    max_leaves=8,
)
DATETIMES = st.datetimes(timezones=st.none()).map(
    lambda value: value.replace(microsecond=0)
)
MAPPING_STYLES = ("direct", "dash", "dot", "bracket")
PATH_STYLES = ("dash", "dot", "bracket")


def mapping_data(name: str, values: dict[str, object], style: str):
    if style == "direct":
        return {name: values}
    if style == "dash":
        return {f"{name}-{key}": value for key, value in values.items()}
    if style == "dot":
        return {f"{name}.{key}": value for key, value in values.items()}
    if style == "bracket":
        return {f"{name}[{key}]": value for key, value in values.items()}
    raise ValueError(style)


def nested_path(name: str, segments: tuple[object, ...], style: str) -> str:
    if style == "dash":
        return "-".join((name, *(str(segment) for segment in segments)))
    if style == "dot":
        return ".".join((name, *(str(segment) for segment in segments)))
    if style == "bracket":
        return name + "".join(f"[{segment}]" for segment in segments)
    raise ValueError(style)


def mixed_path(name: str, segments: tuple[object, ...], styles: tuple[str, ...]):
    for segment, style in zip(segments, styles, strict=True):
        if style == "dash":
            name = f"{name}-{segment}"
        elif style == "dot":
            name = f"{name}.{segment}"
        elif style == "bracket":
            name = f"{name}[{segment}]"
        else:
            raise ValueError(style)
    return name


class PointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


class DictFieldTestCase(SimpleTestCase):
    def test_cleans_every_supported_mapping_spelling(self):
        """It cleans direct, dash, dot, and bracket mapping input."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        for style in MAPPING_STYLES:
            with self.subTest(style=style):
                form = Form(mapping_data("point", {"a": "2", "label": "east"}, style))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["point"], {"a": 2, "label": "east"})

    def test_widget_returns_a_mapping_instead_of_an_internal_transport(self):
        """Widget extraction exposes the field's normal mapping shape."""
        field = nestingdolls.MappingField(PointForm)

        value = field.widget.value_from_datadict(
            {"point-a": "2", "point-label": "east"}, {}, "point"
        )

        self.assertEqual(value, {"a": "2", "label": "east"})
        self.assertIsInstance(value, dict)

    def test_to_python_only_checks_the_container_shape(self):
        """Shape conversion does not run child Form cleaning hooks."""
        cleaned = False

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self):
                nonlocal cleaned
                cleaned = True
                return super().clean()

        field = nestingdolls.MappingField(ChildForm)

        self.assertEqual(field.to_python({"a": "2"}), {"a": "2"})
        self.assertFalse(cleaned)
        self.assertEqual(field.clean({"a": "2"}), {"a": 2})
        self.assertTrue(cleaned)

    def test_cleans_querydict_bracket_input(self):
        """It preserves QueryDict behavior while removing the outer prefix."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(QueryDict("point[a]=3&point[label]=west"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "west"})

    def test_direct_mapping_takes_precedence_over_flat_aliases(self):
        """An exact mapping value wins over flattened values."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point": {"a": "4"}, "point-a": "99"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 4, "label": ""})

    def test_direct_mapping_ignores_undeclared_keys(self):
        """A direct mapping only binds declared child fields."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point": {"a": "4", "label": "east", "junk": "ignored"}})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 4, "label": "east"})

    def test_last_flat_alias_wins(self):
        """The last alias for one child key owns its value."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point-a": "1", "point.a": "2", "point[a]": "3"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"]["a"], 3)

    def test_malformed_bracket_suffix_cannot_name_another_child(self):
        """Text after a closed bracket must start a supported nested suffix."""

        class ChildForm(forms.Form):
            ajunk = forms.IntegerField()

        class Form(forms.Form):
            point = nestingdolls.MappingField(ChildForm)

        form = Form({"point[a]junk": "2"})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["point"][0].code, "required")

    def test_rejects_non_mapping_input(self):
        """It rejects an exact scalar value."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point": "not a mapping"})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["point"][0].code, "invalid")

    def test_required_and_optional_empty_mappings_use_the_container_boundary(self):
        """Required applies to the mapping, and optional empty input returns a dict."""

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(PointForm)
            optional_point = nestingdolls.MappingField(PointForm, required=False)

        form = Form({"required_point": {}, "optional_point": {}})

        self.assertFalse(form.is_valid())
        self.assertFormError(form, "required_point", "This field is required.")
        self.assertEqual(form.cleaned_data["optional_point"], {})

    def test_optional_partial_mapping_keeps_child_requirements(self):
        """Submitted optional mappings still use the child Form rules."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        form = Form({"point-label": "missing a"})

        self.assertFalse(form.is_valid())
        error = form.errors.as_data()["point"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "required")

    def test_child_clean_hooks_and_form_clean_are_preserved(self):
        """It returns the final cleaned_data produced by the child Form."""

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean_a(self):
                return self.cleaned_data["a"] + 1

            def clean(self):
                cleaned_data = super().clean()
                cleaned_data["double"] = cleaned_data["a"] * 2
                return cleaned_data

        field = nestingdolls.MappingField(ChildForm)

        self.assertEqual(field.clean({"a": "2"}), {"a": 3, "double": 6})

    def test_non_field_errors_keep_the_leaf_code(self):
        """Child Form errors remain structured without a path summary."""

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self):
                cleaned_data = super().clean()
                if cleaned_data.get("a") == 2:
                    raise ValidationError("Two is unavailable.", code="unavailable")
                return cleaned_data

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = Form({"value-a": "2"})

        self.assertFalse(form.is_valid())
        error = form.errors.as_data()["value"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "unavailable")
        self.assertEqual(error.params["key"], "__all__")
        self.assertNotIn("path", error.params)

    def test_outer_validators_receive_cleaned_mapping(self):
        """DictField validators receive child-cleaned values."""

        def reject_two(value):
            if value["a"] == 2:
                raise ValidationError("No two.", code="no_two")

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, validators=[reject_two])

        form = Form({"point-a": "2"})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["point"][0].code, "no_two")
        self.assertFormError(form, "point", "No two.")

    def test_form_prefix_is_preserved(self):
        """Nested child names include the normal parent Form prefix."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"outer-point-a": "5"}, prefix="outer")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"]["a"], 5)
        self.assertIn('name="outer-point-a"', str(form["point"]))

    def test_direct_and_flat_initial_values_render(self):
        """It accepts direct and flattened Form initial mappings."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        direct = Form(initial={"point": {"a": 6, "label": "direct"}})
        flat = Form(initial={"point.a": 7, "point[label]": "flat"})

        self.assertIn('value="6"', str(direct["point"]))
        self.assertIn('value="direct"', str(direct["point"]))
        self.assertIn('value="7"', str(flat["point"]))
        self.assertIn('value="flat"', str(flat["point"]))

    def test_callable_initial_and_disabled_field_use_initial(self):
        """It uses Django's resolved callable initial for disabled fields."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                PointForm,
                initial=lambda: {"a": 8, "label": "initial"},
                disabled=True,
            )

        form = Form({"point-a": "99"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 8, "label": "initial"})
        self.assertInHTML(
            '<input type="number" name="point-a" value="8" required disabled id="id_point-a">',
            form.as_div(),
        )

    def test_optional_omission_does_not_bind_child_fields_from_initial(self):
        """A bound optional mapping can replace an initial mapping with empty data."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        form = Form({}, initial={"point": {"a": 8, "label": "saved"}})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["point"], {})
        self.assertTrue(form.has_changed())

    def test_show_hidden_initial_uses_child_hidden_widgets(self):
        """Django can compare hidden mapping initial values by child name."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, show_hidden_initial=True)

        initial = {"point": {"a": 8, "label": "saved"}}
        unbound = Form(initial=initial)
        html = unbound.as_div()
        self.assertIn('type="hidden" name="initial-point-a" value="8"', html)
        self.assertIn('type="hidden" name="initial-point-label" value="saved"', html)

        bound = Form(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "8",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertFalse(bound.has_changed())

    def test_has_changed_uses_child_field_semantics(self):
        """Equivalent raw and Python child values are unchanged."""
        field = nestingdolls.MappingField(PointForm, required=False)

        self.assertFalse(field.has_changed({"a": 2, "label": ""}, {"a": "2"}))
        self.assertTrue(field.has_changed({"a": 2, "label": ""}, {"a": "3"}))

    def test_rejects_wrong_form_widget_and_bound_field_types(self):
        """Constructor extension points require compatible Django types."""

        class NeedsArgForm(forms.Form):
            def __init__(self, token, *args, **kwargs):
                super().__init__(*args, **kwargs)

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(forms.IntegerField)  # type: ignore[arg-type]
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(NeedsArgForm)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(PointForm, widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(PointForm, bound_field_class=forms.BoundField)

    def test_widget_extensions_are_copied_and_rebound_to_the_child_form(self):
        """Django copies widget instances and the field supplies its Form class."""

        class OtherForm(forms.Form):
            other = forms.CharField()

        class CustomWidget(nestingdolls.MappingWidget):
            pass

        widget = CustomWidget(OtherForm)
        instance_field = nestingdolls.MappingField(PointForm, widget=widget)
        class_field = nestingdolls.MappingField(PointForm, widget=CustomWidget)

        self.assertIsNot(instance_field.widget, widget)
        self.assertIs(instance_field.widget.form_class, PointForm)
        self.assertIs(widget.form_class, OtherForm)
        self.assertIsInstance(class_field.widget, CustomWidget)
        self.assertIs(class_field.widget.form_class, PointForm)

    def test_custom_bound_field_keeps_mapping_error_integration(self):
        """Compatible custom bound fields remain supported."""

        class CustomBoundField(nestingdolls.MappingBoundField):
            pass

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                PointForm, bound_field_class=CustomBoundField
            )

        form = Form({"point-a": "bad"})

        self.assertFalse(form.is_valid())
        self.assertIsInstance(form["point"], CustomBoundField)
        self.assertIn("Enter a whole number.", form.as_p())


class DictFieldRenderingTestCase(SimpleTestCase):
    def _without_form_rendering_patch(self):
        class NoPatchContext:
            def __enter__(inner_self):
                inner_self.original_render = BaseForm.render
                inner_self.original_flag = bool(
                    getattr(BaseForm, "nestingdolls_render_patch_installed", False)
                )
                BaseForm.render = getattr(BaseForm, "nestingdolls_original_render")
                setattr(BaseForm, "nestingdolls_render_patch_installed", False)

            def __exit__(inner_self, exc_type, exc, tb):
                BaseForm.render = inner_self.original_render
                setattr(
                    BaseForm,
                    "nestingdolls_render_patch_installed",
                    inner_self.original_flag,
                )

        return NoPatchContext()

    def test_form_rendering_patch_is_idempotent(self):
        original_render = getattr(BaseForm, "nestingdolls_original_render")

        install_form_rendering_patch()
        install_form_rendering_patch()

        self.assertTrue(getattr(BaseForm, "nestingdolls_render_patch_installed"))
        self.assertIs(getattr(BaseForm, "nestingdolls_original_render"), original_render)

    def test_form_rendering_patch_resets_layout_after_render_error(self):
        class ExplodingWidget(forms.TextInput):
            def render(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("boom")

        class Form(forms.Form):
            value = forms.CharField(widget=ExplodingWidget)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            Form().as_p()
        self.assertEqual(FormLayout.current(), FormLayout.div)

    def test_child_errors_render_once_and_not_as_outer_errors(self):
        """The child Form renders its error without an outer duplicate."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point-label": "missing a"})

        self.assertFalse(form.is_valid())
        self.assertEqual(list(form["point"].errors), [])
        rendered = str(form["point"])
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertIn('aria-invalid="true"', rendered)

    def test_widget_renders_in_each_standard_form_layout(self):
        """The child Form renders without inspecting the parent render call."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        for renderer in (form.as_div, form.as_p, form.as_table, form.as_ul):
            with self.subTest(renderer=renderer.__name__):
                html = renderer()
                self.assertIn('name="point-a"', html)
                self.assertIn('name="point-label"', html)

    def test_widget_uses_helper_specific_wrapper_markup(self):
        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        with self.assertTemplateUsed("django/forms/widgets/mapping/div.html"):
            div_html = form.as_div()
        with self.assertTemplateUsed("django/forms/widgets/mapping/table.html"):
            table_html = form.as_table()
        with self.assertTemplateUsed("django/forms/widgets/mapping/ul.html"):
            ul_html = form.as_ul()
        with self.assertTemplateUsed("django/forms/widgets/mapping/p.html"):
            p_html = form.as_p()

        self.assertIn('data-widget="mapping"', div_html)
        self.assertIn("<table>", table_html)
        self.assertIn("<ul>", ul_html)
        self.assertIn('data-widget="mapping"', p_html)
        self.assertIn("<span", p_html)

    def test_widget_switches_layout_between_sequential_renders(self):
        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        table_html = form.as_table()
        p_html = form.as_p()
        ul_html = form.as_ul()

        self.assertIn("<table>", table_html)
        self.assertIn('data-widget="mapping"', p_html)
        self.assertIn("<span", p_html)
        self.assertIn("<ul>", ul_html)

    def test_widget_still_renders_without_form_rendering_patch(self):
        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        with self._without_form_rendering_patch():
            html = form.as_p()

        self.assertIn('data-widget="mapping"', html)
        self.assertIn("<div", html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="point-label"', html)

    def test_widget_exposes_child_media_and_multipart_requirement(self):
        """The outer widget reports child widget integration requirements."""

        class MediaWidget(forms.TextInput):
            class Media:
                js = ("child.js",)

        class ChildForm(forms.Form):
            title = forms.CharField(widget=MediaWidget)
            upload = forms.FileField(required=False)

        field = nestingdolls.MappingField(ChildForm)

        self.assertTrue(field.widget.needs_multipart_form)
        self.assertIn("child.js", field.widget.media._js)


class DictFieldWidgetIntegrationTestCase(SimpleTestCase):
    def test_widget_wrapper_exposes_field_specific_references(self):
        """The wrapper keeps an obvious link back to the parent field name/id."""

        class ChildForm(forms.Form):
            title = forms.CharField()

        class Form(forms.Form):
            filters = nestingdolls.MappingField(ChildForm)

        html = Form().as_p()

        self.assertIn('data-widget="mapping"', html)
        self.assertIn('data-mapping-field="filters"', html)
        self.assertIn('id="id_filters_widget"', html)
        self.assertInHTML(
            '<input type="text" name="filters-title" required id="id_filters-title">',
            html,
        )

    def test_repeated_query_values_use_child_widget_extraction(self):
        """Widgets that use getlist receive every submitted child value."""

        class ChildForm(forms.Form):
            choices = forms.MultipleChoiceField(
                choices=(("a", "A"), ("b", "B"), ("c", "C"))
            )

        class Form(forms.Form):
            filters = nestingdolls.MappingField(ChildForm)

        data = QueryDict("", mutable=True)
        data.setlist("filters[choices]", ["a", "c"])
        form = Form(data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["filters"]["choices"], ["a", "c"])

    def test_direct_json_list_remains_one_child_value(self):
        """A direct list can remain a JSON value instead of repeated input."""

        class ChildForm(forms.Form):
            payload = forms.JSONField()

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = Form({"value": {"payload": [1, {"answer": 42}]}})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["value"]["payload"], [1, {"answer": 42}])

    def test_splitdatetime_uses_child_widget_extraction(self):
        """Compound child widgets retain all submitted parts."""

        class ChildForm(forms.Form):
            happened_at = forms.SplitDateTimeField()

        class Form(forms.Form):
            event = nestingdolls.MappingField(ChildForm)

        form = Form(
            {
                "event[happened_at]_0": "2026-08-01",
                "event[happened_at]_1": "10:30:00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["event"]["happened_at"].replace(tzinfo=None).isoformat(),
            "2026-08-01T10:30:00",
        )

    def test_direct_clean_accepts_an_extracted_compound_value(self):
        """Direct mapping cleaning passes compound values to the child field."""

        class ChildForm(forms.Form):
            happened_at = forms.SplitDateTimeField()

        field = nestingdolls.MappingField(ChildForm)

        cleaned = field.clean({"happened_at": ["2026-08-01", "10:30:00"]})

        self.assertEqual(
            cleaned["happened_at"].replace(tzinfo=None).isoformat(),
            "2026-08-01T10:30:00",
        )

    def test_file_upload_keeps_data_and_files_separate(self):
        """File children receive uploads through the files mapping."""

        class ChildForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField()

        class Form(forms.Form):
            asset = nestingdolls.MappingField(ChildForm)

        upload = SimpleUploadedFile("new.txt", b"new")
        form = Form(
            {"asset": {"title": "report"}},
            files={"asset": {"upload": upload}},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["asset"]["title"], "report")
        self.assertIs(form.cleaned_data["asset"]["upload"], upload)

    def test_file_initial_clear_and_contradiction_follow_django(self):
        """File children retain Django's initial, clear, and contradiction rules."""

        class ChildForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField(required=False)

        class Form(forms.Form):
            asset = nestingdolls.MappingField(ChildForm)

        initial_upload = SimpleUploadedFile("old.txt", b"old")
        initial = {"asset": {"title": "old", "upload": initial_upload}}

        kept = Form({"asset-title": "old"}, initial=initial)
        self.assertTrue(kept.is_valid(), kept.errors)
        self.assertIs(kept.cleaned_data["asset"]["upload"], initial_upload)

        cleared = Form(
            {"asset-title": "old", "asset-upload-clear": "1"}, initial=initial
        )
        self.assertTrue(cleared.is_valid(), cleared.errors)
        self.assertFalse(cleared.cleaned_data["asset"]["upload"])

        contradictory = Form(
            {"asset-title": "old", "asset-upload-clear": "1"},
            files={"asset-upload": SimpleUploadedFile("new.txt", b"new")},
            initial=initial,
        )
        self.assertFalse(contradictory.is_valid())
        self.assertEqual(
            contradictory.errors.as_data()["asset"][0].params["child_code"],
            "contradiction",
        )

    def test_file_only_subforms_keep_initial_uploads_when_untouched(self):
        """Untouched file-only mappings preserve child FileField initials."""

        class ChildForm(forms.Form):
            upload = forms.FileField()

        initial_upload = SimpleUploadedFile("old.txt", b"old")
        initial = {"asset": {"upload": initial_upload}}

        for required in (False, True):
            Form = type(
                "Form",
                (forms.Form,),
                {"asset": nestingdolls.MappingField(ChildForm, required=required)},
            )

            form = Form({}, initial=initial)

            with self.subTest(required=required):
                self.assertTrue(form.is_valid(), form.errors)
                self.assertIs(form.cleaned_data["asset"]["upload"], initial_upload)

    def test_mixed_file_subforms_keep_initial_uploads_when_untouched(self):
        """Untouched mixed mappings preserve child FileField initials."""

        class ChildForm(forms.Form):
            title = forms.CharField(required=False)
            upload = forms.FileField()

        initial_upload = SimpleUploadedFile("old.txt", b"old")
        initial = {"asset": {"title": "", "upload": initial_upload}}

        for required in (False, True):
            Form = type(
                "Form",
                (forms.Form,),
                {"asset": nestingdolls.MappingField(ChildForm, required=required)},
            )

            form = Form({}, initial=initial)

            with self.subTest(required=required):
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["asset"]["title"], "")
                self.assertIs(form.cleaned_data["asset"]["upload"], initial_upload)


class NestedDictFieldTestCase(SimpleTestCase):
    def test_dict_field_accepts_nested_dict_children(self):
        """It cleans recursively nested mapping paths."""

        class OuterForm(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        class Form(forms.Form):
            value = nestingdolls.MappingField(OuterForm)

        form = Form({"value[point][a]": "2", "value[point][label]": "nested"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["value"], {"point": {"a": 2, "label": "nested"}}
        )

    def test_dict_field_accepts_sequence_children(self):
        """It cleans a sequence below a mapping field."""

        class ChildForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = Form({"value.values.0": "1", "value.values.1": "2"})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["value"], {"values": [1, 2]})

    def test_sequence_field_accepts_dict_children(self):
        """It cleans mapping rows below a sequence field."""

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        form = Form(
            {
                "values.0.a": "1",
                "values.0.label": "first",
                "values.1.a": "2",
                "values.1.label": "second",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["values"],
            [{"a": 1, "label": "first"}, {"a": 2, "label": "second"}],
        )

    def test_sequence_mapping_child_accepts_compound_values(self):
        """A mapping cleaned below a sequence retains compound child values."""

        class EventForm(forms.Form):
            happened_at = forms.SplitDateTimeField()

        class Form(forms.Form):
            events = nestingdolls.ListField(nestingdolls.MappingField(EventForm))

        form = Form(
            {
                "events[0][happened_at]_0": "2026-08-01",
                "events[0][happened_at]_1": "10:30:00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["events"][0]["happened_at"]
            .replace(tzinfo=None)
            .isoformat(),
            "2026-08-01T10:30:00",
        )

    def test_mapping_error_inside_sequence_renders_once_at_the_row(self):
        """A sequence row owns errors from its mapping child."""

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        form = Form({"values[0][label]": "missing a"})

        self.assertFalse(form.is_valid())
        rendered = str(form["values"])
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertEqual(list(form["values"].errors), [])

    def test_file_field_inside_sequence_mapping_keeps_upload(self):
        """File input survives a sequence-to-mapping boundary."""

        class AssetForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField()

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(AssetForm))

        upload = SimpleUploadedFile("nested.txt", b"nested")
        form = Form(
            {"values.0.title": "asset"},
            files={"values.0.upload": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"][0]["title"], "asset")
        self.assertIs(form.cleaned_data["values"][0]["upload"], upload)

    def test_deep_alternating_fields_clean_flat_input(self):
        """It cleans mapping, sequence, and mapping layers together."""

        class EntryForm(forms.Form):
            point = nestingdolls.MappingField(PointForm)
            title = forms.CharField()

        class SectionForm(forms.Form):
            heading = forms.CharField()
            entries = nestingdolls.ListField(nestingdolls.MappingField(EntryForm))

        class ChildForm(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.MappingField(SectionForm))

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm)

        form = Form(
            {
                "payload[rows][0][heading]": "alpha",
                "payload[rows][0][entries][0][point][a]": "4",
                "payload[rows][0][entries][0][point][label]": "east",
                "payload[rows][0][entries][0][title]": "first",
                "payload[rows][0][entries][1][point][a]": "5",
                "payload[rows][0][entries][1][title]": "second",
                "payload[rows][1][heading]": "beta",
                "payload[rows][1][entries][0][point][a]": "6",
                "payload[rows][1][entries][0][title]": "third",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["payload"],
            {
                "rows": [
                    {
                        "heading": "alpha",
                        "entries": [
                            {"point": {"a": 4, "label": "east"}, "title": "first"},
                            {"point": {"a": 5, "label": ""}, "title": "second"},
                        ],
                    },
                    {
                        "heading": "beta",
                        "entries": [
                            {"point": {"a": 6, "label": ""}, "title": "third"},
                        ],
                    },
                ]
            },
        )


class DictFieldPropertyTestCase(SimpleTestCase):
    @staticmethod
    def _form_outcome(form, name):
        if form.is_valid():
            return ("ok", form.cleaned_data[name])
        return (
            "error",
            tuple(
                (error.code, (error.params or {}).get("child_code"))
                for error in form.errors.as_data()[name]
            ),
        )

    @HYPOTHESIS_SETTINGS
    @given(value=RAW_INTEGER_VALUES)
    def test_all_mapping_spellings_have_the_same_public_outcome(self, value):
        """Valid and invalid child values behave equally in every spelling."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        outcomes = [
            self._form_outcome(
                Form(mapping_data("point", {"a": value}, style)), "point"
            )
            for style in MAPPING_STYLES
        ]
        self.assertEqual(outcomes, [outcomes[0]] * len(MAPPING_STYLES))

    @HYPOTHESIS_SETTINGS
    @given(value=JSON_VALUES)
    def test_json_values_clean_equally_across_supported_spellings(self, value):
        """Encoded JSON values clean equally across every mapping spelling."""

        class ChildForm(forms.Form):
            payload = forms.JSONField()

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        outcomes = []
        for style in MAPPING_STYLES:
            outcomes.append(
                self._form_outcome(
                    Form(
                        mapping_data(
                            "value", {"payload": json.dumps(value)}, style
                        )
                    ),
                    "value",
                )
            )
        self.assertEqual(outcomes, [outcomes[0]] * len(outcomes))
        if outcomes[0][0] == "ok":
            self.assertEqual(outcomes[0][1], {"payload": value})

    @HYPOTHESIS_SETTINGS
    @given(
        values=st.lists(SMALL_INTEGERS, min_size=1, max_size=4),
        styles=st.tuples(*(st.sampled_from(PATH_STYLES) for _ in range(4))),
    )
    def test_recursive_paths_accept_independent_separator_styles(self, values, styles):
        """Every mapping and sequence boundary normalizes its own separator."""

        class RowForm(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        class ChildForm(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.MappingField(RowForm))

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm)

        data = {
            mixed_path("payload", ("rows", index, "point", "a"), styles): str(value)
            for index, value in enumerate(values)
        }
        form = Form(data)

        self.assertTrue(form.is_valid(), (styles, form.errors))
        self.assertEqual(
            form.cleaned_data["payload"],
            {
                "rows": [
                    {"point": {"a": value, "label": ""}} for value in values
                ]
            },
        )

    @HYPOTHESIS_SETTINGS
    @given(initial=JSON_VALUES, submitted=JSON_VALUES)
    def test_has_changed_matches_json_field_semantics(self, initial, submitted):
        """Mapping change detection delegates semantic comparison to its child."""

        class ChildForm(forms.Form):
            payload = forms.JSONField(required=False)

        field = nestingdolls.MappingField(ChildForm, required=False)
        raw = json.dumps(submitted)

        self.assertEqual(
            field.has_changed({"payload": initial}, {"payload": raw}),
            forms.JSONField(required=False).has_changed(initial, raw),
        )

    @HYPOTHESIS_SETTINGS
    @given(
        values=st.lists(
            st.sampled_from(("a", "b", "c")), min_size=1, max_size=3, unique=True
        ),
        style=st.sampled_from(PATH_STYLES),
    )
    def test_querydict_repeated_values_follow_child_widget_semantics(
        self, values, style
    ):
        """Normalization retains every repeated value for getlist widgets."""

        class ChildForm(forms.Form):
            choices = forms.MultipleChoiceField(
                choices=(("a", "A"), ("b", "B"), ("c", "C"))
            )

        class Form(forms.Form):
            filters = nestingdolls.MappingField(ChildForm)

        key = nested_path("filters", ("choices",), style)
        data = QueryDict("", mutable=True)
        data.setlist(key, values)
        form = Form(data)

        self.assertTrue(form.is_valid(), (style, form.errors))
        self.assertEqual(form.cleaned_data["filters"]["choices"], values)

    @HYPOTHESIS_SETTINGS
    @given(value=DATETIMES, style=st.sampled_from(PATH_STYLES))
    def test_compound_values_clean_across_flat_mapping_spellings(self, value, style):
        """Each flat spelling preserves every part of a compound widget."""

        class ChildForm(forms.Form):
            happened_at = forms.SplitDateTimeField()

        class Form(forms.Form):
            event = nestingdolls.MappingField(ChildForm)

        if style == "dash":
            prefix = "event-happened_at"
        elif style == "dot":
            prefix = "event.happened_at"
        else:
            prefix = "event[happened_at]"
        form = Form(
            {
                f"{prefix}_0": value.date().isoformat(),
                f"{prefix}_1": value.time().strftime("%H:%M:%S"),
            }
        )

        self.assertTrue(form.is_valid(), (style, form.errors))
        self.assertEqual(
            form.cleaned_data["event"]["happened_at"].replace(tzinfo=None), value
        )

    @HYPOTHESIS_SETTINGS
    @given(value=SMALL_INTEGERS, suffix=st.text(max_size=8))
    def test_unrelated_prefixes_do_not_enter_the_mapping(self, value, suffix):
        """Keys outside the exact mapping prefix cannot satisfy the field."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({f"pointer{suffix}": str(value)})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["point"][0].code, "required")

    @HYPOTHESIS_SETTINGS
    @example(
        family=(
            "mapping-child-scalar-plus-leaf",
            {
                "dash": {"payload-point": "1", "payload-point[a]": "2"},
                "dot": {"payload.point": "1", "payload.point[a]": "2"},
                "bracket": {"payload[point]": "1", "payload[point][a]": "2"},
            },
        )
    )
    @given(
        family=st.sampled_from(
            (
                (
                    "mapping-child-scalar-plus-leaf",
                    {
                        "dash": {"payload-point": "1", "payload-point[a]": "2"},
                        "dot": {"payload.point": "1", "payload.point[a]": "2"},
                        "bracket": {"payload[point]": "1", "payload[point][a]": "2"},
                    },
                ),
                (
                    "mapping-child-malformed-suffix",
                    {
                        "dash": {"payload-point[a]junk": "2"},
                        "dot": {"payload.point[a]junk": "2"},
                        "bracket": {"payload[point][a]junk": "2"},
                    },
                ),
                (
                    "mapping-child-direct-collision",
                    {
                        "dash": {"payload": {"point": "1"}, "payload-point[a]": "2"},
                        "dot": {"payload": {"point": "1"}, "payload.point[a]": "2"},
                        "bracket": {
                            "payload": {"point": "1"},
                            "payload[point][a]": "2",
                        },
                    },
                ),
            )
        )
    )
    def test_mapping_child_hostile_cases_match_public_outcomes_across_spellings(
        self, family
    ):
        """Hostile mapping-child aliases should agree on validation and rendering."""

        class ChildForm(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm, required=False)

        _, spellings = family
        is_valid_results = []
        error_results = []
        render_results = []
        value_results = []
        for style in PATH_STYLES:
            form = Form(spellings[style])
            is_valid_results.append(form.is_valid())
            error_results.append(
                tuple(
                    (error.code, (error.params or {}).get("child_code"))
                    for error in form.errors.as_data().get("payload", [])
                )
            )
            try:
                str(form["payload"])
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                render_results.append(type(exc).__name__)
            else:
                render_results.append(None)
            try:
                form["payload"].value()
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                value_results.append(type(exc).__name__)
            else:
                value_results.append(None)
        self.assertEqual(is_valid_results, [is_valid_results[0]] * len(is_valid_results))
        self.assertEqual(error_results, [error_results[0]] * len(error_results))
        self.assertEqual(render_results, [render_results[0]] * len(render_results))
        self.assertEqual(value_results, [value_results[0]] * len(value_results))

    @HYPOTHESIS_SETTINGS
    @example(
        family=(
            "sequence-child-scalar-plus-row",
            {
                "dash": {"payload-rows": "1", "payload-rows[0]": "2"},
                "dot": {"payload.rows": "1", "payload.rows[0]": "2"},
                "bracket": {"payload[rows]": "1", "payload[rows][0]": "2"},
            },
        )
    )
    @given(
        family=st.sampled_from(
            (
                (
                    "sequence-child-scalar-plus-row",
                    {
                        "dash": {"payload-rows": "1", "payload-rows[0]": "2"},
                        "dot": {"payload.rows": "1", "payload.rows[0]": "2"},
                        "bracket": {"payload[rows]": "1", "payload[rows][0]": "2"},
                    },
                ),
                (
                    "sequence-child-direct-collision",
                    {
                        "dash": {"payload": {"rows": "1"}, "payload-rows[0]": "2"},
                        "dot": {"payload": {"rows": "1"}, "payload.rows[0]": "2"},
                        "bracket": {
                            "payload": {"rows": "1"},
                            "payload[rows][0]": "2",
                        },
                    },
                ),
                (
                    "sequence-child-malformed-suffix",
                    {
                        "dash": {"payload-rows[0]junk": "2"},
                        "dot": {"payload.rows[0]junk": "2"},
                        "bracket": {"payload[rows][0]junk": "2"},
                    },
                ),
            )
        )
    )
    def test_sequence_child_hostile_cases_match_public_outcomes_across_spellings(
        self, family
    ):
        """Hostile sequence-child aliases should agree on validation and rendering."""

        class ChildForm(forms.Form):
            rows = nestingdolls.ListField(forms.IntegerField(), required=False)

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm, required=False)

        _, spellings = family
        is_valid_results = []
        error_results = []
        render_results = []
        value_results = []
        for style in PATH_STYLES:
            form = Form(spellings[style])
            is_valid_results.append(form.is_valid())
            error_results.append(
                tuple(
                    (error.code, (error.params or {}).get("child_code"))
                    for error in form.errors.as_data().get("payload", [])
                )
            )
            try:
                str(form["payload"])
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                render_results.append(type(exc).__name__)
            else:
                render_results.append(None)
            try:
                form["payload"].value()
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                value_results.append(type(exc).__name__)
            else:
                value_results.append(None)
        self.assertEqual(is_valid_results, [is_valid_results[0]] * len(is_valid_results))
        self.assertEqual(error_results, [error_results[0]] * len(error_results))
        self.assertEqual(render_results, [render_results[0]] * len(render_results))
        self.assertEqual(value_results, [value_results[0]] * len(value_results))

    @HYPOTHESIS_SETTINGS
    @given(
        data=st.sampled_from(
            (
                {"point[a]junk": "1"},
                {"point[0]junk": "1"},
                {"point[0": "1"},
                {"pointer[0]": "1"},
                {"pointx[a]": "1"},
            )
        )
    )
    def test_malformed_mapping_prefixes_and_suffixes_do_not_satisfy_the_field(
        self, data
    ):
        """Malformed mapping aliases cannot satisfy a required field."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(data)

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["point"][0].code, "required")

class DictFieldRegressionTestCase(SimpleTestCase):
    def test_scalar_and_nested_mapping_aliases_do_not_crash_rendering(self):
        """A scalar alias plus a nested alias stays a form error, not a render crash."""

        class ChildForm(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm, required=False)

        cases = (
            ("dash", {"payload-point": "1", "payload-point[a]": "2"}),
            ("dot", {"payload.point": "1", "payload.point[a]": "2"}),
            ("bracket", {"payload[point]": "1", "payload[point][a]": "2"}),
        )
        for label, data in cases:
            with self.subTest(style=label):
                form = Form(data)
                self.assertFalse(form.is_valid())
                self.assertIn(
                    form.errors.as_data()["payload"][0].code,
                    ("invalid", "item_invalid"),
                )
                rendered = str(form["payload"])
                self.assertIn("Enter a mapping of values.", rendered)

    def test_scalar_and_nested_sequence_aliases_inside_mapping_do_not_crash(self):
        """A direct row alias mixed with nested sequence input remains renderable."""

        class ChildForm(forms.Form):
            rows = nestingdolls.ListField(forms.IntegerField(), required=False)

        class Form(forms.Form):
            payload = nestingdolls.MappingField(ChildForm, required=False)

        cases = (
            ("dash", {"payload-rows": "1", "payload-rows[0]": "2"}),
            ("dot", {"payload.rows": "1", "payload.rows[0]": "2"}),
            ("bracket", {"payload[rows]": "1", "payload[rows][0]": "2"}),
        )
        for label, data in cases:
            with self.subTest(style=label):
                form = Form(data)
                self.assertTrue(form.is_valid(), (label, form.errors))
                self.assertEqual(form.cleaned_data["payload"]["rows"], [1])
                rendered = str(form["payload"])
                self.assertIn("name=", rendered)

    def test_numeric_child_names_accept_bracket_and_dot_spellings(self):
        """Numeric child names currently behave as child keys, not row indexes."""

        NumericChildForm = type(
            "NumericChildForm",
            (forms.Form,),
            {"0": forms.IntegerField()},
        )

        class Form(forms.Form):
            point = nestingdolls.MappingField(NumericChildForm, required=False)

        for style in ("dot", "bracket"):
            with self.subTest(style=style):
                if style == "dot":
                    data = {"point.0": "1"}
                else:
                    data = {"point[0]": "1"}
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["point"], {"0": 1})


class PublicApiTestCase(SimpleTestCase):
    def test_mapping_family_is_exported(self):
        """The package exports canonical mapping types and public aliases."""
        self.assertIs(
            nestingdolls.MappingField.bound_field_class, nestingdolls.MappingBoundField
        )
        self.assertIsInstance(
            nestingdolls.MappingField(PointForm).widget, nestingdolls.MappingWidget
        )
        self.assertIs(nestingdolls.DictField, nestingdolls.MappingField)
        self.assertIs(nestingdolls.FormField, nestingdolls.MappingField)
        self.assertIs(nestingdolls.Subform, nestingdolls.MappingField)

    def test_mapping_bound_field_rejects_non_mapping_field(self):
        """It rejects direct misuse with a non-mapping field under optimized Python."""
        with self.assertRaisesRegex(TypeError, "field must be a MappingField"):
            nestingdolls.MappingBoundField(forms.Form(), forms.CharField(), "value")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
