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

    def test_subwidgets_render_the_submitted_state(self):
        """``BoundField.subwidgets`` renders what ``str(field)`` renders.

        Django reaches ``Widget.get_context`` directly there, so the render
        state has to be installed before it looks.
        """

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        form = Form({"point-label": "typed-value"})
        self.assertIs(form.is_valid(), False)

        subwidgets = form["point"].subwidgets
        self.assertEqual(len(subwidgets), 1)
        rendered = str(subwidgets[0])

        self.assertEqual(rendered.count('value="typed-value"'), 1)
        self.assertEqual(rendered.count("This field is required."), 1)
        self.assertEqual(rendered, str(form["point"]))


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


class MappingLayoutContractTestCase(SimpleTestCase):
    """Assert every layout renders the same errors, classes, and wrapper attrs.

    Only ``mapping/p.html`` renders the field loop itself; the other three
    delegate to ``subform.as_div``/``as_ul``/``as_table``. Each assertion below
    runs against all four so no layout drifts."""

    LAYOUTS = ("as_div", "as_p", "as_ul", "as_table")

    class ScalarInitialForm(forms.Form):
        point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

    class TrippableForm(forms.Form):
        class TripForm(forms.Form):
            a = forms.IntegerField(required=False)

            def clean(self):
                if self.cleaned_data.get("a") == 9:
                    raise ValidationError("Whole child is wrong.")
                return super().clean()

        point = nestingdolls.MappingField(TripForm)

    def test_initial_that_is_not_a_mapping_reports_once_in_every_layout(self):
        """A scalar initial reports its error exactly once per layout."""
        form = self.ScalarInitialForm(initial={"point": "not-a-mapping"})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self.assertEqual(
                    getattr(form, layout)().count("Enter a mapping of values."), 1
                )

    def test_valid_initial_reports_nothing_in_every_layout(self):
        """A mapping initial reports no shape error in any layout."""
        form = self.ScalarInitialForm(initial={"point": {"a": 1, "label": "ok"}})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self.assertEqual(
                    getattr(form, layout)().count("Enter a mapping of values."), 0
                )

    def test_child_non_field_error_and_initial_error_each_render_once(self):
        """Neither list is rendered twice when both errors exist at once."""
        form = self.TrippableForm({"point-a": "9"}, initial={"point": "not-a-mapping"})
        self.assertIs(form.is_valid(), False)

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertEqual(html.count("Whole child is wrong."), 1)
                self.assertEqual(html.count("Enter a mapping of values."), 1)

    def test_non_field_errors_use_djangos_nonfield_class(self):
        """A subform non-field error carries Django's own error classes."""
        form = self.TrippableForm({"point-a": "9"})
        self.assertIs(form.is_valid(), False)

        self.assertIn('class="errorlist nonfield"', form.as_p())

    def test_child_field_errors_use_the_plain_error_class(self):
        """A child field error carries the plain error class."""
        form = self.ScalarInitialForm({"point-label": "missing a"})
        self.assertIs(form.is_valid(), False)

        self.assertIn('class="errorlist"', form.as_p())

    def test_wrapper_renders_the_widget_attrs_in_every_layout(self):
        """Container attrs reach the wrapper element, and ``id`` stays single."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingProbeFixtures.MappingPointForm,
                widget=nestingdolls.MappingWidget(
                    attrs={
                        "class": "cls-marker",
                        "data-z": "zz",
                        "hidden": True,
                        "draggable": False,
                    }
                ),
            )

        form = Form()
        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertEqual(html.count('class="cls-marker"'), 1)
                self.assertEqual(html.count('data-z="zz"'), 1)
                self.assertEqual(html.count(" hidden"), 1)
                self.assertEqual(html.count("draggable"), 0)
                self.assertEqual(html.count('id="id_point_widget"'), 1)
                self.assertEqual(html.count('id="id_point"'), 0)

    def test_wrapper_never_carries_aria_invalid(self):
        """A wrapper element is not a form control, so it stays unmarked."""
        form = self.ScalarInitialForm({"point-label": "missing a"})
        self.assertIs(form.is_valid(), False)

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                wrapper = html[: html.index("data-mapping-field") + 40]
                self.assertNotIn("aria-invalid", wrapper)
                self.assertIn('aria-invalid="true"', html)

    def test_sequence_rows_forward_container_attrs_to_each_mapping_wrapper(self):
        """A sequence forwards its attrs to each row, wrapper element included.

        The row-derived ``id`` still appears once, because the wrapper attrs
        drop ``id``.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm),
                widget=nestingdolls.SequenceWidget(attrs={"class": "outer"}),
            )

        html = Form(initial={"values": [{"a": 1, "label": "row"}]}).as_div()

        # One rendered row plus the empty-row template.
        self.assertEqual(html.count('class="outer"'), 2)
        self.assertEqual(html.count('id="id_values_0_widget"'), 1)
        self.assertEqual(html.count('id="id_values_0"'), 0)


class DictFieldRenderingTestCase(CompositeRenderingAssertions, SimpleTestCase):
    """Make sure ``DictField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection."""

    def test_render_state_is_isolated(self):
        """An invalid mapping form does not change a fresh form."""
        self.assertRenderStateIsIsolated(
            OptionalMappingValueForm, "point", {"point-a": "bad"}
        )

    def test_form_error_class_reaches_the_subform(self):
        """The outer form's error class renders the child's error list."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        self.assertFormErrorClassReachesChildren(
            Form, "point", {"point-label": "missing a"}
        )

    def test_form_renderer_reaches_the_subform(self):
        """The outer form's renderer is the subform's renderer."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)

        self.assertFormRendererReachesChildren(
            Form,
            "point",
            {"point-label": "missing a"},
            lambda bound_field: [bound_field.subform],
        )

    def test_child_only_failure_marks_the_field(self):
        """A mapping that failed only in a child carries the error class."""

        class Form(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)
            plain = forms.CharField()

        self.assertChildOnlyFailureMarksTheField(
            Form, "point", {"point-label": "missing a"}
        )

    def test_late_add_error_marks_the_field(self):
        """An error recorded after a first read still marks a mapping."""

        class Form(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            point = nestingdolls.MappingField(MappingProbeFixtures.MappingPointForm)
            plain = forms.CharField()

        self.assertLateAddErrorMarksTheField(
            Form, "point", {"point-a": "1", "point-label": "ok"}
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
