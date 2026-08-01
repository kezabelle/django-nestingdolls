UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
CROSSHAIR := $(UV_RUN) crosshair
TSC := ./node_modules/typescript/bin/tsc

DEFAULT_GOAL := help

.PHONY: js tscheck format ruff mypy test agents check crosshair crosshair-diff crosshair-slow

.DEFAULT_GOAL := $(DEFAULT_GOAL)

help: ## Show targets and short task text. (This command)
	@awk 'BEGIN {FS = ": ## " ; print "Available targets\n-----------------"} /^[[:alnum:]_-]+: ## / {print $$1 " → " $$2}' $(MAKEFILE_LIST)

js: ## Build JavaScript from TypeScript.
	$(TSC) -p tsconfig.json

tscheck: ## Check TypeScript. Do not write files.
	$(TSC) -p tsconfig.json --noEmit

format: ## Run Ruff formatter on maintained Python files.
	$(RUFF) format demo.py nestingdolls test_dictfield.py test_listfield.py test_settings.py proof_dictfield.py proof_listfield.py scripts/update_package_agents.py

ruff: ## Run Ruff with auto-fixes on kept Python files.
	$(RUFF) check --fix demo.py nestingdolls test_dictfield.py test_listfield.py test_settings.py proof_dictfield.py proof_listfield.py scripts/update_package_agents.py

mypy: ## Run mypy with strict checks.
	$(MYPY) demo.py nestingdolls/__init__.py nestingdolls/errors.py nestingdolls/mappings.py nestingdolls/sequences.py

test: ## Run the Django test files.
	$(PYTHON) -m unittest test_listfield test_dictfield

agents: ## Update the generated field method reference in nestingdolls/AGENTS.md.
	$(PYTHON) scripts/update_package_agents.py

check: ## Update generated docs and run all fast checks.
check: tscheck ruff mypy test agents

crosshair: ## Run CrossHair checks.
	$(CROSSHAIR) check proof_listfield.prove_arbitrary_key_normalization proof_listfield.prove_saturated_index proof_listfield.prove_management_source_precedence proof_listfield.prove_absolute_limit proof_listfield.prove_clean_cardinality proof_listfield.prove_clean_with_deleted_and_omitted proof_listfield.prove_nested_tuple_rows proof_listfield.prove_set_cardinality_after_dedup proof_dictfield.prove_mapping_presence proof_dictfield.prove_nested_sequence

crosshair-diff: ## Compare actual and model behavior.
	$(CROSSHAIR) diffbehavior proof_listfield.actual_clean_cardinality proof_listfield.model_clean_cardinality
	$(CROSSHAIR) diffbehavior proof_listfield.actual_has_changed_integer_rows proof_listfield.model_has_changed_integer_rows
	$(CROSSHAIR) diffbehavior proof_listfield.actual_arbitrary_key_normalization proof_listfield.model_arbitrary_key_normalization
	$(CROSSHAIR) diffbehavior proof_listfield.actual_saturated_index proof_listfield.model_saturated_index
	$(CROSSHAIR) diffbehavior proof_listfield.actual_management_source_precedence proof_listfield.model_management_source_precedence
	$(CROSSHAIR) diffbehavior proof_listfield.actual_absolute_limit proof_listfield.model_absolute_limit
	$(CROSSHAIR) diffbehavior proof_listfield.actual_alias_collision proof_listfield.model_alias_collision
	$(CROSSHAIR) diffbehavior proof_listfield.actual_clean_with_deleted_and_omitted proof_listfield.model_clean_with_deleted_and_omitted
	$(CROSSHAIR) diffbehavior proof_listfield.actual_deleted_indexes proof_listfield.model_deleted_indexes
	$(CROSSHAIR) diffbehavior proof_listfield.actual_omitted_extra_indexes proof_listfield.model_omitted_extra_indexes
	$(CROSSHAIR) diffbehavior proof_listfield.actual_nested_tuple_rows proof_listfield.model_nested_tuple_rows
	$(CROSSHAIR) diffbehavior proof_listfield.actual_nested_tuple_extra_item proof_listfield.model_nested_tuple_extra_item
	$(CROSSHAIR) diffbehavior proof_listfield.actual_nested_tuple_has_changed proof_listfield.model_nested_tuple_has_changed
	$(CROSSHAIR) diffbehavior proof_listfield.actual_tuple_child_delegation proof_listfield.model_tuple_child_delegation
	$(CROSSHAIR) diffbehavior proof_listfield.actual_set_dedup proof_listfield.model_set_dedup
	$(CROSSHAIR) diffbehavior proof_listfield.actual_set_cardinality_after_dedup proof_listfield.model_set_cardinality_after_dedup
	$(CROSSHAIR) diffbehavior proof_listfield.actual_frozenset_has_changed proof_listfield.model_frozenset_has_changed
	$(CROSSHAIR) diffbehavior proof_listfield.actual_frozenset_child_delegation proof_listfield.model_frozenset_child_delegation
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_alias_collision proof_dictfield.model_alias_collision
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_mapping_presence proof_dictfield.model_mapping_presence
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_malformed_bracket_suffix proof_dictfield.model_malformed_bracket_suffix
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_mapping_has_changed proof_dictfield.model_mapping_has_changed
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_nested_sequence proof_dictfield.model_nested_sequence

crosshair-slow: ## Run slow CrossHair checks.
	$(CROSSHAIR) check --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.prove_arbitrary_key_normalization proof_listfield.prove_saturated_index proof_listfield.prove_management_source_precedence proof_listfield.prove_absolute_limit proof_listfield.prove_clean_cardinality proof_listfield.prove_has_changed_integer_rows proof_listfield.prove_alias_collision proof_listfield.prove_clean_with_deleted_and_omitted proof_listfield.prove_deleted_indexes proof_listfield.prove_omitted_extra_indexes proof_listfield.prove_nested_tuple_rows proof_listfield.prove_nested_tuple_extra_item proof_listfield.prove_nested_tuple_has_changed proof_listfield.prove_tuple_child_delegation proof_listfield.prove_set_dedup proof_listfield.prove_set_cardinality_after_dedup proof_listfield.prove_frozenset_has_changed proof_listfield.prove_frozenset_child_delegation proof_listfield.prove_management_names proof_dictfield.prove_alias_collision proof_dictfield.prove_mapping_presence proof_dictfield.prove_malformed_bracket_suffix proof_dictfield.prove_mapping_has_changed proof_dictfield.prove_nested_sequence
