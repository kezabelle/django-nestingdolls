"""Reusable assertions for shared composite-field test cohorts."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from django import forms
from django.forms.renderers import DjangoTemplates
from django.forms.utils import ErrorList
from django.http import QueryDict
from django.template import Context, Template

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = (
    "CompositeErrorDisplayAssertions",
    "CompositeRenderingAssertions",
    "MarkedErrorList",
    "MarkedRenderer",
)


class MarkedErrorList(ErrorList):
    """Tag every rendered error list, the way a project's own class would."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("error_class", "my-errors")
        super().__init__(*args, **kwargs)


class MarkedRenderer(DjangoTemplates):
    """Stand in for a project renderer, identified by object identity."""


class CompositeErrorDisplayAssertions:
    """Assert errors remain visible through composite bound-field rendering."""

    def assertOuterValidatorErrorStaysVisible(
        self,
        form_class: type[forms.Form],
        field_name: str,
        forged_query: str,
    ) -> None:
        form = form_class(QueryDict(forged_query))

        self.assertIs(form.is_valid(), False)
        self.assertEqual(list(form[field_name].errors), ["Outer error."])
        self.assertEqual(form.as_p().count("Outer error."), 1)

    def assertMultipleOuterMessagesStayVisible(
        self,
        form_class: type[forms.Form],
        field_name: str,
        forged_query: str,
    ) -> None:
        form = form_class(QueryDict(forged_query))

        self.assertIs(form.is_valid(), False)
        self.assertEqual(
            list(form[field_name].errors), ["First outer.", "Second outer."]
        )

    def assertBoundFieldHidesChildErrors(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
        invalid_message: str,
    ) -> None:
        form = form_class(invalid_data)

        self.assertIs(form.is_valid(), False)
        bound_field = form[field_name]

        self.assertEqual(list(bound_field.errors), [])
        self.assertIn(invalid_message, list(form.errors[field_name]))
        self.assertIs(bound_field.errors, bound_field.errors)

    def assertManualFieldRenderingIncludesChildErrors(
        self,
        form_class: type[forms.Form],
        invalid_data: dict[str, str],
        invalid_message: str,
    ) -> None:
        form = form_class(invalid_data)

        self.assertIs(form.is_valid(), False)
        html = Template(
            "{% for field in form.visible_fields %}"
            "{{ field.errors }}{{ field.label_tag }}{{ field }}"
            "{% endfor %}"
        ).render(Context({"form": form}))

        self.assertEqual(html.count(invalid_message), 1)

    def assertCustomBoundFieldRendersError(
        self,
        form_class: type[forms.Form],
        bound_field_class: type,
        field_name: str,
        invalid_data: dict[str, str],
        invalid_message: str,
    ) -> None:
        form = form_class(invalid_data)

        self.assertIs(form.is_valid(), False)
        self.assertIsInstance(form[field_name], bound_field_class)
        self.assertIn(invalid_message, form.as_p())

    def assertForeignFieldIsRejected(self, bound_field_class: type) -> None:
        with self.assertRaisesRegex(TypeError, "field must be a"):
            bound_field_class(forms.Form(), forms.CharField(), "value")


