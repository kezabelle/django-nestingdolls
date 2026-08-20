"""Tests for one cohesive composite-field behavior cohort."""

from __future__ import annotations

import unittest

from django.test.utils import setup_test_environment, teardown_test_environment

from .support import (
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
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


@override_settings(ROOT_URLCONF="tests.support")
class SetFieldTestCase(SimpleTestCase):
    """Tests ``SetField`` and ``FrozenSetField``.

    The tests cover deduplication, cardinality, hashability, and bounded change
    detection."""

    def test_cardinality_is_checked_after_deduplication(self):
        """It checks set cardinality after removing duplicates."""
        field = nestingdolls.SetField(forms.IntegerField(), min_length=2, max_length=2)

        with self.assertRaises(ValidationError) as context:
            field.clean(["1", "1"])
        self.assertEqual(context.exception.code, "min_length")

        field = nestingdolls.SetField(forms.IntegerField(), max_length=1)
        self.assertEqual(field.clean(["1", "1"]), {1})

    def test_client_deduplicates_before_cardinality_validation(self):
        def submit(*values):
            return self.client.post(
                "/set-submission-probe/",
                {
                    f"values-{TOTAL_FORM_COUNT}": str(len(values)),
                    f"values-{INITIAL_FORM_COUNT}": "0",
                    **{f"values-{index}": value for index, value in enumerate(values)},
                },
            )

        duplicate = submit("1", "1")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(
            duplicate.json(),
            {"valid": False, "values": None, "errors": {"values": ["min_length"]}},
        )

        deduplicated = submit("1", "1", "2")
        self.assertEqual(deduplicated.status_code, 200)
        self.assertEqual(
            deduplicated.json(),
            {"valid": True, "values": [1, 2], "errors": {}},
        )

        too_many = submit("1", "2", "3")
        self.assertEqual(too_many.status_code, 200)
        self.assertEqual(
            too_many.json(),
            {"valid": False, "values": None, "errors": {"values": ["max_length"]}},
        )

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

    def assertOversizedWholeValueMarksChanged(self, field_class, expected_initial):
        class UnreachableField(forms.IntegerField):
            def has_changed(self, initial, data):
                raise AssertionError("oversized child value was compared")

        field = field_class(UnreachableField(), max_length=0, required=False)
        values = ["1"] * (field.limits.absolute_max + 1)
        self.assertIs(field.has_changed(expected_initial, values), True)

    def test_oversized_whole_value_marks_set_changed_without_child_comparison(self):
        """An oversized set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(nestingdolls.SetField, set())

    def test_oversized_whole_value_marks_frozen_set_changed_without_child_comparison(
        self,
    ):
        """An oversized frozen set whole value is changed without child comparison."""
        self.assertOversizedWholeValueMarksChanged(
            nestingdolls.FrozenSetField, frozenset()
        )

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
        """A hostile submission cannot make set comparison quadratic.

        Submitted rows can reach ``absolute_max``. Budget exhaustion reports a
        change, which is safer than a missed change.
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

    def test_has_changed_reports_unhashable_rows_as_changed(self):
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

    def test_has_changed_keeps_duplicate_blank_invalid_and_json_semantics(self):
        """Indexed matching preserves the child field's semantic edge cases."""
        integer_field = nestingdolls.SetField(
            forms.IntegerField(required=False), required=False
        )
        json_field = nestingdolls.SetField(forms.JSONField(), required=False)

        self.assertIs(integer_field.has_changed({1}, ["1", "1", ""]), False)
        self.assertIs(integer_field.has_changed({1}, ["invalid"]), True)
        self.assertIs(json_field.has_changed({True}, ["1"]), True)

    def test_direct_disabled_and_unreadable_values_answer_without_member_pairing(self):
        """A disabled set reports no change. An unreadable value reports a change."""
        disabled = nestingdolls.SetField(
            forms.IntegerField(), required=False, disabled=True
        )
        field = nestingdolls.SetField(forms.IntegerField(), required=False)

        self.assertIs(disabled.has_changed({1}, ["2"]), False)
        self.assertIs(field.has_changed("bad", ["1"]), True)
        self.assertIs(field.has_changed({1}, "bad"), True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
