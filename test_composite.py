"""Tests shared by sequence and mapping fields.

Each test names the concrete ``ListField`` or ``DictField`` behavior it covers.
Tests for one field family belong in its own test module.
"""

from __future__ import annotations

import copy
import unittest
from typing import ClassVar

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import QueryDict
from django.test import SimpleTestCase
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
    teardown_test_environment()


class PointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


class SequenceForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField())


class OptionalSequenceForm(forms.Form):
    values = nestingdolls.ListField(forms.IntegerField(), required=False)


class MappingForm(forms.Form):
    point = nestingdolls.DictField(PointForm)


class OptionalMappingForm(forms.Form):
    point = nestingdolls.DictField(PointForm, required=False)


class CompositeFieldAssertions:
    def assertRenderStateIsIsolated(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
    ) -> None:
        bound = form_class(invalid_data)
        self.assertIs(bound.is_valid(), False)
        bound_html = bound.as_p()
        bound_widget = bound.fields[field_name].widget

        fresh = form_class()
        fresh_widget = fresh.fields[field_name].widget
        fresh_html = fresh.as_p()

        self.assertIn("errorlist", bound_html)
        self.assertIsNot(fresh_widget, bound_widget)
        self.assertNotIn("errorlist", fresh_html)
        self.assertNotIn("bad", fresh_html)

    def assertChangeDetectionUsesChildSemantics(
        self,
        form_class: type[forms.Form],
        field_name: str,
        prefixed_data: dict[str, str],
        unchanged_initial: object,
        changed_initial: object,
    ) -> None:
        unchanged = form_class(prefixed_data, initial={field_name: unchanged_initial})
        changed = form_class(prefixed_data, initial={field_name: changed_initial})

        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def assertOuterValidatorErrorStaysVisible(
        self,
        form_class: type[forms.Form],
        field_name: str,
        forged_query: str,
    ) -> None:
        form = form_class(QueryDict(forged_query))

        self.assertIs(form.is_valid(), False)
        self.assertEqual(list(form[field_name].errors), ["Outer error."])
        self.assertEqual(form.as_p().count("Outer error."), 1)

    def assertBoundFieldHidesChildErrors(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
        invalid_message: str,
    ) -> None:
        form = form_class(invalid_data)

        self.assertIs(form.is_valid(), False)
        bound_field = form[field_name]

        self.assertEqual(list(bound_field.errors), [])
        self.assertIn(invalid_message, list(form.errors[field_name]))
        self.assertIs(bound_field.errors, bound_field.errors)

    def assertMultipleOuterMessagesStayVisible(
        self,
        form_class: type[forms.Form],
        field_name: str,
        forged_query: str,
    ) -> None:
        form = form_class(QueryDict(forged_query))

        self.assertIs(form.is_valid(), False)
        self.assertEqual(
            list(form[field_name].errors), ["First outer.", "Second outer."]
        )

    def assertCustomBoundFieldRendersError(
        self,
        form_class: type[forms.Form],
        bound_field_class: type,
        field_name: str,
        invalid_data: dict[str, str],
        invalid_message: str,
    ) -> None:
        form = form_class(invalid_data)

        self.assertIs(form.is_valid(), False)
        self.assertIsInstance(form[field_name], bound_field_class)
        self.assertIn(invalid_message, form.as_p())

    def assertForeignFieldIsRejected(self, bound_field_class: type) -> None:
        with self.assertRaisesRegex(TypeError, "field must be a"):
            bound_field_class(forms.Form(), forms.CharField(), "value")

    def assertWrapperMarkup(
        self,
        form_class: type[forms.Form],
        form_method: str,
        template: str,
        widget_name: str,
    ) -> None:
        form = form_class()
        with self.assertTemplateUsed(template):
            html = getattr(form, form_method)()
        self.assertIn(f'data-widget="{widget_name}"', html)

    def assertSequentialRendersUseOwnLayout(
        self, form_class: type[forms.Form], widget_name: str
    ) -> None:
        form = form_class()

        table_html = form.as_table()
        p_html = form.as_p()

        self.assertIn(f'<span\n  data-widget="{widget_name}"', p_html)
        self.assertIn(f'<div\n  data-widget="{widget_name}"', table_html)

    def assertDefaultRenderUsesDivLayout(
        self, form_class: type[forms.Form], widget_name: str
    ) -> None:
        self.assertIn(f'<div\n  data-widget="{widget_name}"', str(form_class()))

    def assertLiteralTemplateNameSurvives(
        self, form_class: type[forms.Form], field_name: str
    ) -> None:
        widget = copy.deepcopy(form_class().fields[field_name].widget)
        widget.template_name = "app/{custom}.html"

        self.assertEqual(widget.template_name, "app/{custom}.html")


