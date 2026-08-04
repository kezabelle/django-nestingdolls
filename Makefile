UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
CROSSHAIR := $(UV_RUN) crosshair
CROSSHAIR_DIFF := $(CROSSHAIR) diffbehavior --max_uninteresting_iterations=25 --per_condition_timeout=12
TSC := ./node_modules/typescript/bin/tsc

DEFAULT_GOAL := help

.PHONY: js tscheck format ruff mypy test agents check crosshair crosshair-contracts crosshair-diff crosshair-slow

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
check: tscheck ruff format mypy test agents

crosshair-contracts: ## Confirm focused normalization and precedence contracts.
	$(CROSSHAIR) check --report_all --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.prove_sequence_direct_extraction proof_dictfield.prove_mapping_direct_precedence proof_dictfield.prove_mapping_hostile_fallback

crosshair: crosshair-contracts ## Check selected semantic laws with CrossHair.
	$(CROSSHAIR) check proof_listfield.prove_arbitrary_key_normalization proof_listfield.prove_saturated_index proof_listfield.prove_sequence_direct_extraction proof_listfield.prove_sequence_key_helper proof_listfield.prove_clean_cardinality proof_listfield.prove_clean_with_deleted_and_omitted proof_listfield.prove_nested_tuple_rows proof_listfield.prove_set_cardinality_after_dedup proof_dictfield.prove_mapping_key_normalization proof_dictfield.prove_mapping_direct_precedence proof_dictfield.prove_mapping_hostile_fallback proof_dictfield.prove_mapping_presence proof_dictfield.prove_nested_sequence

crosshair-diff: ## Compare implementations with independent law models.
	$(CROSSHAIR_DIFF) proof_listfield.actual_clean_cardinality proof_listfield.model_clean_cardinality
	$(CROSSHAIR_DIFF) proof_listfield.actual_has_changed_integer_rows proof_listfield.model_has_changed_integer_rows
	$(CROSSHAIR_DIFF) proof_listfield.actual_arbitrary_key_normalization proof_listfield.model_arbitrary_key_normalization
	$(CROSSHAIR_DIFF) proof_listfield.actual_saturated_index proof_listfield.model_saturated_index
	$(CROSSHAIR_DIFF) proof_listfield.actual_sequence_direct_extraction proof_listfield.model_sequence_direct_extraction
	$(CROSSHAIR_DIFF) proof_listfield.actual_alias_collision proof_listfield.model_alias_collision
	$(CROSSHAIR_DIFF) proof_listfield.actual_clean_with_deleted_and_omitted proof_listfield.model_clean_with_deleted_and_omitted
	$(CROSSHAIR_DIFF) proof_listfield.actual_deleted_indexes proof_listfield.model_deleted_indexes
	$(CROSSHAIR_DIFF) proof_listfield.actual_omitted_extra_indexes proof_listfield.model_omitted_extra_indexes
	$(CROSSHAIR_DIFF) proof_listfield.actual_nested_tuple_rows proof_listfield.model_nested_tuple_rows
	$(CROSSHAIR_DIFF) proof_listfield.actual_nested_tuple_has_changed proof_listfield.model_nested_tuple_has_changed
	$(CROSSHAIR_DIFF) proof_listfield.actual_tuple_child_delegation proof_listfield.model_tuple_child_delegation
	$(CROSSHAIR_DIFF) proof_listfield.actual_set_dedup proof_listfield.model_set_dedup
	$(CROSSHAIR_DIFF) proof_listfield.actual_set_cardinality_after_dedup proof_listfield.model_set_cardinality_after_dedup
	$(CROSSHAIR_DIFF) proof_listfield.actual_frozenset_has_changed proof_listfield.model_frozenset_has_changed
	$(CROSSHAIR_DIFF) proof_listfield.actual_frozenset_child_delegation proof_listfield.model_frozenset_child_delegation
	$(CROSSHAIR_DIFF) proof_dictfield.actual_alias_collision proof_dictfield.model_alias_collision
	$(CROSSHAIR_DIFF) proof_dictfield.actual_mapping_key_normalization proof_dictfield.model_mapping_key_normalization
	$(CROSSHAIR_DIFF) proof_dictfield.actual_mapping_direct_precedence proof_dictfield.model_mapping_direct_precedence
	$(CROSSHAIR_DIFF) proof_dictfield.actual_mapping_hostile_fallback proof_dictfield.model_mapping_hostile_fallback
	$(CROSSHAIR_DIFF) proof_dictfield.actual_mapping_presence proof_dictfield.model_mapping_presence
	$(CROSSHAIR_DIFF) proof_dictfield.actual_mapping_has_changed proof_dictfield.model_mapping_has_changed
	$(CROSSHAIR_DIFF) proof_dictfield.actual_nested_sequence proof_dictfield.model_nested_sequence

crosshair-slow: crosshair-contracts ## Check every modelled semantic law with CrossHair.
	$(CROSSHAIR) check --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.prove_arbitrary_key_normalization proof_listfield.prove_saturated_index proof_listfield.prove_sequence_direct_extraction proof_listfield.prove_sequence_key_helper proof_listfield.prove_clean_cardinality proof_listfield.prove_has_changed_integer_rows proof_listfield.prove_alias_collision proof_listfield.prove_clean_with_deleted_and_omitted proof_listfield.prove_deleted_indexes proof_listfield.prove_omitted_extra_indexes proof_listfield.prove_nested_tuple_rows proof_listfield.prove_nested_tuple_has_changed proof_listfield.prove_tuple_child_delegation proof_listfield.prove_set_dedup proof_listfield.prove_set_cardinality_after_dedup proof_listfield.prove_frozenset_has_changed proof_listfield.prove_frozenset_child_delegation proof_dictfield.prove_alias_collision proof_dictfield.prove_mapping_key_normalization proof_dictfield.prove_mapping_direct_precedence proof_dictfield.prove_mapping_hostile_fallback proof_dictfield.prove_mapping_presence proof_dictfield.prove_mapping_has_changed proof_dictfield.prove_nested_sequence
