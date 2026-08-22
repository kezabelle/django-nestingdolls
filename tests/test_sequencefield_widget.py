"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import copy
import unittest

from django import forms
from django.core.exceptions import ValidationError
from django.forms.formsets import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import QueryDict
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.forms.mapping import (
    MappingPointForm,
)
from .support.forms.sequence import (
    JSONSequenceSubmissionForm,
    MinimumTwoIntegerSequenceForm,
    OptionalSplitDateTimeSequenceForm,
    SequenceForm,
    SequenceHelpTextForm,
    SequenceSubmissionForm,
    StyledSequenceAndPlainTextForm,
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


class SequenceWidgetIntegrationTestCase(CompositeFieldTestCase):
    """These tests check ListField widget integration."""

    def test_custom_child_choices_are_rendered(self) -> None:
        """It renders child choice widgets normally."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.ChoiceField(choices=(("a", "A"),)))

        html = Form(initial={"values": ["a"]}).as_p()

        self.assertInHTML('<option value="a" selected>A</option>', html)

    def test_child_prepare_value_is_used(self) -> None:
        """It uses the child field's prepared value when rendering."""
        html = JSONSequenceSubmissionForm(initial={"values": [{"answer": 42}]}).as_p()

        self.assertInHTML(
            '<textarea name="values-0" cols="40" rows="10" id="id_values_0">{&quot;answer&quot;: 42}</textarea>',
            html,
        )

    def test_subwidgets_render_the_submitted_state(self) -> None:
        """``BoundField.subwidgets`` renders what ``str(field)`` renders.

        Django reaches ``Widget.get_context`` directly there, so the render
        state has to be installed before it looks.
        """
        form = SequenceForm(
            {
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "1",
                "values-0": "not-a-number",
            }
        )
        self.assertFormInvalid(form)

        self.assertSingleSubwidgetMatchesBoundField(
            form,
            "values",
            'value="not-a-number"',
            "Enter a whole number.",
        )

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(
        self,
    ) -> None:
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget()
        file_widget = nestingdolls.SequenceWidget()

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), widget=text_widget)

        class TextForm(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), widget=file_widget)

        self.assertIs(UploadForm().is_multipart(), True)
        self.assertIs(TextForm().is_multipart(), False)

    def test_exact_name_and_row_keys_count_as_input(self) -> None:
        """An exact or row key counts as input. A non-string key does not."""
        widget = nestingdolls.ListField(forms.IntegerField()).widget

        self.assertIs(
            widget.value_omitted_from_data({"values": "x"}, {}, "values"), False
        )
        self.assertIs(
            widget.value_omitted_from_data({"values-0": "1"}, {}, "values"), False
        )
        self.assertIs(widget.value_omitted_from_data({0: "1"}, {}, "values"), True)

    def test_extraction_without_input_returns_an_empty_list(self) -> None:
        """Extraction returns an empty list when a submission has no input."""
        widget = nestingdolls.ListField(forms.IntegerField()).widget

        self.assertEqual(widget.value_from_datadict({}, {}, "values"), [])

    def test_form_required_attribute_opt_out_is_preserved(self) -> None:
        """It respects the form-level required-attribute opt-out."""
        self.assertNotIn(" required", SequenceForm(use_required_attribute=False).as_p())

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_widget_renders_management_inputs_controls_and_media(self) -> None:
        """It renders management inputs, row controls, and the enhancement media."""
        form = MinimumTwoIntegerSequenceForm()
        html = form.as_p()

        self.assertInHTML(
            f'<input type="hidden" name="values-{TOTAL_FORM_COUNT}" value="2" data-sequence-total id="id_values-{TOTAL_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{INITIAL_FORM_COUNT}" value="0" id="id_values-{INITIAL_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{MIN_NUM_FORM_COUNT}" value="2" id="id_values-{MIN_NUM_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            f'<input type="hidden" name="values-{MAX_NUM_FORM_COUNT}" value="1000" id="id_values-{MAX_NUM_FORM_COUNT}">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-0" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-1" id="id_values_1">',
            html,
        )
        self.assertIn('id="id_values_widget"', html)
        self.assertIn('id="id_values_rows"', html)
        self.assertIn('data-widget="sequence"', html)
        self.assertIn('data-sequence-field="values"', html)
        self.assertIn('data-sequence-minimum="2"', html)
        self.assertIn('id="id_values_row_0"', html)
        self.assertIn('id="id_values_0_DELETE"', html)
        self.assertIn('id="id_values_row_1"', html)
        self.assertIn('id="id_values_1_DELETE"', html)
        self.assertIn("data-sequence-empty-row", html)
        self.assertIn('id="id_values_row___prefix__"', html)
        self.assertIn('id="id_values___prefix___DELETE"', html)
        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )
        self.assertIn("data-sequence-remove-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-remove data-sequence-field="values"'
            ' id="id_values___prefix___remove"'
            ' aria-label="Remove row __prefix__">Remove</button>',
            html,
        )
        self.assertIn("data-sequence-actions", html)
        media = str(form.media)
        self.assertIn("nestingdolls/sequence.js", media)
        self.assertIn('id="nestingdolls-sequence"', media)
        self.assertIn('hx-preserve="true"', media)
        self.assertIn('up-keep="true"', media)

        # An invalid bound render keeps the sequence markup in the active layout.
        invalid = MinimumTwoIntegerSequenceForm(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"}
        )
        self.assertFormInvalid(invalid)
        with self.assertTemplateUsed("nestingdolls/sequence/p.html"):
            invalid_html = invalid.as_p()

        self.assertIn('data-widget="sequence"', invalid_html)
        self.assertIn("<span", invalid_html)
        self.assertIn("Enter a whole number.", invalid_html)

    def test_disabled_field_renders_the_disabled_widget_marker(self) -> None:
        """A disabled sequence marks its root element. The script does not change it.

        The server disables controls and ignores submitted input.
        Without the marker, the script adds enabled controls and can lose the user's work.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, required=False
            )

        html = Form(initial={"values": [1]}).as_div()
        self.assertIn("data-sequence-disabled", html)

        self.assertNotIn("data-sequence-disabled", SequenceSubmissionForm().as_div())

    def assertRowErrorMarkup(  # noqa: D102
        self,
        form_kwargs: object,
        expected_input: object,
        expected_errors: object,
        render_method: object = "as_div",
        error_id: object = "id_values_0_error",
    ) -> None:

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        form = Form(
            {
                "values-0": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            },
            **form_kwargs,
        )
        self.assertFormInvalid(form)
        html = getattr(form, render_method)()
        self.assertInHTML(expected_input, html)
        self.assertInHTML(expected_errors, html)
        self.assertRenderedMessageCount(html, "Enter a whole number.")
        if error_id is not None:
            self.assertErrorReferenceResolves(html, error_id)

    def test_row_error_markup_with_automatic_ids(self) -> None:
        """A row error describes its child input when Django creates ids."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
        )

    def test_row_error_markup_without_automatic_ids(self) -> None:
        """A row error keeps the existing description when Django omits ids."""
        self.assertRowErrorMarkup(
            {"auto_id": False},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
            '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
            error_id=None,
        )

    def test_table_row_error_markup_uses_djangos_list_template(self) -> None:
        """An ``as_table()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            render_method="as_table",
        )

    def test_ul_row_error_markup_uses_djangos_list_template(self) -> None:
        """An ``as_ul()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            render_method="as_ul",
        )

    def test_p_layout_row_error_markup_stays_phrasing_content(self) -> None:
        """An ``as_p`` row error does not contain ``ul``. The widget stays in its ``p`` element.

        A ``ul`` start tag closes an open ``p`` element during HTML parsing.
        This moves the remaining widget content outside the widget root.
        The moved content includes the empty-row template.
        The script cannot enhance that content.
        """
        form = SequenceForm(
            {
                "values-0": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertFormInvalid(form)
        html = form.as_p()
        self.assertNotIn("<ul", html)
        self.assertIn("data-sequence-empty-row", html)
        self.assertRenderedMessageCount(html, "Enter a whole number.")
        self.assertErrorReferenceResolves(html, "id_values_0_error")

    def test_row_errors_precede_inputs_in_every_layout(self) -> None:
        """A row error precedes its input in every Django layout."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )
        self.assertFormInvalid(form)

        for layout in ("as_p", "as_table", "as_div", "as_ul"):
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertLess(
                    html.index("Enter a whole number."),
                    html.index('name="values-0"'),
                )

    def test_compound_row_error_markup_describes_each_child_widget(self) -> None:
        """A compound row error describes each child input."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        compound = CompoundForm(
            {
                "values-0_0": "2026-08-05",
                "values-0_1": "not-a-time",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertFormInvalid(compound)
        compound_html = compound.as_div()
        self.assertInHTML(
            '<input type="text" name="values-0_0" value="2026-08-05" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_0">',
            compound_html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0_1" value="not-a-time" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_1">',
            compound_html,
        )
        self.assertRenderedMessageCount(compound_html, "Enter a valid time.")
        self.assertErrorReferenceResolves(compound_html, "id_values_0_error")

    def test_a_disabled_child_field_disables_every_row_input(self) -> None:
        """A disabled child field renders each row input as disabled."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(disabled=True), required=False, initial=[7]
            )

        self.assertInHTML(
            '<input type="number" name="values-0" value="7" disabled id="id_values_0">',
            Form().as_p(),
        )

    def test_a_string_initial_row_renders_a_blank_compound_row(self) -> None:
        """A compound row does not decompress a string initial row."""
        html = OptionalSplitDateTimeSequenceForm(
            initial={"values": ["2026-08-05 10:30"]}
        ).as_p()

        self.assertInHTML(
            '<input type="text" name="values-0_0" id="id_values_0_0">', html
        )
        self.assertNotIn("2026-08-05", html)

    def assertAddButtonSurvivesInitial(self, initial: object) -> None:  # noqa: D102

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": initial}).as_p()
        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )

    def test_add_button_survives_initial_at_maximum(self) -> None:
        """The add button remains when initial rows reach the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2])

    def test_add_button_survives_initial_above_maximum(self) -> None:
        """The add button remains when initial rows exceed the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2, 3])

    def test_initial_reads_are_bounded_by_the_absolute_maximum(self) -> None:
        """It reads at most absolute_max items from a callable or nested initial."""

        class GuardedInitial(list[int]):
            def __iter__(self) -> object:
                for index, value in enumerate(super().__iter__()):
                    if index == 2:
                        raise AssertionError("read beyond absolute_max")
                    yield value

        class CallableInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                max_length=2,
                absolute_max=2,
                initial=lambda: GuardedInitial([1, 2, 3]),
            )

        html = CallableInitialForm().as_p()

        self.assertIn('name="values-0"', html)
        self.assertIn('name="values-1"', html)
        self.assertNotIn('name="values-2"', html)
        self.assertIn('name="values-TOTAL_FORMS" value="2"', html)
        self.assertIn('name="values-INITIAL_FORMS" value="2"', html)

        class NestedForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(), max_length=2, absolute_max=2
                ),
                max_length=1,
                absolute_max=1,
            )

        nested_html = NestedForm(initial={"values": [GuardedInitial([1, 2, 3])]}).as_p()

        self.assertIn('name="values-0-0"', nested_html)
        self.assertIn('name="values-0-1"', nested_html)
        self.assertNotIn('name="values-0-2"', nested_html)
        self.assertIn('name="values-0-TOTAL_FORMS" value="2"', nested_html)
        self.assertIn('name="values-0-INITIAL_FORMS" value="2"', nested_html)


class SequenceFieldErrorRenderingTestCase(CompositeFieldTestCase):
    """Make sure ``ListField`` shows each error at the correct location.

    Each test examines the outer field errors, the row errors, or the rendered
    error markup.
    """

    def test_outer_validator_error_stays_visible(self) -> None:
        """A sequence validator error remains visible at the outer field."""

        def reject(value: object) -> object:
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), validators=[reject])

        form = Form(
            QueryDict(
                "values=forged&values-0=1&values-1=2&"
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0"
            )
        )
        self.assertOuterValidatorErrorForForm(form, "values")

    def test_bound_field_hides_child_item_errors(self) -> None:
        """A sequence bound field hides an error that the row renders."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertChildErrorsHiddenForForm(form, "values", "Enter a whole number.")

    def test_manual_field_rendering_keeps_child_errors_inline(self) -> None:
        """A manual sequence field render includes its row error once."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertManualVisibleFieldsRenderMessageOnce(form, "Enter a whole number.")

    def test_nested_child_item_errors_do_not_repeat_on_parent_row(self) -> None:
        """Nested reviewer errors render beside reviewers, not their milestone."""

        class MilestoneForm(forms.Form):
            reviewers = nestingdolls.ListField(
                forms.EmailField(), required=False, max_length=3
            )

        class Form(forms.Form):
            milestones = nestingdolls.ListField(
                nestingdolls.MappingField(MilestoneForm), min_length=1, max_length=4
            )

        form = Form(
            {
                f"milestones-{TOTAL_FORM_COUNT}": "1",
                f"milestones-{INITIAL_FORM_COUNT}": "1",
                f"milestones-{MIN_NUM_FORM_COUNT}": "1",
                f"milestones-{MAX_NUM_FORM_COUNT}": "4",
                "milestones-0-DELETE": "",
                f"milestones-0-reviewers-{TOTAL_FORM_COUNT}": "3",
                f"milestones-0-reviewers-{INITIAL_FORM_COUNT}": "1",
                f"milestones-0-reviewers-{MIN_NUM_FORM_COUNT}": "0",
                f"milestones-0-reviewers-{MAX_NUM_FORM_COUNT}": "3",
                "milestones-0-reviewers-0": "Grace@example.com",
                "milestones-0-reviewers-1": "gg",
                "milestones-0-reviewers-2": "asgsgasg",
            }
        )
        self.assertFormInvalid(form)

        for layout in ("as_div", "as_p", "as_table", "as_ul"):
            with self.subTest(layout=layout):
                html = getattr(form, layout)()

                self.assertRenderedMessageCount(html, "Enter a valid email address.", 2)
                self.assertErrorReferenceResolves(
                    html, "id_milestones-0-reviewers_1_error"
                )
                self.assertErrorReferenceResolves(
                    html, "id_milestones-0-reviewers_2_error"
                )
                self.assertErrorElementIsAbsent(html, "id_milestones_0_error")

    def test_multiple_outer_validator_messages_stay_visible(self) -> None:
        """A sequence validator keeps both outer messages."""

        def reject_with_two_messages(value: object) -> object:
            raise ValidationError(["First outer.", "Second outer."])

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                required=False,
                validators=[reject_with_two_messages],
            )

        form = Form(
            QueryDict(
                "values=forged&values-0=1&values-1=2&"
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0"
            )
        )
        self.assertMultipleOuterMessagesStayVisible(form, "values")

    def test_custom_bound_field_renders_the_field_error(self) -> None:
        """A custom sequence bound field renders its row error."""

        class CustomBoundField(nestingdolls.SequenceBoundField):
            pass

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=CustomBoundField
            )

        form = Form(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertCustomBoundFieldErrorForForm(
            form, "values", CustomBoundField, "Enter a whole number."
        )

    def test_bound_field_rejects_a_foreign_field(self) -> None:
        """A sequence bound field rejects a foreign field."""
        with self.assertRaisesRegex(TypeError, "field must be a"):
            nestingdolls.SequenceBoundField(forms.Form(), forms.CharField(), "value")


class SequenceFieldStateRenderingTestCase(CompositeFieldTestCase):
    """Make sure ``ListField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection.
    """

    def test_render_state_is_isolated(self) -> None:
        """An invalid sequence form does not change a fresh form."""
        invalid_data = {
            "values-0": "bad",
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        self.assertRenderStateIsolatedForForms(
            SequenceSubmissionForm(invalid_data), SequenceSubmissionForm(), "values"
        )

    def test_form_error_class_reaches_the_rows(self) -> None:
        """The outer form's error class renders each row's error list."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "1",
            },
            error_class=MarkedErrorList,
        )
        self.assertChildErrorMarkupUsesErrorClass(form, "values")

    def test_form_renderer_reaches_the_rows(self) -> None:
        """The outer form's renderer is the formset's and every row's."""
        form = SequenceSubmissionForm(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "1",
            },
            renderer=MarkedRenderer(),
        )
        self.assertFormRendererReachesChildren(
            form,
            "values",
            lambda bound_field: [bound_field.formset, *bound_field.formset.forms],
        )

    def test_child_only_failure_marks_the_field(self) -> None:
        """A sequence that failed only in a row carries the error class."""
        form = StyledSequenceAndPlainTextForm(
            {
                "values-0": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "1",
                "plain": "",
            }
        )
        self.assertChildOnlyFailureMarksField(form, form["values"], form["plain"])

    def test_late_add_error_marks_the_field(self) -> None:
        """An error recorded after a first read still marks a sequence."""
        form = StyledSequenceAndPlainTextForm(
            {
                "values-0": "1",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "1",
                "plain": "ok",
            }
        )
        self.assertFormValid(form)
        composite, plain = form["values"], form["plain"]
        self.assertCssClassesMatchBaseline(composite, plain)
        form.add_error("values", "Late outer error.")
        form.add_error("plain", "Late outer error.")
        self.assertIn("has-error", plain.css_classes())
        self.assertCssClassesMatchBaseline(composite, plain)

    def test_change_detection_uses_child_semantics(self) -> None:
        """A sequence child converts one before change detection."""
        data = {
            "values-0": "1",
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        self.assertChildChangeDetection(
            SequenceSubmissionForm(data, initial={"values": [1]}),
            SequenceSubmissionForm(data, initial={"values": [3, 4]}),
        )

    def test_as_div_uses_the_div_wrapper(self) -> None:
        """The sequence div helper uses the div widget wrapper."""
        form = SequenceForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_div, "nestingdolls/sequence/div.html", "sequence"
        )

    def test_as_p_uses_the_p_wrapper(self) -> None:
        """The sequence paragraph helper uses the paragraph widget wrapper."""
        form = SequenceForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_p, "nestingdolls/sequence/p.html", "sequence"
        )

    def test_as_table_uses_the_table_wrapper(self) -> None:
        """The sequence table helper uses the table widget wrapper."""
        form = SequenceForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_table, "nestingdolls/sequence/table.html", "sequence"
        )

    def test_as_ul_uses_the_ul_wrapper(self) -> None:
        """The sequence list helper uses the list widget wrapper."""
        form = SequenceForm()
        self.assertRenderMethodUsesWidgetTemplate(
            form.as_ul, "nestingdolls/sequence/ul.html", "sequence"
        )

    def test_consecutive_renders_use_their_own_layout(self) -> None:
        """A sequence form keeps each render layout separate."""
        self.assertSequentialRendersForForm(SequenceForm(), "sequence")

    def test_default_render_uses_the_div_layout(self) -> None:
        """A sequence default render uses the Django div layout."""
        self.assertIn('<div\n  data-widget="sequence"', str(SequenceForm()))

    def test_custom_template_name_stays_literal(self) -> None:
        """A sequence widget keeps a literal custom template name."""
        widget = copy.deepcopy(SequenceForm().fields["values"].widget)
        widget.template_name = "app/{custom}.html"
        self.assertEqual(widget.template_name, "app/{custom}.html")


