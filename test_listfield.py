import unittest
from decimal import Decimal

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.boundfield import BoundField
from django.forms.renderers import BaseRenderer
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings
from django.utils.datastructures import MultiValueDict
from django.utils import translation

import nestingdolls


if not settings.configured:
    settings.configure(
        INSTALLED_APPS=("nestingdolls",),
        USE_I18N=False,
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()


class SequenceFieldTestCase(SimpleTestCase):
    field_class = nestingdolls.SequenceField
    collection_class = list

    def assertCleanedValues(self, cleaned_data, values):
        self.assertIsInstance(cleaned_data, self.collection_class)
        self.assertEqual(cleaned_data, self.collection_class(values))

    def test_cleans_every_submitted_item(self):
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        form = Form(QueryDict("values=1&values=2&values=3"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertCleanedValues(form.cleaned_data["values"], [1, 2, 3])

    def test_collects_errors_for_every_invalid_item(self):
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        form = Form(QueryDict("values=bad&values=also-bad"))

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors.as_data()["values"][0].code,
            "invalid_items",
        )
        self.assertEqual(set(form.fields["values"]._item_errors), {0, 1})

        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertEqual(html.count('class="errorlist"'), 3)
        self.assertIn('id="id_values_0"', html)
        self.assertIn('id="id_values_1"', html)

    def test_preserves_the_item_with_an_error_for_redisplay(self):
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        form = Form(QueryDict("values=1&values=bad&values=3"))

        self.assertFalse(form.is_valid())
        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertIn('value="bad"', html)
        self.assertIn("Enter a whole number.", html)

    def test_validates_the_final_collection(self):
        seen = []
        field_class = self.field_class

        def validator(value):
            seen.append(value)

        class Form(forms.Form):
            values = field_class(forms.IntegerField(), validators=(validator,))

        form = Form(QueryDict("values=1&values=2"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(seen, [self.collection_class([1, 2])])

    def test_minimum_and_maximum_cardinality(self):
        field_class = self.field_class

        class OptionalForm(forms.Form):
            values = field_class(forms.IntegerField(), min_num=0)

        class MinimumForm(forms.Form):
            values = field_class(forms.IntegerField(), min_num=2)

        class MaximumForm(forms.Form):
            values = field_class(forms.IntegerField(), max_num=2)

        optional_form = OptionalForm(QueryDict(""))
        self.assertTrue(optional_form.is_valid(), optional_form.errors)
        self.assertCleanedValues(optional_form.cleaned_data["values"], [])

        minimum_form = MinimumForm(QueryDict("values=1"))
        self.assertFalse(minimum_form.is_valid())
        self.assertEqual(minimum_form.errors.as_data()["values"][0].code, "min_num")

        maximum_form = MaximumForm(QueryDict("values=1&values=2&values=3"))
        self.assertFalse(maximum_form.is_valid())
        self.assertEqual(maximum_form.errors.as_data()["values"][0].code, "max_num")
        self.assertEqual(maximum_form.as_p().count('name="values"'), 3)

    def test_accepts_repeated_array_and_indexed_input_names(self):
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        test_cases = (
            (QueryDict("values=1&values=2"), [1, 2]),
            (QueryDict("values[]=1&values[]=2"), [1, 2]),
            (QueryDict("values[2]=3&values[0]=1&values[1]=2"), [1, 2, 3]),
        )

        for data, values in test_cases:
            with self.subTest(data=data.urlencode()):
                form = Form(data)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertCleanedValues(form.cleaned_data["values"], values)


class ListFieldTestCase(SequenceFieldTestCase):
    field_class = nestingdolls.ListField
    collection_class = list


class TupleFieldTestCase(SequenceFieldTestCase):
    field_class = nestingdolls.TupleField
    collection_class = tuple


class SetFieldTestCase(SequenceFieldTestCase):
    field_class = nestingdolls.SetField
    collection_class = set

    def test_rejects_unhashable_cleaned_values(self):
        class Form(forms.Form):
            values = nestingdolls.SetField(forms.JSONField())

        form = Form({"values": [{"answer": 42}]})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["values"][0].code, "unhashable")


class SequenceFieldConstructionTestCase(SimpleTestCase):
    def test_child_field_must_be_a_django_field(self):
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.SequenceField(object())

    def test_cardinality_bounds_must_be_valid(self):
        for min_num, max_num in ((-1, 1), (2, 1), (False, 1), (1, 1.5)):
            with self.subTest(min_num=min_num, max_num=max_num):
                with self.assertRaises(ValueError):
                    nestingdolls.SequenceField(
                        forms.IntegerField(),
                        min_num=min_num,
                        max_num=max_num,
                    )

    def test_frozen_sequence_field_remains_a_tuple_field(self):
        class Form(forms.Form):
            values = nestingdolls.FrozenSequenceField(forms.IntegerField())

        form = Form(QueryDict("values=1&values=2"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], (1, 2))


class SequenceFieldPublicApiTestCase(SimpleTestCase):
    def test_required_and_minimum_are_equivalent(self):
        test_cases = (
            ({}, 1, True),
            ({"min_num": 0}, 0, False),
            ({"min_num": 2}, 2, True),
            ({"required": False}, 0, False),
            ({"required": True}, 1, True),
            ({"min_num": 0, "required": False}, 0, False),
            ({"min_num": 2, "required": True}, 2, True),
        )
        for kwargs, min_num, required in test_cases:
            with self.subTest(kwargs=kwargs):
                field = nestingdolls.ListField(forms.IntegerField(), **kwargs)
                self.assertEqual(field.min_num, min_num)
                self.assertEqual(field.required, required)

        for kwargs in (
            {"min_num": 0, "required": True},
            {"min_num": 1, "required": False},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    nestingdolls.ListField(forms.IntegerField(), **kwargs)

    def test_clean_and_error_messages(self):
        field = nestingdolls.ListField(
            forms.IntegerField(),
            min_num=2,
            max_num=3,
            error_messages={
                "required": "A value is required.",
                "min_num": "Need %(limit_value)d values.",
                "max_num": "At most %(limit_value)d values.",
                "invalid": "Values must be a sequence.",
                "invalid_items": "Values contain errors.",
            },
        )

        self.assertEqual(field.clean(["1", "2"]), [1, 2])
        test_cases = (
            ([], "required", "A value is required."),
            (["1"], "min_num", "Need 2 values."),
            (["1", "2", "3", "4"], "max_num", "At most 3 values."),
            ("not-a-sequence", "invalid", "Values must be a sequence."),
            (["bad", "2"], "invalid_items", "Values contain errors."),
        )
        for value, code, message in test_cases:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    field.clean(value)
                self.assertEqual(context.exception.code, code)
                self.assertEqual(context.exception.messages, [message])

    def test_label_label_suffix_initial_help_text_and_widget(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                label="Numbers",
                label_suffix="!",
                initial=[1, 2],
                help_text="Enter whole numbers.",
                widget=forms.TextInput(attrs={"data-sequence": "item"}),
            )

        html = Form().as_p()
        self.assertIn("<label>Numbers!</label>", html)
        self.assertIn("Enter whole numbers.", html)
        self.assertEqual(html.count('type="text"'), 2)
        self.assertEqual(html.count('data-sequence="item"'), 2)
        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)

        bound_form = Form(QueryDict(""))
        self.assertFalse(bound_form.is_valid())

    def test_callable_initial_is_evaluated_for_unbound_forms(self):
        calls = []

        def initial():
            calls.append(None)
            return [1]

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), initial=initial)

        html = Form().as_p()

        self.assertTrue(calls)
        self.assertIn('value="1"', html)

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_localize_propagates_to_child_cleaning_and_rendering(self):
        field = nestingdolls.ListField(forms.DecimalField(), localize=True)

        self.assertTrue(field.localize)
        self.assertTrue(field.child_field.localize)
        self.assertTrue(field.widget.child_widget.is_localized)
        with translation.override("de"):
            self.assertEqual(field.clean(["1,5"]), [Decimal("1.5")])

    def test_disabled_fields_render_disabled_and_ignore_submitted_data(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, initial=[1]
            )

        form = Form(QueryDict("values=9"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])
        self.assertIn(" disabled", form.as_p())

    def test_show_hidden_initial_and_has_changed(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                initial=[1, 2],
                show_hidden_initial=True,
            )
        unchanged = Form(
            QueryDict("values=1&values=2&initial-values=1&initial-values=2")
        )
        changed = Form(
            QueryDict("values=1&values=3&initial-values=1&initial-values=2")
        )

        self.assertFalse(unchanged.has_changed())
        self.assertTrue(changed.has_changed())
        self.assertEqual(unchanged.as_p().count('name="initial-values"'), 2)

    def test_has_changed_normalizes_child_values_and_set_order(self):
        list_field = nestingdolls.ListField(forms.IntegerField())
        set_field = nestingdolls.SetField(forms.IntegerField())

        self.assertFalse(list_field.has_changed([1, 2], ["1", "2"]))
        self.assertTrue(list_field.has_changed([1, 2], ["1", "3"]))
        self.assertFalse(set_field.has_changed({1, 2}, ["2", "1"]))
        self.assertTrue(list_field.has_changed([1], "not-a-sequence"))

    def test_template_name_and_bound_field_class(self):
        class CustomBoundField(BoundField):
            pass

        class Template:
            def render(self, context, request=None):
                return f"custom:{context['field'].name}"

        class Renderer(BaseRenderer):
            def __init__(self):
                self.template_names = []

            def get_template(self, template_name):
                self.template_names.append(template_name)
                return Template()

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                template_name="sequence-field.html",
                bound_field_class=CustomBoundField,
            )
        renderer = Renderer()
        form = Form(renderer=renderer)

        self.assertIsInstance(form["values"], CustomBoundField)
        self.assertEqual(form["values"].as_field_group(), "custom:values")
        self.assertEqual(renderer.template_names, ["sequence-field.html"])


