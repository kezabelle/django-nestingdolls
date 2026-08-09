from __future__ import annotations

import itertools
import unittest

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import SimpleTestCase
from django.test.html import Element, parse_html
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils.datastructures import MultiValueDict

import nestingdolls

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
    # Undo the global template instrumentation after these unittest-based tests.
    teardown_test_environment()


class PointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


class DictFieldTestCase(SimpleTestCase):
    def test_every_spelling_names_the_same_child(self):
        """Direct, dash, dot, and bracket input all name one child value."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        cases = {
            "direct": {"point": {"a": "2", "label": "east"}},
            "dash": {"point-a": "2", "point-label": "east"},
            "dot": {"point.a": "2", "point.label": "east"},
            "bracket": {"point[a]": "2", "point[label]": "east"},
            # A QueryDict keeps Django's request semantics under the same parser.
            "querydict": QueryDict("point[a]=2&point[label]=east"),
        }
        for style, data in cases.items():
            with self.subTest(style=style):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["point"], {"a": 2, "label": "east"})

        # Extraction exposes a plain mapping, not an internal transport.
        value = Form({"point-a": "2", "point-label": "east"})["point"].value()
        self.assertIsInstance(value, dict)
        self.assertEqual(value, {"a": "2", "label": "east"})

        # The spellings share one canonical key, so the last one submitted wins.
        last_wins = Form({"point-a": "1", "point.a": "2", "point[a]": "3"})
        self.assertIs(last_wins.is_valid(), True, last_wins.errors)
        self.assertEqual(last_wins.cleaned_data["point"]["a"], 3)

        # A numeric child name is a child key, never a sequence row index.
        NumericChildForm = type(
            "NumericChildForm", (forms.Form,), {"0": forms.IntegerField()}
        )
        NumericForm = type(
            "NumericForm",
            (forms.Form,),
            {"point": nestingdolls.MappingField(NumericChildForm, required=False)},
        )
        for style, data in (("dot", {"point.0": "1"}), ("bracket", {"point[0]": "1"})):
            with self.subTest(style=style, child="numeric"):
                form = NumericForm(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["point"], {"0": 1})

    def test_direct_mapping_wins_and_binds_only_declared_children(self):
        """A direct mapping outranks flat aliases and drops undeclared keys."""

        class ChildForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)
            upload = forms.FileField(required=False)

        class Form(forms.Form):
            point = nestingdolls.MappingField(ChildForm)

        upload = SimpleUploadedFile("direct.txt", b"direct")
        form = Form(
            data={
                "point": {"a": "1", "label": "east", "junk": "ignored"},
                "point-a": "99",
                "point-label": "west",
            },
            files={"point[upload]": upload},
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(
            form.cleaned_data["point"], {"a": 1, "label": "east", "upload": upload}
        )

    def test_uploaded_file_named_after_the_field_keeps_the_child_input(self):
        """A file input named after the field cannot replace the whole mapping.

        ``request.FILES`` is a plain ``MultiValueDict``, not a ``QueryDict``,
        so the direct-value rule for programmer-built data would otherwise let
        one upload outrank every real child key.
        """

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(
            data=QueryDict("point-a=1&point-label=kept"),
            files=MultiValueDict(
                {"point": [SimpleUploadedFile("forged.txt", b"forged")]}
            ),
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_flattened_initial_mapping_uses_child_widget_values(self):
        """It reconstructs raw widget values from flat child names."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        self.assertEqual(Form(initial={"point-a": "2"})["point"].initial, {"a": "2"})

    def test_unrecognized_flattened_initial_uses_the_field_initial(self):
        """It leaves Django's configured mapping initial value intact."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                PointForm, required=False, initial={"a": 3}
            )

        self.assertEqual(
            Form(initial={"point-junk": "value"})["point"].initial, {"a": 3}
        )

    def test_invalid_mapping_shapes_stay_in_djangos_bound_data_channel(self):
        """It redisplays hostile submitted data and disabled hostile initials."""
        enabled = nestingdolls.MappingField(PointForm, required=False)
        disabled = nestingdolls.MappingField(PointForm, required=False, disabled=True)

        submitted = ["hostile"]
        initial = ["initial"]
        self.assertIs(enabled.bound_data(submitted, initial), submitted)
        self.assertIs(disabled.bound_data(submitted, initial), initial)

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
        self.assertIs(cleaned, False)
        self.assertEqual(field.clean({"a": "2"}), {"a": 2})
        self.assertIs(cleaned, True)

    def test_dynamic_child_fields_use_instantiated_form_fields(self):
        """Rendering and cleaning use fields added by the child Form instance."""

        class DynamicForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["number"] = forms.IntegerField()
                self.fields["upload"] = forms.FileField(required=False)
                self.fields["nested"] = nestingdolls.MappingField(PointForm)

        class Form(forms.Form):
            point = nestingdolls.MappingField(DynamicForm)

        unbound = Form(
            initial={
                "point": {
                    "number": 3,
                    "nested": {"a": 4, "label": "inside"},
                }
            }
        )
        html = unbound.as_div()
        self.assertIn('type="number" name="point-number"', html)
        self.assertIn('type="file" name="point-upload"', html)
        self.assertIn('name="point-nested-a"', html)
        self.assertIs(unbound["point"].field.widget.is_hidden, False)
        self.assertIs(unbound["point"].field.widget.needs_multipart_form, True)

        upload = SimpleUploadedFile("dynamic.txt", b"dynamic")
        bound = Form(
            data={
                "point": {
                    "number": "5",
                    "nested": {"a": "6", "label": "submitted"},
                }
            },
            files={"point": {"upload": upload}},
        )
        self.assertIs(bound.is_valid(), True, bound.errors)
        self.assertEqual(
            bound.cleaned_data["point"],
            {
                "number": 5,
                "upload": upload,
                "nested": {"a": 6, "label": "submitted"},
            },
        )

    def test_rejects_non_mapping_input(self):
        """It rejects an exact scalar value."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"point": "not a mapping"})

        self.assertIs(form.is_valid(), False)
        self.assertIsInstance(
            form.errors.as_data()["point"][0],
            nestingdolls.MappingInputValidationError,
        )
        self.assertEqual(form.errors.as_data()["point"][0].code, "invalid")

    def test_required_and_optional_empty_mappings_use_the_container_boundary(self):
        """Required applies to the mapping, and optional empty input returns a dict."""

        class Form(forms.Form):
            required_point = nestingdolls.MappingField(PointForm)
            optional_point = nestingdolls.MappingField(PointForm, required=False)

        form = Form({"required_point": {}, "optional_point": {}})

        self.assertIs(form.is_valid(), False)
        self.assertFormError(form, "required_point", "This field is required.")
        self.assertEqual(form.cleaned_data["optional_point"], {})

    def test_optional_partial_mapping_keeps_child_requirements(self):
        """Submitted optional mappings still use the child Form rules."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        form = Form({"point-label": "missing a"})

        self.assertIs(form.is_valid(), False)
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

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = Form({"value-a": "2"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["value"], {"a": 3, "double": 6})

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

        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["value"][0]
        self.assertIsInstance(error, nestingdolls.ItemValidationError)
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "unavailable")
        self.assertEqual(error.params["item"], "__all__")
        self.assertNotIn("path", error.params)

    def test_outer_validators_receive_cleaned_mapping(self):
        """DictField validators receive child-cleaned values."""

        def reject_two(value):
            if value["a"] == 2:
                raise ValidationError("No two.", code="no_two")

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, validators=[reject_two])

        form = Form({"point-a": "2"})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["point"][0].code, "no_two")
        self.assertFormError(form, "point", "No two.")

    def test_form_prefix_is_preserved(self):
        """Nested child names include the normal parent Form prefix."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form({"outer-point-a": "5"}, prefix="outer")

        self.assertIs(form.is_valid(), True, form.errors)
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

        self.assertIs(form.is_valid(), True, form.errors)
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

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {})
        self.assertIs(form.has_changed(), True)

    def test_as_hidden_uses_child_hidden_widgets(self):
        """A hidden mapping renders every child through its hidden widget."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)

        form = Form(initial={"point": {"a": 8, "label": "saved"}})

        html = form["point"].as_hidden()

        self.assertIn('type="hidden" name="point-a" value="8"', html)
        self.assertIn('type="hidden" name="point-label" value="saved"', html)
        self.assertNotIn('type="number"', html)
        self.assertNotIn('type="text"', html)

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
        self.assertIs(bound.is_valid(), True, bound.errors)
        self.assertIs(bound.has_changed(), False)

        malformed_initial = Form(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "not-an-integer",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertIs(malformed_initial.has_changed(), True)

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


class DictFieldRenderingTestCase(SimpleTestCase):
    def test_child_errors_render_once_with_resolvable_references(self):
        """A child error renders beside its own input, with resolvable ids."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm)
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                "point-label": "missing a",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
                "values-0": "bad",
            }
        )
        self.assertIs(form.is_valid(), False)

        # The outer field owns no error; the subform renders it exactly once.
        self.assertEqual(list(form["point"].errors), [])
        rendered = str(form["point"])
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertIn('aria-invalid="true"', rendered)

        paragraphs = form.as_p()
        self.assertIn('aria-describedby="id_point-a_error"', paragraphs)
        self.assertInHTML(
            '<span class="errorlist" id="id_point-a_error">'
            "This field is required."
            "</span>",
            paragraphs,
        )

        for renderer in (form.as_div, form.as_p, form.as_ul, form.as_table):
            with self.subTest(renderer=renderer.__name__):
                elements = [parse_html(renderer())]
                for element in elements:
                    elements.extend(
                        child
                        for child in element.children
                        if isinstance(child, Element)
                    )

                element_attributes = [dict(element.attributes) for element in elements]
                ids = [
                    attributes["id"]
                    for attributes in element_attributes
                    if "id" in attributes
                ]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertIn("id_point-a_error", ids)
                self.assertIn("id_values_0_error", ids)
                for attributes in element_attributes:
                    for reference in attributes.get("aria-describedby", "").split():
                        self.assertIn(reference, ids)

    def test_every_helper_layout_renders_the_child_form_and_wrapper(self):
        """Each helper renders the child inputs, the wrapper, and one hidden initial."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, show_hidden_initial=True)

        form = Form(initial={"point": {"a": 9, "label": "layout"}})

        for renderer in (form.as_div, form.as_p, form.as_table, form.as_ul):
            with self.subTest(renderer=renderer.__name__):
                html = renderer()
                self.assertIn('data-widget="mapping"', html)
                self.assertIn('data-mapping-field="point"', html)
                self.assertIn('id="id_point_widget"', html)
                self.assertIn('name="point-a"', html)
                self.assertIn('name="point-label"', html)
                self.assertEqual(html.count('name="initial-point-a"'), 1)
                self.assertInHTML(
                    '<input type="number" name="point-a" value="9" required'
                    ' id="id_point-a">',
                    html,
                )

    def test_widget_exposes_child_media_and_multipart_requirement(self):
        """The outer widget reports child widget integration requirements."""

        class MediaWidget(forms.TextInput):
            class Media:
                js = ("child.js",)

        class ChildForm(forms.Form):
            title = forms.CharField(widget=MediaWidget)
            upload = forms.FileField(required=False)

        field = nestingdolls.MappingField(ChildForm)

        self.assertIs(field.widget.needs_multipart_form, True)
        self.assertIn("child.js", str(field.widget.media))


class DictFieldWidgetIntegrationTestCase(SimpleTestCase):
    def test_flat_input_ignores_undeclared_child_fields(self):
        """It does not retain matching keys that no child field can consume."""

        class ChildForm(forms.Form):
            title = forms.CharField(required=False)

        widget = nestingdolls.MappingWidget(ChildForm)

        self.assertEqual(
            widget.keys.normalized(
                {"value-title": "kept", "value-untrusted": "ignored"}, "value"
            ),
            {"value-title": "kept"},
        )

    def test_direct_child_values_reach_the_child_field_unchanged(self):
        """Direct mapping input keeps repeated, JSON, compound, and file values."""

        class TagsForm(forms.Form):
            tags = forms.MultipleChoiceField(
                choices=(("one", "One"), ("two", "Two")), required=False
            )

        class TagsOuter(forms.Form):
            point = nestingdolls.MappingField(TagsForm, required=False)

        # A nested MultiValueDict keeps Django's repeated-value shape.
        nested = MultiValueDict[str, object]()
        nested.setlist("tags", ["one", "two"])
        repeated = TagsOuter({"point": nested})
        self.assertIs(repeated.is_valid(), True, repeated.errors)
        self.assertEqual(repeated.cleaned_data["point"], {"tags": ["one", "two"]})

        # A direct list stays one JSON value instead of becoming repeated input.
        class JSONChildForm(forms.Form):
            payload = forms.JSONField()

        class JSONOuter(forms.Form):
            value = nestingdolls.MappingField(JSONChildForm)

        encoded = JSONOuter({"value": {"payload": [1, {"answer": 42}]}})
        self.assertIs(encoded.is_valid(), True, encoded.errors)
        self.assertEqual(encoded.cleaned_data["value"]["payload"], [1, {"answer": 42}])

        # Direct cleaning hands already-extracted compound and file values over.
        class CompoundForm(forms.Form):
            happened_at = forms.SplitDateTimeField()
            upload = forms.FileField()

        upload = SimpleUploadedFile("direct.txt", b"direct")
        cleaned = nestingdolls.MappingField(CompoundForm).clean(
            {"happened_at": ["2026-08-01", "10:30:00"], "upload": upload}
        )
        self.assertEqual(
            cleaned["happened_at"].replace(tzinfo=None).isoformat(),
            "2026-08-01T10:30:00",
        )
        self.assertIs(cleaned["upload"], upload)

    def test_file_children_upload_clear_and_contradict_like_django(self):
        """File children keep Django's upload, initial, clear, and contradiction rules."""

        class ChildForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField(required=False)

        class Form(forms.Form):
            asset = nestingdolls.MappingField(ChildForm)

        upload = SimpleUploadedFile("new.txt", b"new")
        uploaded = Form(
            {"asset": {"title": "report"}},
            files={"asset": {"upload": upload}},
        )
        self.assertIs(uploaded.is_valid(), True, uploaded.errors)
        self.assertEqual(uploaded.cleaned_data["asset"]["title"], "report")
        self.assertIs(uploaded.cleaned_data["asset"]["upload"], upload)

        initial_upload = SimpleUploadedFile("old.txt", b"old")
        initial = {"asset": {"title": "old", "upload": initial_upload}}

        kept = Form({"asset-title": "old"}, initial=initial)
        self.assertIs(kept.is_valid(), True, kept.errors)
        self.assertIs(kept.cleaned_data["asset"]["upload"], initial_upload)

        cleared = Form(
            {"asset-title": "old", "asset-upload-clear": "1"}, initial=initial
        )
        self.assertIs(cleared.is_valid(), True, cleared.errors)
        self.assertIs(cleared.cleaned_data["asset"]["upload"], False)

        contradictory = Form(
            {"asset-title": "old", "asset-upload-clear": "1"},
            files={"asset-upload": SimpleUploadedFile("new.txt", b"new")},
            initial=initial,
        )
        self.assertIs(contradictory.is_valid(), False)
        self.assertEqual(
            contradictory.errors.as_data()["asset"][0].params["child_code"],
            "contradiction",
        )

    def test_untouched_mappings_keep_initial_uploads(self):
        """An unsubmitted mapping preserves its child FileField initials."""

        class FileOnlyForm(forms.Form):
            upload = forms.FileField()

        class MixedForm(forms.Form):
            title = forms.CharField(required=False)
            upload = forms.FileField()

        class NestedForm(forms.Form):
            asset = nestingdolls.MappingField(FileOnlyForm)

        initial_upload = SimpleUploadedFile("old.txt", b"old")
        shapes = {
            "file-only": (FileOnlyForm, {"upload": initial_upload}),
            "mixed": (MixedForm, {"title": "", "upload": initial_upload}),
            "nested": (NestedForm, {"asset": {"upload": initial_upload}}),
        }
        for shape, (child_form, expected) in shapes.items():
            for required in (False, True):
                with self.subTest(shape=shape, required=required):
                    Form = type(
                        "Form",
                        (forms.Form,),
                        {
                            "asset": nestingdolls.MappingField(
                                child_form, required=required
                            )
                        },
                    )

                    form = Form({}, initial={"asset": expected})

                    self.assertIs(form.is_valid(), True, form.errors)
                    self.assertEqual(form.cleaned_data["asset"], expected)

    def test_file_children_drive_change_detection(self):
        """Change detection asks the child FileField, hidden initial or not."""

        class FileForm(forms.Form):
            document = forms.FileField(required=False)

        class HiddenInitialForm(forms.Form):
            asset = nestingdolls.MappingField(
                FileForm,
                initial={"document": "saved.txt"},
                required=False,
                show_hidden_initial=True,
            )

        # A hidden filename does not replace FileField change detection.
        data = QueryDict("initial-asset-document=saved.txt")
        self.assertIs(HiddenInitialForm(data).has_changed(), False)
        replaced = HiddenInitialForm(
            data,
            files=MultiValueDict(
                {"asset-document": [SimpleUploadedFile("replacement.txt", b"new")]}
            ),
        )
        self.assertIs(replaced.has_changed(), True)

        # A submitted upload is a change even when it is also the initial object.
        class Form(forms.Form):
            asset = nestingdolls.MappingField(FileForm, required=False)

        upload = SimpleUploadedFile("same.txt", b"same")
        resubmitted = Form(
            data={},
            files={"asset[document]": upload},
            initial={"asset": {"document": upload}},
        )
        self.assertIs(resubmitted.has_changed(), True)


