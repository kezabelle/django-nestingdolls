"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    ImproperlyConfigured,
    MappingFormBindingUnitTestCase,
    MappingProbeFixtures,
    MappingProxyType,
    MultiValueDict,
    QueryDict,
    SimpleTestCase,
    SimpleUploadedFile,
    ValidationError,
    forms,
    nestingdolls,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class MappingFieldDirectApiTestCase(MappingFormBindingUnitTestCase):
    """These tests check the direct MappingField API."""

    def test_uploaded_file_named_after_the_field_keeps_the_child_input(self):
        """A file named after the field cannot replace its mapped child inputs."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        form = Form(
            data=QueryDict("point-a=1&point-label=kept"),
            files=MultiValueDict(
                {"point": [SimpleUploadedFile("forged.txt", b"forged")]}
            ),
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_file_child_keys_outrank_an_exact_data_scalar_in_extraction(self):
        """Extraction reads child file input before exact scalar input."""

        class ChildForm(forms.Form):
            document = forms.FileField()

        field = nestingdolls.MappingField(ChildForm)
        upload = SimpleUploadedFile("real.txt", b"real")

        value = field.widget.value_from_datadict(
            QueryDict("asset=forged"),
            MultiValueDict({"asset-document": [upload]}),
            "asset",
        )

        self.assertEqual(value, {"document": upload})

    def test_invalid_mapping_shapes_stay_in_djangos_bound_data_path(self):
        """It redisplays hostile submitted data and disabled hostile initials."""
        enabled = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, required=False
        )
        disabled = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, required=False, disabled=True
        )

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

    def test_output_builds_another_mapping_type(self):
        """The ``output`` option builds the cleaned value as a different mapping type."""

        class ChildForm(forms.Form):
            value = forms.IntegerField()

        cleaned = nestingdolls.MappingField(ChildForm, output=MappingProxyType).clean(
            {"value": "2"}
        )

        self.assertIsInstance(cleaned, MappingProxyType)
        self.assertEqual(cleaned, {"value": 2})

    def test_dynamic_child_fields_use_instantiated_form_fields(self):
        """Rendering and cleaning use fields added by the child Form instance."""

        class DynamicForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["number"] = forms.IntegerField()
                self.fields["upload"] = forms.FileField(required=False)
                self.fields["nested"] = nestingdolls.MappingField(
                    MappingProbeFixtures.MappingPointForm
                )

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
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        form = Form({"point": "not a mapping"})

        self.assertIs(form.is_valid(), False)
        self.assertIsInstance(
            form.errors.as_data()["point"][0],
            nestingdolls.MappingInputValidationError,
        )
        self.assertEqual(form.errors.as_data()["point"][0].code, "invalid")

    def test_as_hidden_uses_child_hidden_widgets(self):
        """A hidden mapping renders every child through its hidden widget."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        form = Form(initial={"point": {"a": 8, "label": "saved"}})

        html = form["point"].as_hidden()

        self.assertIn('type="hidden" name="point-a" value="8"', html)
        self.assertIn('type="hidden" name="point-label" value="saved"', html)
        self.assertNotIn('type="number"', html)
        self.assertNotIn('type="text"', html)

    def test_show_hidden_initial_uses_child_hidden_widgets(self):
        """Django can compare hidden mapping initial values by child name."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, show_hidden_initial=True
            )

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

    def test_partial_hidden_initial_reports_the_missing_member_as_a_change(self):
        """A hidden initial without one member compares that member as missing."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, show_hidden_initial=True
            )

        partial = Form(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "8",
            },
            initial={"point": {"a": 8, "label": "saved"}},
        )
        self.assertIs(partial.has_changed(), True)

    def test_direct_has_changed_covers_disabled_unreadable_and_failing_members(self):
        """A disabled mapping reports no change. An unreadable value or a failing member reports a change."""
        disabled = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, disabled=True
        )
        field = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        self.assertIs(disabled.has_changed({"a": 1}, {"a": 2}), False)
        self.assertIs(field.has_changed(["bad"], {"a": 1}), True)
        self.assertIs(field.has_changed({"a": 1}, "bad"), True)

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise ValidationError("comparison failed")

        class ErrorForm(forms.Form):
            a = ErrorField()

        self.assertIs(
            nestingdolls.MappingField(ErrorForm).has_changed({"a": 1}, {"a": 2}), True
        )

    def test_rejects_wrong_form_widget_output_and_bound_field_types(self):
        """Constructor extension points require compatible types."""

        class NeedsArgForm(forms.Form):
            def __init__(self, token, *args, **kwargs):
                super().__init__(*args, **kwargs)

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(forms.IntegerField)  # type: ignore[arg-type]
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(NeedsArgForm)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, widget=forms.TextInput
            )
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm,
                bound_field_class=forms.BoundField,
            )
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm, output=1)

    def test_widget_extensions_are_copied_and_rebound_to_the_child_form(self):
        """Django copies widget instances and the field supplies its Form class."""

        class CustomWidget(nestingdolls.MappingWidget):
            pass

        widget = CustomWidget()
        instance_field = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, widget=widget
        )
        class_field = nestingdolls.MappingField(
            MappingProbeFixtures.MappingPointForm, widget=CustomWidget
        )

        self.assertIsNot(instance_field.widget, widget)
        self.assertIs(
            instance_field.widget.form_class, MappingProbeFixtures.MappingPointForm
        )
        self.assertIsInstance(class_field.widget, CustomWidget)
        self.assertIs(
            class_field.widget.form_class, MappingProbeFixtures.MappingPointForm
        )