class SequenceWidgetLayoutContractTestCase(CompositeFieldTestCase):
    """Assert every layout marks invalid rows and renders the child help text."""

    LAYOUTS = ("as_div", "as_p", "as_ul", "as_table")
    HELP_TEXT_ID = "id_values_rows_helptext"

    def test_whole_field_error_marks_every_row(self) -> None:
        """A ``min_length`` failure belongs to no row, so every row is marked.

        Django marks every sub-input of a ``use_fieldset`` widget; the
        ``aria-describedby`` reference stays on the fieldset, which already
        points at the field's error list.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), min_length=3)

        form = Form(
            {
                "values-0": "a",
                "values-1": "b",
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
            }
        )
        self.assertFormInvalid(form)

        html = form.as_div()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertIn('aria-describedby="id_values_error"', html)
        self.assertNotIn('aria-describedby="id_values_0_error"', html)
        for message in form.errors["values"]:
            self.assertRenderedMessageCount(html, message)
        self.assertErrorReferenceResolves(html, "id_values_error")
        self.assertErrorElementIsAbsent(html, "id_values_0_error")

    def test_row_error_marks_only_that_row(self) -> None:
        """An item failure on one row of three marks that row alone."""
        form = SequenceForm(
            {
                "values-0": "1",
                "values-1": "bad",
                "values-2": "3",
                f"values-{TOTAL_FORM_COUNT}": "3",
                f"values-{INITIAL_FORM_COUNT}": "3",
            }
        )
        self.assertFormInvalid(form)

        html = form.as_div()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertIn('aria-describedby="id_values_1_error"', html)
        for message in form.errors["values"]:
            self.assertRenderedMessageCount(html, message)
        self.assertErrorReferenceResolves(html, "id_values_1_error")

    def test_child_help_text_renders_once_under_the_rows(self) -> None:
        """The child's help text renders one time and every row points at it."""
        form = SequenceHelpTextForm(initial={"values": ["a", "b"]})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                tag = "span" if layout == "as_p" else "div"
                self.assertEqual(html.count("ROWHELP"), 1)
                self.assertIn(
                    f'<{tag} class="helptext" id="{self.HELP_TEXT_ID}">ROWHELP</{tag}>',
                    html,
                )
                # Two rendered rows plus the empty-row template.
                self.assertEqual(
                    html.count(f'aria-describedby="{self.HELP_TEXT_ID}"'), 3
                )

    def test_child_label_is_never_rendered(self) -> None:
        """A row has no label of its own; the field's legend names the group."""
        form = SequenceHelpTextForm(initial={"values": ["a"]})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                self.assertEqual(getattr(form, layout)().count("ROWLABEL"), 0)

    def test_no_child_help_text_renders_nothing(self) -> None:
        """A child without help text adds no element and no reference."""
        form = SequenceForm(initial={"values": ["a"]})

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                self.assertNotIn("helptext", html)
                self.assertNotIn("aria-describedby", html)

    def test_no_render_path_writes_the_shared_child_render_state(self) -> None:
        """Test that rendering does not mutate the shared child widget.

        Row forms deep-copy their child field, so each render reaches a
        per-row widget rather than the shared widget.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(MappingPointForm))

        form = Form(initial={"values": [{"a": 1, "label": "one"}]})
        child_widget = form.fields["values"].widget.child_field.widget
        sentinel = child_widget.RenderState()
        child_widget.render_state = sentinel

        form.as_div()

        self.assertIs(child_widget.render_state, sentinel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
