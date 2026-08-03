# crosshair: analysis_kind=PEP316

from __future__ import annotations

from typing import cast

import django
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.formsets import (
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    TOTAL_FORM_COUNT,
)

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


_PROOF_ABSOLUTE_MAX = 4


def _integer_field(
    min_length: int = 0,
    max_length: int = 4,
    required: bool = True,
    absolute_max: int | None = None,
) -> nestingdolls.ListField:
    return nestingdolls.ListField(
        forms.IntegerField(),
        min_length=min_length,
        max_length=max_length,
        absolute_max=absolute_max,
        required=required,
    )


def _char_field() -> nestingdolls.ListField:
    return nestingdolls.ListField(forms.CharField(required=False), required=False)


def _tuple_pair_field(required: bool = False) -> nestingdolls.ListField:
    return nestingdolls.ListField(
        nestingdolls.TupleField(forms.IntegerField(), min_length=2, max_length=2),
        required=required,
    )


def _nested_list_field(required: bool = False) -> nestingdolls.ListField:
    return nestingdolls.ListField(
        nestingdolls.ListField(
            nestingdolls.ListField(forms.IntegerField(), required=False),
            required=False,
        ),
        required=required,
    )


def _set_field(min_length: int = 0, max_length: int = 4) -> nestingdolls.SetField:
    return nestingdolls.SetField(
        forms.IntegerField(),
        min_length=min_length,
        max_length=max_length,
        required=False,
    )


def _frozen_set_field() -> nestingdolls.FrozenSetField:
    return nestingdolls.FrozenSetField(forms.IntegerField(), required=False)


_PARSER_WIDGET = nestingdolls.SequenceWidget(
    forms.CharField(required=False), max_length=2, absolute_max=4
)


def _model_normalized_row_key(key: str) -> tuple[str, int] | None:
    for separator in ("-", ".", "["):
        prefix = f"values{separator}"
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        index_end = 0
        index = 0
        while index_end < len(suffix) and "0" <= suffix[index_end] <= "9":
            if index < 4:
                index = min(4, index * 10 + ord(suffix[index_end]) - ord("0"))
            index_end += 1
        if index_end == 0:
            return None
        if separator == "[":
            if index_end == len(suffix) or suffix[index_end] != "]":
                return None
            suffix = suffix[index_end + 1 :]
        else:
            suffix = suffix[index_end:]
        if suffix and suffix[0] not in "_-.[":
            return None
        return (f"values-{index}{suffix}", index)
    return None


def actual_arbitrary_key_normalization(key: str) -> tuple[str, ...]:
    """pre: len(key) <= 8"""
    normalized = _PARSER_WIDGET._normalize_mapping({key: "x"}, "values")
    return tuple(sorted(normalized))


def model_arbitrary_key_normalization(key: str) -> tuple[str, ...]:
    """pre: len(key) <= 8"""
    management_names = _PARSER_WIDGET.management_names("values")
    if key in management_names:
        return (key,)
    if key == "values":
        return tuple(
            sorted(
                (
                    "values",
                    f"values-{TOTAL_FORM_COUNT}",
                    f"values-{INITIAL_FORM_COUNT}",
                )
            )
        )
    row_key = _model_normalized_row_key(key)
    if row_key is None:
        return ()
    canonical, index = row_key
    keys = [f"values-{TOTAL_FORM_COUNT}", f"values-{INITIAL_FORM_COUNT}"]
    if index < 4:
        original_prefix = f"values-{index}"
        mapped_index = min(index, 1)
        keys.append(f"values-{mapped_index}{canonical.removeprefix(original_prefix)}")
    return tuple(sorted(keys))


def prove_arbitrary_key_normalization(key: str) -> bool:
    """
    pre: len(key) <= 8
    post[]: __return__
    """
    return actual_arbitrary_key_normalization(key) == model_arbitrary_key_normalization(
        key
    )


