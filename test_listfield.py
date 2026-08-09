import json
import tracemalloc
import unittest
from collections import deque
from datetime import datetime
from decimal import Decimal

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
)
from django.http import JsonResponse, QueryDict
from django.test import Client, SimpleTestCase, override_settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import path
from django.utils import translation
from django.utils.datastructures import MultiValueDict
from hypothesis import HealthCheck, assume, example, given
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
    # Undo the global template instrumentation after these unittest-based tests.
    teardown_test_environment()


HYPOTHESIS_SETTINGS = hypothesis_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
SMALL_INTEGERS = st.integers(min_value=-5, max_value=5)
SMALL_INTEGER_LISTS = st.lists(SMALL_INTEGERS, max_size=5)
JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-5, max_value=5)
    | st.text(max_size=5)
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=8,
)
DATETIME_ROWS = st.lists(
    st.datetimes(timezones=st.none()).map(lambda value: value.replace(microsecond=0)),
    max_size=4,
)
SET_COLLECTIONS = (nestingdolls.SetField, nestingdolls.FrozenSetField)


class _SequenceRootSubmissionLimitForm(forms.Form):
    outer = nestingdolls.ListField(
        nestingdolls.ListField(
            forms.BooleanField(required=False),
            max_length=10,
            absolute_max=10,
        ),
        max_length=10,
        absolute_max=10,
    )


def _sequence_root_submission_limit_view(request):
    form = _SequenceRootSubmissionLimitForm(request.POST)
    return JsonResponse(
        {
            "valid": form.is_valid(),
            "errors": {
                name: [error.code for error in errors]
                for name, errors in form.errors.as_data().items()
            },
        }
    )


urlpatterns = [
    path(
        "sequence-root-submission-limit/",
        _sequence_root_submission_limit_view,
    ),
]
SET_CHILD_KINDS = ("integer", "tuple", "splitdatetime")


