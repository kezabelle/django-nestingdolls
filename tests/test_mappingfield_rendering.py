"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import copy
import unittest

from django import forms
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test.html import Element, parse_html
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.mapping import (
    HiddenInitialMappingPointForm,
    MappingPointForm,
    OptionalMappingPointForm,
    RequiredMappingPointForm,
    TrippableMappingPointForm,
)
from .support.testcases import (
    CompositeFieldTestCase,
    MarkedErrorList,
    MarkedRenderer,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class MappingFieldRenderingTestCase(CompositeFieldTestCase):
    """Test mapping field rendering.

    Check wrappers and resolvable error references in every layout.
    """

    def assertChildErrorReferencesResolve(self, renderer: object) -> None:  # noqa: D102

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingPointForm)
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                "point-label": "missing a",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
                "values-0": "bad",
            }
        )
        self.assertFormInvalid(form)

        # The outer field owns no error; the subform renders it exactly once.
        self.assertBoundFieldErrors(form, "point", [])
        rendered = str(form["point"])
        self.assertRenderedMessageCount(rendered, "This field is required.")
        self.assertIn('aria-invalid="true"', rendered)

        paragraphs = form.as_p()
        self.assertErrorReferenceResolves(paragraphs, "id_point-a_error")
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

    def test_div_layout_resolves_child_error_references(self) -> None:
        """The div layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_div")

    def test_p_layout_resolves_child_error_references(self) -> None:
        """The paragraph layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_p")

    def test_ul_layout_resolves_child_error_references(self) -> None:
        """The list layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_ul")

    def test_table_layout_resolves_child_error_references(self) -> None:
        """The table layout resolves every child error reference."""
        self.assertChildErrorReferencesResolve("as_table")

    def assertMappingChildFormAndWrapperRender(self, renderer: object) -> None:  # noqa: D102

        form = HiddenInitialMappingPointForm(
            initial={"point": {"a": 9, "label": "layout"}}
        )
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

    def test_div_layout_renders_mapping_child_form_and_wrapper(self) -> None:
        """The div layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_div")

    def test_p_layout_renders_mapping_child_form_and_wrapper(self) -> None:
        """The paragraph layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_p")

    def test_ul_layout_renders_mapping_child_form_and_wrapper(self) -> None:
        """The list layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_ul")

    def test_table_layout_renders_mapping_child_form_and_wrapper(self) -> None:
        """The table layout renders the mapping child form and wrapper."""
        self.assertMappingChildFormAndWrapperRender("as_table")

    def test_widget_exposes_child_media_and_multipart_requirement(self) -> None:
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

    def test_a_direct_widget_render_builds_the_child_form_from_the_value(
        self,
    ) -> None:
        """A direct widget render builds the child form from the value it gets."""
        field = nestingdolls.MappingField(MappingPointForm)

        html = field.widget.render("point", {"a": 4, "label": "direct"})

        self.assertInHTML(
            '<input type="number" name="point-a" value="4" required id="id_point-a">',
            html,
        )

    def test_subwidgets_render_the_submitted_state(self) -> None:
        """``BoundField.subwidgets`` renders what ``str(field)`` renders.

        Django reaches ``Widget.get_context`` directly there, so the render
        state has to be installed before it looks.
        """
        form = RequiredMappingPointForm({"point-label": "typed-value"})
        self.assertFormInvalid(form)

        self.assertSingleSubwidgetMatchesBoundField(
            form,
            "point",
            'value="typed-value"',
            "This field is required.",
        )