def actual_saturated_index(digits: str) -> tuple[str, bool]:
    """
    pre: 1 <= len(digits) <= 6
    pre: all("0" <= digit <= "9" for digit in digits)
    """
    if not 1 <= len(digits) <= 6 or any(digit < "0" or digit > "9" for digit in digits):
        return ("invalid", False)
    normalized = _PARSER_WIDGET._normalize_mapping({f"values-{digits}": "x"}, "values")
    total = normalized.get(f"values-{TOTAL_FORM_COUNT}")
    row_present = any(
        key not in _PARSER_WIDGET.management_names("values") for key in normalized
    )
    return (total if isinstance(total, str) else "", row_present)


def model_saturated_index(digits: str) -> tuple[str, bool]:
    """
    pre: 1 <= len(digits) <= 6
    pre: all("0" <= digit <= "9" for digit in digits)
    """
    if not 1 <= len(digits) <= 6 or any(digit < "0" or digit > "9" for digit in digits):
        return ("invalid", False)
    index = 0
    for digit in digits:
        if index < 4:
            index = min(4, index * 10 + ord(digit) - ord("0"))
    if index >= 4:
        return ("5", False)
    return (str(min(index, 1) + 1), True)


def prove_saturated_index(digits: str) -> bool:
    """
    pre: 1 <= len(digits) <= 6
    pre: all("0" <= digit <= "9" for digit in digits)
    post[]: __return__
    """
    return actual_saturated_index(digits) == model_saturated_index(digits)


def actual_clean_cardinality(
    min_length: int, max_length: int, required: bool, values: list[int]
) -> tuple[str, tuple[int, ...]]:
    """
    pre: 0 <= min_length <= max_length <= _PROOF_ABSOLUTE_MAX
    pre: len(values) <= _PROOF_ABSOLUTE_MAX + 1
    """
    try:
        field = _integer_field(
            min_length=min_length,
            max_length=max_length,
            required=required,
            absolute_max=_PROOF_ABSOLUTE_MAX,
        )
    except ValueError:
        return ("constructor_error", ())
    try:
        cleaned = cast(list[int], field.clean(values))
    except ValidationError as exc:
        return (exc.code or "invalid", ())
    return ("ok", tuple(cleaned))


def model_clean_cardinality(
    min_length: int, max_length: int, required: bool, values: list[int]
) -> tuple[str, tuple[int, ...]]:
    """
    pre: 0 <= min_length <= max_length <= _PROOF_ABSOLUTE_MAX
    pre: len(values) <= _PROOF_ABSOLUTE_MAX + 1
    """
    if (
        min_length < 0
        or max_length < 0
        or min_length > max_length
        or max_length > _PROOF_ABSOLUTE_MAX
    ):
        return ("constructor_error", ())
    length = len(values)
    if length > _PROOF_ABSOLUTE_MAX:
        return ("too_many_forms", ())
    if length == 0 and required:
        return ("required", ())
    if length == 0:
        return ("ok", ())
    if length < min_length:
        return ("min_length", ())
    if length > max_length:
        return ("max_length", ())
    return ("ok", tuple(values))


def prove_clean_cardinality(
    min_length: int, max_length: int, required: bool, values: list[int]
) -> bool:
    """
    pre: 0 <= min_length <= max_length <= 4
    pre: len(values) <= 5
    post[]: __return__
    """
    return actual_clean_cardinality(
        min_length, max_length, required, values
    ) == model_clean_cardinality(min_length, max_length, required, values)