class SequenceFieldTestCase(SimpleTestCase):
    field_class = nestingdolls.ListField
    collection_class = list

    def assert_cleaned_values(self, cleaned_data, values):
        self.assertIsInstance(cleaned_data, self.collection_class)
        self.assertEqual(cleaned_data, self.collection_class(values))

    def test_submitted_row_spellings_clean_to_the_same_value(self):
        """Every supported submitted row spelling cleans to the same value."""
        field_class = self.field_class

        class Form(forms.Form):
            values = field_class(forms.IntegerField())

        managed = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2&values-2=3"
            )
        )
        self.assertIs(managed.is_valid(), True, managed.errors)
        self.assert_cleaned_values(managed.cleaned_data["values"], [1, 2, 3])

        for data, expected in (
            ({"values": ["1", "2", "3"]}, [1, 2, 3]),
            ({"values-0": "1", "values-1": "2", "values-2": "3"}, [1, 2, 3]),
            ({"values.0": "1", "values.1": "2", "values.2": "3"}, [1, 2, 3]),
            ({"values[0]": "1", "values[1]": "2", "values[2]": "3"}, [1, 2, 3]),
            # A leading zero names the same row as its bare index.
            ({"values-01": "2"}, [2]),
        ):
            with self.subTest(data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assert_cleaned_values(form.cleaned_data["values"], expected)

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        # A sparse dot or bracket row needs no explicit management data either.
        for data in ({"values.2": "3"}, {"values[2]": "3"}):
            with self.subTest(data=data):
                form = OptionalForm(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [3])

        class TextForm(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(required=False), required=False
            )

        for data in ({"values-0": "x"}, {"values.0": "x"}, {"values[0]": "x"}):
            with self.subTest(data=data):
                self.assertEqual(TextForm(data)["values"].value(), ["x"])

        class JsonForm(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        for data in (
            {"values": ["null"]},
            {"values-0": "null"},
            {"values.0": "null"},
            {"values[0]": "null"},
        ):
            with self.subTest(data=data):
                form = JsonForm(data)
                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertIsInstance(error, nestingdolls.ItemValidationError)
                self.assertEqual(error.code, "item_invalid")
                self.assertEqual(error.params["child_code"], "required")

    def test_initial_row_spellings_are_normalized(self):
        """Every supported initial row spelling normalizes to the same rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        for initial in (
            {"values": [1, 2, 3]},
            {"values-0": 1, "values-1": 2, "values-2": 3},
            {"values.0": 1, "values.1": 2, "values.2": 3},
            {"values[0]": 1, "values[1]": 2, "values[2]": 3},
        ):
            with self.subTest(initial=initial):
                self.assertEqual(Form(initial=initial)["values"].value(), [1, 2, 3])

        class FieldInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial={"values[0]": 1, "values[1]": 2}
            )

        self.assertEqual(FieldInitialForm()["values"].value(), [1, 2])

        flattened = Form(initial={"values.0": 1, "values[1]": 2})
        self.assertEqual(flattened["values"].value(), [1, 2])
        html = flattened.as_p()
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            html,
        )
        self.assertInHTML(
            '<input type="number" name="values-1" value="2" id="id_values_1">',
            html,
        )

        class DefaultingForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, initial=[3]
            )

        self.assertEqual(
            DefaultingForm(initial={"values-0": "1", "values-1": "2"})[
                "values"
            ].initial,
            ["1", "2"],
        )
        self.assertEqual(
            DefaultingForm(initial={"other": "value"})["values"].initial, [3]
        )

    def test_initial_accepts_generic_sequence_and_collection_types(self):
        """It accepts non-string collection-shaped initial values beyond builtins."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        class FieldInitialForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, initial=range(1, 3)
            )

        self.assertEqual(
            Form(initial={"values": range(3)})["values"].value(), [0, 1, 2]
        )
        self.assertEqual(
            Form(initial={"values": deque([4, 5])})["values"].value(),
            [4, 5],
        )
        self.assertEqual(FieldInitialForm()["values"].value(), [1, 2])

    def test_exact_name_scalar_mapping_is_treated_as_one_row(self):
        """It treats an exact-name scalar mapping as one row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        bound = Form({"values": "1"})
        self.assertIs(bound.is_valid(), True, bound.errors)
        self.assertEqual(bound.cleaned_data["values"], [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            bound.as_p(),
        )

        unbound = Form(initial={"values": 1})
        self.assertEqual(unbound["values"].value(), [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" id="id_values_0">',
            unbound.as_p(),
        )

    def test_overlapping_spellings_use_normal_overwrite_semantics(self):
        """It lets later overlapping spellings overwrite earlier ones."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            ({"values-1": "2", "values.1": "3"}, [3], "later canonical row wins"),
            (
                {"values": ["1"], "values-0": "2"},
                [1],
                "direct value wins over indexed convenience",
            ),
            ({"values-01": "2", "values-1": "3"}, [3], "later normalized index wins"),
            ({"values-0": "2", "values[00]": "3"}, [3], "later bracket alias wins"),
            (
                {"values.0": "2", "values[00]": "3"},
                [3],
                "later bracket canonical alias wins",
            ),
        )
        for data, expected, label in cases:
            with self.subTest(label=label, data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], expected)

    def test_missing_or_invalid_management_data_is_reported_and_redisplayed(self):
        """Incomplete management data errors out and redisplays the raw submission."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        for missing, query in (
            ("values-INITIAL_FORMS", "values-TOTAL_FORMS=1&values-0=1"),
            ("values-TOTAL_FORMS", "values-INITIAL_FORMS=0&values-0=1"),
        ):
            with self.subTest(missing=missing):
                form = Form(QueryDict(query))
                self.assertIs(form.is_valid(), False)
                self.assertFormError(
                    form,
                    "values",
                    [
                        (
                            "ManagementForm data is missing or has been tampered "
                            f"with. Missing fields: {missing}. You may need to file "
                            "a bug report if the issue persists."
                        )
                    ],
                )
                self.assertEqual(
                    form.errors.as_data()["values"][0].params["field_names"],
                    missing,
                )

        # An unusable initial count keeps the raw management data and
        # every row. The user can then see and fix what was submitted.
        cases = (
            (
                QueryDict(f"values-{TOTAL_FORM_COUNT}=2&values-0=1&values-1=bad"),
                '<input type="hidden" name="values-INITIAL_FORMS" id="id_values-INITIAL_FORMS">',
            ),
            (
                QueryDict(
                    f"values-{TOTAL_FORM_COUNT}=2&"
                    f"values-{INITIAL_FORM_COUNT}=bad&"
                    "values-0=1&values-1=bad"
                ),
                '<input type="hidden" name="values-INITIAL_FORMS" value="bad" id="id_values-INITIAL_FORMS">',
            ),
        )
        for data, management_input in cases:
            with self.subTest(data=data):
                form = Form(data, initial={"values": [1]})

                self.assertIs(form.is_valid(), False)
                self.assertIsInstance(
                    form.errors.as_data()["values"][0],
                    nestingdolls.MissingManagementFormValidationError,
                )
                html = form.as_p()
                self.assertInHTML(management_input, html)
                self.assertInHTML(
                    '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add" disabled>Add another</button>',
                    html,
                )
                self.assertInHTML(
                    '<input type="number" name="values-0" value="1" id="id_values_0">',
                    html,
                )
                self.assertInHTML(
                    '<input type="number" name="values-1" value="bad" id="id_values_1">',
                    html,
                )

    def test_duplicate_management_values_use_the_last_submitted_value(self):
        """It matches Django formsets by using the last management value."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        query = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-TOTAL_FORMS=2&values-INITIAL_FORMS=0"
                "&values-0=1&values-1=2"
            )
        )
        self.assertIs(query.is_valid(), True, query.errors)
        self.assertEqual(query.cleaned_data["values"], [1, 2])

        # A plain dict of lists is accepted the same way a QueryDict is.
        mapping = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": ["1", "2"],
                f"values-{INITIAL_FORM_COUNT}": ["0"],
                "values-0": ["1"],
                "values-1": ["2"],
            }
        )
        self.assertIs(mapping.is_valid(), True, mapping.errors)
        self.assertEqual(mapping.cleaned_data["values"], [1, 2])

    def test_invalid_rows_redisplay_the_submitted_management_state(self):
        """An invalid submission redisplays its own counts, rows, and delete flags."""
        submitted = (
            f"values-{TOTAL_FORM_COUNT}=2&"
            f"values-{INITIAL_FORM_COUNT}=1&"
            "values-0=1&values-1=2"
        )

        class MaximumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        with self.subTest(case="added row over the maximum"):
            form = MaximumForm(QueryDict(submitted), initial={"values": [1]})
            self.assertIs(form.is_valid(), False)
            html = form.as_p()
            self.assertInHTML(
                '<input type="hidden" name="values-TOTAL_FORMS" value="2" data-sequence-total id="id_values-TOTAL_FORMS">',
                html,
            )
            self.assertInHTML(
                '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
                html,
            )

        class MinimumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), min_length=3)

        with self.subTest(case="rows below the minimum"):
            form = MinimumForm(QueryDict(submitted), initial={"values": [1]})
            self.assertIs(form.is_valid(), False)
            self.assertEqual(form.errors.as_data()["values"][0].code, "min_length")
            self.assertInHTML(
                '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
                form.as_p(),
            )

        class PlainForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        with self.subTest(case="invalid original row beside a deleted added row"):
            data = QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                "values-0=bad&values-1=2",
                mutable=True,
            )
            data[f"values-1-{DELETION_FIELD_NAME}"] = "on"
            form = PlainForm(data, initial={"values": [1]})

            self.assertIs(form.is_valid(), False)
            html = form.as_p()
            self.assertInHTML(
                '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
                html,
            )
            self.assertInHTML(
                '<input type="hidden" name="values-1-DELETE" value="1" data-sequence-deleted-row data-sequence-field="values">',
                html,
            )
            self.assertNotInHTML(
                '<input type="number" name="values-1" value="2" id="id_values_1">',
                html,
            )

    def test_deleted_rows_round_trip(self):
        """Deleted rows leave the cleaned value without renumbering the rest."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        preserved = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2&"
                f"values-1-{DELETION_FIELD_NAME}=1"
            ),
            initial={"values": [1, 2]},
        )
        self.assertIs(preserved.is_valid(), True, preserved.errors)
        self.assertEqual(preserved.cleaned_data["values"], [1])
        self.assertIs(preserved.has_changed(), True)

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        for delete_value in ("1", "on", "true"):
            with self.subTest(delete_value=delete_value):
                data = QueryDict(
                    f"values-{TOTAL_FORM_COUNT}=1&"
                    f"values-{INITIAL_FORM_COUNT}=1&"
                    "values-0=1",
                    mutable=True,
                )
                data["values-0-DELETE"] = delete_value
                form = OptionalForm(data, initial={"values": [1]})
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [])

        class MaximumForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        # A deleted extra row never consumes the final maximum.
        deleted_extra = MaximumForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&"
                f"values-1-{DELETION_FIELD_NAME}=1"
            )
        )
        self.assertIs(deleted_extra.is_valid(), True, deleted_extra.errors)
        self.assertEqual(deleted_extra.cleaned_data["values"], [1])

    def test_management_total_governs_which_rows_are_read(self):
        """The submitted total decides which indexed rows are read at all."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        beyond_total = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        beyond_total["values-1"] = "not an integer"
        form = Form(beyond_total)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])

        extra_only = Form({"values-1": "2"})
        self.assertIs(extra_only.is_valid(), True, extra_only.errors)
        self.assertEqual(extra_only.cleaned_data["values"], [2])

        initial_missing = Form(
            QueryDict("values-TOTAL_FORMS=1&values-INITIAL_FORMS=1"),
            initial={"values": [1]},
        )
        self.assertIs(initial_missing.is_valid(), False)
        self.assertEqual(
            initial_missing.errors.as_data()["values"][0].params["item"], 0
        )

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        omitted_extras = OptionalForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                "values-0=10&values-2=30"
            ),
            initial={"values": [10]},
        )
        self.assertIs(omitted_extras.is_valid(), True, omitted_extras.errors)
        self.assertEqual(omitted_extras.cleaned_data["values"], [10, 30])

    def test_disabled_fields_and_children_keep_their_initial_values(self):
        """A disabled composite ignores submitted rows, hidden or visible."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), disabled=True, initial=[1]
            )

        form = Form(QueryDict("values-TOTAL_FORMS=1&values-0=9"))
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [1])
        self.assertInHTML(
            '<input type="number" name="values-0" value="1" disabled id="id_values_0">',
            form.as_p(),
        )

        class ChildForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(disabled=True))

        submitted = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=99"
        )
        valid = ChildForm(submitted, initial={"values": ["7"]})
        self.assertIs(valid.is_valid(), True, valid.errors)
        self.assertEqual(valid.cleaned_data["values"], [7])

        invalid = ChildForm(submitted, initial={"values": ["bad"]})
        self.assertIs(invalid.is_valid(), False)
        error = invalid.errors.as_data()["values"][0]
        self.assertEqual(error.code, "item_invalid")
        self.assertEqual(error.params["child_code"], "invalid")

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("disabled child value was compared")

        for field_class in (nestingdolls.ListField, nestingdolls.SetField):
            with self.subTest(field_class=field_class.__name__):
                OversizedForm = type(
                    "OversizedForm",
                    (forms.Form,),
                    {
                        "values": field_class(
                            UnreachableField(),
                            max_length=0,
                            required=False,
                            disabled=True,
                        )
                    },
                )
                absolute_max = OversizedForm.base_fields["values"].absolute_max
                oversized = OversizedForm({"values": ["1"] * (absolute_max + 1)})
                self.assertIs(oversized.has_changed(), False)

        class PointForm(forms.Form):
            a = forms.IntegerField()

        class TamperedForm(forms.Form):
            point = nestingdolls.MappingField(
                PointForm,
                initial={"a": 1},
                disabled=True,
                show_hidden_initial=True,
            )
            values = nestingdolls.ListField(
                forms.IntegerField(),
                initial=[1],
                disabled=True,
                show_hidden_initial=True,
            )

        tampered = TamperedForm(
            QueryDict(
                "point-a=9&initial-point=malformed&"
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=1&values-0=9&"
                "initial-values-TOTAL_FORMS=malformed&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=8"
            )
        )
        self.assertIs(tampered.has_changed(), False)
        self.assertIs(tampered.is_valid(), True, tampered.errors)
        self.assertEqual(tampered.cleaned_data["point"], {"a": 1})
        self.assertEqual(tampered.cleaned_data["values"], [1])

    def test_cardinality_errors_follow_the_limit_table(self):
        """Required and length checks come from the final row count alone."""
        cases = (
            ({"required": False, "min_length": 2}, [], None),
            ({"required": False, "min_length": 2}, [1], "min_length"),
            ({"required": False, "min_length": 2, "max_length": 3}, [1, 2], None),
            ({}, [], "required"),
            ({"max_length": 1}, [1, 2], "max_length"),
            ({"min_length": 2, "max_length": 2}, [1, 2], None),
        )
        for kwargs, values, expected in cases:
            with self.subTest(kwargs=kwargs, values=values):
                Form = type(
                    "Form",
                    (forms.Form,),
                    {"values": nestingdolls.ListField(forms.IntegerField(), **kwargs)},
                )
                submitted = QueryDict("", mutable=True)
                submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
                submitted[f"values-{INITIAL_FORM_COUNT}"] = "0"
                for index, value in enumerate(values):
                    submitted[f"values-{index}"] = str(value)
                form = Form(submitted)
                if expected is None:
                    self.assertIs(form.is_valid(), True, form.errors)
                    self.assertEqual(form.cleaned_data["values"], values)
                else:
                    self.assertIs(form.is_valid(), False)
                    self.assertEqual(form.errors.as_data()["values"][0].code, expected)

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), required=False, min_length=2
            )

        short = OptionalForm(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1"
            )
        )
        self.assertIs(short.is_valid(), False)
        self.assertFormError(
            short,
            "values",
            ["Ensure this value has at least 2 items (it has 1)."],
        )

        class RequiredForm(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        empty = RequiredForm({"values": []})
        self.assertIs(empty.is_valid(), False)
        self.assertEqual(empty.errors.as_data()["values"][0].code, "required")

    def test_management_total_beyond_the_absolute_maximum_is_rejected(self):
        """A management total past the absolute maximum is a hostile submission."""
        cases = (
            ({"max_length": 1}, DEFAULT_MAX_NUM + 2),
            ({"max_length": 1, "absolute_max": 2}, 3),
        )
        for kwargs, total in cases:
            with self.subTest(kwargs=kwargs, total=total):
                Form = type(
                    "Form",
                    (forms.Form,),
                    {"values": nestingdolls.ListField(forms.IntegerField(), **kwargs)},
                )
                data = QueryDict("", mutable=True)
                data[f"values-{TOTAL_FORM_COUNT}"] = str(total)
                data[f"values-{INITIAL_FORM_COUNT}"] = "0"
                form = Form(data)

                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertIsInstance(error, nestingdolls.TooManyFormsValidationError)
                self.assertEqual(error.code, "too_many_forms")

    def test_hostile_row_counts_are_bounded_before_child_work(self):
        """Row keys and direct payloads are bounded before any child is touched."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=1)

        # An index no row can hold is discarded rather than clamped.
        discarded = Form({f"values-{DEFAULT_MAX_NUM + 1}": "1"})
        self.assertIs(discarded.is_valid(), False)
        self.assertEqual(discarded.errors.as_data()["values"][0].code, "required")
        normalized = discarded.fields["values"].widget.keys.normalized(
            discarded.data, "values"
        )
        self.assertEqual(dict(normalized), {})

        widget = nestingdolls.SequenceWidget(
            forms.CharField(), max_length=1, absolute_max=2
        )
        matching = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "0",
            **{f"values-0-{index}": "value" for index in range(3)},
        }
        # Three keys naming one row are one row, not an overflow.
        self.assertEqual(
            widget.keys.normalized(matching, "values")[f"values-{TOTAL_FORM_COUNT}"],
            "2",
        )
        distinct = {
            f"values-{TOTAL_FORM_COUNT}": "2",
            f"values-{INITIAL_FORM_COUNT}": "0",
            **{f"values-{index}": "value" for index in range(3)},
        }
        # A row index at or past absolute_max names no row, so canonical()
        # drops it and the two rows that remain keep the submitted total.
        normalized_distinct = widget.keys.normalized(distinct, "values")
        self.assertEqual(normalized_distinct[f"values-{TOTAL_FORM_COUNT}"], "2")
        self.assertNotIn("values-2", normalized_distinct)

        class UnreachableField(forms.IntegerField):
            def clean(self, value):
                raise AssertionError("oversized child value was cleaned")

            def bound_data(self, data, initial):
                raise AssertionError("oversized child value was bound")

            def prepare_value(self, value):
                raise AssertionError("oversized child value was prepared")

            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        class DirectForm(forms.Form):
            values = nestingdolls.ListField(UnreachableField(), max_length=1)

        field = DirectForm.base_fields["values"]
        values = ["1"] * (field.absolute_max + 1)
        # The bound form below is the reachable path. These two paths
        # share the same contract through the public field API.
        with self.assertRaises(ValidationError) as context:
            field.clean(values)
        self.assertEqual(context.exception.error_list[0].code, "too_many_forms")
        self.assertIs(field.has_changed([], values), True)

        oversized = DirectForm(
            {
                "values": values,
                f"values-{TOTAL_FORM_COUNT}": "1",
                f"values-{INITIAL_FORM_COUNT}": "0",
            }
        )
        self.assertIs(oversized.is_valid(), False)
        self.assertEqual(oversized.errors.as_data()["values"][0].code, "too_many_forms")
        oversized.as_p()

    def test_item_errors_stay_inline_and_out_of_the_field_error_list(self):
        """Per-row errors render inline and never promote to field errors."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=3&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=bad&values-2=also-bad"
            )
        )

        self.assertIs(form.is_valid(), False)
        errors = form.errors.as_data()["values"]
        self.assertEqual(
            [error.code for error in errors], ["item_invalid", "item_invalid"]
        )
        self.assertEqual([error.params["item"] for error in errors], [1, 2])
        self.assertEqual(list(form["values"].errors), [])

        html = form.as_p()
        self.assertEqual(html.count('aria-invalid="true"'), 2)
        self.assertInHTML(
            '<input type="number" name="values-1" value="bad" id="id_values_1" aria-invalid="true" aria-describedby="id_values_1_error">',
            html,
        )
        self.assertInHTML("<li>Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 1: Enter a whole number.</li>", html)
        self.assertNotInHTML("<li>Item 2: Enter a whole number.</li>", html)

        class EmailForm(forms.Form):
            emails = nestingdolls.ListField(forms.EmailField(), min_length=4)

        blanks = EmailForm(
            QueryDict(
                f"emails-{TOTAL_FORM_COUNT}=5&"
                f"emails-{INITIAL_FORM_COUNT}=0&"
                "emails-0=&emails-1=&emails-2=&emails-3=&emails-4="
            )
        )

        self.assertIs(blanks.is_valid(), False)
        self.assertEqual(
            [error.code for error in blanks.errors.as_data()["emails"]],
            ["item_invalid"] * 5,
        )
        self.assertEqual(list(blanks["emails"].errors), [])

        blank_html = blanks.as_p()
        self.assertNotInHTML("<li>Item 0: This field is required.</li>", blank_html)
        self.assertInHTML("<li>This field is required.</li>", blank_html)

    def test_item_invalid_errors_preserve_child_codes(self):
        """It preserves child error codes inside item errors."""

        class MultiErrorField(forms.Field):
            def clean(self, value):
                raise ValidationError(
                    [
                        ValidationError("first", code="first_code"),
                        ValidationError("second", code="second_code"),
                    ]
                )

        class Form(forms.Form):
            values = nestingdolls.ListField(MultiErrorField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=x"
            )
        )
        self.assertIs(form.is_valid(), False)
        errors = form.errors.as_data()["values"]
        self.assertEqual([error.message for error in errors], ["first", "second"])
        self.assertEqual(
            [error.params["child_code"] for error in errors],
            ["first_code", "second_code"],
        )

    def test_item_error_messages_with_percent_signs_render_literally(self):
        """A child message keeps its percent sign, eager or lazy."""

        class PercentField(forms.Field):
            def clean(self, value):
                raise ValidationError("50% off is required", code="required")

        class LazyPercentField(forms.Field):
            def clean(self, value):
                raise ValidationError(
                    translation.gettext_lazy("%(pct)s%% off is required"),
                    code="required",
                    params={"pct": 50},
                )

        for child_field in (PercentField(), LazyPercentField()):
            with self.subTest(child_field=type(child_field).__name__):
                Form = type(
                    "Form",
                    (forms.Form,),
                    {"values": nestingdolls.ListField(child_field)},
                )
                form = Form(
                    QueryDict(
                        f"values-{TOTAL_FORM_COUNT}=1&"
                        f"values-{INITIAL_FORM_COUNT}=0&values-0=x"
                    )
                )
                self.assertIs(form.is_valid(), False)
                error = form.errors.as_data()["values"][0]
                self.assertEqual(error.messages, ["50% off is required"])
                self.assertEqual(error.child_message, "50% off is required")
                self.assertEqual(error.params["message"], "50% off is required")
                self.assertEqual(
                    dict(form["values"].submitted.errors),
                    {0: ["50% off is required"]},
                )
                html = form.as_p()
                self.assertIn("50% off is required", html)
                self.assertNotIn("50%% off", html)

    def test_nested_mapping_rows_are_partitioned_before_extraction(self):
        """It gives each nested mapping only its own normalized row inputs."""

        class RowForm(forms.Form):
            value = forms.IntegerField()

        class CountingWidget(nestingdolls.MappingWidget):
            key_visits = 0

            class Keys(nestingdolls.MappingWidget.Keys):
                def normalized(self, data, name):
                    CountingWidget.key_visits += len(data)
                    return super().normalized(data, name)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(RowForm, widget=CountingWidget),
                required=False,
            )

        row_count = 50
        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": str(row_count),
                f"values-{INITIAL_FORM_COUNT}": "0",
                **{f"values-{index}-value": str(index) for index in range(row_count)},
            }
        )

        self.assertIs(form.is_valid(), True, form.errors)
        # The bound must stay sub-quadratic in the row count. A per-row
        # rescan of the whole input visits row_count * row_count keys.
        # The exact figure is an implementation detail. Do not pin it
        # here.
        self.assertLess(CountingWidget.key_visits, row_count * row_count)

    def test_indexes_are_ascii_only_and_do_not_use_unbounded_integer_parsing(self):
        """It ignores Unicode digits, densifies sparse rows, and bounds overflow."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), max_length=1, required=False
            )

        unicode_digits = Form({"values-²": "1", "values[١]": "2"})
        self.assertIs(unicode_digits.is_valid(), True, unicode_digits.errors)
        self.assertEqual(unicode_digits.cleaned_data["values"], [])

        class SparseForm(forms.Form):
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        for style, data in (
            ("dash", {"values-1999": "on"}),
            ("dot", {"values.1999": "on"}),
            ("bracket", {"values[1999]": "on"}),
        ):
            with self.subTest(style=style):
                form = SparseForm(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [False, True])
                normalized = form.fields["values"].widget.keys.normalized(
                    form.data, "values"
                )
                self.assertEqual(normalized[f"values-{TOTAL_FORM_COUNT}"], "2")
                self.assertIn("values-1", normalized)

        long_index = Form({f"values-{'9' * 5000}": "1"})
        self.assertIs(long_index.is_valid(), True, long_index.errors)
        self.assertEqual(long_index.cleaned_data["values"], [])
        normalized = long_index.fields["values"].widget.keys.normalized(
            long_index.data, "values"
        )
        self.assertEqual(dict(normalized), {})

    def test_sparse_unmanaged_indexes_do_not_expand_rendering(self):
        """A sparse flat index renders as one dense row when management data is absent."""

        class Form(forms.Form):
            other = forms.IntegerField()
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        form = Form({"other": "bad", "values-1999": "on"})

        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertIn('name="values-1"', html)
        self.assertNotIn('name="values-1999"', html)

    def test_added_removed_and_failing_rows_drive_has_changed(self):
        """Row cardinality changes and child comparison errors both mean "changed"."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        self.assertIs(Form({"values": []}, initial={"values": []}).has_changed(), False)
        self.assertIs(Form({"values": [0]}, initial={"values": []}).has_changed(), True)
        self.assertIs(Form({"values": []}, initial={"values": [0]}).has_changed(), True)
        self.assertIs(
            Form({"values": [0, 1]}, initial={"values": [0, 1]}).has_changed(), False
        )

        class ErrorField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise ValidationError("comparison failed")

        class ErrorForm(forms.Form):
            values = nestingdolls.ListField(ErrorField(), required=False)

        self.assertIs(ErrorForm({"values": ["1"]}).has_changed(), True)

    def test_has_changed_propagates_child_value_errors(self):
        """It preserves child has_changed() value errors."""

        class ExtraRowBoomField(forms.CharField):
            def has_changed(self, initial, data):
                if initial is None:
                    raise ValueError("extra row boom")
                return super().has_changed(initial, data)

        class Form(forms.Form):
            values = nestingdolls.ListField(ExtraRowBoomField(), required=False)

        form = Form({"values-0": "x"})

        with self.assertRaises(ValueError):
            form.has_changed()

    def test_to_python_rejects_errors_as_values(self):
        """It rejects validation errors passed in as raw values."""
        field = nestingdolls.ListField(forms.IntegerField())

        with self.assertRaises(ValidationError) as context:
            field.to_python(ValidationError("not submitted data"))
        self.assertEqual(context.exception.code, "invalid")

    def test_rejects_unhashable_cleaned_values(self):
        """It rejects unhashable cleaned values for sets."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.JSONField())

        form = Form({"values": [{"answer": 42}]})

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["values"][0].code, "unhashable")

    def test_long_digit_run_is_refused_before_leading_zeros_are_stripped(self):
        """A padded index is a long digit run, whatever it strips down to."""
        widget = nestingdolls.SequenceWidget(forms.CharField())
        padded = "0" * 500_000

        self.assertIsNone(widget.keys.canonical(f"values-{padded}", "values"))
        self.assertIsNone(widget.keys.canonical(f"values-{padded}1", "values"))
        # A run inside the limit still names its row.
        self.assertEqual(widget.keys.canonical("values-007", "values"), ("values-7", 7))

    def test_absolute_max_must_stay_addressable_by_a_row_index(self):
        """``max_index_digits`` is an invariant, so a limit past it is refused."""
        with self.assertRaises(ValueError):
            nestingdolls.ListField(forms.CharField(), absolute_max=10_000_000)

    def test_uploaded_file_named_after_the_field_keeps_the_child_rows(self):
        """A file input named after the field cannot replace the whole value."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        form = Form(
            QueryDict(
                f"values-0=1&values-1=2&values-{TOTAL_FORM_COUNT}=2"
                f"&values-{INITIAL_FORM_COUNT}=0"
            ),
            files=MultiValueDict(
                {"values": [SimpleUploadedFile("forged.txt", b"forged")]}
            ),
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [1, 2])

    def test_composite_rows_are_counted_as_rows_not_as_keys(self):
        """A composite child submits several keys per row, and that is one row."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            b = forms.IntegerField()
            c = forms.IntegerField()

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.DictField(PointForm), max_length=5, absolute_max=10
            )

        form = Form(
            {
                f"values-{TOTAL_FORM_COUNT}": "4",
                f"values-{INITIAL_FORM_COUNT}": "0",
                **{
                    f"values-{index}-{child}": "1"
                    for index in range(4)
                    for child in ("a", "b", "c")
                },
            }
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(len(form.cleaned_data["values"]), 4)

    def test_negative_submitted_total_clamps_instead_of_slicing_from_the_end(self):
        """A negative total renders no row, rather than dropping the last one.

        ``IntegerField`` accepts ``-1``, so ``ManagementForm.clean()`` keeps
        it and it reaches the slice that limits the rendered rows. Django
        feeds its own total to ``range()``, where a negative is harmless. As a
        slice bound it counts from the end instead, so the page would show
        every row but the last and still claim a total of ``-1``.
        """
        widget = nestingdolls.SequenceWidget(forms.CharField())
        widget.bound = widget.Bound(
            management_data={
                f"values-{TOTAL_FORM_COUNT}": "-1",
                f"values-{INITIAL_FORM_COUNT}": "2",
            }
        )

        context = widget.get_context("values", ["a", "b"], {})

        self.assertEqual([row["index"] for row in context["widget"]["rows"]], [])

    def test_disabled_sequence_renders_the_initial_rows_it_cleans(self):
        """A disabled field ignores submitted render state, as it ignores data."""
        cases = (
            {
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "2",
                f"values-0-{DELETION_FIELD_NAME}": "on",
            },
            {
                f"values-{TOTAL_FORM_COUNT}": "bad",
                f"values-{INITIAL_FORM_COUNT}": "0",
            },
        )
        for data in cases:
            with self.subTest(data=data):

                class Form(forms.Form):
                    values = nestingdolls.ListField(
                        forms.IntegerField(), disabled=True, initial=[1, 2]
                    )

                form = Form(data)
                html = form.as_p()

                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [1, 2])
                self.assertIn('value="1"', html)
                self.assertIn('value="2"', html)


