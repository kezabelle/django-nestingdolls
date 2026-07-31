PYTHON := .direnv/python-3.13/bin/python
TSC := ./node_modules/typescript/bin/tsc

.PHONY: js tscheck ruff mypy test check crosshair crosshair-cover crosshair-diff crosshair-slow

js:
	$(TSC) -p tsconfig.json

tscheck:
	$(TSC) -p tsconfig.json --noEmit

ruff:
	$(PYTHON) -m ruff check nestingdolls/__init__.py test_listfield.py test_settings.py

mypy:
	DJANGO_SETTINGS_MODULE=test_settings $(PYTHON) -m mypy --strict nestingdolls/__init__.py

test:
	$(PYTHON) test_listfield.py

check: tscheck ruff mypy test

crosshair:
	uv run crosshair check proof_listfield.py

crosshair-cover:
	uv run crosshair cover --example_output_format=pytest proof_listfield.prove_clean_cardinality proof_listfield.prove_has_changed_integer_rows proof_listfield.prove_alias_collision proof_listfield.prove_clean_with_deleted_and_omitted proof_listfield.prove_nested_tuple_rows proof_listfield.prove_set_dedup

crosshair-diff:
	uv run crosshair diffbehavior proof_listfield.actual_clean_cardinality proof_listfield.model_clean_cardinality
	uv run crosshair diffbehavior proof_listfield.actual_has_changed_integer_rows proof_listfield.model_has_changed_integer_rows
	uv run crosshair diffbehavior proof_listfield.actual_single_row_spelling proof_listfield.model_single_row_spelling
	uv run crosshair diffbehavior proof_listfield.actual_direct_value_precedence proof_listfield.model_direct_value_precedence
	uv run crosshair diffbehavior proof_listfield.actual_alias_collision proof_listfield.model_alias_collision
	uv run crosshair diffbehavior proof_listfield.actual_generated_management_total proof_listfield.model_generated_management_total
	uv run crosshair diffbehavior proof_listfield.actual_clean_with_deleted_and_omitted proof_listfield.model_clean_with_deleted_and_omitted
	uv run crosshair diffbehavior proof_listfield.actual_deleted_indexes proof_listfield.model_deleted_indexes
	uv run crosshair diffbehavior proof_listfield.actual_omitted_extra_indexes proof_listfield.model_omitted_extra_indexes
	uv run crosshair diffbehavior proof_listfield.actual_nested_tuple_rows proof_listfield.model_nested_tuple_rows
	uv run crosshair diffbehavior proof_listfield.actual_nested_tuple_extra_item proof_listfield.model_nested_tuple_extra_item
	uv run crosshair diffbehavior proof_listfield.actual_nested_tuple_has_changed proof_listfield.model_nested_tuple_has_changed
	uv run crosshair diffbehavior proof_listfield.actual_tuple_child_delegation proof_listfield.model_tuple_child_delegation
	uv run crosshair diffbehavior proof_listfield.actual_set_dedup proof_listfield.model_set_dedup
	uv run crosshair diffbehavior proof_listfield.actual_set_cardinality_after_dedup proof_listfield.model_set_cardinality_after_dedup
	uv run crosshair diffbehavior proof_listfield.actual_frozenset_has_changed proof_listfield.model_frozenset_has_changed
	uv run crosshair diffbehavior proof_listfield.actual_frozenset_child_delegation proof_listfield.model_frozenset_child_delegation

crosshair-slow:
	uv run crosshair check --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.py
