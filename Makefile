UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
NPM := npm --silent

PYTHON_FILES := demo.py nestingdolls pathological.py test_composite.py test_dataclassfield.py test_dictfield.py test_hostile.py test_listfield.py test_namedtuplefield.py test_patches.py mypy_settings.py
COMPILED_JS := nestingdolls/static/nestingdolls/sequence.js

.PHONY: js jsdrift tscheck jstest format formatcheck ruff rufffix mypy test pathological distcheck hooks check fix

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
	$(PYTHON) -W error::DeprecationWarning -W error::PendingDeprecationWarning -m unittest test_composite test_dataclassfield test_listfield test_dictfield test_hostile test_namedtuplefield test_patches

pathological: ## Measure what hostile nested submissions cost. Not part of check.
	$(PYTHON) pathological.py $(ARGS)

distcheck: ## Build both distributions from the tracked tree and check their metadata.
	@tmp=$$(mktemp -d) ; \
	status=0 ; \
	git archive --format=tar $$(git write-tree) | tar -xf - -C $$tmp && \
	uv build --out-dir $$tmp/dist $$tmp >$$tmp/build.log 2>&1 && \
	$(UV_RUN) twine check --strict $$tmp/dist/* && \
	tar -tzf $$tmp/dist/*.tar.gz | grep -q '/LICENSE$$' || status=1 ; \
	if [ $$status -ne 0 ]; then \
		cat $$tmp/build.log ; \
		echo "packaging metadata incomplete: the tracked tree does not build a publishable distribution."; \
	fi ; \
	rm -rf $$tmp ; \
	exit $$status

hooks: ## Install Git hooks, preferring prek over pre-commit.
	@if $(UV_RUN) prek --version >/dev/null 2>&1; then \
		$(UV_RUN) prek install; \
	elif command -v prek >/dev/null 2>&1; then \
		prek install; \
	elif command -v pre-commit >/dev/null 2>&1; then \
		pre-commit install; \
	else \
		echo "Neither prek nor pre-commit is installed. See https://github.com/j178/prek or https://pre-commit.com/#install."; \
		exit 1; \
	fi

check: ## Run every fast check. Writes nothing, so CI can gate on it.
check: tscheck jsdrift jstest ruff formatcheck test distcheck mypy

fix: ## Apply the formatter and the lint auto-fixes.
fix: rufffix format
