"""Contracts that both composite families share.

Every test here exercises ``CompositeWidget``/``CompositeBoundField`` in
``_shared.py`` rather than either field, so each one runs against both
``ListField`` and ``DictField``. A behaviour that only one family has belongs in
``test_listfield.py`` or ``test_dictfield.py``.
"""

from __future__ import annotations

import copy
import dataclasses
import unittest
from collections.abc import Callable

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import QueryDict
from django.test import SimpleTestCase
from django.test.utils import setup_test_environment, teardown_test_environment
from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

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


HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


class PointForm(forms.Form):
    a = forms.IntegerField()
    label = forms.CharField(required=False)


@dataclasses.dataclass(frozen=True)
class Family:
    """One composite family, described by what a shared test needs from it."""

    name: str
    field_name: str
    widget_class: type[nestingdolls.CompositeWidget]
    bound_field_class: type
    make_field: Callable[..., forms.Field]
    # A submission with one valid child, spelled with the dot separator.
    dotted_data: dict[str, str]
    # The same submission as a QueryDict, plus a forged value under the field
    # name itself.
    forged_query: str
    # What the forged submission must still clean to.
    forged_cleaned: object
    # A direct Python value a programmer would pass, and its cleaned form.
    direct_data: dict[str, object]
    direct_cleaned: object
    # A submission whose only child is invalid.
    invalid_data: dict[str, str]
    invalid_message: str
    # An initial equal to ``dotted_data`` once the child field converts it.
    unchanged_initial: object


FAMILIES = (
    Family(
        name="sequence",
        field_name="values",
        widget_class=nestingdolls.SequenceWidget,
        bound_field_class=nestingdolls.SequenceBoundField,
        make_field=lambda **kwargs: nestingdolls.ListField(
            forms.IntegerField(), **kwargs
        ),
        dotted_data={"values.0": "1"},
        forged_query=(
            "values=forged&values-0=1&values-1=2&"
            f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0"
        ),
        forged_cleaned=[1, 2],
        direct_data={"values": ["3", "4"]},
        direct_cleaned=[3, 4],
        invalid_data={"values.0": "bad"},
        invalid_message="Enter a whole number.",
        unchanged_initial=[1],
    ),
    Family(
        name="mapping",
        field_name="point",
        widget_class=nestingdolls.MappingWidget,
        bound_field_class=nestingdolls.MappingBoundField,
        make_field=lambda **kwargs: nestingdolls.DictField(PointForm, **kwargs),
        dotted_data={"point.a": "1"},
        forged_query="point=forged&point-a=1&point-label=kept",
        forged_cleaned={"a": 1, "label": "kept"},
        direct_data={"point": {"a": "3", "label": "direct"}},
        direct_cleaned={"a": 3, "label": "direct"},
        invalid_data={"point.a": "bad"},
        invalid_message="Enter a whole number.",
        unchanged_initial={"a": 1},
    ),
)


def form_class_for(family: Family, **kwargs: object) -> type[forms.Form]:
    """Return a Form with one field of this family, named after the family."""
    return type(
        "Form",
        (forms.Form,),
        {family.field_name: family.make_field(**kwargs)},
    )


