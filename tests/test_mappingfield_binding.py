"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest
from types import MappingProxyType

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils.datastructures import MultiValueDict

import nestingdolls

from .support.forms.mapping import (
    HiddenInitialMappingPointForm,
    MappingPointForm,
    RequiredMappingPointForm,
)
from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class MappingFieldBindingTestCase(CompositeFieldTestCase):
    """These tests check the direct MappingField API."""

    def test_uploaded_file_named_after_the_field_keeps_the_child_input(self) -> None:
        """A file named after the field cannot replace its mapped child inputs."""
        form = RequiredMappingPointForm(
            data=QueryDict("point-a=1&point-label=kept"),
            files=MultiValueDict(
                {"point": [SimpleUploadedFile("forged.txt", b"forged")]}
            ),
        )

        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_file_child_keys_outrank_an_exact_data_scalar_in_extraction(self) -> None:
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

    def test_invalid_mapping_shapes_stay_in_djangos_bound_data_path(self) -> None:
        """It redisplays hostile submitted data and disabled hostile initials."""
        enabled = nestingdolls.MappingField(MappingPointForm, required=False)
        disabled = nestingdolls.MappingField(
            MappingPointForm, required=False, disabled=True
        )

        submitted = ["hostile"]
        initial = ["initial"]
        self.assertIs(enabled.bound_data(submitted, initial), submitted)
        self.assertIs(disabled.bound_data(submitted, initial), initial)

    def test_to_python_only_checks_the_container_shape(self) -> None:
        """Shape conversion does not run child Form cleaning hooks."""
        cleaned = False

        class ChildForm(forms.Form):
            a = forms.IntegerField()

            def clean(self) -> object:
                nonlocal cleaned
                cleaned = True
                return super().clean()

        field = nestingdolls.MappingField(ChildForm)

        self.assertEqual(field.to_python({"a": "2"}), {"a": "2"})
        self.assertIs(cleaned, False)
        self.assertEqual(field.clean({"a": "2"}), {"a": 2})
        self.assertIs(cleaned, True)

    def test_output_builds_another_mapping_type(self) -> None:
        """The ``output`` option builds the cleaned value as a different mapping type."""

        class ChildForm(forms.Form):
            value = forms.IntegerField()

        cleaned = nestingdolls.MappingField(ChildForm, output=MappingProxyType).clean(
            {"value": "2"}
        )

        self.assertIsInstance(cleaned, MappingProxyType)
        self.assertEqual(cleaned, {"value": 2})

    def test_dynamic_child_fields_use_instantiated_form_fields(self) -> None:
        """Rendering and cleaning use fields added by the child Form instance."""

        class DynamicForm(forms.Form):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)
                self.fields["number"] = forms.IntegerField()
                self.fields["upload"] = forms.FileField(required=False)
                self.fields["nested"] = nestingdolls.MappingField(MappingPointForm)

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
        self.assertFormValid(bound)
        self.assertEqual(
            bound.cleaned_data["point"],
            {
                "number": 5,
                "upload": upload,
                "nested": {"a": 6, "label": "submitted"},
            },
        )

    def test_exact_none_with_initial_file_is_invalid_mapping_input(self) -> None:
        """A present null cannot retain an initial file as a mapping submission."""

        class ChildForm(forms.Form):
            document = forms.FileField(required=False)

        class Form(forms.Form):
            asset = nestingdolls.MappingField(ChildForm, required=False)

        initial = SimpleUploadedFile("saved.txt", b"saved")
        form = Form(
            {"asset": None},
            initial={"asset": {"document": initial}},
        )

        self.assertFormInvalid(form)
        self.assertFormErrorCode(form, "asset", "invalid")

    def test_rejects_non_mapping_input(self) -> None:
        """It rejects an exact scalar value."""
        form = RequiredMappingPointForm({"point": "not a mapping"})

        self.assertFormInvalid(form)
        self.assertIsInstance(
            form.errors.as_data()["point"][0],
            nestingdolls.MappingInputValidationError,
        )
        self.assertFormErrorCode(form, "point", "invalid")

    def test_as_hidden_uses_child_hidden_widgets(self) -> None:
        """A hidden mapping renders every child through its hidden widget."""
        form = RequiredMappingPointForm(initial={"point": {"a": 8, "label": "saved"}})

        html = form["point"].as_hidden()

        self.assertIn('type="hidden" name="point-a" value="8"', html)
        self.assertIn('type="hidden" name="point-label" value="saved"', html)
        self.assertNotIn('type="number"', html)
        self.assertNotIn('type="text"', html)

    def test_show_hidden_initial_uses_child_hidden_widgets(self) -> None:
        """Django can compare hidden mapping initial values by child name."""
        initial = {"point": {"a": 8, "label": "saved"}}
        unbound = HiddenInitialMappingPointForm(initial=initial)
        html = unbound.as_div()
        self.assertIn('type="hidden" name="initial-point-a" value="8"', html)
        self.assertIn('type="hidden" name="initial-point-label" value="saved"', html)

        bound = HiddenInitialMappingPointForm(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "8",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertFormValid(bound)
        self.assertIs(bound.has_changed(), False)

        malformed_initial = HiddenInitialMappingPointForm(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "not-an-integer",
                "initial-point-label": "saved",
            },
            initial=initial,
        )
        self.assertIs(malformed_initial.has_changed(), True)

    def test_partial_hidden_initial_reports_the_missing_member_as_a_change(
        self,
    ) -> None:
        """A hidden initial without one member compares that member as missing."""
        partial = HiddenInitialMappingPointForm(
            {
                "point-a": "8",
                "point-label": "saved",
                "initial-point-a": "8",
            },
            initial={"point": {"a": 8, "label": "saved"}},
        )
        self.assertIs(partial.has_changed(), True)

    def test_direct_has_changed_covers_disabled_unreadable_and_failing_members(
        self,
    ) -> None:
        """A disabled mapping reports no change. An unreadable value or a failing member reports a change."""
        disabled = nestingdolls.MappingField(MappingPointForm, disabled=True)
        field = nestingdolls.MappingField(MappingPointForm)

        self.assertIs(disabled.has_changed({"a": 1}, {"a": 2}), False)
        self.assertIs(field.has_changed(["bad"], {"a": 1}), True)
        self.assertIs(field.has_changed({"a": 1}, "bad"), True)

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial: object, data: object) -> object:
                raise ValidationError("comparison failed")

        class ErrorForm(forms.Form):
            a = ErrorField()

        self.assertIs(
            nestingdolls.MappingField(ErrorForm).has_changed({"a": 1}, {"a": 2}), True
        )

    def test_rejects_wrong_form_widget_output_and_bound_field_types(self) -> None:
        """Constructor extension points require compatible types."""

        class NeedsArgForm(forms.Form):
            def __init__(self, token: object, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)

        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(forms.IntegerField)  # type: ignore[arg-type]
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.MappingField(NeedsArgForm)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(MappingPointForm, widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(
                MappingPointForm,
                bound_field_class=forms.BoundField,
            )
        with self.assertRaises(TypeError):
            nestingdolls.MappingField(MappingPointForm, output=1)

    def test_widget_extensions_are_copied_and_rebound_to_the_child_form(self) -> None:
        """Django copies widget instances and the field supplies its Form class."""

        class CustomWidget(nestingdolls.MappingWidget):
            pass

        widget = CustomWidget()
        instance_field = nestingdolls.MappingField(MappingPointForm, widget=widget)
        class_field = nestingdolls.MappingField(MappingPointForm, widget=CustomWidget)

        self.assertIsNot(instance_field.widget, widget)
        self.assertIs(instance_field.widget.form_class, MappingPointForm)
        self.assertIsInstance(class_field.widget, CustomWidget)
        self.assertIs(class_field.widget.form_class, MappingPointForm)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