class TupleFieldTestCase(SimpleTestCase):
    """`TupleField` is `SequenceField` with one line changed: ``compress``.

    These tests cover that difference and nothing else.
    """

    def test_clean_returns_an_immutable_tuple(self):
        """It collects cleaned rows into a tuple, through clean() and a bound form."""
        field = nestingdolls.TupleField(forms.IntegerField())

        cleaned = field.clean(["1", "2"])

        self.assertIsInstance(cleaned, tuple)
        self.assertEqual(cleaned, (1, 2))
        with self.assertRaises(TypeError):
            cleaned[0] = 3  # type: ignore[index]

        class Form(forms.Form):
            values = nestingdolls.TupleField(forms.IntegerField())

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                "values-0=1&values-1=2"
            )
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], (1, 2))
        self.assertIsInstance(form.cleaned_data["values"], tuple)

    def test_has_changed_compares_a_tuple_initial(self):
        """A tuple initial compares against submitted rows, order included."""
        field = nestingdolls.TupleField(forms.IntegerField(), required=False)

        self.assertIs(field.has_changed((1, 2), ["1", "2"]), False)
        self.assertIs(field.has_changed((1, 2), ["2", "1"]), True)
        self.assertIs(field.has_changed((1, 2), ["1"]), True)

    def test_cardinality_limits_apply_to_the_tuple(self):
        """Length limits are checked on the compressed value."""
        field = nestingdolls.TupleField(
            forms.IntegerField(), min_length=2, max_length=2
        )

        with self.assertRaises(ValidationError) as context:
            field.clean(["1"])
        self.assertEqual(context.exception.code, "min_length")
        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "2", "3"])
        self.assertEqual(context.exception.code, "max_length")


