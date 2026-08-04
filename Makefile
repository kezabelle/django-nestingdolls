UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
CROSSHAIR := $(UV_RUN) crosshair
TSC := ./node_modules/typescript/bin/tsc

DEFAULT_GOAL := help

.PHONY: js tscheck format ruff mypy test agents check crosshair

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

crosshair: ## Confirm the small set of independent semantic models.
	$(CROSSHAIR) check --report_all --max_uninteresting_iterations=25 --per_condition_timeout=12 proof_listfield.prove_sequence_direct_extraction proof_dictfield.prove_mapping_direct_precedence proof_dictfield.prove_mapping_hostile_fallback