class MappingFieldErrorRenderingTestCase(CompositeFieldTestCase):
    """Make sure ``DictField`` shows each error at the correct location.

    Each test examines the outer field errors, the child errors, or the rendered
    error markup.
    """

    def test_outer_validator_error_stays_visible(self) -> None:
        """A mapping validator error remains visible at the outer field."""

        def reject(value: object) -> object:
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            point = nestingdolls.DictField(MappingPointForm, validators=[reject])

        form = Form(QueryDict("point=forged&point-a=1&point-label=kept"))
        self.assertOuterValidatorErrorForForm(form, "point")

    def test_bound_field_hides_child_item_errors(self) -> None:
        """A mapping bound field hides an error that the child renders."""
        form = OptionalMappingPointForm({"point-a": "bad"})
        self.assertChildErrorsHiddenForForm(form, "point", "Enter a whole number.")

    def test_manual_field_rendering_keeps_child_errors_inline(self) -> None:
        """A manual mapping field render includes its child error once."""
        form = OptionalMappingPointForm({"point-a": "bad"})
        self.assertManualVisibleFieldsRenderMessageOnce(form, "Enter a whole number.")

    def test_multiple_outer_validator_messages_stay_visible(self) -> None:
        """A mapping validator keeps both outer messages."""

        def reject_with_two_messages(value: object) -> object:
            raise ValidationError(["First outer.", "Second outer."])

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm,
                required=False,
                validators=[reject_with_two_messages],
            )

        form = Form(QueryDict("point=forged&point-a=1&point-label=kept"))
        self.assertMultipleOuterMessagesStayVisible(form, "point")

    def test_custom_bound_field_renders_the_field_error(self) -> None:
        """A custom mapping bound field renders its child error."""

        class CustomBoundField(nestingdolls.MappingBoundField):
            pass

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm, bound_field_class=CustomBoundField
            )

        form = Form({"point-a": "bad"})
        self.assertCustomBoundFieldErrorForForm(
            form, "point", CustomBoundField, "Enter a whole number."
        )

    def test_bound_field_rejects_a_foreign_field(self) -> None:
        """A mapping bound field rejects a foreign field."""
        with self.assertRaisesRegex(TypeError, "field must be a"):
            nestingdolls.MappingBoundField(forms.Form(), forms.CharField(), "value")


class MappingFieldLayoutContractTestCase(CompositeFieldTestCase):
    """Assert every layout renders the same errors, classes, and wrapper attrs.

    Only ``mapping/p.html`` renders the field loop itself; the other three
    delegate to ``subform.as_div``/``as_ul``/``as_table``. Each assertion below
    runs against all four so no layout drifts.
    """

    LAYOUTS = ("as_div", "as_p", "as_ul", "as_table")

    def test_initial_that_is_not_a_mapping_reports_once_in_every_layout(self) -> None:
        """A scalar initial reports its error exactly once per layout."""
        form = RequiredMappingPointForm(initial={"point": "not-a-mapping"})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self.assertRenderedMessageCount(
                    getattr(form, layout)(), "Enter a mapping of values."
                )

    def test_valid_initial_reports_nothing_in_every_layout(self) -> None:
        """A mapping initial reports no shape error in any layout."""
        form = RequiredMappingPointForm(initial={"point": {"a": 1, "label": "ok"}})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self.assertRenderedMessageCount(
                    getattr(form, layout)(), "Enter a mapping of values.", 0
                )

    def test_child_non_field_error_and_initial_error_each_render_once(self) -> None:
        """Neither list is rendered twice when both errors exist at once."""
        form = TrippableMappingPointForm(
            {"point-a": "9"}, initial={"point": "not-a-mapping"}
        )
        self.assertFormInvalid(form)

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertRenderedMessageCount(html, "Whole child is wrong.")
                self.assertRenderedMessageCount(html, "Enter a mapping of values.")

    def test_non_field_errors_use_djangos_nonfield_class(self) -> None:
        """A subform non-field error carries Django's own error classes."""
        form = TrippableMappingPointForm({"point-a": "9"})
        self.assertFormInvalid(form)

        self.assertIn('class="errorlist nonfield"', form.as_p())

    def test_child_field_errors_use_the_plain_error_class(self) -> None:
        """A child field error carries the plain error class."""
        form = RequiredMappingPointForm({"point-label": "missing a"})
        self.assertFormInvalid(form)

        self.assertIn('class="errorlist"', form.as_p())

    def test_wrapper_renders_the_widget_attrs_in_every_layout(self) -> None:
        """Container attrs reach the wrapper element, and ``id`` stays single."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(
                MappingPointForm,
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

    def test_wrapper_never_carries_aria_invalid(self) -> None:
        """A wrapper element is not a form control, so it stays unmarked."""
        form = RequiredMappingPointForm({"point-label": "missing a"})
        self.assertFormInvalid(form)

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                wrapper = html[: html.index("data-mapping-field") + 40]
                self.assertNotIn("aria-invalid", wrapper)
                self.assertIn('aria-invalid="true"', html)

    def test_sequence_rows_forward_container_attrs_to_each_mapping_wrapper(
        self,
    ) -> None:
        """A sequence forwards its attrs to each row, wrapper element included.

        The row-derived ``id`` still appears once, because the wrapper attrs
        drop ``id``.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(MappingPointForm),
                widget=nestingdolls.SequenceWidget(attrs={"class": "outer"}),
            )

        html = Form(initial={"values": [{"a": 1, "label": "row"}]}).as_div()

        # One rendered row plus the empty-row template.
        self.assertEqual(html.count('class="outer"'), 2)
        self.assertEqual(html.count('id="id_values_0_widget"'), 1)
        self.assertEqual(html.count('id="id_values_0"'), 0)


