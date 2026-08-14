"""Tests shared by sequence and mapping fields.

Each test runs with ``ListField`` and ``DictField``. Tests for one field
family belong in its own test module.
"""

from __future__ import annotations

import copy
import dataclasses
import unittest
from typing import TYPE_CHECKING, ClassVar

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

if TYPE_CHECKING:
    from collections.abc import Callable

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


@dataclasses.dataclass(frozen=True)
class CompositeCase:
    """One composite family, described by what a shared test needs from it."""

    name: str
    field_name: str
    widget_class: type[nestingdolls.CompositeWidget]
    bound_field_class: type
    make_field: Callable[..., forms.Field]
    # A submission with one valid child in Django's prefixed-key grammar.
    prefixed_data: dict[str, str]
    # The same submission in a repeated-key mapping, plus a forged exact key.
    forged_query: str
    # A whole value a programmer would pass as Python data, and its cleaned form.
    whole_data: dict[str, object]
    whole_cleaned: object
    # A submission whose only child is invalid.
    invalid_data: dict[str, str]
    invalid_message: str
    # An initial equal to ``prefixed_data`` once the child field converts it.
    unchanged_initial: object


COMPOSITE_CASES = (
    CompositeCase(
        name="sequence",
        field_name="values",
        widget_class=nestingdolls.SequenceWidget,
        bound_field_class=nestingdolls.SequenceBoundField,
        make_field=lambda **kwargs: nestingdolls.ListField(
            forms.IntegerField(), **kwargs
        ),
        prefixed_data={
            "values-0": "1",
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
        },
        forged_query=(
            "values=forged&values-0=1&values-1=2&"
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0"
        ),
        whole_data={"values": ["3", "4"]},
        whole_cleaned=[3, 4],
        invalid_data={
            "values-0": "bad",
            f"values-{TOTAL_FORM_COUNT}": "1",
            f"values-{INITIAL_FORM_COUNT}": "0",
        },
        invalid_message="Enter a whole number.",
        unchanged_initial=[1],
    ),
    CompositeCase(
        name="mapping",
        field_name="point",
        widget_class=nestingdolls.MappingWidget,
        bound_field_class=nestingdolls.MappingBoundField,
        make_field=lambda **kwargs: nestingdolls.DictField(PointForm, **kwargs),
        prefixed_data={"point-a": "1"},
        forged_query="point=forged&point-a=1&point-label=kept",
        whole_data={"point": {"a": "3", "label": "whole"}},
        whole_cleaned={"a": 3, "label": "whole"},
        invalid_data={"point-a": "bad"},
        invalid_message="Enter a whole number.",
        unchanged_initial={"a": 1},
    ),
)


def form_class_for(family: CompositeCase, **kwargs: object) -> type[forms.Form]:
    """Return a Form with one field of this family, named after the family."""
    return type(
        "Form",
        (forms.Form,),
        {family.field_name: family.make_field(**kwargs)},
    )