class SequenceCompositeFunctionalTestCase(CompositeFieldAssertions, SimpleTestCase):
    def test_render_state_is_isolated(self):
        """An invalid sequence form does not change a fresh form."""
        self.assertRenderStateIsIsolated(
            OptionalSequenceForm,
            "values",
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )

    def test_change_detection_uses_child_semantics(self):
        """A sequence child converts one before change detection."""
        self.assertChangeDetectionUsesChildSemantics(
            OptionalSequenceForm,
            "values",
            {
                "values-0": "1",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
            [1],
            [3, 4],
        )

    def test_outer_validator_error_stays_visible(self):
        """A sequence validator error remains visible at the outer field."""

        def reject(value):
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), validators=[reject])

        self.assertOuterValidatorErrorStaysVisible(
            Form,
            "values",
            "values=forged&values-0=1&values-1=2&"
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0",
        )

    def test_bound_field_hides_child_item_errors(self):
        """A sequence bound field hides an error that the row renders."""
        self.assertBoundFieldHidesChildErrors(
            OptionalSequenceForm,
            "values",
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
            "Enter a whole number.",
        )

    def test_multiple_outer_validator_messages_stay_visible(self):
        """A sequence validator keeps both outer messages."""

        def reject_with_two_messages(value):
            raise ValidationError(["First outer.", "Second outer."])

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                required=False,
                validators=[reject_with_two_messages],
            )

        self.assertMultipleOuterMessagesStayVisible(
            Form,
            "values",
            "values=forged&values-0=1&values-1=2&"
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0",
        )

    def test_custom_bound_field_renders_the_field_error(self):
        """A custom sequence bound field renders its row error."""

        class CustomBoundField(nestingdolls.SequenceBoundField):
            pass

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=CustomBoundField
            )

        self.assertCustomBoundFieldRendersError(
            Form,
            CustomBoundField,
            "values",
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
            "Enter a whole number.",
        )

    def test_bound_field_rejects_a_foreign_field(self):
        """A sequence bound field rejects a foreign field."""
        self.assertForeignFieldIsRejected(nestingdolls.SequenceBoundField)

    def test_as_div_uses_the_div_wrapper(self):
        """The sequence div helper uses the div widget wrapper."""
        self.assertWrapperMarkup(
            SequenceForm,
            "as_div",
            "nestingdolls/sequence/div.html",
            "sequence",
        )

    def test_as_p_uses_the_p_wrapper(self):
        """The sequence paragraph helper uses the paragraph widget wrapper."""
        self.assertWrapperMarkup(
            SequenceForm,
            "as_p",
            "nestingdolls/sequence/p.html",
            "sequence",
        )

    def test_as_table_uses_the_table_wrapper(self):
        """The sequence table helper uses the table widget wrapper."""
        self.assertWrapperMarkup(
            SequenceForm,
            "as_table",
            "nestingdolls/sequence/table.html",
            "sequence",
        )

    def test_as_ul_uses_the_ul_wrapper(self):
        """The sequence list helper uses the list widget wrapper."""
        self.assertWrapperMarkup(
            SequenceForm,
            "as_ul",
            "nestingdolls/sequence/ul.html",
            "sequence",
        )

    def test_sequential_renders_use_their_own_layout(self):
        """A sequence form keeps each render layout separate."""
        self.assertSequentialRendersUseOwnLayout(SequenceForm, "sequence")

    def test_default_render_uses_the_div_layout(self):
        """A sequence default render uses the Django div layout."""
        self.assertDefaultRenderUsesDivLayout(SequenceForm, "sequence")

    def test_custom_template_name_stays_literal(self):
        """A sequence widget keeps a literal custom template name."""
        self.assertLiteralTemplateNameSurvives(SequenceForm, "values")

    def test_whole_value_dict_cleans(self):
        """A sequence whole value in a dict cleans every row."""
        form = OptionalSequenceForm({"values": ["3", "4"]})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_whole_value_multi_value_dict_cleans(self):
        """A sequence whole value in a multi-value dict cleans every row."""
        form = OptionalSequenceForm(MultiValueDict({"values": [["3", "4"]]}))
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_prefixed_data_cleans(self):
        """A prefixed sequence submission cleans its row."""
        form = SequenceForm(
            {
                "values-0": "1",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])

    def test_whole_value_cleans(self):
        """A whole sequence value cleans every row."""
        form = SequenceForm({"values": ["3", "4"]})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [3, 4])