class MappingFieldHostileValueRenderingTestCase(SimpleTestCase):
    """These tests check MappingField rendering for hostile values."""

    def assertPointValueRenders(self, form):
        self.assertEqual(form["point"].value(), ["bad"])
        str(form["point"])

    def test_list_initial_stays_renderable(self):
        """A list initial for a mapping field stays renderable."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, required=False
            )

        self.assertPointValueRenders(Form(initial={"point": ["bad"]}))

    def test_callable_list_initial_stays_renderable(self):
        """A callable list initial for a mapping field stays renderable."""

        class CallableInitialForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm,
                required=False,
                initial=lambda: ["bad"],
            )

        self.assertPointValueRenders(CallableInitialForm())

    def test_disabled_and_scalar_file_hostile_values_stay_renderable_errors(self):
        """Disabled and scalar file hostile values stay Django form errors."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, required=False
            )

        class DisabledForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, required=False, disabled=True
            )

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

    def assertHostileHiddenInitialPayloadRendersError(self, data):
        class NestedForm(forms.Form):
            rows = nestingdolls.ListField(
                nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm),
                required=False,
            )

        class HiddenInitialForm(forms.Form):
            payload = nestingdolls.MappingField(
                NestedForm, required=False, show_hidden_initial=True
            )

        hidden = HiddenInitialForm(
            data,
            initial={"payload": {"rows": [{"a": 1, "label": "saved"}]}},
        )
        self.assertIs(hidden.is_valid(), False)
        self.assertIn("Enter a mapping of values.", hidden.as_p())

    def test_scalar_hidden_initial_payload_stays_a_renderable_error(self):
        """A scalar hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError({"payload": "hostile"})

    def test_nested_list_hidden_initial_payload_stays_a_renderable_error(self):
        """A nested list hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError(
            {"payload": {"rows": ["hostile"]}}
        )

    def test_prepare_value_rejection_returns_the_mapping_initial_value(self):
        """A child prepare value rejection returns the mapping initial value."""

        class RejectingField(forms.CharField):
            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class ChildForm(forms.Form):
            value = RejectingField()

        field = nestingdolls.MappingField(ChildForm)
        value = {"value": "hostile"}
        self.assertEqual(field.prepare_value(value), value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
