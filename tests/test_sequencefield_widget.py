"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import copy
import unittest
from decimal import Decimal

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
from django.utils import translation

import nestingdolls

from .support.forms.mapping import (
    MappingPointForm,
)
from .support.forms.sequence import (
    BoundedNestedIntegerSequenceForm,
    DisabledSequenceForm,
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
    WidgetTemplateMarkerRenderer,
    rendered_controls,
    rendered_elements,
    rendered_wrapper,
)


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


class SequenceFieldWidgetTestCase(CompositeFieldTestCase):
    """These tests check ListField widget integration."""

    def test_nested_render_does_not_format_rows_beyond_child_cap(self) -> None:
        """An excluded inner value is never formatted by the outer widget."""

        class Unformattable:
            def __repr__(self) -> str:
                raise AssertionError("excluded row was formatted")

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.IntegerField(), required=False, max_length=1, absolute_max=1
                ),
                required=False,
            )

        html = Form(initial={"values": [[1, Unformattable()]]}).as_div()
        self.assertIn('name="values-0-value-0-value"', html)

    def test_hidden_render_does_not_restore_a_deleted_row(self) -> None:
        """Hidden controls rebind to the same cleaned value after a deletion."""

        class Form(forms.Form):
            values = nestingdolls.SequenceField(forms.IntegerField(), required=False)

        submitted = {
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "1",
            "values-0-value": "7",
            "values-0-DELETE": "on",
        }
        form = Form(submitted, initial={"values": [7]})
        html = form["values"].as_hidden()
        self.assertFormValid(form)
        self.assertEqual(form.cleaned_data["values"], [])
        self.assertNotIn('name="values-0-value"', html)
        controls = rendered_controls(html, "values-")
        rebound = Form(
            {name: attrs.get("value") or "" for name, attrs in controls.items()},
            initial={"values": [7]},
        )
        self.assertFormValid(rebound)
        self.assertEqual(rebound.cleaned_data["values"], [])

    def test_string_decompressing_child_widget_keeps_its_parts(self) -> None:
        """A MultiWidget may legitimately decompress a string initial."""

        class PairWidget(forms.MultiWidget):
            def __init__(self) -> None:
                super().__init__((forms.TextInput(), forms.TextInput()))

            def decompress(self, value: object) -> list[object]:
                if isinstance(value, str):
                    return value.split("|")
                return ["", ""]

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.MultiValueField(
                    (forms.CharField(), forms.CharField()), widget=PairWidget()
                )
            )

        html = Form(initial={"values": ["left|right"]}).as_div()
        controls = rendered_controls(html, "values-0-value_")
        self.assertEqual(controls["values-0-value_0"]["value"], "left")
        self.assertEqual(controls["values-0-value_1"]["value"], "right")

    def test_choice_options_refer_to_their_row_errors(self) -> None:
        """Every invalid radio and checkbox option identifies its row error."""
        for widget in (forms.RadioSelect, forms.CheckboxSelectMultiple):
            for layout in ("as_div", "as_p", "as_ul", "as_table"):
                with self.subTest(widget=widget, layout=layout):

                    class Form(forms.Form):
                        values = nestingdolls.SequenceField(
                            forms.ChoiceField(
                                choices=(("a", "A"), ("b", "B")), widget=widget
                            )
                        )

                    form = Form(
                        {
                            "values-TOTAL_FORMS": "1",
                            "values-INITIAL_FORMS": "0",
                            "values-0-value": "invalid",
                        }
                    )
                    self.assertFormInvalid(form)
                    html = getattr(form, layout)()
                    options = [
                        dict(element.attributes)
                        for element in rendered_elements(html)
                        if element.name == "input"
                        and dict(element.attributes).get("name") == "values-0-value"
                    ]
                    self.assertEqual(len(options), 2)
                    for attrs in options:
                        self.assertEqual(attrs.get("aria-invalid"), "true")
                        self.assertIn(
                            "id_values_0_error", attrs.get("aria-describedby", "")
                        )

    def test_select_options_do_not_repeat_row_error_attributes(self) -> None:
        """An invalid select carries the row error; its options do not."""
        for field, widget in (
            (forms.ChoiceField, forms.Select),
            (forms.MultipleChoiceField, forms.SelectMultiple),
        ):
            for layout in ("as_div", "as_p", "as_ul", "as_table"):
                with self.subTest(widget=widget, layout=layout):

                    class Form(forms.Form):
                        values = nestingdolls.SequenceField(
                            field(choices=(("a", "A"), ("b", "B")), widget=widget)
                        )

                    form = Form(
                        {
                            "values-TOTAL_FORMS": "1",
                            "values-INITIAL_FORMS": "0",
                            "values-0-value": "invalid",
                        }
                    )
                    self.assertFormInvalid(form)
                    (select,) = [
                        element
                        for element in rendered_elements(getattr(form, layout)())
                        if element.name == "select"
                        and dict(element.attributes).get("name") == "values-0-value"
                    ]
                    self.assertEqual(
                        dict(select.attributes).get("aria-invalid"), "true"
                    )
                    options = [
                        dict(child.attributes)
                        for child in select.children
                        if not isinstance(child, str)
                    ]
                    self.assertEqual(len(options), 2)
                    for attrs in options:
                        self.assertNotIn("aria-invalid", attrs)
                        self.assertNotIn("aria-describedby", attrs)

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
            '<textarea name="values-0-value" cols="40" rows="10" id="id_values_0">{&quot;answer&quot;: 42}</textarea>',
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
                "values-0-value": "not-a-number",
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
            widget.value_omitted_from_data({"values-0-value": "1"}, {}, "values"), False
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
    def test_localize_flag_renders_and_reads_rows_in_one_format(self) -> None:
        """The sequence ``localize`` flag drives both the row render and the row read.

        A localized row uses a text input: a browser shows ``1,5`` in a
        ``type="number"`` input as blank.
        """
        cases = (
            (forms.DecimalField(), True, "1,5"),
            (forms.DecimalField(localize=True), False, "1.5"),
        )
        for child_field, localize, rendered in cases:
            with self.subTest(localize=localize), translation.override("de"):

                class Form(forms.Form):
                    values = nestingdolls.SequenceField(child_field, localize=localize)

                html = Form(initial={"values": [Decimal("1.5")]}).as_p()
                bound = Form(
                    QueryDict(
                        f"values-{TOTAL_FORM_COUNT}=1&"
                        f"values-{INITIAL_FORM_COUNT}=0&"
                        f"values-0-value={rendered}"
                    )
                )

                self.assertIn(
                    f'<input type="text" name="values-0-value" value="{rendered}"', html
                )
                self.assertFormValid(bound)
                self.assertEqual(bound.cleaned_data["values"], [Decimal("1.5")])

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_widget_renders_management_inputs(self) -> None:
        """It renders the four formset management inputs with unlocalized counts."""
        html = MinimumTwoIntegerSequenceForm().as_p()

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

    def test_widget_renders_wrapper_ids_and_initial_rows(self) -> None:
        """It renders the wrapper, the rows container, and one deletable row per minimum row."""
        html = MinimumTwoIntegerSequenceForm().as_p()

        wrapper = rendered_wrapper(html, "sequence")
        self.assertEqual(wrapper["id"], "id_values_widget")
        self.assertEqual(wrapper["data-sequence-field"], "values")
        self.assertEqual(wrapper["data-sequence-minimum"], "2")
        self.assertIn('id="id_values_rows"', html)
        self.assertInHTML(
            '<input type="number" name="values-0-value" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-1-value" id="id_values_1">',
            html,
        )
        self.assertIn('id="id_values_row_0"', html)
        self.assertIn('id="id_values_0_DELETE"', html)
        self.assertIn('id="id_values_row_1"', html)
        self.assertIn('id="id_values_1_DELETE"', html)

    def test_widget_renders_inert_add_and_remove_templates(self) -> None:
        """It renders an inert empty row and the add and remove controls the script copies."""
        html = MinimumTwoIntegerSequenceForm().as_p()

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

    def test_widget_media_declares_a_preserved_controller_script(self) -> None:
        """The media loads the controller once, and tells htmx and Unpoly to keep it."""
        media = str(MinimumTwoIntegerSequenceForm().media)

        self.assertIn("nestingdolls/sequence.js", media)
        self.assertIn('id="nestingdolls-sequence"', media)
        self.assertIn('hx-preserve="true"', media)
        self.assertIn('up-keep="true"', media)

    def test_invalid_bound_render_uses_the_paragraph_template(self) -> None:
        """An invalid bound render keeps the sequence markup in the active layout."""
        invalid = MinimumTwoIntegerSequenceForm(
            {
                "values-0-value": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertFormInvalid(invalid)
        self.assertRenderMethodUsesWidgetTemplate(
            invalid.as_p, "nestingdolls/sequence/p.html", "sequence"
        )

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

    def test_optional_widget_sets_minimum_to_zero(self) -> None:
        """An optional sequence lets the browser remove every row, despite ``min_length``."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, min_length=1
            )

        html = Form(initial={"values": [1]}).as_div()

        self.assertEqual(
            rendered_wrapper(html, "sequence")["data-sequence-minimum"], "0"
        )

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
                "values-0-value": "bad",
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
            '<input type="number" name="values-0-value" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
        )

    def test_row_error_markup_without_automatic_ids(self) -> None:
        """A row error keeps the existing description when Django omits ids."""
        self.assertRowErrorMarkup(
            {"auto_id": False},
            '<input type="number" name="values-0-value" value="bad" aria-describedby="existing-description" aria-invalid="true">',
            '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
            error_id=None,
        )

    def test_table_row_error_markup_uses_djangos_list_template(self) -> None:
        """An ``as_table()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0-value" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            render_method="as_table",
        )

    def test_ul_row_error_markup_uses_djangos_list_template(self) -> None:
        """An ``as_ul()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0-value" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
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
                "values-0-value": "bad",
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
                "values-0-value": "bad",
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
                    html.index('name="values-0-value"'),
                )

    def test_compound_row_error_markup_describes_each_child_widget(self) -> None:
        """A compound row error describes each child input."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        compound = CompoundForm(
            {
                "values-0-value_0": "2026-08-05",
                "values-0-value_1": "not-a-time",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertFormInvalid(compound)
        compound_html = compound.as_div()
        self.assertInHTML(
            '<input type="text" name="values-0-value_0" value="2026-08-05" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_0">',
            compound_html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0-value_1" value="not-a-time" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_1">',
            compound_html,
        )
        self.assertRenderedMessageCount(compound_html, "Enter a valid time.")
        self.assertErrorReferenceResolves(compound_html, "id_values_0_error")

    def test_compound_row_error_keeps_each_part_description(self) -> None:
        """A compound row error adds to each part's own description."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(
                    widget=forms.SplitDateTimeWidget(
                        date_attrs={"aria-describedby": "date-help"},
                        time_attrs={"aria-describedby": "time-help"},
                    )
                )
            )

        compound = CompoundForm(
            {
                "values-0-value_0": "2026-08-05",
                "values-0-value_1": "not-a-time",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )
        self.assertFormInvalid(compound)

        for layout in ("as_div", "as_p", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                controls = rendered_controls(
                    getattr(compound, layout)(), "values-0-value_"
                )
                self.assertEqual(
                    controls["values-0-value_0"]["aria-describedby"],
                    "date-help id_values_0_error",
                )
                self.assertEqual(
                    controls["values-0-value_1"]["aria-describedby"],
                    "time-help id_values_0_error",
                )

    def test_a_disabled_child_field_disables_every_row_input(self) -> None:
        """A disabled child field renders each row input as disabled."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(disabled=True), required=False, initial=[7]
            )

        self.assertInHTML(
            '<input type="number" name="values-0-value" value="7" disabled id="id_values_0">',
            Form().as_p(),
        )

    def test_a_disabled_sequence_disables_every_mapping_row_control(self) -> None:
        """A disabled sequence disables each editable control inside a mapping row.

        HTML ``disabled`` on the mapping wrapper ``div`` does not reach the
        inputs inside it. Hidden management inputs stay enabled: the user
        cannot edit them, and the disabled field ignores them.
        """

        class RowForm(forms.Form):
            text = forms.CharField()
            flag = forms.BooleanField(required=False)
            secret = forms.CharField(widget=forms.HiddenInput)
            tags = nestingdolls.ListField(forms.CharField(), required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(RowForm),
                disabled=True,
                initial=[{"text": "a", "flag": True, "secret": "s", "tags": ["x"]}],
            )

        # A disabled sequence never copies the inert empty-row template.
        controls = {
            name: attributes
            for name, attributes in rendered_controls(
                Form().as_div(), "values-0-"
            ).items()
            if "__prefix__" not in name
        }

        self.assertLessEqual(
            {
                "values-0-value-text",
                "values-0-value-flag",
                "values-0-value-secret",
                "values-0-value-tags-TOTAL_FORMS",
                "values-0-value-tags-0-value",
                "values-0-DELETE",
            },
            set(controls),
        )
        management = ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS")
        for name, attributes in controls.items():
            with self.subTest(name=name):
                if name.rpartition("-")[2] in management:
                    self.assertNotIn("disabled", attributes)
                else:
                    self.assertIn("disabled", attributes)

    def test_a_disabled_sequence_follows_the_form_auto_id(self) -> None:
        """A disabled sequence uses the ID pattern of the outer form."""
        unnamed = DisabledSequenceForm(auto_id=False).as_div()
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="1" data-sequence-total>',
            unnamed,
        )
        self.assertNotIn('id="', unnamed)

        custom = DisabledSequenceForm(auto_id="custom_%s").as_div()
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="1" data-sequence-total id="custom_values-TOTAL_FORMS">',
            custom,
        )
        self.assertNotIn('id="id_', custom)

    def test_a_disabled_sequence_uses_the_form_renderer(self) -> None:
        """A disabled sequence renders its management inputs with the form renderer."""
        renderer = WidgetTemplateMarkerRenderer("django/forms/widgets/hidden.html")
        html = DisabledSequenceForm(renderer=renderer).as_div()

        self.assertEqual(html.count('<marker data-name="values-TOTAL_FORMS">'), 1)
        self.assertNotIn('type="hidden" name="values-TOTAL_FORMS"', html)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_an_overdrawn_sequence_follows_the_form_auto_id(self) -> None:
        """The zero-row overflow render uses the ID pattern of the form."""
        form = BoundedNestedIntegerSequenceForm(
            {"outer": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}, auto_id=False
        )
        self.assertFormInvalid(form)

        html = form.as_div()

        self.assertInHTML(
            '<input type="hidden" name="outer-TOTAL_FORMS" value="0" data-sequence-total>',
            html,
        )
        self.assertNotIn('id="', html)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_an_overdrawn_sequence_uses_the_form_renderer(self) -> None:
        """The zero-row overflow render uses the renderer of the form."""
        renderer = WidgetTemplateMarkerRenderer("django/forms/widgets/hidden.html")
        form = BoundedNestedIntegerSequenceForm(
            {"outer": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}, renderer=renderer
        )
        self.assertFormInvalid(form)

        self.assertEqual(
            form.as_div().count('<marker data-name="outer-TOTAL_FORMS">'), 1
        )

    def test_rows_render_through_the_form_renderer(self) -> None:
        """Each row input, and the empty row, renders through the form renderer.

        A project renderer can replace a widget template in ``get_template``.
        """
        renderer = WidgetTemplateMarkerRenderer("django/forms/widgets/number.html")
        html = SequenceForm(initial={"values": [1]}, renderer=renderer).as_div()

        self.assertEqual(html.count('<marker data-name="values-0-value">'), 1)
        self.assertEqual(html.count('<marker data-name="values-__prefix__-value">'), 1)
        self.assertNotIn('type="number"', html)

    def test_a_composite_child_needs_a_composite_hidden_widget(self) -> None:
        """A composite row child with an ordinary hidden widget fails clearly.

        A hidden render gives each row its child field's ``hidden_widget()``,
        and a composite child needs a composite widget.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField()),
                initial=[[1]],
                show_hidden_initial=True,
            )

        form = Form()
        form.fields["values"].child_field.hidden_widget = forms.HiddenInput

        with self.assertRaisesMessage(
            TypeError, "composite field must have a composite widget"
        ):
            form.as_div()

    def test_a_string_initial_row_renders_a_blank_compound_row(self) -> None:
        """A compound row does not decompress a string initial row."""
        html = OptionalSplitDateTimeSequenceForm(
            initial={"values": ["2026-08-05 10:30"]}
        ).as_p()

        self.assertInHTML(
            '<input type="text" name="values-0-value_0" id="id_values_0_0">', html
        )
        self.assertNotIn("2026-08-05", html)

    def test_whole_value_rows_render_each_value_without_errors(self) -> None:
        """A valid decoded whole value renders every row with its value and no error markup."""
        form = SequenceForm({"values": [1, 2, 3]})

        self.assertFormValid(form)
        html = form.as_p()

        self.assertNotIn("errorlist", html)
        self.assertIn('name="values-0-value" value="1"', html)
        self.assertIn('name="values-1-value" value="2"', html)
        self.assertIn('name="values-2-value" value="3"', html)

    def test_exact_compound_row_renders_each_part(self) -> None:
        """A whole compound row reaches each part of the child's MultiWidget."""
        form = OptionalSplitDateTimeSequenceForm({"values": [["2026-01-02", "03:04"]]})

        html = str(form["values"])

        self.assertInHTML(
            '<input type="text" name="values-0-value_0" value="2026-01-02"'
            ' id="id_values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0-value_1" value="03:04" id="id_values_0_1">',
            html,
        )

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

        self.assertIn('name="values-0-value"', html)
        self.assertIn('name="values-1-value"', html)
        self.assertNotIn('name="values-2-value"', html)
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

        self.assertIn('name="values-0-value-0-value"', nested_html)
        self.assertIn('name="values-0-value-1-value"', nested_html)
        self.assertNotIn('name="values-0-value-2-value"', nested_html)
        self.assertIn('name="values-0-value-TOTAL_FORMS" value="2"', nested_html)
        self.assertIn('name="values-0-value-INITIAL_FORMS" value="2"', nested_html)


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
                "values=forged&values-0-value=1&values-1-value=2&"
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0"
            )
        )
        self.assertOuterValidatorErrorForForm(form, "values")

    def test_bound_field_hides_child_item_errors(self) -> None:
        """A sequence bound field hides an error that the row renders."""
        form = SequenceSubmissionForm(
            {
                "values-0-value": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertChildErrorsHiddenForForm(form, "values", "Enter a whole number.")

    def test_late_outer_error_renders_beside_the_row_error(self) -> None:
        """An outer error added after a first read still renders once."""
        form = SequenceSubmissionForm(
            {
                "values-0-value": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertLateOuterErrorRendersOnce(form, "values", "Enter a whole number.")

    def test_hidden_sequence_promotes_row_errors(self) -> None:
        """A sequence of hidden rows shows its row error at the top."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(widget=forms.HiddenInput)
            )

        form = Form(
            {
                "values-0-value": "bad",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertHiddenCompositeErrorRendersOnce(
            form, "values", "Enter a whole number."
        )

    def test_manual_field_rendering_keeps_child_errors_inline(self) -> None:
        """A manual sequence field render includes its row error once."""
        form = SequenceSubmissionForm(
            {
                "values-0-value": "bad",
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
                f"milestones-0-value-reviewers-{TOTAL_FORM_COUNT}": "3",
                f"milestones-0-value-reviewers-{INITIAL_FORM_COUNT}": "1",
                f"milestones-0-value-reviewers-{MIN_NUM_FORM_COUNT}": "0",
                f"milestones-0-value-reviewers-{MAX_NUM_FORM_COUNT}": "3",
                "milestones-0-value-reviewers-0-value": "Grace@example.com",
                "milestones-0-value-reviewers-1-value": "gg",
                "milestones-0-value-reviewers-2-value": "asgsgasg",
            }
        )
        self.assertFormInvalid(form)

        for layout in ("as_div", "as_p", "as_table", "as_ul"):
            with self.subTest(layout=layout):
                html = getattr(form, layout)()

                self.assertRenderedMessageCount(html, "Enter a valid email address.", 2)
                self.assertErrorReferenceResolves(
                    html, "id_milestones-0-value-reviewers_1_error"
                )
                self.assertErrorReferenceResolves(
                    html, "id_milestones-0-value-reviewers_2_error"
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
                "values=forged&values-0-value=1&values-1-value=2&"
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
                "values-0-value": "bad",
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

    def test_whole_value_row_error_renders_at_its_input(self) -> None:
        """A bad row in a decoded whole value shows its error inline, not silence.

        Rendering an invalid redisplay once built an unbound row formset and
        dropped the row error instead of showing it beside its input.
        """
        form = SequenceForm({"values": [1, "bad", 3]})

        self.assertFormInvalid(form)
        html = form.as_p()

        self.assertEqual(html.count("errorlist"), 1)
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertIn('name="values-1-value" value="bad"', html)
        self.assertErrorReferenceResolves(html, "id_values_1_error")
        self.assertInHTML(
            '<span class="errorlist" id="id_values_1_error">Enter a whole number.</span>',
            html,
        )


class SequenceFieldStateRenderingTestCase(CompositeFieldTestCase):
    """Make sure ``ListField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection.
    """

    def test_render_state_is_isolated(self) -> None:
        """An invalid sequence form does not change a fresh form."""
        invalid_data = {
            "values-0-value": "bad",
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
                "values-0-value": "bad",
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
                "values-0-value": "bad",
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
                "values-0-value": "bad",
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
                "values-0-value": "1",
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
            "values-0-value": "1",
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
        }
        self.assertChildChangeDetection(
            SequenceSubmissionForm(data, initial={"values": [1]}),
            SequenceSubmissionForm(data, initial={"values": [3, 4]}),
        )

    def test_render_methods_use_their_layout_wrapper(self) -> None:
        """Each Django layout method selects its own sequence widget wrapper."""
        form = SequenceForm()
        for layout, template in (
            ("as_div", "nestingdolls/sequence/div.html"),
            ("as_p", "nestingdolls/sequence/p.html"),
            ("as_table", "nestingdolls/sequence/table.html"),
            ("as_ul", "nestingdolls/sequence/ul.html"),
        ):
            with self.subTest(layout=layout):
                self.assertRenderMethodUsesWidgetTemplate(
                    getattr(form, layout), template, "sequence"
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


class SequenceFieldLayoutTestCase(CompositeFieldTestCase):
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
                "values-0-value": "a",
                "values-1-value": "b",
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
                "values-0-value": "1",
                "values-1-value": "bad",
                "values-2-value": "3",
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

    def test_outer_description_is_on_one_group_without_a_fieldset(self) -> None:
        """``as_div`` keeps Django's fieldset. The other layouts use one group.

        Only ``as_div`` marks each row.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                min_length=2,
                help_text="Outer help.",
                widget=nestingdolls.SequenceWidget(
                    attrs={"aria-labelledby": "values-label", "aria-label": "Numbers"}
                ),
            )

        form = Form(
            {
                "values-0-value": "1",
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "1",
            }
        )
        self.assertFormInvalid(form)
        outer = "id_values_helptext id_values_error"
        names = (
            "role",
            "aria-label",
            "aria-labelledby",
            "aria-describedby",
            "aria-invalid",
        )

        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                html = getattr(form, layout)()
                wrapper = rendered_wrapper(html, "sequence")
                group = {name: wrapper.get(name) for name in names}
                control = rendered_controls(html, "values-0-value")["values-0-value"]
                self.assertIsNone(control.get("aria-describedby"))
                if layout == "as_div":
                    self.assertIn(f'<fieldset aria-describedby="{outer}">', html)
                    self.assertEqual(set(group.values()), {None})
                    self.assertEqual(control.get("aria-invalid"), "true")
                else:
                    self.assertNotIn("<fieldset", html)
                    self.assertEqual(
                        group,
                        {
                            "role": "group",
                            "aria-label": "Numbers",
                            "aria-labelledby": "values-label",
                            "aria-describedby": outer,
                            "aria-invalid": "true",
                        },
                    )
                    self.assertIsNone(control.get("aria-label"))
                    self.assertIsNone(control.get("aria-labelledby"))
                    self.assertIsNone(control.get("aria-invalid"))

    def test_non_div_layouts_name_the_group_from_its_label(self) -> None:
        """A group without a caller-supplied name is labelled by the field label text.

        ``as_div`` keeps Django's fieldset and legend. A ``role="group"``
        element in another layout has no ``<legend>``, so its
        ``aria-labelledby`` must resolve to the element that holds the label.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), label="Numbers")

        form = Form(initial={"values": [1]})

        for layout in ("as_p", "as_ul", "as_table"):
            with self.subTest(layout=layout):
                html = getattr(form, layout)()

                self.assertGroupIsNamedByLabel(html, "sequence", "Numbers")

    def test_div_layout_keeps_its_fieldset_name(self) -> None:
        """``as_div`` names the group with Django's fieldset and legend.

        The inner ``data-widget`` element adds no ``role``, ``aria-label``,
        or ``aria-labelledby``.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), label="Numbers")

        html = Form(initial={"values": [1]}).as_div()

        self.assertDivGroupKeepsItsFieldsetName(html, "sequence", "Numbers")

    def test_caller_aria_label_is_not_overridden(self) -> None:
        """A name that the caller supplies is kept, and the label adds no second one."""
        for caller_name, other_name in (
            ({"aria-label": "Numbers"}, "aria-labelledby"),
            ({"aria-labelledby": "outside-label"}, "aria-label"),
        ):

            class Form(forms.Form):
                values = nestingdolls.ListField(
                    forms.IntegerField(),
                    label="Field label",
                    widget=nestingdolls.SequenceWidget(attrs=caller_name),
                )

            form = Form(initial={"values": [1]})
            for layout in ("as_p", "as_ul", "as_table"):
                with self.subTest(caller_name=caller_name, layout=layout):
                    wrapper = rendered_wrapper(getattr(form, layout)(), "sequence")

                    (name,) = caller_name
                    self.assertEqual(wrapper[name], caller_name[name])
                    self.assertIsNone(wrapper.get(other_name))

    def test_no_render_path_writes_the_shared_child_render_state(self) -> None:
        """Test that rendering does not mutate the shared child widget.

        Row forms deep-copy their child field, so each render reaches a
        per-row widget rather than the shared widget.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(nestingdolls.DictField(MappingPointForm))

        form = Form(initial={"values": [{"a": 1, "label": "one"}]})
        child_widget = form.fields["values"].widget.child_field.widget
        sentinel = child_widget.RenderState()
        child_widget.render_state = sentinel

        form.as_div()

        self.assertIs(child_widget.render_state, sentinel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