class SetFieldTestCase(SimpleTestCase):
    def test_cardinality_is_checked_after_deduplication(self):
        """It checks set cardinality after removing duplicates."""
        field = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)

        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "1"])
        self.assertEqual(context.exception.code, "min_length")

        field = nestingdolls.SetField(forms.IntegerField(), max_length=1)
        self.assertEqual(field.clean(["1", "1"]), {1})

    def test_frozen_set_field_is_an_immutable_set_variant(self):
        """It exposes a frozenset variant of the set field."""
        field = nestingdolls.FrozenSetField(forms.IntegerField())

        cleaned = field.clean(["2", "1", "1"])
        self.assertIsInstance(cleaned, frozenset)
        self.assertEqual(cleaned, frozenset({1, 2}))
        self.assertIs(field.has_changed(frozenset({1, 2}), ["2", "1", "1"]), False)
        with self.assertRaises(ValidationError) as context:
            nestingdolls.FrozenSetField(forms.JSONField()).clean([{"answer": 42}])
        self.assertEqual(context.exception.code, "unhashable")
        parent = nestingdolls.ListField(
            nestingdolls.FrozenSetField(forms.IntegerField(), required=False),
            required=False,
        )
        self.assertIs(parent.has_changed([frozenset({1, 2})], [["2", "1", "1"]]), False)

    def test_oversized_direct_payload_short_circuits_set_comparison(self):
        """It stops set comparison immediately for oversized direct lists."""

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        for field_class, expected_initial in (
            (nestingdolls.SetField, set()),
            (nestingdolls.FrozenSetField, frozenset()),
        ):
            field = field_class(UnreachableField(), max_length=0, required=False)
            values = ["1"] * (field.absolute_max + 1)
            with self.subTest(field_class=field_class.__name__):
                self.assertIs(field.has_changed(expected_initial, values), True)

    def test_has_changed_propagates_child_value_errors(self):
        """It preserves child comparison value errors."""

        class AnyBoomField(forms.CharField):
            def has_changed(self, initial, data):
                raise ValueError("boom")

        class Form(forms.Form):
            values = nestingdolls.SetField(AnyBoomField(), required=False)

        form = Form({"values-0": "x", "values-1": "x"})

        with self.assertRaises(ValueError):
            form.has_changed()

    def test_has_changed_uses_linear_comparisons_for_hashable_members(self):
        """Reordered unique integer members use indexed child comparisons."""

        class CountingIntegerField(forms.IntegerField):
            comparisons = 0

            def has_changed(self, initial, data):
                self.comparisons += 1
                return super().has_changed(initial, data)

        size = 1001
        field = nestingdolls.SetField(
            CountingIntegerField(), max_length=size, required=False
        )

        self.assertIs(
            field.has_changed(
                set(range(size)), [str(value) for value in reversed(range(size))]
            ),
            False,
        )
        self.assertLessEqual(field.child_field.comparisons, size * 3)

    def test_has_changed_bounds_comparisons_for_non_matching_rows(self):
        """A hostile submission cannot drive a quadratic set comparison.

        Rows are attacker-controlled up to ``absolute_max`` while the members
        come from the server, so an unbudgeted scan is quadratic in a number
        the attacker picks. Exhausting the budget reports "changed", which is
        the safe direction: a missed change loses data, an extra one costs one
        save.
        """

        class CountingCharField(forms.CharField):
            comparisons = 0

            def has_changed(self, initial, data):
                self.comparisons += 1
                return super().has_changed(initial, data)

        members = 1000
        rows = 2000
        field = nestingdolls.SetField(
            CountingCharField(required=False),
            max_length=rows,
            absolute_max=rows,
            required=False,
        )

        # An empty row matches no member. It is itself unchanged
        # against None. So nothing short-circuits the scan.
        changed = field.has_changed(
            {f"m{index}" for index in range(members)}, [""] * rows
        )

        self.assertIs(changed, True)
        self.assertLess(field.child_field.comparisons, 5 * (members + rows))

    def test_member_order_does_not_build_one_index_per_member_per_row(self):
        """A row that hits its hash candidate must not look at other members.

        A comparison looks at one member at a time, and a hit looks at one.
        Building the whole order up front costs ``len(members)`` writes for
        each row even then. That is the quadratic that ``members_left`` stops.
        """
        size = 100_000
        members = [f"m{index}" for index in range(size)]
        match = nestingdolls.SetField.Match(
            forms.CharField(), members, members_left=size
        )
        rows = members[:100]

        tracemalloc.start()
        try:
            for row in rows:
                self.assertIs(match.claim(row, match.candidate(row)), True)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        self.assertEqual(size - match.members_left, len(rows))
        # An eager order builds one tuple of `size` indexes for each row.
        self.assertLess(peak, size)

    def test_has_changed_uses_fallback_for_multiple_choice_lists(self):
        """It compares multiple-choice lists without hashing them."""
        field = nestingdolls.SetField(
            forms.MultipleChoiceField(
                choices=[("first", "First"), ("second", "Second")]
            ),
            required=False,
        )

        self.assertIs(
            field.has_changed({("first", "second")}, [["second", "first"]]), False
        )
        self.assertIs(field.has_changed({("first", "second")}, [["first"]]), True)

    def test_has_changed_keeps_duplicate_blank_invalid_and_json_semantics(self):
        """Indexed matching preserves the child field's semantic edge cases."""
        integer_field = nestingdolls.SetField(
            forms.IntegerField(required=False), required=False
        )
        json_field = nestingdolls.SetField(forms.JSONField(), required=False)

        self.assertIs(integer_field.has_changed({1}, ["1", "1", ""]), False)
        self.assertIs(integer_field.has_changed({1}, ["invalid"]), True)
        self.assertIs(json_field.has_changed({True}, ["1"]), True)


class CompositeHiddenInitialTestCase(SimpleTestCase):
    def test_hidden_initial_markup_and_change_detection(self):
        """Hidden initial rows drive change detection and survive an invalid redisplay."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&"
            f"initial-values-{MIN_NUM_FORM_COUNT}=0&"
            f"initial-values-{MAX_NUM_FORM_COUNT}=1000&initial-values-0=1"
        )
        form = Form(data)

        self.assertIs(form.has_changed(), False)
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-TOTAL_FORMS" value="1" id="id_initial-values-TOTAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-INITIAL_FORMS" value="1" id="id_initial-values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MIN_NUM_FORMS" value="0" id="id_initial-values-MIN_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-MAX_NUM_FORMS" value="1000" id="id_initial-values-MAX_NUM_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0" value="1" id="initial-id_values_0">',
            html,
        )

        malformed_initial = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1&"
            f"initial-values-{TOTAL_FORM_COUNT}=1&"
            f"initial-values-{INITIAL_FORM_COUNT}=1&initial-values-0=not-an-integer"
        )
        self.assertIs(Form(malformed_initial).has_changed(), True)

        changed = data.copy()
        changed["values-0"] = "2"
        self.assertIs(Form(changed).has_changed(), True)

        legacy = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0&values-0=1",
            mutable=True,
        )
        legacy.setlist("initial-values", ["1"])
        self.assertIs(Form(legacy).has_changed(), False)

        invalid = Form(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=bad&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&initial-values-0=7"
            )
        )
        self.assertIs(invalid.is_valid(), False)
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0" value="7" id="initial-id_values_0">',
            invalid.as_p(),
        )

    def test_each_sequence_collection_round_trips_an_integer_child(self):
        """Each sequence collection reads one indexed hidden integer."""
        for field_class, initial in (
            (nestingdolls.ListField, [1]),
            (nestingdolls.TupleField, (1,)),
            (nestingdolls.SetField, {1}),
            (nestingdolls.FrozenSetField, frozenset({1})),
        ):
            with self.subTest(field_class=field_class.__name__):

                class Form(forms.Form):
                    values = field_class(
                        forms.IntegerField(),
                        initial=initial,
                        show_hidden_initial=True,
                    )

                form = Form(
                    QueryDict(
                        "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0=1&"
                        "initial-values-TOTAL_FORMS=1&"
                        "initial-values-INITIAL_FORMS=1&initial-values-0=1"
                    )
                )

                self.assertIs(form.has_changed(), False)

    def test_compound_and_file_children_use_their_own_hidden_widgets(self):
        """A compound child hides every subwidget; a file child hides no filename."""

        class CompoundForm(forms.Form):
            values = nestingdolls.ListField(
                forms.SplitDateTimeField(),
                initial=[datetime(2024, 1, 2, 3, 4, 5)],  # noqa: DTZ001
                show_hidden_initial=True,
            )

        html = CompoundForm().as_p()
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_0" value="2024-01-02" id="initial-id_values_0_0">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="initial-values-0_1" value="03:04:05" id="initial-id_values_0_1">',
            html,
        )

        compound = CompoundForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&"
                "values-0_0=2024-01-02&values-0_1=03%3A04%3A05&"
                "initial-values-TOTAL_FORMS=1&"
                "initial-values-INITIAL_FORMS=1&"
                "initial-values-0_0=2024-01-02&"
                "initial-values-0_1=03%3A04%3A05"
            )
        )
        self.assertIs(compound.has_changed(), False)

        class FileForm(forms.Form):
            files = nestingdolls.ListField(
                forms.FileField(required=False),
                initial=["saved.txt"],
                required=False,
                show_hidden_initial=True,
            )

        data = QueryDict(
            "files-TOTAL_FORMS=1&files-INITIAL_FORMS=1&"
            "initial-files-TOTAL_FORMS=1&initial-files-INITIAL_FORMS=1&"
            "initial-files-0=saved.txt"
        )
        self.assertIs(FileForm(data).has_changed(), False)

        upload = SimpleUploadedFile("replacement.txt", b"replacement")
        uploaded = FileForm(data, files=MultiValueDict({"files-0": [upload]}))
        self.assertIs(uploaded.has_changed(), True)

    def test_hidden_initial_recurses_through_nested_composites(self):
        """Hidden initial parsing recurses through alternating composites."""

        class PointForm(forms.Form):
            a = forms.IntegerField()

        class SequenceOfMappingsForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                initial=[{"a": 1}],
                show_hidden_initial=True,
            )

        html = SequenceOfMappingsForm().as_p()
        self.assertNotIn("{&#x27;a&#x27;: 1}", html)
        self.assertIn('name="initial-values-TOTAL_FORMS"', html)
        self.assertIn('name="initial-values-0-a"', html)

        rows = SequenceOfMappingsForm(
            QueryDict(
                "values-TOTAL_FORMS=1&values-INITIAL_FORMS=0&values-0-a=1&"
                "initial-values-TOTAL_FORMS=1&initial-values-INITIAL_FORMS=1&"
                "initial-values-MIN_NUM_FORMS=0&initial-values-MAX_NUM_FORMS=1000&"
                "initial-values-0-a=1"
            )
        )
        self.assertIs(rows.has_changed(), False)

        class ContainerForm(forms.Form):
            rows = nestingdolls.ListField(nestingdolls.MappingField(PointForm))

        class MappingOfSequenceForm(forms.Form):
            container = nestingdolls.MappingField(
                ContainerForm,
                initial={"rows": [{"a": 1}]},
                show_hidden_initial=True,
            )

        container_html = MappingOfSequenceForm().as_p()
        self.assertIn('name="initial-container-rows-TOTAL_FORMS"', container_html)
        self.assertIn('name="initial-container-rows-0-a"', container_html)

        container = MappingOfSequenceForm(
            QueryDict(
                "container-rows-TOTAL_FORMS=1&"
                "container-rows-INITIAL_FORMS=0&container-rows-0-a=1&"
                "initial-container-rows-TOTAL_FORMS=1&"
                "initial-container-rows-INITIAL_FORMS=1&"
                "initial-container-rows-0-a=1"
            )
        )
        self.assertIs(container.has_changed(), False)

    def test_hidden_sequence_markup_is_minimal_in_each_form_layout(self):
        """Each helper emits one hidden child and no hidden sequence controls."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(), initial=[1], show_hidden_initial=True
            )

        for helper in ("as_p", "as_div", "as_ul", "as_table"):
            with self.subTest(helper=helper):
                html = getattr(Form(), helper)()
                self.assertEqual(html.count('name="initial-values-0"'), 1)
                self.assertEqual(html.count('id="initial-id_values_0"'), 1)
                for name in (
                    TOTAL_FORM_COUNT,
                    INITIAL_FORM_COUNT,
                    MIN_NUM_FORM_COUNT,
                    MAX_NUM_FORM_COUNT,
                ):
                    self.assertEqual(html.count(f'name="initial-values-{name}"'), 1)
                self.assertNotIn('name="initial-values-0-DELETE"', html)
                self.assertNotIn('name="initial-values-__prefix__"', html)
                self.assertNotIn('data-sequence-field="initial-values"', html)