class NestedDictFieldTestCase(SimpleTestCase):
    def test_every_three_level_mapping_sequence_order_cleans_flat_input(self):
        """Every three-level mapping and sequence order cleans one leaf value."""

        for order in itertools.product(("mapping", "sequence"), repeat=3):
            field = forms.IntegerField()
            expected = 1
            for depth, kind in enumerate(reversed(order)):
                if kind == "mapping":
                    child_form = type(
                        f"MappingChild{depth}", (forms.Form,), {"child": field}
                    )
                    field = nestingdolls.MappingField(child_form)
                    expected = {"child": expected}
                else:
                    field = nestingdolls.ListField(field)
                    expected = [expected]

            form_class = type("Form", (forms.Form,), {"value": field})
            name = "value"
            for kind in order:
                name += "[child]" if kind == "mapping" else "[0]"
            form = form_class({name: "1"})

            with self.subTest(order=order):
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["value"], expected)

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

        self.assertIs(form.is_valid(), True, form.errors)
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

    def test_mapping_error_inside_sequence_renders_once_at_the_row(self):
        """A sequence row owns errors from its mapping child."""

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        form = Form({"values[0][label]": "missing a"})

        self.assertIs(form.is_valid(), False)
        rendered = str(form["values"])
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertEqual(list(form["values"].errors), [])

    def test_nested_file_and_compound_children_follow_django(self):
        """Files and compound widgets survive the sequence-to-mapping boundary."""

        class AssetForm(forms.Form):
            title = forms.CharField()
            upload = forms.FileField(required=False, widget=forms.ClearableFileInput)
            happened_at = forms.SplitDateTimeField()

        class Form(forms.Form):
            assets = nestingdolls.ListField(nestingdolls.MappingField(AssetForm))

        upload = SimpleUploadedFile("nested.txt", b"nested")
        uploaded = Form(
            {
                "assets.0.title": "asset",
                "assets[0][happened_at]_0": "2026-08-01",
                "assets[0][happened_at]_1": "10:30:00",
            },
            files={"assets.0.upload": upload},
        )
        self.assertIs(uploaded.is_valid(), True, uploaded.errors)
        row = uploaded.cleaned_data["assets"][0]
        self.assertEqual(row["title"], "asset")
        self.assertIs(row["upload"], upload)
        self.assertEqual(
            row["happened_at"].replace(tzinfo=None).isoformat(), "2026-08-01T10:30:00"
        )

        data = {
            "assets-0-title": "asset",
            "assets-0-upload-clear": "1",
            "assets-0-happened_at_0": "2026-08-01",
            "assets-0-happened_at_1": "10:30:00",
        }
        initial = {"assets": [{"upload": SimpleUploadedFile("old.txt", b"old")}]}
        cleared = Form(data, initial=initial)

        self.assertIs(cleared.is_valid(), True, cleared.errors)
        self.assertIs(cleared.cleaned_data["assets"][0]["upload"], False)
        self.assertEqual(
            cleared.cleaned_data["assets"][0]["happened_at"]
            .replace(tzinfo=None)
            .isoformat(),
            "2026-08-01T10:30:00",
        )

        contradictory = Form(
            data,
            files={"assets-0-upload": SimpleUploadedFile("new.txt", b"new")},
            initial=initial,
        )
        self.assertIs(contradictory.is_valid(), False)