def actual_has_changed_integer_rows(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    return _integer_field(required=False).has_changed(initial, data)


def model_has_changed_integer_rows(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    if len(initial) != len(data):
        return True
    for index, initial_value in enumerate(initial):
        if initial_value != data[index]:
            return True
    return False


def prove_has_changed_integer_rows(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    post[]: __return__
    """
    return actual_has_changed_integer_rows(
        initial, data
    ) == model_has_changed_integer_rows(initial, data)


def actual_alias_collision(
    first_style: int, first_value: str, second_style: int, second_value: str
) -> tuple[str, ...]:
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    """
    if not 0 <= first_style <= 2 or not 0 <= second_style <= 2:
        return ("invalid_style",)
    field = _char_field()
    keys = ("values-0", "values.0", "values[00]")
    data = {
        keys[first_style]: first_value,
        keys[second_style]: second_value,
    }
    return tuple(field.widget.value_from_datadict(data, {}, "values"))


def model_alias_collision(
    first_style: int, first_value: str, second_style: int, second_value: str
) -> tuple[str, ...]:
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    """
    if not 0 <= first_style <= 2 or not 0 <= second_style <= 2:
        return ("invalid_style",)
    del first_style, first_value, second_style
    return (second_value,)


def prove_alias_collision(
    first_style: int, first_value: str, second_style: int, second_value: str
) -> bool:
    """
    pre: 0 <= first_style <= 2
    pre: 0 <= second_style <= 2
    post[]: __return__
    """
    return actual_alias_collision(
        first_style, first_value, second_style, second_value
    ) == model_alias_collision(first_style, first_value, second_style, second_value)


def actual_clean_with_deleted_and_omitted(
    values: list[int],
    initial_values: list[int],
    deleted_indexes: list[int],
    omitted_indexes: list[int],
) -> tuple[str, tuple[int, ...]]:
    """
    pre: len(values) <= 4
    pre: len(initial_values) <= 4
    pre: len(deleted_indexes) <= 4
    pre: len(omitted_indexes) <= 4
    pre: all(0 <= index < len(values) for index in deleted_indexes)
    pre: all(0 <= index < len(values) for index in omitted_indexes)
    """
    field = _integer_field(required=False)
    object_values = cast(list[object], values)
    object_initial_values = cast(list[object], initial_values)
    try:
        cleaned = cast(
            list[int],
            field._clean_values(
                object_values,
                object_initial_values,
                frozenset(deleted_indexes),
                frozenset(omitted_indexes),
            ),
        )
    except ValidationError as exc:
        return (exc.code or "invalid", ())
    return ("ok", tuple(cleaned))


def model_clean_with_deleted_and_omitted(
    values: list[int],
    initial_values: list[int],
    deleted_indexes: list[int],
    omitted_indexes: list[int],
) -> tuple[str, tuple[int, ...]]:
    """
    pre: len(values) <= 4
    pre: len(initial_values) <= 4
    pre: len(deleted_indexes) <= 4
    pre: len(omitted_indexes) <= 4
    pre: all(0 <= index < len(values) for index in deleted_indexes)
    pre: all(0 <= index < len(values) for index in omitted_indexes)
    """
    del initial_values
    skipped = set(deleted_indexes) | set(omitted_indexes)
    return (
        "ok",
        tuple(value for index, value in enumerate(values) if index not in skipped),
    )


def prove_clean_with_deleted_and_omitted(
    values: list[int],
    initial_values: list[int],
    deleted_indexes: list[int],
    omitted_indexes: list[int],
) -> bool:
    """
    pre: len(values) <= 4
    pre: len(initial_values) <= 4
    pre: len(deleted_indexes) <= 4
    pre: len(omitted_indexes) <= 4
    pre: all(0 <= index < len(values) for index in deleted_indexes)
    pre: all(0 <= index < len(values) for index in omitted_indexes)
    post[]: __return__
    """
    return actual_clean_with_deleted_and_omitted(
        values, initial_values, deleted_indexes, omitted_indexes
    ) == model_clean_with_deleted_and_omitted(
        values, initial_values, deleted_indexes, omitted_indexes
    )


def actual_deleted_indexes(delete_flags: list[bool]) -> tuple[int, ...]:
    """pre: len(delete_flags) <= 4"""

    class Form(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), required=False)

    data: dict[str, object] = {
        f"values-{TOTAL_FORM_COUNT}": str(len(delete_flags)),
        f"values-{INITIAL_FORM_COUNT}": "0",
    }
    for index, delete_flag in enumerate(delete_flags):
        data[f"values-{index}"] = str(index)
        if delete_flag:
            data[f"values-{index}-{DELETION_FIELD_NAME}"] = "1"
    bound_field = cast(nestingdolls.SequenceBoundField, Form(data)["values"])
    return tuple(sorted(bound_field._deleted_indexes))


def model_deleted_indexes(delete_flags: list[bool]) -> tuple[int, ...]:
    """pre: len(delete_flags) <= 4"""
    return tuple(index for index, delete_flag in enumerate(delete_flags) if delete_flag)


def prove_deleted_indexes(delete_flags: list[bool]) -> bool:
    """
    pre: len(delete_flags) <= 4
    post[]: __return__
    """
    return actual_deleted_indexes(delete_flags) == model_deleted_indexes(delete_flags)


def actual_omitted_extra_indexes(
    total_forms: int, present_indexes: list[int], initial_count: int
) -> tuple[int, ...]:
    """
    pre: 0 <= total_forms <= 4
    pre: 0 <= initial_count <= total_forms
    pre: len(present_indexes) <= 4
    pre: all(0 <= index < total_forms for index in present_indexes)
    """

    class Form(forms.Form):
        values = nestingdolls.ListField(forms.IntegerField(), required=False)

    data: dict[str, object] = {
        f"values-{TOTAL_FORM_COUNT}": str(total_forms),
        f"values-{INITIAL_FORM_COUNT}": str(initial_count),
    }
    for index in present_indexes:
        data[f"values-{index}"] = str(index)
    initial = {"values": list(range(initial_count))}
    bound_field = cast(
        nestingdolls.SequenceBoundField, Form(data, initial=initial)["values"]
    )
    return tuple(sorted(bound_field._omitted_indexes))


def model_omitted_extra_indexes(
    total_forms: int, present_indexes: list[int], initial_count: int
) -> tuple[int, ...]:
    """
    pre: 0 <= total_forms <= 4
    pre: 0 <= initial_count <= total_forms
    pre: len(present_indexes) <= 4
    pre: all(0 <= index < total_forms for index in present_indexes)
    """
    present = set(present_indexes)
    return tuple(
        index
        for index in range(total_forms)
        if index >= initial_count and index not in present
    )


def prove_omitted_extra_indexes(
    total_forms: int, present_indexes: list[int], initial_count: int
) -> bool:
    """
    pre: 0 <= total_forms <= 4
    pre: 0 <= initial_count <= total_forms
    pre: len(present_indexes) <= 4
    pre: all(0 <= index < total_forms for index in present_indexes)
    post[]: __return__
    """
    return actual_omitted_extra_indexes(
        total_forms, present_indexes, initial_count
    ) == model_omitted_extra_indexes(total_forms, present_indexes, initial_count)


def actual_nested_tuple_rows(
    row0_left: int,
    row0_right: int,
    row1_left: int,
    row1_right: int,
    include_second_row: bool,
) -> tuple[tuple[int, int], ...]:
    class Form(forms.Form):
        values = _tuple_pair_field()

    data: dict[str, object] = {
        "values-0-0": str(row0_left),
        "values-0-1": str(row0_right),
    }
    if include_second_row:
        data["values-1-0"] = str(row1_left)
        data["values-1-1"] = str(row1_right)
    form = Form(data)
    if not form.is_valid():
        return ()
    return tuple(cast(list[tuple[int, int]], form.cleaned_data["values"]))


def model_nested_tuple_rows(
    row0_left: int,
    row0_right: int,
    row1_left: int,
    row1_right: int,
    include_second_row: bool,
) -> tuple[tuple[int, int], ...]:
    rows = [(row0_left, row0_right)]
    if include_second_row:
        rows.append((row1_left, row1_right))
    return tuple(rows)


def prove_nested_tuple_rows(
    row0_left: int,
    row0_right: int,
    row1_left: int,
    row1_right: int,
    include_second_row: bool,
) -> bool:
    """
    post[]: __return__
    """
    return actual_nested_tuple_rows(
        row0_left, row0_right, row1_left, row1_right, include_second_row
    ) == model_nested_tuple_rows(
        row0_left, row0_right, row1_left, row1_right, include_second_row
    )


def actual_nested_tuple_has_changed(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    initial = [(initial_left, initial_right)]
    data = [[data_left, data_right]]
    return _tuple_pair_field(required=False).has_changed(initial, data)


def model_nested_tuple_has_changed(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    return (initial_left, initial_right) != (data_left, data_right)


def prove_nested_tuple_has_changed(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    """
    post[]: __return__
    """
    return actual_nested_tuple_has_changed(
        initial_left, initial_right, data_left, data_right
    ) == model_nested_tuple_has_changed(
        initial_left, initial_right, data_left, data_right
    )


def actual_tuple_child_delegation(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    child = nestingdolls.TupleField(forms.IntegerField(), min_length=2, max_length=2)
    parent = nestingdolls.ListField(child, required=False)
    return parent.has_changed(
        [(initial_left, initial_right)], [[data_left, data_right]]
    )


def model_tuple_child_delegation(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    child = nestingdolls.TupleField(forms.IntegerField(), min_length=2, max_length=2)
    return child.has_changed((initial_left, initial_right), [data_left, data_right])


def prove_tuple_child_delegation(
    initial_left: int, initial_right: int, data_left: int, data_right: int
) -> bool:
    """
    post[]: __return__
    """
    return actual_tuple_child_delegation(
        initial_left, initial_right, data_left, data_right
    ) == model_tuple_child_delegation(
        initial_left, initial_right, data_left, data_right
    )


def actual_set_dedup(values: list[int]) -> tuple[str, tuple[int, ...]]:
    """pre: len(values) <= 4"""
    try:
        cleaned = cast(set[int], _set_field().clean(values))
    except ValidationError as exc:
        return (exc.code or "invalid", ())
    return ("ok", tuple(sorted(cleaned)))


def model_set_dedup(values: list[int]) -> tuple[str, tuple[int, ...]]:
    """pre: len(values) <= 4"""
    if len(set(values)) == 0:
        return ("ok", ())
    if len(set(values)) > 4:
        return ("max_length", ())
    return ("ok", tuple(sorted(set(values))))


def prove_set_dedup(values: list[int]) -> bool:
    """
    pre: len(values) <= 4
    post[]: __return__
    """
    return actual_set_dedup(values) == model_set_dedup(values)


def actual_set_cardinality_after_dedup(
    min_length: int, max_length: int, values: list[int]
) -> tuple[str, tuple[int, ...]]:
    """
    pre: 0 <= min_length <= max_length <= 4
    pre: len(values) <= 4
    """
    try:
        field = _set_field(min_length=min_length, max_length=max_length)
    except ValueError:
        return ("constructor_error", ())
    try:
        cleaned = cast(set[int], field.clean(values))
    except ValidationError as exc:
        return (exc.code or "invalid", ())
    return ("ok", tuple(sorted(cleaned)))


def model_set_cardinality_after_dedup(
    min_length: int, max_length: int, values: list[int]
) -> tuple[str, tuple[int, ...]]:
    """
    pre: 0 <= min_length <= max_length <= 4
    pre: len(values) <= 4
    """
    if min_length < 0 or max_length < 0 or min_length > max_length:
        return ("constructor_error", ())
    deduped = tuple(sorted(set(values)))
    length = len(deduped)
    if length == 0:
        return ("ok", ())
    if length < min_length:
        return ("min_length", ())
    if length > max_length:
        return ("max_length", ())
    return ("ok", deduped)


def prove_set_cardinality_after_dedup(
    min_length: int, max_length: int, values: list[int]
) -> bool:
    """
    pre: 0 <= min_length <= max_length <= 4
    pre: len(values) <= 4
    post[]: __return__
    """
    return actual_set_cardinality_after_dedup(
        min_length, max_length, values
    ) == model_set_cardinality_after_dedup(min_length, max_length, values)


def actual_frozenset_has_changed(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    return _frozen_set_field().has_changed(frozenset(initial), data)


def model_frozenset_has_changed(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    return frozenset(initial) != frozenset(data)


def prove_frozenset_has_changed(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    post[]: __return__
    """
    return actual_frozenset_has_changed(initial, data) == model_frozenset_has_changed(
        initial, data
    )


def actual_frozenset_child_delegation(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    child = nestingdolls.FrozenSetField(forms.IntegerField(), required=False)
    parent = nestingdolls.ListField(child, required=False)
    return parent.has_changed([frozenset(initial)], [data])


def model_frozenset_child_delegation(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    """
    child = nestingdolls.FrozenSetField(forms.IntegerField(), required=False)
    return child.has_changed(frozenset(initial), data)


def prove_frozenset_child_delegation(initial: list[int], data: list[int]) -> bool:
    """
    pre: len(initial) <= 4
    pre: len(data) <= 4
    post[]: __return__
    """
    return actual_frozenset_child_delegation(
        initial, data
    ) == model_frozenset_child_delegation(initial, data)