class CompositeRenderingAssertions:
    """Assert composite widgets render without leaking form-specific state."""

    def assertRenderStateIsIsolated(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
    ) -> None:
        bound = form_class(invalid_data)
        self.assertIs(bound.is_valid(), False)
        bound_html = bound.as_p()
        bound_widget = bound.fields[field_name].widget

        fresh = form_class()
        fresh_widget = fresh.fields[field_name].widget
        fresh_html = fresh.as_p()

        self.assertIn("errorlist", bound_html)
        self.assertIsNot(fresh_widget, bound_widget)
        self.assertNotIn("errorlist", fresh_html)
        self.assertNotIn("bad", fresh_html)

    def assertChangeDetectionUsesChildSemantics(
        self,
        form_class: type[forms.Form],
        field_name: str,
        prefixed_data: dict[str, str],
        unchanged_initial: object,
        changed_initial: object,
    ) -> None:
        unchanged = form_class(prefixed_data, initial={field_name: unchanged_initial})
        changed = form_class(prefixed_data, initial={field_name: changed_initial})

        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def assertWrapperMarkup(
        self,
        form_class: type[forms.Form],
        form_method: str,
        template: str,
        widget_name: str,
    ) -> None:
        form = form_class()
        with self.assertTemplateUsed(template):
            html = getattr(form, form_method)()
        self.assertIn(f'data-widget="{widget_name}"', html)

    def assertSequentialRendersUseOwnLayout(
        self, form_class: type[forms.Form], widget_name: str
    ) -> None:
        form = form_class()

        table_html = form.as_table()
        p_html = form.as_p()

        self.assertIn(f'<span\n  data-widget="{widget_name}"', p_html)
        self.assertIn(f'<div\n  data-widget="{widget_name}"', table_html)

    def assertDefaultRenderUsesDivLayout(
        self, form_class: type[forms.Form], widget_name: str
    ) -> None:
        self.assertIn(f'<div\n  data-widget="{widget_name}"', str(form_class()))

    def assertLiteralTemplateNameSurvives(
        self, form_class: type[forms.Form], field_name: str
    ) -> None:
        widget = copy.deepcopy(form_class().fields[field_name].widget)
        widget.template_name = "app/{custom}.html"

        self.assertEqual(widget.template_name, "app/{custom}.html")

    def assertFormErrorClassReachesChildren(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
    ) -> None:
        form = form_class(invalid_data, error_class=MarkedErrorList)

        self.assertIs(form.is_valid(), False)
        self.assertIn('class="errorlist my-errors"', str(form[field_name]))

    def assertFormRendererReachesChildren(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
        child_forms: Callable[[forms.BoundField], list[forms.BaseForm]],
    ) -> None:
        renderer = MarkedRenderer()
        form = form_class(invalid_data, renderer=renderer)

        self.assertIs(form.is_valid(), False)
        children = child_forms(form[field_name])
        self.assertNotEqual(children, [])
        for child in children:
            self.assertIs(child.renderer, renderer)

    def assertChildOnlyFailureMarksTheField(
        self,
        form_class: type[forms.Form],
        field_name: str,
        invalid_data: dict[str, str],
    ) -> None:
        """Assert a composite that failed only in a child looks invalid.

        ``form_class`` declares ``error_css_class``, ``required_css_class``,
        the composite under ``field_name``, and a required ``plain``
        ``CharField`` that supplies the plain-Django baseline.
        """
        form = form_class({**invalid_data, "plain": ""})

        self.assertIs(form.is_valid(), False)
        # The composite failed only through a child, so its own error list
        # stays empty while the form still records the failure.
        self.assertEqual(list(form[field_name].errors), [])
        self.assertNotEqual(list(form.errors[field_name]), [])
        self.assertEqual(
            sorted(form[field_name].css_classes().split()),
            sorted(form["plain"].css_classes().split()),
        )
        # ``BoundField.css_classes`` accepts a space-separated string or an
        # iterable, and de-duplicates through a set. Both shapes must keep the
        # caller's classes and gain the error class exactly once.
        for extra in ("mine yours", ["mine", "yours"]):
            with self.subTest(extra=extra):
                classes = form[field_name].css_classes(extra).split()
                self.assertEqual(sorted(classes), sorted(set(classes)))
                self.assertEqual(
                    sorted(classes),
                    sorted(form["plain"].css_classes(extra).split()),
                )
        self.assertEqual(form.as_div().count("has-error"), 2)

    def assertLateAddErrorMarksTheField(
        self,
        form_class: type[forms.Form],
        field_name: str,
        valid_data: dict[str, str],
    ) -> None:
        """Assert ``css_classes`` follows an error recorded after a first read.

        Django's ``BoundField.errors`` is a plain property, so a view that
        calls ``form.add_error`` after something already rendered the field
        still gets the error class. A composite must not cache its way out of
        that. ``form_class`` supplies the same ``plain`` baseline field.
        """
        form = form_class({**valid_data, "plain": "ok"})

        self.assertIs(form.is_valid(), True, form.errors)
        composite, plain = form[field_name], form["plain"]
        self.assertEqual(composite.css_classes(), plain.css_classes())

        form.add_error(field_name, "Late outer error.")
        form.add_error("plain", "Late outer error.")

        self.assertIn("has-error", plain.css_classes())
        self.assertEqual(
            sorted(composite.css_classes().split()),
            sorted(plain.css_classes().split()),
        )
