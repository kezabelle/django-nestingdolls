"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    CompositeErrorDisplayAssertions,
    CompositeRenderingAssertions,
    ImproperlyConfigured,
    MultiValueDict,
    OptionalSequenceForm,
    QueryDict,
    SequenceForm,
    SimpleTestCase,
    ValidationError,
    forms,
    nestingdolls,
    override_settings,
)


def setUpModule():
    setup_test_environment()


def tearDownModule():
    teardown_test_environment()


class SequenceFieldCopyTestCase(SimpleTestCase):
    """What a deep copy of a nested sequence field shares, and what it does not.

    ``SequenceField.__deepcopy__`` keeps the row formset class that the
    source widget cached, instead of a rebuild of two classes for each
    row. These tests hold the lines that make that sharing safe.
    """

    def test_row_field_copies_share_one_row_formset_class(self):
        """Every row's field copy shares one cached row formset class.

        The shared class is the performance contract: without it, each
        nested row form builds two new classes. The row fields and their
        widgets must stay distinct objects, so no row shares mutable
        state with another row.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        form = Form(
            {
                "values-TOTAL_FORMS": "2",
                "values-INITIAL_FORMS": "0",
                "values-0-TOTAL_FORMS": "1",
                "values-0-INITIAL_FORMS": "0",
                "values-0-0": "a",
                "values-1-TOTAL_FORMS": "1",
                "values-1-INITIAL_FORMS": "0",
                "values-1-0": "b",
            }
        )
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [["a"], ["b"]])

        first, second = (row.fields["value"] for row in form["values"].formset.forms)
        self.assertIsNot(first, second)
        self.assertIsNot(first.widget, second.widget)
        self.assertIsNot(first.child_field, second.child_field)
        self.assertIs(first.widget.formset_class, second.widget.formset_class)

    def test_a_new_child_field_assignment_rebuilds_the_class(self):
        """A widget assigned a new child field builds a new class.

        The deep-copy path keeps the cached class only because its new
        child is a copy of the field that the class names. A
        ``child_field`` assignment brings a child with no such relation,
        so the setter must remove the cache, or the widget builds rows
        from the old child field.
        """
        field = nestingdolls.ListField(forms.CharField(), required=False)
        widget = field.widget
        old_class = widget.formset_class
        self.assertIs(old_class.form.base_fields["value"], field.child_field)

        new_child = forms.IntegerField()
        widget.child_field = new_child

        self.assertIsNot(widget.formset_class, old_class)
        self.assertIs(widget.formset_class.form.base_fields["value"], new_child)

    def test_a_child_field_change_on_one_form_reaches_its_rows(self):
        """A change to one form's child field changes that form's own rows.

        The shared class must not cross form instances. Each form's rows
        must come from that form's own child field chain, so a per-form
        change stays visible, and one form cannot leak configuration
        into another form of the same class.

        The form class is local to this test. The scope of the sharing is
        what this test measures, so no other test may touch this class.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        payload = {
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
            "values-0-TOTAL_FORMS": "1",
            "values-0-INITIAL_FORMS": "0",
            "values-0-0": "  padded  ",
        }
        # Complete one form lifecycle first. Sharing that crossed form
        # instances would then be observable in the second form.
        first = Form(payload)
        self.assertIs(first.is_valid(), True, first.errors)
        self.assertEqual(first.cleaned_data["values"], [["padded"]])

        second = Form(payload)
        second.fields["values"].child_field.child_field.strip = False
        self.assertIs(second.is_valid(), True, second.errors)
        self.assertEqual(second.cleaned_data["values"], [["  padded  "]])