class NestedSequenceFieldTestCase(SimpleTestCase):
    def test_nested_shapes_clean_from_flat_keys(self):
        """Each supported nesting shape cleans from its flat nested keys."""

        class PairForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                )
            )

        class DeepListForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(nestingdolls.ListField(forms.IntegerField()))
            )

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class EntryForm(forms.Form):
            point = nestingdolls.MappingField(PointForm)
            title = forms.CharField()

        class SectionForm(forms.Form):
            name = forms.CharField()
            entries = nestingdolls.ListField(nestingdolls.MappingField(EntryForm))

        class AlternatingForm(forms.Form):
            values = nestingdolls.ListField(nestingdolls.MappingField(SectionForm))

        class CheckboxRowForm(forms.Form):
            active = forms.BooleanField(required=False)

        class BlankRowForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(CheckboxRowForm), required=False
            )

        cases = (
            (
                "tuple pairs",
                PairForm,
                {
                    "values-0-0": "1",
                    "values-0-1": "2",
                    "values-1-0": "3",
                    "values-1-1": "4",
                },
                [(1, 2), (3, 4)],
            ),
            (
                "list of lists of lists",
                DeepListForm,
                {
                    "values-0-0-0": "1",
                    "values-0-0-1": "2",
                    "values-0-1-0": "3",
                    "values-1-0-0": "4",
                    "values-1-1-0": "5",
                    "values-1-1-1": "6",
                },
                [[[1, 2], [3]], [[4], [5, 6]]],
            ),
            (
                "alternating list, mapping, list, mapping layers",
                AlternatingForm,
                {
                    "values[0][name]": "alpha",
                    "values[0][entries][0][point][a]": "1",
                    "values[0][entries][0][point][label]": "north",
                    "values[0][entries][0][title]": "first",
                    "values[0][entries][1][point][a]": "2",
                    "values[0][entries][1][title]": "second",
                    "values[1][name]": "beta",
                    "values[1][entries][0][point][a]": "3",
                    "values[1][entries][0][title]": "third",
                },
                [
                    {
                        "name": "alpha",
                        "entries": [
                            {"point": {"a": 1, "label": "north"}, "title": "first"},
                            {"point": {"a": 2, "label": ""}, "title": "second"},
                        ],
                    },
                    {
                        "name": "beta",
                        "entries": [
                            {"point": {"a": 3, "label": ""}, "title": "third"},
                        ],
                    },
                ],
            ),
            (
                "blank optional mapping row stays absent",
                BlankRowForm,
                QueryDict("values-TOTAL_FORMS=1&values-INITIAL_FORMS=0"),
                [],
            ),
        )
        for label, form_class, data, expected in cases:
            with self.subTest(shape=label):
                form = form_class(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], expected)

    def test_nested_change_detection_uses_child_semantics(self):
        """Nested change detection delegates to the child field's comparison."""
        tuple_field = nestingdolls.ListField(
            nestingdolls.TupleField(
                forms.IntegerField(),
                min_length=2,
                max_length=2,
            ),
            required=False,
        )

        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 0]]), False)
        self.assertIs(tuple_field.has_changed([(2, 0)], [[2, 1]]), True)
        self.assertIs(tuple_field.has_changed([(2, 0)], []), True)
        self.assertIs(tuple_field.has_changed([], [[2, 0]]), True)

        child = nestingdolls.ListField(
            nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField(), required=False),
                required=False,
            ),
            required=False,
        )
        field = nestingdolls.ListField(child, required=False)

        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]), False)
        self.assertIs(field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]), True)
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [1]]]]),
            child.has_changed([[[2], [0]]], [[[2], [1]]]),
        )
        self.assertEqual(
            field.has_changed([[[[2], [0]]]], [[[[2], [0]]]]),
            child.has_changed([[[2], [0]]], [[[2], [0]]]),
        )

    def test_nested_row_errors_are_reported_and_redisplayed(self):
        """A nested row error keeps the inner counts and names the child code."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(forms.IntegerField())
            )

        form = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&"
                f"values-{INITIAL_FORM_COUNT}=1&"
                f"values-0-{TOTAL_FORM_COUNT}=2&"
                f"values-0-{INITIAL_FORM_COUNT}=1&"
                "values-0-0=1&values-0-1=bad"
            ),
            initial={"values": [[1]]},
        )

        self.assertIs(form.is_valid(), False)
        html = form.as_p()
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="1" id="id_values-INITIAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="values-0-INITIAL_FORMS" value="1" id="id_values-0-INITIAL_FORMS">',
            html,
        )

        class PairForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                )
            )

        extra_item = PairForm(
            {
                "values-0-0": "1",
                "values-0-1": "2",
                "values-0-2": "3",
            }
        )

        self.assertIs(extra_item.is_valid(), False)
        self.assertEqual(extra_item.errors.as_data()["values"][0].code, "item_invalid")
        self.assertEqual(
            extra_item.errors.as_data()["values"][0].params["child_code"], "max_length"
        )

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
    def test_nested_initial_rendering_reserves_rows_before_leaf_preparation(self):
        """Rendering clips nested initials before preparing excess leaf values."""

        class CountingField(forms.IntegerField):
            preparations = 0

            def prepare_value(self, value):
                CountingField.preparations += 1
                return super().prepare_value(value)

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    CountingField(),
                    max_length=10,
                    absolute_max=10,
                ),
                max_length=10,
                absolute_max=10,
            )

        large_initial = [list(range(10)), list(range(10, 20))]
        CountingField.preparations = 0
        large_html = Form(initial={"outer": large_initial}).as_p()
        large_leaf_names = (
            f"outer-{outer_index}-{inner_index}"
            for outer_index in range(2)
            for inner_index in range(10)
        )
        rendered_large_leaves = sum(
            large_html.count(f'name="{name}"') for name in large_leaf_names
        )

        self.assertLessEqual(rendered_large_leaves, 10)
        self.assertLessEqual(CountingField.preparations, 10)

        small_initial = [list(range(4)), list(range(4, 8))]
        CountingField.preparations = 0
        small_html = Form(initial={"outer": small_initial}).as_p()
        small_leaf_names = (
            f"outer-{outer_index}-{inner_index}"
            for outer_index in range(2)
            for inner_index in range(4)
        )
        rendered_small_leaves = sum(
            small_html.count(f'name="{name}"') for name in small_leaf_names
        )

        self.assertEqual(rendered_small_leaves, 8)
        self.assertEqual(CountingField.preparations, 8)

    def test_submission_limit_follows_the_django_request_limit(self):
        """Use Django's key limit and the per-level cap for the shared cap.

        A populated row needs a key. One level can still request
        ``absolute_max`` empty rows with one ``TOTAL_FORMS`` key. The shared cap
        is the larger value.
        """
        limits = nestingdolls.ListField(forms.CharField()).limits
        self.assertEqual(limits.absolute_max, 2000)

        cases = (
            # (Django key limit, expected shared cap)
            (1000, 2000),  # The per-level cap is larger.
            (5000, 5000),  # More accepted keys allow more populated rows.
            (10, 2000),  # The field still permits its empty rows.
            (None, 2000),  # The key limit is off, so the per-level cap applies.
        )
        for keys, expected in cases:
            with (
                self.subTest(keys=keys),
                override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=keys),
            ):
                self.assertEqual(limits.submission_max, expected)

    def test_a_raised_django_limit_lets_a_larger_nested_submission_through(self):
        """A higher Django key limit permits a larger nested submission."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        # Three parent rows and 900 child rows in each parent need 2703 rows.
        # Each child total is valid. Only the shared cap can reject this data.
        data = {
            f"outer-{TOTAL_FORM_COUNT}": "3",
            f"outer-{INITIAL_FORM_COUNT}": "0",
            **{f"outer-{index}-{TOTAL_FORM_COUNT}": "900" for index in range(3)},
        }

        refused = Form(data)
        self.assertIs(refused.is_valid(), False)
        self.assertEqual(refused.errors.as_data()["outer"][0].code, "too_many_forms")

        with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=10_000):
            allowed = Form(data)
            self.assertIs(allowed.is_valid(), True, allowed.errors)
            self.assertEqual(
                [len(rows) for rows in allowed.cleaned_data["outer"]],
                [900, 900, 900],
            )

    def test_submission_cap_allows_an_exact_nested_total(self):
        """Exact use of the shared cap does not report too many forms."""

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(
                    forms.CharField(required=False),
                    max_length=1999,
                ),
                required=False,
            )

        # One parent row and 1999 child rows use the default cap of 2000 exactly.
        form = Form(
            {
                f"outer-{TOTAL_FORM_COUNT}": "1",
                f"outer-{INITIAL_FORM_COUNT}": "0",
                f"outer-0-{TOTAL_FORM_COUNT}": "1999",
                f"outer-0-{INITIAL_FORM_COUNT}": "0",
            }
        )

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual([len(rows) for rows in form.cleaned_data["outer"]], [1999])


