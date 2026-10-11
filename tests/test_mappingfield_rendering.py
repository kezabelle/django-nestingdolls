"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

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
    ValidatedMappingPointForm,
)
from .support.testcases import (
    CompositeFieldTestCase,
    MarkedErrorList,
    MarkedRenderer,
    rendered_controls,
    rendered_elements,
    rendered_wrapper,
)

LAYOUTS = ("as_div", "as_p", "as_ul", "as_table")


def child_error_form() -> forms.Form:
    """Return a bound form whose mapping and sequence children both fail."""

    class Form(forms.Form):
        point = nestingdolls.MappingField(MappingPointForm)
        values = nestingdolls.SequenceField(forms.IntegerField())

    return Form(
        {
            "point-label": "missing a",
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
            "values-0-value": "bad",
        }
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

    def test_child_error_renders_inline_and_is_referenced_by_its_input(self) -> None:
        """A child error renders once inside the mapping, not on the outer field."""
        form = RequiredMappingPointForm({"point-label": "missing a"})
        self.assertFormInvalid(form)

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

    def test_every_layout_resolves_child_error_references(self) -> None:
        """Every layout renders unique ids and resolves every described-by id."""
        form = child_error_form()
        self.assertFormInvalid(form)

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                elements = [parse_html(getattr(form, layout)())]
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

    def test_every_layout_renders_the_mapping_child_form_and_wrapper(self) -> None:
        """Every layout renders the wrapper, both child inputs, and one hidden initial."""
        form = HiddenInitialMappingPointForm(
            initial={"point": {"a": 9, "label": "layout"}}
        )

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
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

    def test_late_outer_error_renders_beside_the_child_error(self) -> None:
        """An outer error added after a first read still renders once."""
        form = OptionalMappingPointForm({"point-a": "bad"})
        self.assertLateOuterErrorRendersOnce(form, "point", "Enter a whole number.")

    def test_hidden_mapping_promotes_child_errors(self) -> None:
        """A mapping with only hidden children shows its child error at the top."""

        class HiddenChildForm(forms.Form):
            number = forms.IntegerField(widget=forms.HiddenInput)

        class Form(forms.Form):
            value = nestingdolls.MappingField(HiddenChildForm)

        form = Form({"value-number": "bad"})
        self.assertHiddenCompositeErrorRendersOnce(
            form, "value", "Enter a whole number."
        )

    def test_manual_field_rendering_keeps_child_errors_inline(self) -> None:
        """A manual mapping field render includes its child error once."""
        form = OptionalMappingPointForm({"point-a": "bad"})
        self.assertManualVisibleFieldsRenderMessageOnce(form, "Enter a whole number.")

    def test_child_errors_precede_inputs_in_every_layout(self) -> None:
        """A child error precedes its input in every Django layout."""
        form = RequiredMappingPointForm({"point-a": "bad"})
        self.assertFormInvalid(form)

        for layout in ("as_p", "as_table", "as_div", "as_ul"):
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertLess(
                    html.index("Enter a whole number."),
                    html.index('name="point-a"'),
                )

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

    def test_initial_that_is_not_a_mapping_reports_once_in_every_layout(self) -> None:
        """A scalar initial reports its error exactly once per layout."""
        form = RequiredMappingPointForm(initial={"point": "not-a-mapping"})

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                self.assertRenderedMessageCount(
                    getattr(form, layout)(), "Enter a mapping of values."
                )

    def test_valid_initial_reports_nothing_in_every_layout(self) -> None:
        """A mapping initial reports no shape error in any layout."""
        form = RequiredMappingPointForm(initial={"point": {"a": 1, "label": "ok"}})

        for layout in LAYOUTS:
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

        for layout in LAYOUTS:
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
            point = nestingdolls.DictField(
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
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertEqual(html.count('class="cls-marker"'), 1)
                self.assertEqual(html.count('data-z="zz"'), 1)
                self.assertEqual(html.count(" hidden"), 1)
                self.assertEqual(html.count("draggable"), 0)
                self.assertEqual(html.count('id="id_point_widget"'), 1)
                self.assertEqual(html.count('id="id_point"'), 0)

    def test_child_error_leaves_the_wrapper_unmarked(self) -> None:
        """A child error marks the child control, not the wrapper."""
        form = RequiredMappingPointForm({"point-label": "missing a"})
        self.assertFormInvalid(form)

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                wrapper = html[: html.index("data-mapping-field") + 40]
                self.assertNotIn("aria-invalid", wrapper)
                self.assertIn('aria-invalid="true"', html)

    def test_non_div_layouts_name_the_group_from_its_label(self) -> None:
        """The paragraph, list, and table groups take their name from the field label."""
        form = RequiredMappingPointForm()

        for layout in ("as_p", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                self.assertGroupIsNamedByLabel(
                    getattr(form, layout)(), "mapping", "Point"
                )

    def test_div_layout_keeps_its_fieldset_name(self) -> None:
        """The div layout names the field with its fieldset and adds no group name."""
        self.assertDivGroupKeepsItsFieldsetName(
            RequiredMappingPointForm().as_div(), "mapping", "Point"
        )

    def test_div_layout_legend_has_no_id(self) -> None:
        """The div layout leaves Django's ``legend`` without an ``id``.

        The legend names the field, so no ``aria-labelledby`` refers to it.
        """
        html = RequiredMappingPointForm().as_div()

        legends = [
            dict(element.attributes)
            for element in rendered_elements(html)
            if element.name == "legend"
        ]

        self.assertEqual(len(legends), 1)
        self.assertNotIn("id", legends[0])

    def test_caller_aria_label_is_not_overridden(self) -> None:
        """A caller-supplied ``aria-label`` stays the only accessible name."""

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm,
                widget=nestingdolls.MappingWidget(attrs={"aria-label": "Caller name"}),
            )

        form = Form()
        for layout in ("as_p", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                wrapper = rendered_wrapper(getattr(form, layout)(), "mapping")
                self.assertEqual(wrapper.get("aria-label"), "Caller name")
                self.assertIsNone(wrapper.get("aria-labelledby"))

    def test_caller_aria_labelledby_is_not_overridden(self) -> None:
        """A caller-supplied ``aria-labelledby`` is kept as given."""

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm,
                widget=nestingdolls.MappingWidget(
                    attrs={"aria-labelledby": "caller-heading"}
                ),
            )

        form = Form()
        for layout in ("as_p", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                wrapper = rendered_wrapper(getattr(form, layout)(), "mapping")
                self.assertEqual(wrapper.get("aria-labelledby"), "caller-heading")
                self.assertIsNone(wrapper.get("aria-label"))

    def test_outer_description_is_on_one_group_without_a_fieldset(self) -> None:
        """``as_div`` keeps Django's fieldset. The other layouts use one group.

        The child controls get no outer reference or mark.
        """

        class Form(forms.Form):
            point = nestingdolls.DictField(
                MappingPointForm,
                help_text="Outer help.",
                validators=[ValidatedMappingPointForm.reject_two],
            )

        form = Form({"point-a": "2", "point-label": "ok"})
        self.assertFormInvalid(form)
        outer = "id_point_helptext id_point_error"

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                wrapper = rendered_wrapper(html, "mapping")
                group = {
                    name: wrapper.get(name)
                    for name in ("role", "aria-describedby", "aria-invalid")
                }
                if layout == "as_div":
                    self.assertIn(f'<fieldset aria-describedby="{outer}">', html)
                    self.assertEqual(set(group.values()), {None})
                else:
                    self.assertNotIn("<fieldset", html)
                    self.assertEqual(
                        group,
                        {
                            "role": "group",
                            "aria-describedby": outer,
                            "aria-invalid": "true",
                        },
                    )
                controls = rendered_controls(html, "point-")
                self.assertEqual(set(controls), {"point-a", "point-label"})
                for control in controls.values():
                    self.assertIsNone(control.get("aria-describedby"))
                    self.assertIsNone(control.get("aria-invalid"))

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

    def test_hidden_child_error_renders_once_in_every_layout(self) -> None:
        """A hidden child's error shows once, with Django's hidden-field marker."""

        class ChildForm(forms.Form):
            visible = forms.CharField(required=False)
            secret = forms.IntegerField(widget=forms.HiddenInput)

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm)

        form = Form({"value-visible": "ok", "value-secret": "bad"})
        self.assertFormInvalid(form)

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertRenderedMessageCount(
                    html, "(Hidden field secret) Enter a whole number."
                )
                self.assertRenderedMessageCount(html, "Enter a whole number.")

    def child_css_class_counts(self, css_class: str) -> dict[str, int]:
        """Return the occurrences of a child-form CSS class in each layout."""

        class ChildForm(forms.Form):
            error_css_class = "child-error"
            required_css_class = "child-required"
            number = forms.IntegerField()

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm, required=False)

        form = Form({"value-number": "bad"})
        self.assertFormInvalid(form)
        return {layout: getattr(form, layout)().count(css_class) for layout in LAYOUTS}

    def test_child_error_class_renders_once_in_every_layout(self) -> None:
        """Each layout marks the failing child with the child form's error class."""
        self.assertEqual(
            self.child_css_class_counts("child-error"), dict.fromkeys(LAYOUTS, 1)
        )

    def test_child_required_class_renders_in_every_layout(self) -> None:
        """Each layout carries the child form's required class as the div layout does."""
        counts = self.child_css_class_counts("child-required")

        self.assertGreater(counts["as_div"], 0)
        self.assertEqual(counts, dict.fromkeys(LAYOUTS, counts["as_div"]))

    def test_paragraph_child_wrapper_does_not_nest_paragraphs(self) -> None:
        """The paragraph layout wraps each child in phrasing content only."""

        class ChildForm(forms.Form):
            error_css_class = "child-error"
            number = forms.IntegerField()

        class Form(forms.Form):
            value = nestingdolls.MappingField(ChildForm, required=False)

        form = Form({"value-number": "bad"})
        self.assertFormInvalid(form)

        html = form.as_p()
        # The outer form's own paragraph is the only one.
        self.assertEqual(html.count("<p"), 1)
        self.assertIn('<span class="child-error">', html)


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

    def test_each_layout_uses_its_widget_template(self) -> None:
        """Every form render method selects its own mapping wrapper template."""
        form = RequiredMappingPointForm()

        for layout, template in (
            ("as_div", "nestingdolls/mapping/div.html"),
            ("as_p", "nestingdolls/mapping/p.html"),
            ("as_table", "nestingdolls/mapping/table.html"),
            ("as_ul", "nestingdolls/mapping/ul.html"),
        ):
            with self.subTest(layout=layout):
                self.assertRenderMethodUsesWidgetTemplate(
                    getattr(form, layout), template, "mapping"
                )

    def test_consecutive_renders_use_their_own_layout(self) -> None:
        """A mapping form keeps each render layout separate."""
        self.assertSequentialRendersForForm(RequiredMappingPointForm(), "mapping")

    def test_default_render_uses_the_div_layout(self) -> None:
        """A mapping default render uses the Django div layout."""
        self.assertIn('<div\n  data-widget="mapping"', str(RequiredMappingPointForm()))


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
            point = nestingdolls.DictField(
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
            point = nestingdolls.DictField(
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