class ListFieldWidgetIntegrationTestCase(SimpleTestCase):
    """These tests check ListField widget integration."""

    def test_custom_child_choices_are_rendered(self):
        """It renders child choice widgets normally."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.ChoiceField(choices=(("a", "A"),)))

        html = Form(initial={"values": ["a"]}).as_p()

        self.assertInHTML('<option value="a" selected>A</option>', html)

    def test_child_prepare_value_is_used(self):
        """It uses the child field's prepared value when rendering."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField())

        html = Form(initial={"values": [{"answer": 42}]}).as_p()

        self.assertInHTML(
            '<textarea name="values-0" cols="40" rows="10" id="id_values_0">{&quot;answer&quot;: 42}</textarea>',
            html,
        )

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(self):
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget()
        file_widget = nestingdolls.SequenceWidget()

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), widget=text_widget)

        class TextForm(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), widget=file_widget)

        self.assertIs(UploadForm().is_multipart(), True)
        self.assertIs(TextForm().is_multipart(), False)

    def test_exact_name_and_row_keys_count_as_input(self):
        """An exact or row key counts as input. A non-string key does not."""
        widget = nestingdolls.ListField(forms.IntegerField()).widget

        self.assertIs(
            widget.value_omitted_from_data({"values": "x"}, {}, "values"), False
        )
        self.assertIs(
            widget.value_omitted_from_data({"values-0": "1"}, {}, "values"), False
        )
        self.assertIs(widget.value_omitted_from_data({0: "1"}, {}, "values"), True)

    def test_extraction_without_input_returns_an_empty_list(self):
        """Extraction returns an empty list when a submission has no input."""
        widget = nestingdolls.ListField(forms.IntegerField()).widget

        self.assertEqual(widget.value_from_datadict({}, {}, "values"), [])

    def test_form_required_attribute_opt_out_is_preserved(self):
        """It respects the form-level required-attribute opt-out."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertNotIn(" required", Form(use_required_attribute=False).as_p())

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_widget_renders_management_inputs_controls_and_media(self):
        """It renders management inputs, row controls, and the enhancement media."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=2)

        form = Form()
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
        self.assertIn("nestingdolls/sequence.js", str(form.media))

        # An invalid bound render keeps the sequence markup in the active layout.
        invalid = Form(
            {"values-0": "bad", "values-TOTAL_FORMS": "1", "values-INITIAL_FORMS": "0"}
        )
        self.assertIs(invalid.is_valid(), False)
        with self.assertTemplateUsed("nestingdolls/sequence/p.html"):
            invalid_html = invalid.as_p()

        self.assertIn('data-widget="sequence"', invalid_html)
        self.assertIn("<span", invalid_html)
        self.assertIn("Enter a whole number.", invalid_html)

    def test_disabled_field_renders_the_disabled_widget_marker(self):
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

        class EnabledForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertNotIn("data-sequence-disabled", EnabledForm().as_div())

    def assertRowErrorMarkup(
        self, form_kwargs, expected_input, expected_errors, render_method="as_div"
    ):
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
        self.assertIs(form.is_valid(), False)
        html = getattr(form, render_method)()
        self.assertInHTML(expected_input, html)
        self.assertInHTML(expected_errors, html)

    def test_row_error_markup_with_automatic_ids(self):
        """A row error describes its child input when Django creates ids."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
        )

    def test_row_error_markup_without_automatic_ids(self):
        """A row error keeps the existing description when Django omits ids."""
        self.assertRowErrorMarkup(
            {"auto_id": False},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
            '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
        )

    def test_table_row_error_markup_uses_djangos_list_template(self):
        """An ``as_table()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            render_method="as_table",
        )

    def test_ul_row_error_markup_uses_djangos_list_template(self):
        """An ``as_ul()`` row error uses Django's list template."""
        self.assertRowErrorMarkup(
            {},
            '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
            '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            render_method="as_ul",
        )

    def test_p_layout_row_error_markup_stays_phrasing_content(self):
        """An ``as_p`` row error does not contain ``ul``. The widget stays in its ``p`` element.

        A ``ul`` start tag closes an open ``p`` element during HTML parsing.
        This moves the remaining widget content outside the widget root.
        The moved content includes the empty-row template.
        The script cannot enhance that content.
        """

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            {
                "values-0": "bad",
                "values-TOTAL_FORMS": "1",
                "values-INITIAL_FORMS": "0",
            }
        )

        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertNotIn("<ul", html)
        self.assertIn("data-sequence-empty-row", html)

    def test_compound_row_error_markup_describes_each_child_widget(self):
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

        self.assertIs(compound.is_valid(), False)
        compound_html = compound.as_div()
        self.assertInHTML(
            '<input type="text" name="values-0_0" value="2026-08-05" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_0">',
            compound_html,
        )
        self.assertInHTML(
            '<input type="text" name="values-0_1" value="not-a-time" aria-invalid="true" aria-describedby="id_values_0_error" id="id_values_0_1">',
            compound_html,
        )

    def test_a_disabled_child_field_disables_every_row_input(self):
        """A disabled child field renders each row input as disabled."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(disabled=True), required=False, initial=[7]
            )

        self.assertInHTML(
            '<input type="number" name="values-0" value="7" disabled id="id_values_0">',
            Form().as_p(),
        )

    def test_a_string_initial_row_renders_a_blank_compound_row(self):
        """A compound row does not decompress a string initial row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField(), required=False)

        html = Form(initial={"values": ["2026-08-05 10:30"]}).as_p()

        self.assertInHTML(
            '<input type="text" name="values-0_0" id="id_values_0_0">', html
        )
        self.assertNotIn("2026-08-05", html)

    def assertAddButtonSurvivesInitial(self, initial):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        html = Form(initial={"values": initial}).as_p()
        self.assertIn("data-sequence-add-button", html)
        self.assertInHTML(
            '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
            html,
        )

    def test_add_button_survives_initial_at_maximum(self):
        """The add button remains when initial rows reach the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2])

    def test_add_button_survives_initial_above_maximum(self):
        """The add button remains when initial rows exceed the maximum."""
        self.assertAddButtonSurvivesInitial([1, 2, 3])

    def test_initial_reads_are_bounded_by_the_absolute_maximum(self):
        """It reads at most absolute_max items from a callable or nested initial."""

        class GuardedInitial(list[int]):
            def __iter__(self):
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


class PublicApiTestCase(SimpleTestCase):
    """Tests public constructor contracts.

    Invalid limits, child fields, widgets, and bound field classes are refused."""

    def test_constructor_bounds_are_enforced(self):
        """It refuses limit and initial combinations the field cannot satisfy."""
        self.assertEqual(
            nestingdolls.ListField(forms.IntegerField(), initial=range(2)).initial,
            range(2),
        )
        with self.assertRaises(nestingdolls.SequenceInputValidationError):
            nestingdolls.ListField(forms.IntegerField()).clean("not a list")

        with self.assertRaisesMessage(
            ValueError, "max_length=0 requires required=False"
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=0)
        with self.assertRaisesMessage(
            ValueError, "max_length must be greater than or equal to min_length"
        ):
            nestingdolls.ListField(forms.IntegerField(), min_length=5, max_length=2)
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=1, initial=[1, 2])
        with self.assertRaisesMessage(
            ValueError, "'absolute_max' must be greater or equal to 'max_length'."
        ):
            nestingdolls.ListField(forms.IntegerField(), max_length=2, absolute_max=1)

    def test_constructor_rejects_negative_min_length(self):
        """The constructor rejects a negative minimum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=-1)

    def test_constructor_rejects_negative_max_length(self):
        """The constructor rejects a negative maximum length."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), max_length=-1)

    def test_constructor_rejects_max_length_below_min_length(self):
        """The constructor rejects a maximum length below the minimum."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.IntegerField(), min_length=2, max_length=1)

    def test_scalar_initial_becomes_one_row(self):
        """A scalar initial wraps into one row instead of raising."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), initial=5)

        constructor_html = Form().as_p()
        keyword_html = Form(initial={"values": 5}).as_p()

        self.assertIn('value="5"', constructor_html)
        self.assertIn('name="values-TOTAL_FORMS" value="1"', constructor_html)
        self.assertEqual(constructor_html, keyword_html)

    def test_rejects_non_fields_and_legacy_widget_usage(self):
        """It rejects invalid child fields and legacy widget configuration."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)
        with self.assertRaises(TypeError):
            nestingdolls.SequenceWidget(child_field=forms.IntegerField())
        with self.assertRaises(TypeError):
            nestingdolls.MappingWidget(form_class=forms.Form)

    def test_constructor_rejects_a_foreign_bound_field_class(self):
        """The constructor rejects a bound field class with a wrong base class."""
        with self.assertRaises(TypeError):
            nestingdolls.ListField(
                forms.IntegerField(), bound_field_class=forms.BoundField
            )

    def test_widget_instance_is_copied_and_rebound_to_field_configuration(self):
        """Django copies a supplied widget before the field configures it."""
        widget = nestingdolls.SequenceWidget()

        field = nestingdolls.ListField(
            forms.IntegerField(),
            min_length=1,
            max_length=2,
            absolute_max=3,
            widget=widget,
        )

        self.assertIsNot(field.widget, widget)
        self.assertIs(field.widget.child_field, field.child_field)
        self.assertEqual(field.widget.limits.min_length, 1)
        self.assertEqual(field.widget.limits.max_length, 2)
        self.assertEqual(field.limits.absolute_max, 3)
        self.assertIs(field.widget.limits, field.limits)

    def test_a_reused_widget_rebuilds_for_its_new_field(self):
        """A reused widget's new field builds a class from its own child."""
        first = nestingdolls.ListField(forms.CharField(), required=False)
        stale = first.widget.formset_class

        second = nestingdolls.ListField(
            forms.IntegerField(), required=False, widget=first.widget
        )

        self.assertIsNot(second.widget.formset_class, stale)
        self.assertIs(
            second.widget.formset_class.form.base_fields["value"], second.child_field
        )
        self.assertIs(first.widget.formset_class, stale)


