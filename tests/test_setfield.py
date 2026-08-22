"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django import forms
from django.core.exceptions import ValidationError
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.test import override_settings
from django.test.utils import setup_test_environment, teardown_test_environment

import nestingdolls

from .support.testcases import CompositeFieldTestCase


def setUpModule() -> None:
    """Set up the module test environment."""
    setup_test_environment()


def tearDownModule() -> None:
    """Tear down the module test environment."""
    teardown_test_environment()


@override_settings(ROOT_URLCONF="tests.support.urls")
class SetFieldTestCase(CompositeFieldTestCase):
    """Tests ``SetField`` and ``FrozenSetField``.

    The tests cover deduplication, cardinality, hashability, and bounded change
    detection.
    """

    def test_cardinality_is_checked_after_deduplication(self) -> None:
        """It checks set cardinality after removing duplicates."""
        field = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)

        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "1"])
        self.assertEqual(context.exception.code, "min_length")

        field = nestingdolls.SetField(forms.IntegerField(), max_length=1)
        self.assertEqual(field.clean(["1", "1"]), {1})

    def test_client_deduplicates_before_cardinality_validation(self) -> None:
        """Test client deduplicates before cardinality validation."""

        def submit(*values: object) -> object:
            return self.client.post(
                "/set-submission-probe/",
                {
                    f"values-{TOTAL_FORM_COUNT}": str(len(values)),
                    f"values-{INITIAL_FORM_COUNT}": "0",
                    **{f"values-{index}": value for index, value in enumerate(values)},
                },
            )

        duplicate = submit("1", "1")
        self.assertJSONResponse(
            duplicate,
            {"valid": False, "values": None, "errors": {"values": ["min_length"]}},
        )

        deduplicated = submit("1", "1", "2")
        self.assertJSONResponse(
            deduplicated, {"valid": True, "values": [1, 2], "errors": {}}
        )

        too_many = submit("1", "2", "3")
        self.assertJSONResponse(
            too_many,
            {"valid": False, "values": None, "errors": {"values": ["max_length"]}},
        )

    def test_frozen_set_field_is_an_immutable_set_variant(self) -> None:
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

    def assertOversizedWholeValueMarksChanged(  # noqa: D102
        self, field_class: object, expected_initial: object
    ) -> None:

        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial: object, data: object) -> object:
                raise AssertionError("oversized child value was compared")

        field = field_class(UnreachableField(), max_length=0, required=False)
        values = ["1"] * (field.limits.absolute_max + 1)
        self.assertIs(field.has_changed(expected_initial, values), True)

    def test_oversized_whole_value_marks_set_changed_without_child_comparison(
        self,
    ) -> None:
        """An oversized set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(nestingdolls.SetField, set())

    def test_oversized_whole_value_marks_frozen_set_changed_without_child_comparison(
        self,
    ) -> None:
        """An oversized frozen set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(
            nestingdolls.FrozenSetField, frozenset()
        )

    def test_has_changed_uses_linear_comparisons_for_hashable_members(self) -> None:
        """Reordered unique integer members use indexed child comparisons."""

        class CountingIntegerField(forms.IntegerField):
            comparisons = 0

            def has_changed(self, initial: object, data: object) -> object:
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

    def test_has_changed_bounds_comparisons_for_non_matching_rows(self) -> None:
        """A hostile submission cannot make set comparison quadratic.

        Submitted rows can reach ``absolute_max``. Budget exhaustion reports a
        change, which is safer than a missed change.
        """

        class CountingCharField(forms.CharField):
            comparisons = 0

            def has_changed(self, initial: object, data: object) -> object:
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

    def test_has_changed_reports_unhashable_rows_as_changed(self) -> None:
        """A compound child's unhashable rows count as a change, never a miss."""
        field = nestingdolls.SetField(
            forms.MultipleChoiceField(
                choices=[("first", "First"), ("second", "Second")]
            ),
            required=False,
        )

        self.assertIs(
            field.has_changed({("first", "second")}, [["second", "first"]]), True
        )
        self.assertIs(field.has_changed({("first", "second")}, [["first"]]), True)

    def test_has_changed_keeps_duplicate_blank_invalid_and_json_semantics(
        self,
    ) -> None:
        """Indexed matching preserves the child field's semantic edge cases."""
        integer_field = nestingdolls.SetField(
            forms.IntegerField(required=False), required=False
        )
        json_field = nestingdolls.SetField(forms.JSONField(), required=False)

        self.assertIs(integer_field.has_changed({1}, ["1", "1", ""]), False)
        self.assertIs(integer_field.has_changed({1}, ["invalid"]), True)
        self.assertIs(json_field.has_changed({True}, ["1"]), True)

    def test_direct_disabled_and_unreadable_values_answer_without_member_pairing(
        self,
    ) -> None:
        """A disabled set reports no change. An unreadable value reports a change."""
        disabled = nestingdolls.SetField(
            forms.IntegerField(), required=False, disabled=True
        )
        field = nestingdolls.SetField(forms.IntegerField(), required=False)

        self.assertIs(disabled.has_changed({1}, ["2"]), False)
        self.assertIs(field.has_changed("bad", ["1"]), True)
        self.assertIs(field.has_changed({1}, "bad"), True)

    def test_set_cleaned_output_cleans_again(self) -> None:
        """The set ``compress`` produced is valid input for ``clean``."""
        self.assertCleanedOutputCleansAgain(
            nestingdolls.SetField(forms.IntegerField()), ["1", "2"]
        )

    def test_frozen_set_cleaned_output_cleans_again(self) -> None:
        """The frozenset ``compress`` produced is valid input for ``clean``."""
        self.assertCleanedOutputCleansAgain(
            nestingdolls.FrozenSetField(forms.IntegerField()), ["1", "2"]
        )

    def assertEmptyValueSkipsValidators(  # noqa: D102
        self, field_class: object, empty_collection: object
    ) -> None:
        calls = []
        field = field_class(
            forms.IntegerField(), required=False, validators=[calls.append]
        )

        self.assertEqual(field.clean([]), empty_collection)
        # An empty ``ListField`` skips its validators because ``[]`` is in
        # Django's ``EMPTY_VALUES``; a set variant must behave the same.
        self.assertEqual(calls, [])

        self.assertEqual(field.clean(["1"]), type(empty_collection)({1}))
        self.assertEqual(calls, [type(empty_collection)({1})])

    def test_empty_set_skips_validators_like_an_empty_list(self) -> None:
        """An empty set is an empty value, so validators do not run."""
        self.assertEmptyValueSkipsValidators(nestingdolls.SetField, set())

    def test_empty_frozen_set_skips_validators_like_an_empty_list(self) -> None:
        """An empty frozenset is an empty value, so validators do not run."""
        self.assertEmptyValueSkipsValidators(nestingdolls.FrozenSetField, frozenset())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