class MappingCompositeFunctionalTestCase(CompositeFieldAssertions, SimpleTestCase):
    def test_render_state_is_isolated(self):
        """An invalid mapping form does not change a fresh form."""
        self.assertRenderStateIsIsolated(
            OptionalMappingForm, "point", {"point-a": "bad"}
        )

    def test_change_detection_uses_child_semantics(self):
        """A mapping child converts one before change detection."""
        self.assertChangeDetectionUsesChildSemantics(
            OptionalMappingForm,
            "point",
            {"point-a": "1"},
            {"a": 1},
            {"a": 3, "label": "whole"},
        )

    def test_outer_validator_error_stays_visible(self):
        """A mapping validator error remains visible at the outer field."""

        def reject(value):
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            point = nestingdolls.DictField(PointForm, validators=[reject])

        self.assertOuterValidatorErrorStaysVisible(
            Form, "point", "point=forged&point-a=1&point-label=kept"
        )

    def test_bound_field_hides_child_item_errors(self):
        """A mapping bound field hides an error that the child renders."""
        self.assertBoundFieldHidesChildErrors(
            OptionalMappingForm,
            "point",
            {"point-a": "bad"},
            "Enter a whole number.",
        )

    def test_multiple_outer_validator_messages_stay_visible(self):
        """A mapping validator keeps both outer messages."""

        def reject_with_two_messages(value):
            raise ValidationError(["First outer.", "Second outer."])

        class Form(forms.Form):
            point = nestingdolls.DictField(
                PointForm,
                required=False,
                validators=[reject_with_two_messages],
            )

        self.assertMultipleOuterMessagesStayVisible(
            Form,
            "point",
            "point=forged&point-a=1&point-label=kept",
        )

    def test_mapping_accepts_declared_prefixed_children_only(self):
        """Dot, bracket, and undeclared keys cannot enter a child form."""
        form = OptionalMappingForm(
            {
                "point-a": "1",
                "point-label": "kept",
                "point-undeclared": "ignored",
                "point.a": "ignored",
                "point[a]": "ignored",
            }
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": "kept"})

    def test_mapping_preserves_getlist_values_for_child_widgets(self):
        """Canonicalization copies every repeated value through Django's protocol."""

        class RepeatedInput(dict[str, object]):
            def getlist(self, key: str) -> list[object]:
                return self.lists.get(key, [])

            def __init__(self) -> None:
                super().__init__({"point-a": "second"})
                self.lists = {"point-a": ["first", "second"]}

        class CaptureWidget(forms.TextInput):
            values: ClassVar[list[object]] = []

            def value_from_datadict(self, data, files, name):
                type(self).values = data.getlist(name)
                return super().value_from_datadict(data, files, name)

        class CaptureForm(forms.Form):
            a = forms.CharField(widget=CaptureWidget)

        class Form(forms.Form):
            point = nestingdolls.DictField(CaptureForm)

        form = Form(RepeatedInput())
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(CaptureWidget.values, ["first", "second"])

    def test_custom_bound_field_renders_the_field_error(self):
        """A custom mapping bound field renders its child error."""

        class CustomBoundField(nestingdolls.MappingBoundField):
            pass

        class Form(forms.Form):
            point = nestingdolls.DictField(
                PointForm, bound_field_class=CustomBoundField
            )

        self.assertCustomBoundFieldRendersError(
            Form,
            CustomBoundField,
            "point",
            {"point-a": "bad"},
            "Enter a whole number.",
        )

    def test_bound_field_rejects_a_foreign_field(self):
        """A mapping bound field rejects a foreign field."""
        self.assertForeignFieldIsRejected(nestingdolls.MappingBoundField)

    def test_as_div_uses_the_div_wrapper(self):
        """The mapping div helper uses the div widget wrapper."""
        self.assertWrapperMarkup(
            MappingForm,
            "as_div",
            "nestingdolls/mapping/div.html",
            "mapping",
        )

    def test_as_p_uses_the_p_wrapper(self):
        """The mapping paragraph helper uses the paragraph widget wrapper."""
        self.assertWrapperMarkup(
            MappingForm,
            "as_p",
            "nestingdolls/mapping/p.html",
            "mapping",
        )

    def test_as_table_uses_the_table_wrapper(self):
        """The mapping table helper uses the table widget wrapper."""
        self.assertWrapperMarkup(
            MappingForm,
            "as_table",
            "nestingdolls/mapping/table.html",
            "mapping",
        )

    def test_as_ul_uses_the_ul_wrapper(self):
        """The mapping list helper uses the list widget wrapper."""
        self.assertWrapperMarkup(
            MappingForm,
            "as_ul",
            "nestingdolls/mapping/ul.html",
            "mapping",
        )

    def test_sequential_renders_use_their_own_layout(self):
        """A mapping form keeps each render layout separate."""
        self.assertSequentialRendersUseOwnLayout(MappingForm, "mapping")

    def test_default_render_uses_the_div_layout(self):
        """A mapping default render uses the Django div layout."""
        self.assertDefaultRenderUsesDivLayout(MappingForm, "mapping")

    def test_custom_template_name_stays_literal(self):
        """A mapping widget keeps a literal custom template name."""
        self.assertLiteralTemplateNameSurvives(MappingForm, "point")

    def test_whole_value_dict_cleans(self):
        """A mapping whole value in a dict cleans every child."""
        form = OptionalMappingForm({"point": {"a": "3", "label": "whole"}})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_whole_value_multi_value_dict_cleans(self):
        """A mapping whole value in a multi-value dict cleans every child."""
        form = OptionalMappingForm(
            MultiValueDict({"point": [{"a": "3", "label": "whole"}]})
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})

    def test_prefixed_data_cleans(self):
        """A prefixed mapping submission cleans its child."""
        form = MappingForm({"point-a": "1"})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 1, "label": ""})

    def test_whole_value_cleans(self):
        """A whole mapping value cleans every child."""
        form = MappingForm({"point": {"a": "3", "label": "whole"}})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["point"], {"a": 3, "label": "whole"})


class CompositeWidgetTestCase(SimpleTestCase):
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

    def test_every_exported_name_is_importable(self):
        """Every name in ``__all__`` is importable."""
        missing = {
            name for name in nestingdolls.__all__ if not hasattr(nestingdolls, name)
        }
        self.assertEqual(missing, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
