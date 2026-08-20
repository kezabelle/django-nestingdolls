"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    CompositeErrorDisplayAssertions,
    CompositeRenderingAssertions,
    Element,
    MappingPointForm,
    MappingProbeFixtures,
    MappingValueForm,
    OptionalMappingValueForm,
    SimpleTestCase,
    ValidationError,
    forms,
    nestingdolls,
    parse_html,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class MappingFieldRenderingTestCase(SimpleTestCase):
    """Tests that each form layout renders the mapping child form, its wrapper, and
    resolvable error references."""

    def assertChildErrorReferencesResolve(self, renderer):
        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)
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

        elements = [parse_html(getattr(form, renderer)())]
        for element in elements:
            elements.extend(
                child for child in element.children if isinstance(child, Element)
            )

        element_attributes = [dict(element.attributes) for element in elements]
        ids = [
            attributes["id"] for attributes in element_attributes if "id" in attributes
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("id_point-a_error", ids)
        self.assertIn("id_values_0_error", ids)
        for attributes in element_attributes:
            for reference in attributes.get("aria-describedby", "").split():
                self.assertIn(reference, ids)

    def test_div_layout_resolves_child_error_references(self):
        """The div layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_div")

    def test_p_layout_resolves_child_error_references(self):
        """The paragraph layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_p")

    def test_ul_layout_resolves_child_error_references(self):
        """The list layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_ul")

    def test_table_layout_resolves_child_error_references(self):
        """The table layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_table")

    def assertMappingChildFormAndWrapperRender(self, renderer):
        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm, show_hidden_initial=True
            )

        form = Form(initial={"point": {"a": 9, "label": "layout"}})
        html = getattr(form, renderer)()
        self.assertIn('data-widget="mapping"', html)
        self.assertIn('data-mapping-field="point"', html)
        self.assertIn('id="id_point_widget"', html)
        self.assertIn('name="point-a"', html)
        self.assertIn('name="point-label"', html)
        self.assertEqual(html.count('name="initial-point-a"'), 1)
        self.assertInHTML(
            '<input type="number" name="point-a" value="9" required id="id_point-a">',
            html,
        )

    def test_div_layout_renders_mapping_child_form_and_wrapper(self):
        """The div layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_div")

    def test_p_layout_renders_mapping_child_form_and_wrapper(self):
        """The paragraph layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_p")

    def test_ul_layout_renders_mapping_child_form_and_wrapper(self):
        """The list layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_ul")

    def test_table_layout_renders_mapping_child_form_and_wrapper(self):
        """The table layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_table")

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

    def test_a_direct_widget_render_builds_the_child_form_from_the_value(self):
        """A direct widget render builds the child form from the value it gets."""
        field = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        html = field.widget.render("point", {"a": 4, "label": "direct"})

        self.assertInHTML(
            '<input type="number" name="point-a" value="4" required id="id_point-a">',
            html,
        )


class DictFieldErrorDisplayTestCase(CompositeErrorDisplayAssertions, SimpleTestCase):
    """Make sure ``DictField`` shows each error at the correct location.

    Each test examines the outer field errors, the child errors, or the rendered
    error markup."""

    def test_outer_validator_error_stays_visible(self):
        """A mapping validator error remains visible at the outer field."""

        def reject(value):
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            point = nestingdolls.DictField(MappingPointForm, validators=[reject])

        self.assertOuterValidatorErrorStaysVisible(
            Form, "point", "point=forged&point-a=1&point-label=kept"
        )

    def test_bound_field_hides_child_item_errors(self):
        """A mapping bound field hides an error that the child renders."""
        self.assertBoundFieldHidesChildErrors(
            OptionalMappingValueForm,
            "point",
            {"point-a": "bad"},
            "Enter a whole number.",
        )

    def test_manual_field_rendering_keeps_child_errors_inline(self):
        """A manual mapping field render includes its child error once."""
        self.assertManualFieldRenderingIncludesChildErrors(
            OptionalMappingValueForm,
            {"point-a": "bad"},
            "Enter a whole number.",
        )

    def test_multiple_outer_validator_messages_stay_visible(self):
        """A mapping validator keeps both outer messages."""

        def reject_with_two_messages(value):
            raise ValidationError(["First outer.", "Second outer."])

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm,
                required=False,
                validators=[reject_with_two_messages],
            )

        self.assertMultipleOuterMessagesStayVisible(
            Form,
            "point",
            "point=forged&point-a=1&point-label=kept",
        )

    def test_custom_bound_field_renders_the_field_error(self):
        """A custom mapping bound field renders its child error."""

        class CustomBoundField(nestingdolls.MappingBoundField):
            pass

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm, bound_field_class=CustomBoundField
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


class DictFieldRenderingTestCase(CompositeRenderingAssertions, SimpleTestCase):
    """Make sure ``DictField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection."""

    def test_render_state_is_isolated(self):
        """An invalid mapping form does not change a fresh form."""
        self.assertRenderStateIsIsolated(
            OptionalMappingValueForm, "point", {"point-a": "bad"}
        )

    def test_change_detection_uses_child_semantics(self):
        """A mapping child converts one before change detection."""
        self.assertChangeDetectionUsesChildSemantics(
            OptionalMappingValueForm,
            "point",
            {"point-a": "1"},
            {"a": 1},
            {"a": 3, "label": "whole"},
        )

    def test_as_div_uses_the_div_wrapper(self):
        """The mapping div helper uses the div widget wrapper."""
        self.assertWrapperMarkup(
            MappingValueForm,
            "as_div",
            "nestingdolls/mapping/div.html",
            "mapping",
        )

    def test_as_p_uses_the_p_wrapper(self):
        """The mapping paragraph helper uses the paragraph widget wrapper."""
        self.assertWrapperMarkup(
            MappingValueForm,
            "as_p",
            "nestingdolls/mapping/p.html",
            "mapping",
        )

    def test_as_table_uses_the_table_wrapper(self):
        """The mapping table helper uses the table widget wrapper."""
        self.assertWrapperMarkup(
            MappingValueForm,
            "as_table",
            "nestingdolls/mapping/table.html",
            "mapping",
        )

    def test_as_ul_uses_the_ul_wrapper(self):
        """The mapping list helper uses the list widget wrapper."""
        self.assertWrapperMarkup(
            MappingValueForm,
            "as_ul",
            "nestingdolls/mapping/ul.html",
            "mapping",
        )

    def test_consecutive_renders_use_their_own_layout(self):
        """A mapping form keeps each render layout separate."""
        self.assertSequentialRendersUseOwnLayout(MappingValueForm, "mapping")

    def test_default_render_uses_the_div_layout(self):
        """A mapping default render uses the Django div layout."""
        self.assertDefaultRenderUsesDivLayout(MappingValueForm, "mapping")

    def test_custom_template_name_stays_literal(self):
        """A mapping widget keeps a literal custom template name."""
        self.assertLiteralTemplateNameSurvives(MappingValueForm, "point")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
