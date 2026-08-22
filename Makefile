UV_RUN := uv run --group dev
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
MYPY := $(UV_RUN) mypy
NPM := npm --silent

PYTHON_TEST_FILES := $(wildcard tests/test_*.py)
PYTHON_SUPPORT_FILES := $(wildcard tests/support/*.py tests/support/forms/*.py)
PYTHON_FILES := demo.py nestingdolls pathological.py $(PYTHON_TEST_FILES) $(PYTHON_SUPPORT_FILES) mypy_settings.py
COMPILED_JS := nestingdolls/static/nestingdolls/sequence.js

.PHONY: js jsdrift tscheck jstest format formatcheck ruff rufffix mypy test test-django pathological distcheck check fix

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
	$(PYTHON) -W error::DeprecationWarning -W error::PendingDeprecationWarning -m coverage run -m unittest discover -s tests -t . -p 'test_*.py'
	$(PYTHON) -m coverage report --show-missing

test-django: ## Run the suite against Django version $(DJANGO).
	@test -n "$(DJANGO)" || (echo "set DJANGO, for example DJANGO=5.2.*" >&2; exit 2)
	$(UV_RUN) --with "django==$(DJANGO)" python -W error::DeprecationWarning -W error::PendingDeprecationWarning -m unittest discover -s tests -t . -p 'test_*.py'

pathological: ## Measure what hostile nested submissions cost. Not part of check.
	$(PYTHON) pathological.py $(ARGS)

distcheck: ## Build both distributions from the tracked tree and check their metadata and contents.
	@tmp=$$(mktemp -d) ; \
	status=0 ; \
	git archive --format=tar $$(git write-tree) | tar -xf - -C $$tmp && \
	uv build --out-dir $$tmp/dist $$tmp >$$tmp/build.log 2>&1 && \
	$(UV_RUN) twine check --strict $$tmp/dist/* && \
	sdist_files=$$(tar -tzf $$tmp/dist/*.tar.gz) && \
	echo "$$sdist_files" | grep -q '/LICENSE$$' && \
	echo "$$sdist_files" | grep -Eq '^[^/]+/AGENTS\.md$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/AGENTS.md$$' && \
	echo "$$sdist_files" | grep -Eq '^[^/]+/CHANGELOG\.md$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/static/AGENTS.md$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/templates/AGENTS.md$$' && \
	echo "$$sdist_files" | grep -q '/tests/AGENTS.md$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/templates/nestingdolls/sequence/row.html$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/static/nestingdolls/sequence.js$$' && \
	echo "$$sdist_files" | grep -q '/nestingdolls/py.typed$$' && \
	! echo "$$sdist_files" | grep -q '/tests/test_' && \
	! echo "$$sdist_files" | grep -q '/tests/support/' || status=1 ; \
	if [ $$status -ne 0 ]; then \
		cat $$tmp/build.log ; \
		echo "packaging metadata incomplete: the tracked tree does not build a publishable distribution."; \
	fi ; \
	rm -rf $$tmp ; \
	exit $$status


check: ## Run every fast check. Writes nothing, so CI can gate on it.
check: tscheck jsdrift jstest ruff formatcheck test distcheck mypy

fix: ## Apply the formatter and the lint auto-fixes.
fix: rufffix format
