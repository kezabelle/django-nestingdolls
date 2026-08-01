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
	$(CROSSHAIR) check proof_listfield.py proof_dictfield.py

crosshair-diff: ## Compare actual and model behavior.
	$(CROSSHAIR) diffbehavior proof_listfield.actual_clean_cardinality proof_listfield.model_clean_cardinality
	$(CROSSHAIR) diffbehavior proof_listfield.actual_has_changed_integer_rows proof_listfield.model_has_changed_integer_rows
	$(CROSSHAIR) diffbehavior proof_listfield.actual_single_row_spelling proof_listfield.model_single_row_spelling
	$(CROSSHAIR) diffbehavior proof_listfield.actual_direct_value_precedence proof_listfield.model_direct_value_precedence
	$(CROSSHAIR) diffbehavior proof_listfield.actual_alias_collision proof_listfield.model_alias_collision
	$(CROSSHAIR) diffbehavior proof_listfield.actual_generated_management_total proof_listfield.model_generated_management_total
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
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_widget_mapping_shape proof_dictfield.model_widget_mapping_shape
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_single_mapping_spelling proof_dictfield.model_single_mapping_spelling
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_direct_mapping_precedence proof_dictfield.model_direct_mapping_precedence
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_alias_collision proof_dictfield.model_alias_collision
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_mapping_presence proof_dictfield.model_mapping_presence
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_malformed_bracket_suffix proof_dictfield.model_malformed_bracket_suffix
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_mapping_has_changed proof_dictfield.model_mapping_has_changed
	$(CROSSHAIR) diffbehavior proof_dictfield.actual_nested_sequence proof_dictfield.model_nested_sequence

crosshair-slow: ## Run slow CrossHair checks.
	$(CROSSHAIR) check --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.py proof_dictfield.py