class SequenceFieldWidgetTestCase(SimpleTestCase):
    def test_form_shortcuts_keep_the_widget_markup_valid(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_num=2)

        form = Form()

        rendered = {
            "p": form.as_p(),
            "div": form.as_div(),
            "table": form.as_table(),
        }

        for html in rendered.values():
            self.assertIn('id="id_values_0"', html)
            self.assertIn('id="id_values_1"', html)
            self.assertNotIn("sequence-item", html)
            self.assertNotIn("<pre", html)
            self.assertNotIn("<hr", html)

        self.assertIn("<label>Values:</label>", rendered["p"])
        self.assertNotIn("<fieldset", rendered["p"])
        self.assertIn("<fieldset", rendered["div"])
        self.assertIn("<legend>Values:</legend>", rendered["div"])
        self.assertIn("<tr", rendered["table"])
        self.assertIn("<label>Values:</label>", rendered["table"])

    def test_empty_initial_sequences_render_the_minimum_controls(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_num=2)

        form = Form(initial={"values": []})

        html = form.as_p()
        self.assertIn('id="id_values_0"', html)
        self.assertIn('id="id_values_1"', html)

    def test_multipart_child_fields_read_uploaded_files(self):
        class Form(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), min_num=2)

        files = MultiValueDict(
            {
                "values": [
                    SimpleUploadedFile("one.txt", b"one"),
                    SimpleUploadedFile("two.txt", b"two"),
                ]
            }
        )
        form = Form(data=QueryDict(""), files=files)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            [uploaded_file.name for uploaded_file in form.cleaned_data["values"]],
            ["one.txt", "two.txt"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