class MappingFieldStateRenderingTestCase(CompositeFieldTestCase):
    """Make sure ``DictField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection.
    """

    def test_render_state_is_isolated(self) -> None:
        """An invalid mapping form does not change a fresh form."""
        self.assertRenderStateIsolatedForForms(
            OptionalMappingPointForm({"point-a": "bad"}),
            OptionalMappingPointForm(),
            "point",
        )

    def test_form_error_class_reaches_the_subform(self) -> None:
        """The outer form's error class renders the child's error list."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingPointForm)

        form = Form({"point-label": "missing a"}, error_class=MarkedErrorList)
        self.assertChildErrorMarkupUsesErrorClass(form, "point")

    def test_form_renderer_reaches_the_subform(self) -> None:
        """The outer form's renderer is the subform's renderer."""

        class Form(forms.Form):
            point = nestingdolls.MappingField(MappingPointForm)

        form = Form({"point-label": "missing a"}, renderer=MarkedRenderer())
        self.assertFormRendererReachesChildren(
            form, "point", lambda bound_field: [bound_field.subform]
        )

    def test_child_only_failure_marks_the_field(self) -> None:
        """A mapping that failed only in a child carries the error class."""

        class Form(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            point = nestingdolls.MappingField(MappingPointForm)
            plain = forms.CharField()

        form = Form({"point-label": "missing a", "plain": ""})
        self.assertChildOnlyFailureMarksField(form, form["point"], form["plain"])

    def test_late_add_error_marks_the_field(self) -> None:
        """An error recorded after a first read still marks a mapping."""

        class Form(forms.Form):
            error_css_class = "has-error"
            required_css_class = "is-required"
            point = nestingdolls.MappingField(MappingPointForm)
            plain = forms.CharField()

        form = Form({"point-a": "1", "point-label": "ok", "plain": "ok"})
        self.assertFormValid(form)
        composite, plain = form["point"], form["plain"]
        self.assertCssClassesMatchBaseline(composite, plain)
        form.add_error("point", "Late outer error.")
        form.add_error("plain", "Late outer error.")
        self.assertIn("has-error", plain.css_classes())
        self.assertCssClassesMatchBaseline(composite, plain)

    def test_change_detection_uses_child_semantics(self) -> None:
        """A mapping child converts one before change detection."""
        self.assertChildChangeDetection(
            OptionalMappingPointForm({"point-a": "1"}, initial={"point": {"a": 1}}),
            OptionalMappingPointForm(
                {"point-a": "1"}, initial={"point": {"a": 3, "label": "whole"}}
            ),
        )

    def test_as_div_uses_the_div_wrapper(self) -> None:
        """The mapping div helper uses the div widget wrapper."""
        form = RequiredMappingPointForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_div, "nestingdolls/mapping/div.html", "mapping"
        )

    def test_as_p_uses_the_p_wrapper(self) -> None:
        """The mapping paragraph helper uses the paragraph widget wrapper."""
        form = RequiredMappingPointForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_p, "nestingdolls/mapping/p.html", "mapping"
        )

    def test_as_table_uses_the_table_wrapper(self) -> None:
        """The mapping table helper uses the table widget wrapper."""
        form = RequiredMappingPointForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_table, "nestingdolls/mapping/table.html", "mapping"
        )

    def test_as_ul_uses_the_ul_wrapper(self) -> None:
        """The mapping list helper uses the list widget wrapper."""
        form = RequiredMappingPointForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_ul, "nestingdolls/mapping/ul.html", "mapping"
        )

    def test_consecutive_renders_use_their_own_layout(self) -> None:
        """A mapping form keeps each render layout separate."""
        self.assertSequentialRendersForForm(RequiredMappingPointForm(), "mapping")

    def test_default_render_uses_the_div_layout(self) -> None:
        """A mapping default render uses the Django div layout."""
        self.assertIn('<div\n  data-widget="mapping"', str(RequiredMappingPointForm()))

    def test_custom_template_name_stays_literal(self) -> None:
        """A mapping widget keeps a literal custom template name."""
        widget = copy.deepcopy(RequiredMappingPointForm().fields["point"].widget)
        widget.template_name = "app/{custom}.html"
        self.assertEqual(widget.template_name, "app/{custom}.html")


class MappingFieldInvalidInitialRenderingTestCase(CompositeFieldTestCase):
    """These tests check MappingField rendering for hostile values."""

    def assertPointValueRenders(self, form: object) -> None:  # noqa: D102
        self.assertEqual(form["point"].value(), ["bad"])
        str(form["point"])

    def test_list_initial_stays_renderable(self) -> None:
        """A list initial for a mapping field stays renderable."""
        self.assertPointValueRenders(
            OptionalMappingPointForm(initial={"point": ["bad"]})
        )

    def test_callable_list_initial_stays_renderable(self) -> None:
        """A callable list initial for a mapping field stays renderable."""

        class CallableInitialForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingPointForm,
                required=False,
                initial=lambda: ["bad"],
            )

        self.assertPointValueRenders(CallableInitialForm())

    def test_disabled_and_scalar_file_hostile_values_stay_renderable_errors(
        self,
    ) -> None:
        """Disabled and scalar file hostile values stay Django form errors."""

        class DisabledForm(forms.Form):
            point = nestingdolls.MappingField(
                MappingPointForm, required=False, disabled=True
            )

        disabled = DisabledForm({}, initial={"point": ["bad"]})
        self.assertFormInvalid(disabled)
        self.assertFormErrorCode(disabled, "point", "invalid")
        str(disabled["point"])

        # A hostile scalar in `files` is a form error, never a render crash.
        scalar_file = OptionalMappingPointForm(data={}, files={"point": False})
        self.assertFormInvalid(scalar_file)
        self.assertFormErrorCode(scalar_file, "point", "invalid")
        self.assertIs(scalar_file["point"].value(), False)
        str(scalar_file["point"])

    def assertHostileHiddenInitialPayloadRendersError(self, data: object) -> None:  # noqa: D102

        class NestedForm(forms.Form):
            rows = nestingdolls.ListField(
                nestingdolls.MappingField(MappingPointForm),
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
        self.assertFormInvalid(hidden)
        self.assertIn("Enter a mapping of values.", hidden.as_p())

    def test_scalar_hidden_initial_payload_stays_a_renderable_error(self) -> None:
        """A scalar hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError({"payload": "hostile"})

    def test_nested_list_hidden_initial_payload_stays_a_renderable_error(
        self,
    ) -> None:
        """A nested list hidden initial payload stays a renderable form error."""
        self.assertHostileHiddenInitialPayloadRendersError(
            {"payload": {"rows": ["hostile"]}}
        )

    def test_prepare_value_rejection_returns_the_mapping_initial_value(self) -> None:
        """A child prepare value rejection returns the mapping initial value."""

        class RejectingField(forms.CharField):
            def prepare_value(self, value: object) -> object:
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