@override_settings(ROOT_URLCONF=__name__, DATA_UPLOAD_MAX_NUMBER_FIELDS=10)
class SequenceRootSubmissionLimitRequestTestCase(SimpleTestCase):
    def test_sequence_root_request_cap_boundaries(self):
        """Django parses four management keys before nested row work is capped."""

        client = Client()

        for inner_total, expected_valid, expected_errors in (
            (10, False, {"outer": ["too_many_forms"]}),
            (9, True, {}),
        ):
            with self.subTest(inner_total=inner_total):
                response = client.post(
                    "/sequence-root-submission-limit/",
                    {
                        f"outer-{TOTAL_FORM_COUNT}": "1",
                        f"outer-{INITIAL_FORM_COUNT}": "0",
                        f"outer-0-{TOTAL_FORM_COUNT}": str(inner_total),
                        f"outer-0-{INITIAL_FORM_COUNT}": "0",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {"valid": expected_valid, "errors": expected_errors},
                )


class _HypothesisTestCase(SimpleTestCase):
    _row_spelling_names = ("direct", "dash", "dot", "bracket")
    _multiwidget_spelling_names = ("dash", "dot", "bracket")

    @staticmethod
    def _spelled_sequence_data(name, values, style, formatter=str):
        if style == "direct":
            return {name: [formatter(value) for value in values]}
        if style == "dash":
            return {
                f"{name}-{index}": formatter(value)
                for index, value in enumerate(values)
            }
        if style == "dot":
            return {
                f"{name}.{index}": formatter(value)
                for index, value in enumerate(values)
            }
        if style == "bracket":
            return {
                f"{name}[{index}]": formatter(value)
                for index, value in enumerate(values)
            }
        raise AssertionError(f"unsupported style: {style}")

    @staticmethod
    def _cardinality_result(required, min_length, max_length, values):
        length = len(values)
        if length == 0 and required:
            return "required"
        if length == 0:
            return "ok"
        if length < min_length:
            return "min_length"
        if length > max_length:
            return "max_length"
        return "ok"

    @staticmethod
    def _undeleted_rows(values, deleted):
        return [value for index, value in enumerate(values) if index not in deleted]

    @staticmethod
    def _nested_tuple_data(name, rows):
        return {
            f"{name}-{row_index}-{column_index}": str(value)
            for row_index, row in enumerate(rows)
            for column_index, value in enumerate(row)
        }

    def _json_row_data(self, name, values, style):
        return self._spelled_sequence_data(name, values, style, formatter=json.dumps)

    def _boolean_row_data(self, name, values):
        data = QueryDict("", mutable=True)
        data[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(values))
        data[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            if value:
                data[f"{name}-{index}"] = "on"
        return data

    def _integer_row_data(self, name, values):
        data = QueryDict("", mutable=True)
        data[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(values))
        data[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            data[f"{name}-{index}"] = str(value)
        return data

    def _splitdatetime_row_data(self, name, values, style):
        data = {}
        for index, value in enumerate(values):
            date_part = value.date().isoformat()
            time_part = value.time().strftime("%H:%M:%S")
            if style == "dash":
                prefix = f"{name}-{index}"
            elif style == "dot":
                prefix = f"{name}.{index}"
            elif style == "bracket":
                prefix = f"{name}[{index}]"
            else:
                raise AssertionError(f"unsupported style: {style}")
            data[f"{prefix}_0"] = date_part
            data[f"{prefix}_1"] = time_part
        return data

    # The three set child kinds below share one contract, with three
    # different child fields: a scalar, a compound sequence child, and
    # a Django multiwidget.
    def _set_child_field(self, kind):
        if kind == "integer":
            return forms.IntegerField()
        if kind == "tuple":
            return nestingdolls.TupleField(
                forms.IntegerField(), min_length=2, max_length=2
            )
        if kind == "splitdatetime":
            return forms.SplitDateTimeField()
        raise AssertionError(f"unsupported child kind: {kind}")

    def _set_member_strategy(self, kind):
        if kind == "integer":
            return SMALL_INTEGERS
        if kind == "tuple":
            return st.tuples(SMALL_INTEGERS, SMALL_INTEGERS)
        if kind == "splitdatetime":
            return st.datetimes(timezones=st.none()).map(
                lambda value: value.replace(microsecond=0)
            )
        raise AssertionError(f"unsupported child kind: {kind}")

    def _set_row_data(self, kind, members):
        if kind == "integer":
            return self._integer_row_data("values", members)
        if kind == "tuple":
            return self._nested_tuple_data("values", list(members))
        if kind == "splitdatetime":
            return self._splitdatetime_row_data("values", list(members), "dash")
        raise AssertionError(f"unsupported child kind: {kind}")

    def _set_form_class(self, field_class, kind):
        return type(
            "Form",
            (forms.Form,),
            {"values": field_class(self._set_child_field(kind), required=False)},
        )


class SequenceFieldPropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(values=[{"answer": 42}])
    @given(values=st.lists(JSON_VALUES, max_size=4))
    def test_json_rows_clean_equally_across_supported_spellings(self, values):
        """It gives the same public outcome for every supported JSON spelling."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        outcomes = []
        for style in self._row_spelling_names:
            form = Form(self._json_row_data("values", values, style))
            if form.is_valid():
                outcomes.append(("ok", form.cleaned_data["values"]))
            else:
                outcomes.append(
                    (
                        "error",
                        tuple(error.code for error in form.errors.as_data()["values"]),
                    )
                )
        self.assertEqual(outcomes, [outcomes[0]] * len(self._row_spelling_names))

    @HYPOTHESIS_SETTINGS
    @given(
        required=st.booleans(),
        bounds=st.integers(min_value=0, max_value=5).flatmap(
            lambda min_length: st.tuples(
                st.just(min_length), st.integers(min_value=min_length, max_value=5)
            )
        ),
        values=SMALL_INTEGER_LISTS,
        data=st.data(),
    )
    def test_cardinality_matches_the_public_validation_contract(
        self, required, bounds, values, data
    ):
        """It applies required/min/max to the rows that survive deletion."""
        min_length, max_length = bounds
        if required and max_length == 0:
            # A required field with no rows can never be satisfied. So
            # the constructor refuses that combination, instead of
            # rendering no input.
            with self.assertRaises(ValueError):
                nestingdolls.ListField(
                    forms.IntegerField(), required=True, max_length=0
                )
            return

        deleted = (
            data.draw(
                st.sets(
                    st.integers(min_value=0, max_value=len(values) - 1),
                    max_size=len(values),
                )
            )
            if values
            else set()
        )
        remaining = self._undeleted_rows(values, deleted)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(),
                required=required,
                min_length=min_length,
                max_length=max_length,
            )

        submitted = QueryDict("", mutable=True)
        submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
        submitted[f"values-{INITIAL_FORM_COUNT}"] = "0"
        for index, value in enumerate(values):
            submitted[f"values-{index}"] = str(value)
        for index in sorted(deleted):
            submitted[f"values-{index}-{DELETION_FIELD_NAME}"] = "1"

        form = Form(submitted)
        expected = self._cardinality_result(required, min_length, max_length, remaining)
        self.assertEqual(form.is_valid(), expected == "ok")
        if expected == "ok":
            self.assertEqual(form.cleaned_data["values"], remaining)
        else:
            self.assertEqual(form.errors.as_data()["values"][0].code, expected)

    @HYPOTHESIS_SETTINGS
    @given(
        values=SMALL_INTEGER_LISTS,
        initial_forms=st.integers(min_value=0, max_value=5),
        data=st.data(),
    )
    def test_delete_flags_remove_rows_before_cleaned_output(
        self, values, initial_forms, data
    ):
        """It removes deleted rows from cleaned output regardless of initial_forms."""
        initial_forms = min(initial_forms, len(values))
        deleted = (
            data.draw(
                st.sets(
                    st.integers(min_value=0, max_value=len(values) - 1),
                    max_size=len(values),
                )
            )
            if values
            else set()
        )

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), required=False)

        submitted = QueryDict("", mutable=True)
        submitted[f"values-{TOTAL_FORM_COUNT}"] = str(len(values))
        submitted[f"values-{INITIAL_FORM_COUNT}"] = str(initial_forms)
        for index, value in enumerate(values):
            submitted[f"values-{index}"] = str(value)
        for index in sorted(deleted):
            submitted[f"values-{index}-{DELETION_FIELD_NAME}"] = "1"

        form = Form(submitted)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(
            form.cleaned_data["values"], self._undeleted_rows(values, deleted)
        )

    @HYPOTHESIS_SETTINGS
    @given(values=st.lists(st.booleans(), max_size=5))
    def test_boolean_rows_preserve_unchecked_positions(self, values):
        """It keeps false boolean rows in position with management data."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.BooleanField(required=False), required=False
            )

        form = Form(self._boolean_row_data("values", values))
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], values)

    @HYPOTHESIS_SETTINGS
    @example(values=[{"nested": [1, 2]}], style="dash")
    @given(
        values=st.lists(JSON_VALUES, max_size=4),
        style=st.sampled_from(_HypothesisTestCase._row_spelling_names),
    )
    def test_json_rows_use_semantic_change_detection(self, values, style):
        """It compares JSON rows semantically instead of by raw string form."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.JSONField(), required=False)

        form = Form(
            self._json_row_data("values", values, style), initial={"values": values}
        )
        self.assertIs(form.has_changed(), False)

    @HYPOTHESIS_SETTINGS
    @given(values=DATETIME_ROWS)
    def test_splitdatetime_rows_clean_equally_across_indexed_spellings(self, values):
        """It cleans compound datetime rows identically across indexed spellings."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField(), required=False)

        cleaned_results = []
        for style in self._multiwidget_spelling_names:
            form = Form(self._splitdatetime_row_data("values", values, style))
            self.assertIs(form.is_valid(), True, (style, form.errors))
            cleaned_results.append(
                [item.replace(tzinfo=None) for item in form.cleaned_data["values"]]
            )
        self.assertEqual(
            cleaned_results, [values] * len(self._multiwidget_spelling_names)
        )

    @HYPOTHESIS_SETTINGS
    @example(
        cases=(
            (
                "scalar-row-only",
                {
                    "direct": {"values": ["1"]},
                    "dash": {"values-0": "1"},
                    "dot": {"values.0": "1"},
                    "bracket": {"values[0]": "1"},
                },
            ),
        )
    )
    @example(
        cases=(
            (
                "scalar-row-plus-leaf",
                {
                    "direct": {"values": ["1"]},
                    "dash": {"values-0": "1", "values-0[a]": "2"},
                    "dot": {"values.0": "1", "values.0[a]": "2"},
                    "bracket": {"values[0]": "1", "values[0][a]": "2"},
                },
            ),
        )
    )
    @given(
        cases=st.lists(
            st.sampled_from(
                (
                    (
                        "scalar-row-only",
                        {
                            "direct": {"values": ["1"]},
                            "dash": {"values-0": "1"},
                            "dot": {"values.0": "1"},
                            "bracket": {"values[0]": "1"},
                        },
                    ),
                    (
                        "scalar-row-plus-leaf",
                        {
                            "direct": {"values": ["1"]},
                            "dash": {"values-0": "1", "values-0[a]": "2"},
                            "dot": {"values.0": "1", "values.0[a]": "2"},
                            "bracket": {"values[0]": "1", "values[0][a]": "2"},
                        },
                    ),
                    (
                        "malformed-row-suffix",
                        {
                            "dash": {"values-0junk": "1"},
                            "dot": {"values.0junk": "1"},
                            "bracket": {"values[0]junk": "1"},
                        },
                    ),
                    (
                        "nested-repeat-into-row",
                        {
                            "dash": {"values-0-0": "1"},
                            "dot": {"values.0.0": "1"},
                            "bracket": {"values[0][0]": "1"},
                        },
                    ),
                    (
                        "second-row-plus-leaf",
                        {
                            "dash": {"values-1": "1", "values-1[a]": "2"},
                            "dot": {"values.1": "1", "values.1[a]": "2"},
                            "bracket": {"values[1]": "1", "values[1][a]": "2"},
                        },
                    ),
                )
            ),
            min_size=1,
            max_size=1,
            unique_by=lambda item: item[0],
        )
    )
    def test_mapping_row_hostile_cases_match_public_outcomes_across_spellings(
        self, cases
    ):
        """Hostile row-shape spellings should agree on validation and rendering."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        spellings = {style: {} for style in self._row_spelling_names}
        for _, family in cases:
            for style, payload in family.items():
                spellings[style].update(payload)
        populated_styles = [
            style for style in self._row_spelling_names if spellings.get(style)
        ]
        if not populated_styles:
            populated_styles = ["direct"]
        is_valid_results = []
        error_results = []
        render_results = []
        value_results = []
        for style in populated_styles:
            form = Form(spellings[style])
            is_valid_results.append(form.is_valid())
            error_results.append(
                tuple(
                    (error.code, (error.params or {}).get("child_code"))
                    for error in form.errors.as_data().get("values", [])
                )
            )
            try:
                str(form["values"])
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                render_results.append(type(exc).__name__)
            else:
                render_results.append(None)
            try:
                form["values"].value()
            except Exception as exc:  # noqa: BLE001 - crashes are the property outcome
                value_results.append(type(exc).__name__)
            else:
                value_results.append(None)
        self.assertEqual(
            is_valid_results, [is_valid_results[0]] * len(is_valid_results)
        )
        self.assertEqual(error_results, [error_results[0]] * len(error_results))
        self.assertEqual(render_results, [render_results[0]] * len(render_results))
        self.assertEqual(value_results, [value_results[0]] * len(value_results))

    @HYPOTHESIS_SETTINGS
    @given(
        data=st.sampled_from(
            (
                {"values0": "1"},
                {"values_0": "1"},
                {"valuesx[0]": "1"},
                {"values[0]junk": "1"},
                {"values[a]": "1"},
            )
        )
    )
    def test_unrelated_sequence_prefixes_and_suffixes_do_not_satisfy_the_field(
        self, data
    ):
        """Keys outside the exact indexed row prefix cannot satisfy a required field."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        form = Form(data)

        self.assertIs(form.is_valid(), False)
        self.assertEqual(form.errors.as_data()["values"][0].code, "required")


class SetFieldPropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(values=[1, 1])
    @given(values=SMALL_INTEGER_LISTS)
    def test_set_field_cleans_to_the_semantic_set(self, values):
        """It deduplicates rows exactly as a set would."""

        class Form(forms.Form):
            values = nestingdolls.SetField(forms.IntegerField(), required=False)

        form = Form(self._integer_row_data("values", values))
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], set(values))

    @HYPOTHESIS_SETTINGS
    @given(
        field_class=st.sampled_from(SET_COLLECTIONS),
        kind=st.sampled_from(SET_CHILD_KINDS),
        data=st.data(),
    )
    def test_set_has_changed_is_false_for_reordered_equal_members(
        self, field_class, kind, data
    ):
        """A set field is unchanged when its rows permute or repeat its initial."""
        members = data.draw(
            st.lists(self._set_member_strategy(kind), unique=True, max_size=4)
        )
        extras = (
            data.draw(st.lists(st.sampled_from(members), max_size=3)) if members else []
        )
        submitted = list(data.draw(st.permutations(tuple(members) + tuple(extras))))
        collection = frozenset if field_class is nestingdolls.FrozenSetField else set

        form = self._set_form_class(field_class, kind)(
            self._set_row_data(kind, submitted),
            initial={"values": collection(members)},
        )

        self.assertIs(form.has_changed(), False)

    @HYPOTHESIS_SETTINGS
    @given(
        field_class=st.sampled_from(SET_COLLECTIONS),
        kind=st.sampled_from(SET_CHILD_KINDS),
        data=st.data(),
    )
    def test_set_has_changed_is_true_for_semantic_difference(
        self, field_class, kind, data
    ):
        """A set field reports a change from semantic set inequality."""
        members = self._set_member_strategy(kind)
        initial_members = data.draw(st.lists(members, unique=True, max_size=4))
        submitted_members = data.draw(st.lists(members, unique=True, max_size=4))
        assume(set(initial_members) != set(submitted_members))
        collection = frozenset if field_class is nestingdolls.FrozenSetField else set

        form = self._set_form_class(field_class, kind)(
            self._set_row_data(kind, submitted_members),
            initial={"values": collection(initial_members)},
        )

        self.assertIs(form.has_changed(), True)