class SharedCompositeTestCase(SimpleTestCase):
    def test_render_state_is_not_shared_between_form_instances(self):
        """Errors and per-render state of one form never reach another."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, required=False)

                bound = form_class(family.invalid_data)
                self.assertIs(bound.is_valid(), False)
                bound_html = bound.as_p()
                bound_widget = bound.fields[family.field_name].widget

                fresh = form_class()
                fresh_widget = fresh.fields[family.field_name].widget
                fresh_html = fresh.as_p()

                self.assertIn("errorlist", bound_html)
                self.assertIsNot(fresh_widget, bound_widget)
                self.assertNotIn("errorlist", fresh_html)
                self.assertNotIn("bad", fresh_html)

    def test_has_changed_uses_child_field_semantics(self):
        """Change detection asks the child field, not ``==`` on raw input."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, required=False)

                # The child field converts "1" to 1.
                # Comparing the raw strings would report a change.
                unchanged = form_class(
                    family.prefixed_data,
                    initial={family.field_name: family.unchanged_initial},
                )
                changed = form_class(
                    family.prefixed_data,
                    initial={family.field_name: family.whole_cleaned},
                )

                self.assertIs(unchanged.has_changed(), False)
                self.assertIs(changed.has_changed(), True)

    def test_outer_item_invalid_validator_error_stays_visible(self):
        """A validator that collides with the child error code is still shown."""

        def reject(value):
            raise ValidationError(
                "Outer error.",
                code="item_invalid",
                params={"index": "0", "message": "outer", "child_code": "outer"},
            )

        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, validators=[reject])

                form = form_class(QueryDict(family.forged_query))

                self.assertIs(form.is_valid(), False)
                self.assertEqual(list(form[family.field_name].errors), ["Outer error."])
                self.assertEqual(form.as_p().count("Outer error."), 1)

    def test_field_errors_hide_child_item_errors(self):
        """The outer field hides child errors.

        The row or subform renders each error beside its input. Showing it again at
        the outer field would duplicate it. ``form.errors`` keeps the unfiltered
        errors for row and subform rendering.
        """
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form = form_class_for(family, required=False)(family.invalid_data)

                self.assertIs(form.is_valid(), False)
                bound_field = form[family.field_name]

                self.assertEqual(list(bound_field.errors), [])
                self.assertIn(
                    family.invalid_message, list(form.errors[family.field_name])
                )
                # A cached_property: a template touching it twice must not
                # rebuild the list.
                self.assertIs(bound_field.errors, bound_field.errors)

    def test_multi_message_field_errors_survive_the_item_filter(self):
        """One stored error carrying several messages keeps all of them.

        The filter compares stored errors, not rendered messages, because
        ``ErrorList.__len__`` counts the latter and ``as_data()`` flattens.
        """

        def reject_with_two_messages(value):
            raise ValidationError(["First outer.", "Second outer."])

        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form_class = form_class_for(
                    family, required=False, validators=[reject_with_two_messages]
                )

                form = form_class(QueryDict(family.forged_query))

                self.assertIs(form.is_valid(), False)
                self.assertEqual(
                    list(form[family.field_name].errors),
                    ["First outer.", "Second outer."],
                )

    def test_whole_values_do_not_depend_on_mapping_type(self):
        """A whole composite value works in ordinary and repeated-key mappings."""
        for family in COMPOSITE_CASES:
            form_class = form_class_for(family, required=False)
            inputs = (
                family.whole_data,
                MultiValueDict(
                    {key: [value] for key, value in family.whole_data.items()}
                ),
            )
            for data in inputs:
                with self.subTest(family=family.name, data_type=type(data).__name__):
                    form = form_class(data)

                    self.assertIs(form.is_valid(), True, form.errors)
                    self.assertEqual(
                        form.cleaned_data[family.field_name], family.whole_cleaned
                    )

    def test_mapping_accepts_declared_prefixed_children_only(self):
        """Dot, bracket, and undeclared mapping keys cannot enter a child form."""

        class Form(forms.Form):
            point = nestingdolls.DictField(PointForm, required=False)

        form = Form(
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

    def test_custom_bound_field_keeps_error_integration(self):
        """A bound-field subclass keeps the family's error rendering."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                custom = type("CustomBoundField", (family.bound_field_class,), {})
                form_class = form_class_for(family, bound_field_class=custom)

                form = form_class(family.invalid_data)

                self.assertIs(form.is_valid(), False)
                self.assertIsInstance(form[family.field_name], custom)
                self.assertIn(family.invalid_message, form.as_p())

    def test_bound_field_rejects_a_foreign_field(self):
        """Misuse raises even when asserts are stripped."""
        for family in COMPOSITE_CASES:
            with (
                self.subTest(family=family.name),
                self.assertRaisesRegex(TypeError, "field must be a"),
            ):
                family.bound_field_class(forms.Form(), forms.CharField(), "value")

    def test_widget_uses_helper_specific_wrapper_markup(self):
        """Each form helper selects the widget template of the same layout."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()

                for layout in ("div", "p", "table", "ul"):
                    template = f"nestingdolls/{family.name}/{layout}.html"
                    with self.subTest(layout=layout):
                        with self.assertTemplateUsed(template):
                            html = getattr(form, f"as_{layout}")()
                        self.assertIn(f'data-widget="{family.name}"', html)

    def test_widget_switches_layout_between_sequential_renders(self):
        """Layout is per render: no render leaks its choice into the next."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()

                table_html = form.as_table()
                p_html = form.as_p()

                self.assertIn(f'<span\n  data-widget="{family.name}"', p_html)
                self.assertIn(f'<div\n  data-widget="{family.name}"', table_html)

    def test_default_render_uses_the_layout_django_will_use(self):
        """``{{ form }}`` picks the layout of the form's own template."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()

                # BaseForm.template_name defaults to django/forms/div.html.
                self.assertIn(f'<div\n  data-widget="{family.name}"', str(form))

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

    def test_custom_template_name_without_a_layout_placeholder_survives(self):
        """A developer's own template name is used verbatim, braces and all."""
        for family in COMPOSITE_CASES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()
                widget = copy.deepcopy(form.fields[family.field_name].widget)
                widget.template_name = "app/{custom}.html"

                self.assertEqual(widget.template_name, "app/{custom}.html")

    def test_every_exported_name_is_importable(self):
        """``__all__`` and the module agree, so no export is a dangling name."""
        for name in nestingdolls.__all__:
            with self.subTest(name=name):
                self.assertIs(hasattr(nestingdolls, name), True, name)


class SharedCompositeStyleParityTestCase(SimpleTestCase):
    """A prefixed-key submission and a whole Python value both bind and clean.

    Each ``CompositeCase`` already carries a prefixed-key fixture (``prefixed_data``)
    and a whole-value fixture (``whole_data``/``whole_cleaned``). Neither
    style is a fallback for the other: both must validate and clean on their
    own terms, for both the sequence and the mapping family.
    """

    def test_sequence_prefixed_data_cleans_its_one_row(self):
        family = COMPOSITE_CASES[0]
        form = form_class_for(family)(family.prefixed_data)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data[family.field_name], [1])

    def test_sequence_whole_data_cleans_every_row(self):
        family = COMPOSITE_CASES[0]
        form = form_class_for(family)(family.whole_data)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data[family.field_name], family.whole_cleaned)

    def test_mapping_prefixed_data_cleans_its_one_child(self):
        family = COMPOSITE_CASES[1]
        form = form_class_for(family)(family.prefixed_data)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data[family.field_name], {"a": 1, "label": ""})

    def test_mapping_whole_data_cleans_every_child(self):
        family = COMPOSITE_CASES[1]
        form = form_class_for(family)(family.whole_data)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data[family.field_name], family.whole_cleaned)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