class DictFieldRegressionTestCase(SimpleTestCase):
    def test_hostile_initials_and_payloads_stay_renderable_errors(self):
        """Malformed initials and payloads stay in Django's error channel."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False)

        class CallableInitialForm(forms.Form):
            point = nestingdolls.MappingField(
                PointForm, required=False, initial=lambda: ["bad"]
            )

        class DisabledForm(forms.Form):
            point = nestingdolls.MappingField(PointForm, required=False, disabled=True)

        for form in (Form(initial={"point": ["bad"]}), CallableInitialForm()):
            with self.subTest(form=form.__class__.__name__):
                self.assertEqual(form["point"].value(), ["bad"])
                str(form["point"])

        disabled = DisabledForm({}, initial={"point": ["bad"]})
        self.assertIs(disabled.is_valid(), False)
        self.assertEqual(disabled.errors.as_data()["point"][0].code, "invalid")
        str(disabled["point"])

        # A hostile scalar in `files` is a form error, never a render crash.
        scalar_file = Form(data={}, files={"point": False})
        self.assertIs(scalar_file.is_valid(), False)
        self.assertEqual(scalar_file.errors.as_data()["point"][0].code, "invalid")
        self.assertIs(scalar_file["point"].value(), False)
        str(scalar_file["point"])

        class NestedForm(forms.Form):
            rows = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm), required=False
            )

        class HiddenInitialForm(forms.Form):
            payload = nestingdolls.MappingField(
                NestedForm, required=False, show_hidden_initial=True
            )

        initial = {"payload": {"rows": [{"a": 1, "label": "saved"}]}}
        for data in ({"payload": "hostile"}, {"payload": {"rows": ["hostile"]}}):
            with self.subTest(data=data):
                hidden = HiddenInitialForm(data, initial=initial)
                self.assertIs(hidden.is_valid(), False)
                self.assertIn("Enter a mapping of values.", hidden.as_p())

    def test_child_rebinding_rejections_use_mapping_fallbacks(self):
        """A child rejection returns a mapping through Django's base contract."""

        class RejectingField(forms.CharField):
            def bound_data(self, data, initial):
                raise ValidationError("Cannot bind this value.")

            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class ChildForm(forms.Form):
            value = RejectingField()

        field = nestingdolls.MappingField(ChildForm)
        value = {"value": "hostile"}

        operations = (
            ("bound_data", lambda: field.bound_data(value, {})),
            ("prepare_value", lambda: field.prepare_value(value)),
        )
        for operation_name, operation in operations:
            with self.subTest(operation=operation_name):
                self.assertEqual(operation(), value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