class NestedSequencePropertyTestCase(_HypothesisTestCase):
    @HYPOTHESIS_SETTINGS
    @example(initial_rows=[(2, 0)], submitted_rows=[(2, 0)])
    @given(
        initial_rows=st.lists(
            st.tuples(
                SMALL_INTEGERS,
                SMALL_INTEGERS,
            ),
            max_size=5,
        ),
        submitted_rows=st.lists(
            st.tuples(
                SMALL_INTEGERS,
                SMALL_INTEGERS,
            ),
            max_size=5,
        ),
    )
    def test_nested_tuple_rows_change_exactly_on_semantic_difference(
        self, initial_rows, submitted_rows
    ):
        """Nested tuple initials compare semantically against list submissions."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.TupleField(
                    forms.IntegerField(),
                    min_length=2,
                    max_length=2,
                ),
                required=False,
            )

        form = Form(
            self._nested_tuple_data("values", [list(row) for row in submitted_rows]),
            initial={"values": initial_rows},
        )
        self.assertIs(form.has_changed(), initial_rows != submitted_rows)

    @HYPOTHESIS_SETTINGS
    @example(outer_total=2, inner_totals=[2000, 2000])
    @example(outer_total=-1, inner_totals=[])
    @given(
        outer_total=st.integers(min_value=-3, max_value=4000),
        inner_totals=st.lists(st.integers(min_value=-3, max_value=4000), max_size=12),
    )
    def test_nested_totals_never_build_more_rows_than_one_submission_permits(
        self, outer_total, inner_totals
    ):
        """Keep all built rows inside the shared cap.

        Each payload stays within Django's key limit. Django can pass it to the
        form, but nested totals can still multiply rows. This test checks the
        package cap.
        """

        class Form(forms.Form):
            outer = nestingdolls.ListField(
                nestingdolls.ListField(forms.CharField(required=False)),
                required=False,
            )

        data = {
            f"outer-{TOTAL_FORM_COUNT}": str(outer_total),
            f"outer-{INITIAL_FORM_COUNT}": "0",
        }
        for index, total in enumerate(inner_totals):
            data[f"outer-{index}-{TOTAL_FORM_COUNT}"] = str(total)
            data[f"outer-{index}-{INITIAL_FORM_COUNT}"] = "0"
        # Django rejects requests above this key count. A real request cannot
        # reach the form with more keys.
        self.assertLessEqual(len(data), settings.DATA_UPLOAD_MAX_NUMBER_FIELDS)

        # Extraction and rendering must not raise for any submitted totals.
        form = Form(data)
        form.is_valid()
        form.as_p()


class NestedParserRegressionTestCase(SimpleTestCase):
    def test_unrecognized_mapping_initial_becomes_one_renderable_row(self):
        """A mapping that is not flattened sequence data remains one raw row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), required=False)

        value = {"unexpected": "saved"}
        form = Form(initial={"values": value})

        self.assertEqual(form["values"].initial, [value])
        self.assertIn("unexpected", str(form["values"]))

    def test_invalid_mapping_row_shapes_stay_in_the_validation_channel(self):
        """Every hostile mapping-row shape becomes an inline error and still renders."""

        class PointForm(forms.Form):
            a = forms.IntegerField()
            label = forms.CharField(required=False)

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(PointForm),
                required=False,
            )

        class NestedForm(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.ListField(
                    nestingdolls.MappingField(PointForm),
                    required=False,
                ),
                required=False,
            )

        cases = (
            ("direct", Form, {"values": ["1"]}, ["1"]),
            ("dash", Form, {"values-0": "1"}, ["1"]),
            ("dot", Form, {"values.0": "1"}, ["1"]),
            ("bracket", Form, {"values[0]": "1"}, ["1"]),
            (
                "scalar row alias plus nested child alias",
                Form,
                {"values[0]": "1", "values[0][a]": "2"},
                ["1"],
            ),
            (
                "repeated sequence-to-mapping boundary",
                NestedForm,
                {"values[0][0]": "1"},
                [["1"]],
            ),
        )
        for label, form_class, data, expected_value in cases:
            with self.subTest(shape=label):
                form = form_class(data)
                self.assertIs(form.is_valid(), False)
                self.assertIn(
                    form.errors.as_data()["values"][0].code,
                    ("invalid", "item_invalid"),
                )
                rendered = str(form["values"])
                self.assertEqual(form["values"].value(), expected_value)
                self.assertIn("Enter a mapping of values.", rendered)

    def test_custom_child_rebinding_uses_django_field_fallbacks(self):
        """A custom child widget receives hostile input without type assumptions."""

        class CustomWidget(forms.TextInput):
            pass

        class RejectingField(forms.CharField):
            widget = CustomWidget

            def bound_data(self, data, initial):
                raise ValidationError("Cannot bind this value.")

            def prepare_value(self, value):
                raise nestingdolls.InvalidInitialValueError(
                    "Cannot prepare this value."
                )

        class Form(forms.Form):
            values = nestingdolls.ListField(RejectingField(), required=False)

        form = Form({"values[0]": "hostile"})

        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form["values"].value(), ["hostile"])
        self.assertIn('value="hostile"', str(form["values"]))

    def test_numeric_mapping_child_names_remain_valid_below_a_list(self):
        """A mapping child named ``0`` still accepts ``values[0][0]`` spellings."""

        NumericChildForm = type(
            "NumericChildForm",
            (forms.Form,),
            {"0": forms.IntegerField()},
        )

        class Form(forms.Form):
            values = nestingdolls.ListField(
                nestingdolls.MappingField(NumericChildForm),
                required=False,
            )

        cases = (
            {"values[0][0]": "1"},
            {"values.0.0": "1"},
            {"values-0-0": "1"},
        )
        for data in cases:
            with self.subTest(data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [{"0": 1}])
                self.assertEqual(form["values"].value(), [{"0": "1"}])
                str(form["values"])

    def test_text_list_indexes_do_not_bind(self):
        """Text segments cannot name sequence rows."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        cases = (
            {"values[text]": "1"},
            {"values.text": "1"},
            {"values[text][a]": "1"},
        )
        for data in cases:
            with self.subTest(data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), False)
                self.assertEqual(form.errors.as_data()["values"][0].code, "required")


class WidgetIntegrationTestCase(SimpleTestCase):
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

    def test_unchecked_boolean_rows_keep_their_positions(self):
        """A false boolean row keeps its position, with or without a QueryDict."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.BooleanField(required=False))

        for data in (
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=2&values-{INITIAL_FORM_COUNT}=0&values-1=on"
            ),
            {"values-1": "on"},
        ):
            with self.subTest(data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                self.assertEqual(form.cleaned_data["values"], [False, True])

    def test_multiwidget_child_accepts_every_indexed_row_name(self):
        """It passes indexed row names into child multiwidgets for each spelling."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        for data in (
            {"values-0_0": "2024-01-02", "values-0_1": "03:04:05"},
            {"values.0_0": "2024-01-02", "values.0_1": "03:04:05"},
            {"values[0]_0": "2024-01-02", "values[0]_1": "03:04:05"},
        ):
            with self.subTest(data=data):
                form = Form(data)
                self.assertIs(form.is_valid(), True, form.errors)
                cleaned = form.cleaned_data["values"][0]
                self.assertEqual(
                    cleaned.replace(tzinfo=None),
                    datetime(2024, 1, 2, 3, 4, 5),  # noqa: DTZ001
                )

    def test_file_rows_keep_clear_and_delete_initial_values(self):
        """It keeps, clears, and deletes file rows, and preserves omitted ones."""
        initial = SimpleUploadedFile("initial.txt", b"initial")

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.FileField(required=False), required=False
            )

        kept = Form(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0"),
            initial={"values": [initial]},
        )
        self.assertIs(kept.is_valid(), True, kept.errors)
        self.assertIs(kept.cleaned_data["values"][0], initial)
        self.assertIs(kept["values"].value()[0], initial)

        clear_data = QueryDict(
            f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0",
            mutable=True,
        )
        clear_data["values-0-clear"] = "on"
        cleared = Form(clear_data, initial={"values": [initial]})
        self.assertIs(cleared.is_valid(), True, cleared.errors)
        self.assertEqual(cleared.cleaned_data["values"], [False])

        contradictory = Form(
            clear_data,
            files={"values-0": SimpleUploadedFile("new.txt", b"new")},
            initial={"values": [initial]},
        )
        self.assertIs(contradictory.is_valid(), False)
        self.assertEqual(
            contradictory.errors.as_data()["values"][0].code, "item_invalid"
        )

        deleted = Form(
            QueryDict(
                f"values-{TOTAL_FORM_COUNT}=1&"
                f"values-{INITIAL_FORM_COUNT}=0&"
                f"values-0-{DELETION_FIELD_NAME}=1"
            ),
            initial={"values": [initial]},
        )
        self.assertIs(deleted.is_valid(), True, deleted.errors)
        self.assertEqual(deleted.cleaned_data["values"], [])

        uploads = [
            SimpleUploadedFile("first.txt", b"first"),
            SimpleUploadedFile("second.txt", b"second"),
        ]
        for required in (False, True):
            OmittedForm = type(
                "OmittedForm",
                (forms.Form,),
                {
                    "values": nestingdolls.ListField(
                        forms.FileField(), required=required
                    )
                },
            )
            omitted = OmittedForm({}, initial={"values": uploads})

            with self.subTest(required=required):
                self.assertIs(omitted.is_valid(), True, omitted.errors)
                self.assertEqual(omitted.cleaned_data["values"], uploads)

        class OptionalForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), required=False)

        emptied = OptionalForm({"values": []}, initial={"values": uploads})
        self.assertIs(emptied.is_valid(), True, emptied.errors)
        self.assertEqual(emptied.cleaned_data["values"], [])

    def test_file_uploads_are_extracted_from_every_supported_source(self):
        """Uploads arrive through the child widget, flat keys, files, or a direct list."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.FileField())

        managed = Form(
            QueryDict(f"values-{TOTAL_FORM_COUNT}=1&values-{INITIAL_FORM_COUNT}=0"),
            files={"values-0": SimpleUploadedFile("one.txt", b"one")},
        )
        self.assertIs(managed.is_valid(), True, managed.errors)
        self.assertEqual(managed.cleaned_data["values"][0].name, "one.txt")

        flat = Form({}, files={"values.1": SimpleUploadedFile("one.txt", b"one")})
        self.assertIs(flat.is_valid(), True, flat.errors)
        self.assertEqual(flat.cleaned_data["values"][0].name, "one.txt")

        widget = nestingdolls.SequenceWidget(
            forms.CharField(required=False), max_length=1, absolute_max=2
        )
        self.assertEqual(
            widget.value_from_datadict({}, {"values": ["first", "second"]}, "values"),
            ["first", "second"],
        )

        class DataOrFilesWidget(forms.TextInput):
            def value_from_datadict(self, data, files, name):
                return data.get(name, files.get(name))

            def value_omitted_from_data(self, data, files, name):
                return name not in data and name not in files

        class TextForm(forms.Form):
            values = nestingdolls.ListField(
                forms.CharField(widget=DataOrFilesWidget), required=False
            )

        inferred = TextForm({"values-0": "data"}, files={"values-1": "file"})
        self.assertIs(inferred.is_valid(), True, inferred.errors)
        self.assertEqual(inferred.cleaned_data["values"], ["data", "file"])

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), required=False)

        first = SimpleUploadedFile("first.txt", b"first")
        second = SimpleUploadedFile("second.txt", b"second")
        files_authoritative = UploadForm(
            {},
            files={
                f"values-{TOTAL_FORM_COUNT}": "2",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": first,
                "values-1": second,
            },
        )
        self.assertIs(files_authoritative.is_valid(), True, files_authoritative.errors)
        self.assertEqual(files_authoritative.cleaned_data["values"], [first, second])

        malformed = TextForm(
            {
                f"values-{TOTAL_FORM_COUNT}": "not a number",
                f"values-{INITIAL_FORM_COUNT}": "0",
                "values-0": "data",
            },
            files={"values-1": "file"},
        )
        self.assertIs(malformed.is_valid(), False)
        self.assertIsInstance(
            malformed.errors.as_data()["values"][0],
            nestingdolls.MissingManagementFormValidationError,
        )
        self.assertEqual(
            malformed.errors.as_data()["values"][0].code,
            "missing_management_form",
        )
        html = malformed.as_p()
        self.assertInHTML(
            '<input type="hidden" name="values-TOTAL_FORMS" value="not a number" data-sequence-total id="id_values-TOTAL_FORMS">',
            html,
        )
        self.assertInHTML(
            '<input type="hidden" name="values-INITIAL_FORMS" value="0" id="id_values-INITIAL_FORMS">',
            html,
        )
        self.assertNotIn('name="values-0"', html)
        self.assertNotIn('name="values-1"', html)

    def test_reused_widget_derives_multipart_requirement_from_the_new_child(self):
        """It does not retain multipart state from a widget's original child."""
        text_widget = nestingdolls.SequenceWidget(forms.CharField())
        file_widget = nestingdolls.SequenceWidget(forms.FileField())

        class UploadForm(forms.Form):
            values = nestingdolls.ListField(forms.FileField(), widget=text_widget)

        class TextForm(forms.Form):
            values = nestingdolls.ListField(forms.CharField(), widget=file_widget)

        self.assertIs(UploadForm().is_multipart(), True)
        self.assertIs(TextForm().is_multipart(), False)

    def test_splitdatetime_initial_microseconds_do_not_report_a_change(self):
        """It applies Django's initial microsecond normalization to each row."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.SplitDateTimeField())

        initial = datetime(2024, 1, 2, 3, 4, 5, 123456)  # noqa: DTZ001
        initial_shapes = (
            {"values": [initial]},
            {"values": initial},
        )
        for initial_data in initial_shapes:
            with self.subTest(initial_data=initial_data):
                form = Form(
                    {"values-0_0": "2024-01-02", "values-0_1": "03:04:05"},
                    initial=initial_data,
                )
                self.assertIs(form.has_changed(), False)

    def test_form_required_attribute_opt_out_is_preserved(self):
        """It respects the form-level required-attribute opt-out."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField())

        self.assertNotIn(" required", Form(use_required_attribute=False).as_p())

    @override_settings(USE_I18N=True, LANGUAGE_CODE="de")
    def test_localize_propagates_to_child_cleaning_and_rendering(self):
        """It propagates localization to child cleaning and rendering."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.DecimalField(), localize=True)

        with translation.override("de"):
            form = Form({"values-0": "1,5"})

        self.assertIs(Form.base_fields["values"].child_field.localize, True)
        self.assertIs(form.is_valid(), True, form.errors)
        self.assertEqual(form.cleaned_data["values"], [Decimal("1.5")])

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

    def test_row_error_markup_describes_the_child_widgets(self):
        """A row error points every child subwidget at that row's error list."""

        class Form(forms.Form):
            values = nestingdolls.ListField(
                forms.IntegerField(
                    widget=forms.NumberInput(
                        attrs={"aria-describedby": "existing-description"}
                    )
                )
            )

        data = {
            "values-0": "bad",
            "values-TOTAL_FORMS": "1",
            "values-INITIAL_FORMS": "0",
        }
        cases = (
            (
                {},
                '<input type="number" name="values-0" value="bad" aria-describedby="existing-description id_values_0_error" aria-invalid="true" id="id_values_0">',
                '<ul class="errorlist" id="id_values_0_error"><li>Enter a whole number.</li></ul>',
            ),
            (
                {"auto_id": False},
                '<input type="number" name="values-0" value="bad" aria-describedby="existing-description" aria-invalid="true">',
                '<ul class="errorlist"><li>Enter a whole number.</li></ul>',
            ),
        )
        for kwargs, expected_input, expected_errors in cases:
            with self.subTest(kwargs=kwargs):
                form = Form(data, **kwargs)
                self.assertIs(form.is_valid(), False)
                html = form.as_div()
                self.assertInHTML(expected_input, html)
                self.assertInHTML(expected_errors, html)

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

    def test_add_button_survives_an_initial_at_or_over_the_maximum(self):
        """It keeps only the add template when initial rows fill or exceed the limit."""

        class Form(forms.Form):
            values = nestingdolls.ListField(forms.IntegerField(), max_length=2)

        for initial in ([1, 2], [1, 2, 3]):
            with self.subTest(initial=initial):
                html = Form(initial={"values": initial}).as_p()

                self.assertIn("data-sequence-add-button", html)
                self.assertInHTML(
                    '<button type="button" data-sequence-add data-sequence-field="values" id="id_values_add">Add another</button>',
                    html,
                )

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

        for kwargs in (
            {"min_length": -1},
            {"max_length": -1},
            {"min_length": 2, "max_length": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                nestingdolls.ListField(forms.IntegerField(), **kwargs)

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
        """It rejects invalid child fields and legacy widget arguments."""
        with self.assertRaises(ImproperlyConfigured):
            nestingdolls.ListField(object())
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), widget=forms.TextInput)
        with self.assertRaises(TypeError):
            nestingdolls.ListField(forms.IntegerField(), min_num=1)

    def test_widget_instance_is_copied_and_rebound_to_field_configuration(self):
        """Django copies a supplied widget before the field configures it."""
        original_child = forms.CharField()
        widget = nestingdolls.SequenceWidget(
            original_child,
            min_length=4,
            max_length=5,
            absolute_max=6,
        )

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
        self.assertEqual(field.absolute_max, 3)
        self.assertEqual(field.widget.limits.absolute_max, field.absolute_max)
        self.assertIs(widget.child_field, original_child)
        self.assertEqual(widget.limits.min_length, 4)
        self.assertEqual(widget.limits.max_length, 5)
        self.assertEqual(widget.limits.absolute_max, 6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
