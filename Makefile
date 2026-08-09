UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
NPM := npm --silent

PYTHON_FILES := demo.py nestingdolls test_composite.py test_dictfield.py test_listfield.py test_patches.py mypy_settings.py
COMPILED_JS := nestingdolls/static/nestingdolls/sequence.js

.PHONY: js jsdrift tscheck jstest format formatcheck ruff rufffix mypy test check fix

.DEFAULT_GOAL := help

help: ## Show targets and short task text. (This command)
	@awk 'BEGIN {FS = ": ## " ; print "Available targets\n-----------------"} /^[[:alnum:]_-]+: ## / {print $$1 " → " $$2}' $(MAKEFILE_LIST)

js: ## Build JavaScript from TypeScript.
	$(NPM) run build

jsdrift: ## Fail when the committed JavaScript is not the current build.
	@cp $(COMPILED_JS) $(COMPILED_JS).drift
	@$(NPM) run build
	@if cmp -s $(COMPILED_JS) $(COMPILED_JS).drift; then \
		rm -f $(COMPILED_JS).drift; \
	else \
		mv $(COMPILED_JS).drift $(COMPILED_JS); \
		echo "$(COMPILED_JS) is stale: run 'make js' and commit the result."; \
		exit 1; \
	fi

tscheck: ## Check TypeScript. Do not write files.
	$(NPM) run typecheck

jstest: ## Run JavaScript DOM tests.
	$(NPM) test

format: ## Run Ruff formatter on maintained Python files.
	$(RUFF) format $(PYTHON_FILES)

formatcheck: ## Check formatting without writing files.
	$(RUFF) format --check $(PYTHON_FILES)

ruff: ## Lint the maintained Python files.
	$(RUFF) check $(PYTHON_FILES)

rufffix: ## Lint with auto-fixes.
	$(RUFF) check --fix $(PYTHON_FILES)

mypy: ## Run mypy with strict checks.
	$(MYPY) demo.py nestingdolls

test: ## Run the Django test files.
	$(PYTHON) -W error::DeprecationWarning -W error::PendingDeprecationWarning -m unittest test_composite test_listfield test_dictfield test_patches

check: ## Run every fast check. Writes nothing, so CI can gate on it.
check: tscheck jsdrift jstest ruff formatcheck test mypy

fix: ## Apply the formatter and the lint auto-fixes.
fix: rufffix format
