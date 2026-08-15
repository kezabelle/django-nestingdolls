# Guides

This file is the repository guide, and it applies everywhere. It covers the
commands, the important directories, and how to write and verify tests.
Each guide below covers one directory, applies to every file under it, and
adds to this file instead of replacing it. Read this file first, then the
guide for the directory you edit.

- [`nestingdolls/AGENTS.md`](nestingdolls/AGENTS.md) is the package guide.
  Read it before you edit Python in the package, and read its "Input limits"
  section before you change normalization, extraction, or row counts.
- [`nestingdolls/static/AGENTS.md`](nestingdolls/static/AGENTS.md) is the
  TypeScript guide. Read it before you edit `sequence.ts` or
  `test_sequence.mjs`.
- [`nestingdolls/templates/AGENTS.md`](nestingdolls/templates/AGENTS.md) is
  the template guide. Read it before you edit a Django template.

# Directories

- `nestingdolls/` is the package: fields, widgets, bound fields, errors, and
  the form-layout render patch. The package guide's source map pairs each
  module with its concern and its tests.
- `nestingdolls/static/nestingdolls/` holds the TypeScript source
  `sequence.ts` and its compiled `sequence.js`, which stays committed.
- `nestingdolls/templates/nestingdolls/` holds the widget templates.
- The repository root holds the Python tests (`test_*.py`), the jsdom tests
  (`test_sequence.mjs`), `demo.py`, `pathological.py` (the hostile-submission
  cost measurements), and `mypy_settings.py`.

# Commands

Every command below is a `make` target. Run `make help` for the list.

- `make check` runs everything and leaves every file as it was, so it is
  also the CI gate: `tscheck`, `jsdrift`, `jstest`, `ruff`, `formatcheck`,
  `test`, `distcheck`, `mypy`.
- `make fix` applies the lint auto-fixes and the formatter. `check` never does.

# Tests and verification

Run `make check` after an implementation change. For a prose-only change, do
not run runtime checks unless executable examples changed.

Python:

- `make test` runs `test_composite`, `test_dataclassfield`, `test_listfield`,
  `test_dictfield`, `test_hostile`, `test_namedtuplefield`, and `test_patches`.
  Put a new test in the module that already covers the concern; the package
  guide's source map names the pairings, and `test_composite.py` covers the
  contract shared by mappings and sequences.
- `make mypy` type-checks `demo.py` and the whole `nestingdolls` package under
  the settings in `mypy_settings.py`, which exists only for `django-stubs`; no
  test imports it.
- `make ruff` and `make formatcheck` cover the maintained Python files listed in
  the Makefile's `PYTHON_FILES`.
- `make distcheck` builds both distributions from the tracked tree in a
  temporary directory and runs `twine check --strict` on them, then confirms
  the sdist carries `LICENSE`. It reads `git write-tree`, not the working
  tree, so a build input that is present on disk but never `git add`ed fails
  the gate instead of shipping an artifact with no README or no license text.

TypeScript:

- After editing `sequence.ts`, follow the build order in
  [`nestingdolls/static/AGENTS.md`](nestingdolls/static/AGENTS.md). `make
  check` fails when `sequence.js` on disk is not the current build of
  `sequence.ts`; the comparison uses `cmp`, not git.