class ListFieldCleaningTestCase(SimpleTestCase):
    """Make sure ``ListField`` cleans each input shape correctly.

    Each test sends one input shape. Each test examines the cleaned list or the
    error codes."""

    def test_exact_name_blank_is_one_row(self):
        """A blank request value is one submitted sequence row."""
        form = OptionalSequenceForm(QueryDict("values="))
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "required")

    def test_optional_direct_list_cleans_every_row(self):
        """A direct Python list in a dict cleans every row."""
        form = OptionalSequenceForm({"values": ["3", "4"]})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_request_list_payload_is_one_row(self):
        """A request list payload is one row, not the outer sequence."""
        form = OptionalSequenceForm(MultiValueDict({"values": [["3", "4"]]}))
        self.assertIs(form.is_valid(), False)
        error = form.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.child_code, "invalid")

    def test_direct_non_lists_are_invalid_sequence_input(self):
        """A direct exact sequence input must be a Python list."""
        for value in (None, "", "3", ("3",), {"number": "3"}):
            with self.subTest(value=value):
                form = OptionalSequenceForm({"values": value})
                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertEqual(error.code, "invalid")

    def test_direct_none_cleans_empty_when_optional(self):
        """An optional field treats ``clean(None)`` as an empty submission.

        ``MappingField.clean(None)`` returns ``{}``.
        The sequence field has the same direct-call behavior.
        Only ``clean`` makes this conversion.
        Bound ``{"values": None}`` input remains invalid.
        """
        field = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertEqual(field.clean(None), [])

    def test_direct_none_reports_required(self):
        """A required field reports ``required`` for ``clean(None)``."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as caught:
            field.clean(None)

        self.assertEqual(caught.exception.code, "required")

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

    def test_required_direct_list_cleans_every_row(self):
        """A direct sequence list cleans every row."""
        form = SequenceForm({"values": ["3", "4"]})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [3, 4])

    def test_exact_list_blank_and_none_are_rows(self):
        """A list entry remains a row regardless of its value."""
        for submitted in ({"values": [""]}, {"values": [None]}, QueryDict("values=")):
            with self.subTest(submitted=submitted):
                form = OptionalSequenceForm(submitted)
                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertEqual(error.code, "item_invalid")
                self.assertEqual(error.child_code, "required")

    def test_direct_empty_list_cleans_empty(self):
        """An empty direct list is an empty submitted sequence."""
        form = OptionalSequenceForm({"values": []})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [])

    def test_direct_list_keeps_a_multiple_choice_row(self):
        """A direct row list reaches Django's list-aware child widget."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.MultipleChoiceField(choices=(("a", "A"), ("b", "B"))),
                required=False,
            )

        form = Form({"values": [["a", "b"]]})
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [["a", "b"]])


class ListFieldErrorDisplayTestCase(CompositeErrorDisplayAssertions, SimpleTestCase):
    """Make sure ``ListField`` shows each error at the correct location.

    Each test examines the outer field errors, the row errors, or the rendered
    error markup."""

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

    def test_manual_field_rendering_keeps_child_errors_inline(self):
        """A manual sequence field render includes its row error once."""
        self.assertManualFieldRenderingIncludesChildErrors(
            OptionalSequenceForm,
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


class ListFieldRenderingTestCase(CompositeRenderingAssertions, SimpleTestCase):
    """Make sure ``ListField`` renders each layout correctly.

    Each test examines the rendered markup, the render state, or change
    detection."""

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

    def test_consecutive_renders_use_their_own_layout(self):
        """A sequence form keeps each render layout separate."""
        self.assertSequentialRendersUseOwnLayout(SequenceForm, "sequence")

    def test_default_render_uses_the_div_layout(self):
        """A sequence default render uses the Django div layout."""
        self.assertDefaultRenderUsesDivLayout(SequenceForm, "sequence")

    def test_custom_template_name_stays_literal(self):
        """A sequence widget keeps a literal custom template name."""
        self.assertLiteralTemplateNameSurvives(SequenceForm, "values")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
