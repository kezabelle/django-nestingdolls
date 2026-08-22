"""Reusable test helpers for composite-field cohorts."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, Self
from urllib.parse import urlencode

from django.forms.renderers import DjangoTemplates
from django.forms.utils import ErrorList
from django.http import QueryDict
from django.template import Context, Template
from django.test import SimpleTestCase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from django import forms
    from django.forms.boundfield import BoundField
    from django.forms.renderers import BaseRenderer
    from django.http import HttpResponseBase


class HasRenderer(Protocol):
    """Expose the renderer inherited from an enclosing form."""

    renderer: BaseRenderer


class MarkedErrorList(ErrorList):
    """Tag every rendered error list, the way a project's own class would."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("error_class", "my-errors")
        super().__init__(*args, **kwargs)


class TestQueryDict(QueryDict):
    """Construct immutable query dictionaries from test submission mappings."""

    @classmethod
    def from_dict(cls, data: Mapping[str, str | Sequence[str]]) -> Self:
        """Encode mapping values as a browser form submission."""
        return cls(urlencode(data, doseq=True))


class MarkedRenderer(DjangoTemplates):
    """Stand in for a project renderer, identified by object identity."""


class CompositeFieldTestCase(SimpleTestCase):
    """Provide composite-field assertions shared by multiple behavior cohorts."""

    def assertFormValid(self, form: forms.BaseForm) -> None:
        """Assert that validating a bound form succeeds."""
        self.assertIs(form.is_valid(), True, form.errors)

    def assertFormInvalid(self, form: forms.BaseForm) -> None:
        """Assert that validating a bound form fails."""
        self.assertIs(form.is_valid(), False)

    def assertFormErrorCode(
        self, form: forms.BaseForm, field_name: str, expected: str
    ) -> None:
        """Assert the first validation error on a form field has the expected code."""
        self.assertEqual(form.errors.as_data()[field_name][0].code, expected)

    def assertBoundFieldErrors(
        self, form: forms.BaseForm, field_name: str, expected: Sequence[str]
    ) -> None:
        """Assert the errors exposed directly by a bound field."""
        self.assertEqual(list(form[field_name].errors), expected)

    def assertJSONResponse(self, response: HttpResponseBase, expected: object) -> None:
        """Assert a successful response has exactly the expected JSON value."""
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, expected)

    def assertJSONResponseContains(
        self, response: HttpResponseBase, expected: Mapping[str, object]
    ) -> None:
        """Assert a successful response JSON object contains expected properties."""
        self.assertLessEqual(expected.items(), response.json().items())

    def assertRenderedMessageCount(
        self, html: str, message: str, count: int = 1
    ) -> None:
        """Assert that rendered markup contains a validation message exactly count times."""
        self.assertEqual(html.count(message), count)

    def assertSingleSubwidgetMatchesBoundField(
        self,
        form: forms.BaseForm,
        field_name: str,
        submitted_value: str,
        error_message: str,
    ) -> None:
        """Assert one rendered subwidget preserves submitted value and error markup."""
        subwidgets = form[field_name].subwidgets
        self.assertEqual(len(subwidgets), 1)
        rendered = str(subwidgets[0])
        self.assertEqual(rendered.count(submitted_value), 1)
        self.assertRenderedMessageCount(rendered, error_message)
        self.assertEqual(rendered, str(form[field_name]))

    def assertErrorReferenceResolves(self, html: str, error_id: str) -> None:
        """Assert an error element exists and is referenced by aria-describedby."""
        self.assertIn(f'id="{error_id}"', html)
        escaped_error_id = re.escape(error_id)
        self.assertRegex(
            html, rf'aria-describedby="(?:[^"]* )?{escaped_error_id}(?: [^"]*)?"'
        )

    def assertErrorElementIsAbsent(self, html: str, error_id: str) -> None:
        """Assert rendered markup has no error element with the given identifier."""
        self.assertNotIn(f'id="{error_id}"', html)

    def assertCompositeChildrenUseRenderer(
        self, children: Iterable[HasRenderer], renderer: BaseRenderer
    ) -> None:
        """Assert every composite child inherits the enclosing form renderer."""
        children = list(children)
        self.assertNotEqual(children, [])
        for child in children:
            self.assertIs(child.renderer, renderer)

    def assertCssClassesMatchBaseline(
        self,
        composite: BoundField,
        baseline: BoundField,
        extra_classes: str | Iterable[str] | None = None,
    ) -> None:
        """Assert composite CSS classes are unique and match an ordinary field."""
        composite_classes = composite.css_classes(extra_classes).split()
        baseline_classes = baseline.css_classes(extra_classes).split()
        self.assertEqual(sorted(composite_classes), sorted(set(composite_classes)))
        self.assertEqual(sorted(composite_classes), sorted(baseline_classes))

    def assertOuterValidatorErrorForForm(
        self, form: forms.BaseForm, field_name: str
    ) -> None:
        """Assert an outer validator error remains form-visible and rendered once."""
        self.assertFormInvalid(form)
        self.assertFormError(form, field_name, ["Outer error."])
        self.assertRenderedMessageCount(form.as_p(), "Outer error.")

    def assertChildErrorsHiddenForForm(
        self, form: forms.BaseForm, field_name: str, message: str
    ) -> None:
        """Assert child errors stay off the bound field but remain in form errors."""
        self.assertFormInvalid(form)
        self.assertBoundFieldErrors(form, field_name, [])
        self.assertIn(message, list(form.errors[field_name]))
        self.assertIs(form[field_name].errors, form[field_name].errors)

    def assertManualVisibleFieldsRenderMessageOnce(
        self, form: forms.BaseForm, message: str
    ) -> None:
        """Assert manually rendered visible fields include a child error once."""
        self.assertFormInvalid(form)
        html = Template(
            "{% for field in form.visible_fields %}"
            "{{ field.errors }}{{ field.label_tag }}{{ field }}"
            "{% endfor %}"
        ).render(Context({"form": form}))
        self.assertRenderedMessageCount(html, message)

    def assertCustomBoundFieldErrorForForm(
        self,
        form: forms.BaseForm,
        field_name: str,
        expected_type: type[BoundField],
        message: str,
    ) -> None:
        """Assert a custom bound field retains its type and renders its error."""
        self.assertFormInvalid(form)
        self.assertIsInstance(form[field_name], expected_type)
        self.assertRenderedMessageCount(form.as_p(), message)

    def assertRenderStateIsolatedForForms(
        self, bound: forms.BaseForm, fresh: forms.BaseForm, field_name: str
    ) -> None:
        """Assert rendering an invalid form leaves a separate fresh form pristine."""
        self.assertFormInvalid(bound)
        bound_html = bound.as_p()
        bound_widget = bound.fields[field_name].widget
        fresh_widget = fresh.fields[field_name].widget
        fresh_html = fresh.as_p()

        self.assertIn("errorlist", bound_html)
        self.assertIsNot(fresh_widget, bound_widget)
        self.assertNotIn("errorlist", fresh_html)
        self.assertNotIn("bad", fresh_html)

    def assertChildChangeDetection(
        self, unchanged: forms.BaseForm, changed: forms.BaseForm
    ) -> None:
        """Assert child normalization drives unchanged and changed form states."""
        self.assertIs(unchanged.has_changed(), False)
        self.assertIs(changed.has_changed(), True)

    def assertCleanedOutputCleansAgain(
        self, field: forms.Field, submitted_value: object
    ) -> None:
        """Assert a field accepts its normalized output as a later input."""
        once = field.clean(submitted_value)
        self.assertEqual(field.clean(once), once)

    def assertRenderMethodUsesWidgetTemplate(
        self, render: Callable[[], str], template: str, widget_name: str
    ) -> None:
        """Assert a form rendering method selects its widget template and markup."""
        with self.assertTemplateUsed(template):
            html = render()
        self.assertIn(f'data-widget="{widget_name}"', html)

    def assertSequentialRendersForForm(
        self, form: forms.BaseForm, widget_name: str
    ) -> None:
        """Assert sequential table and paragraph renders retain their own wrappers."""
        table_html = form.as_table()
        paragraph_html = form.as_p()
        self.assertIn(f'<span\n  data-widget="{widget_name}"', paragraph_html)
        self.assertIn(f'<div\n  data-widget="{widget_name}"', table_html)

    def assertChildErrorMarkupUsesErrorClass(
        self, form: forms.BaseForm, field_name: str
    ) -> None:
        """Assert child error markup uses the form's configured error-list class."""
        self.assertFormInvalid(form)
        self.assertIn('class="errorlist my-errors"', str(form[field_name]))

    def assertMultipleOuterMessagesStayVisible(
        self, form: forms.BaseForm, field_name: str
    ) -> None:
        """Assert all outer validator messages remain attached to the field."""
        self.assertFormInvalid(form)
        self.assertFormError(form, field_name, ["First outer.", "Second outer."])

    def assertFormRendererReachesChildren(
        self,
        form: forms.BaseForm,
        field_name: str,
        child_forms: Callable[[BoundField], Iterable[HasRenderer]],
    ) -> None:
        """Assert a form renderer propagates to every supplied composite child."""
        self.assertFormInvalid(form)
        self.assertCompositeChildrenUseRenderer(
            child_forms(form[field_name]), form.renderer
        )

    def assertChildOnlyFailureMarksField(
        self, form: forms.BaseForm, field: BoundField, baseline: BoundField
    ) -> None:
        """Assert a child-only failure gives its composite field ordinary error CSS."""
        self.assertFormInvalid(form)
        self.assertBoundFieldErrors(form, field.name, [])
        self.assertNotEqual(list(form.errors[field.name]), [])
        self.assertCssClassesMatchBaseline(field, baseline)
        for extra in ("mine yours", ["mine", "yours"]):
            with self.subTest(extra=extra):
                self.assertCssClassesMatchBaseline(field, baseline, extra)
        self.assertRenderedMessageCount(form.as_div(), "has-error", 2)