class SharedCompositeTestCase(SimpleTestCase):
    def test_normalizes_bound_data_once(self):
        """One render normalizes one form's bound data one time."""
        for family in FAMILIES:
            with self.subTest(family=family.name):
                counter = {"normalizations": 0}

                class CountingKeys(family.widget_class.Keys):
                    def normalized(self, data, name, _counter=counter):
                        _counter["normalizations"] += 1
                        return super().normalized(data, name)

                widget_class = type(
                    "CountingWidget", (family.widget_class,), {"Keys": CountingKeys}
                )
                form_class = form_class_for(family, widget=widget_class)

                form = form_class(family.dotted_data)

                self.assertIs(form.is_valid(), True, form.errors)
                self.assertIs(form.has_changed(), True)
                form.as_p()
                self.assertEqual(counter["normalizations"], 1)

    def test_render_state_is_not_shared_between_form_instances(self):
        """Errors and per-render state of one form never reach another."""
        for family in FAMILIES:
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
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, required=False)

                # The child field converts "1" to 1, so a raw `==` on the
                # submitted strings would call this changed.
                unchanged = form_class(
                    family.dotted_data,
                    initial={family.field_name: family.unchanged_initial},
                )
                changed = form_class(
                    family.dotted_data,
                    initial={family.field_name: family.direct_cleaned},
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

        for family in FAMILIES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, validators=[reject])

                form = form_class(QueryDict(family.forged_query))

                self.assertIs(form.is_valid(), False)
                self.assertEqual(list(form[family.field_name].errors), ["Outer error."])
                self.assertEqual(form.as_p().count("Outer error."), 1)

    def test_field_errors_hide_child_item_errors(self):
        """The outer field shows its own errors only.

        The subform or the row renders an item error beside the input that
        produced it, so repeating it on the outer field would show the user the
        same problem twice. ``_all_errors`` keeps the unfiltered list for the
        row and subform machinery.
        """
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form = form_class_for(family, required=False)(family.invalid_data)

                self.assertIs(form.is_valid(), False)
                bound_field = form[family.field_name]

                self.assertEqual(list(bound_field.errors), [])
                self.assertIn(family.invalid_message, list(bound_field._all_errors))
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

        for family in FAMILIES:
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

    def test_forged_field_name_key_does_not_discard_child_input(self):
        """A stray control named after the field cannot wipe the real input.

        A ``QueryDict`` is the browser's own data. A submit button, or a forged
        key, sharing the field's name must not outrank the flat child keys.
        """
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, required=False)

                form = form_class(QueryDict(family.forged_query))

                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(
                    form.cleaned_data[family.field_name], family.forged_cleaned
                )

    def test_programmer_data_keeps_direct_value_precedence(self):
        """Data a programmer built keeps direct-wins precedence."""
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form_class = form_class_for(family, required=False)

                form = form_class(family.direct_data)

                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(
                    form.cleaned_data[family.field_name], family.direct_cleaned
                )

    def test_custom_bound_field_keeps_error_integration(self):
        """A bound-field subclass keeps the family's error rendering."""
        for family in FAMILIES:
            with self.subTest(family=family.name):
                custom = type("CustomBoundField", (family.bound_field_class,), {})
                form_class = form_class_for(family, bound_field_class=custom)

                form = form_class(family.invalid_data)

                self.assertIs(form.is_valid(), False)
                self.assertIsInstance(form[family.field_name], custom)
                self.assertIn(family.invalid_message, form.as_p())

    def test_bound_field_rejects_a_foreign_field(self):
        """Direct misuse raises even when asserts are stripped."""
        for family in FAMILIES:
            with (
                self.subTest(family=family.name),
                self.assertRaisesRegex(TypeError, "field must be a"),
            ):
                family.bound_field_class(forms.Form(), forms.CharField(), "value")

    def test_widget_uses_helper_specific_wrapper_markup(self):
        """Each form helper selects the widget template of the same layout."""
        for family in FAMILIES:
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
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()

                table_html = form.as_table()
                p_html = form.as_p()

                self.assertIn(f'<span\n  data-widget="{family.name}"', p_html)
                self.assertIn(f'<div\n  data-widget="{family.name}"', table_html)

    def test_default_render_uses_the_layout_django_will_use(self):
        """``{{ form }}`` picks the layout of the form's own template."""
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()

                # BaseForm.template_name defaults to django/forms/div.html.
                self.assertIn(f'<div\n  data-widget="{family.name}"', str(form))

    def test_child_widgets_are_not_shared_between_form_instances(self):
        """A deep-copied composite widget never shares a cached child widget.

        ``Widget.__deepcopy__`` is a shallow copy, so a warmed child cache would
        be shared by every form. ``ClearableFileInput`` mutates its widget while
        reading data, which makes that sharing a cross-request bug.
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
        """A widget subclass adds to the family's media instead of replacing it.

        Both composite widgets define ``media``, so ``MediaDefiningClass`` never
        installs its own property for them and the merge has to happen here.
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
        for family in FAMILIES:
            with self.subTest(family=family.name):
                form = form_class_for(family)()
                widget = copy.deepcopy(form.fields[family.field_name].widget)
                widget.template_name = "app/{custom}.html"

                self.assertEqual(widget.template_name, "app/{custom}.html")

    @HYPOTHESIS_SETTINGS
    @given(
        data=st.dictionaries(
            st.text(max_size=12),
            st.text(max_size=8),
            max_size=8,
        )
    )
    def test_normalization_is_total_bounded_idempotent_and_prefix_local(self, data):
        """Arbitrary keys cannot escape the canonical bounded parser contract."""
        for family in FAMILIES:
            name = family.field_name
            widget = form_class_for(family, required=False)().fields[name].widget

            normalized = widget.keys.normalized(data, name)
            # Idempotent: normalizing the result changes nothing.
            self.assertEqual(widget.keys.normalized(normalized, name), normalized)
            # Prefix-local: every key belongs to this field.
            for key in normalized:
                self.assertIs(key == name or key.startswith(f"{name}-"), True, key)
            # Prefix-local: keys of another field cannot change the result.
            unrelated = {f"other:{key}": value for key, value in data.items()}
            self.assertEqual(widget.keys.normalized(data | unrelated, name), normalized)
            # Total: neither extraction nor rendering may raise.
            widget.value_from_datadict(data, {}, name)
            widget.value_omitted_from_data(data, {}, name)

    def test_every_exported_name_is_importable(self):
        """``__all__`` and the module agree, so no export is a dangling name."""
        for name in nestingdolls.__all__:
            with self.subTest(name=name):
                self.assertIs(hasattr(nestingdolls, name), True, name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
