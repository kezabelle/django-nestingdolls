## Scope and guides

This repository-wide guide applies everywhere; read it before the guide for the
directory you edit. A nested guide supplements, rather than replaces, this one.

- Before package Python edits, read
  [`nestingdolls/AGENTS.md`](nestingdolls/AGENTS.md); read its **Input limits**
  section before changing normalization, extraction, or row counts.
- Before creating or changing a test, read
  [`tests/AGENTS.md`](tests/AGENTS.md), the canonical test guide.
- Before editing `sequence.ts` or `tests/test_sequence.mjs`, read
  [`nestingdolls/static/AGENTS.md`](nestingdolls/static/AGENTS.md).
- Before editing a Django template, read
  [`nestingdolls/templates/AGENTS.md`](nestingdolls/templates/AGENTS.md).

## Layout

- `nestingdolls/` contains fields, widgets, bound fields, errors, and the
  form-layout render patch; its guide maps modules to concerns and tests.
  `nestingdolls/static/nestingdolls/` contains `sequence.ts` and its committed
  compiled artifact, `sequence.js`; `nestingdolls/templates/nestingdolls/`
  contains widget templates.
- `tests/` contains Python tests (`test_*.py`) and the jsdom tests
  (`test_sequence.mjs`). The root also contains `demo.py`, `pathological.py`
  (hostile-submission cost measurements), and `mypy_settings.py`.

## Commands and verification

All commands below are Make targets; use `make help` to list them. A fresh
clone needs `npm ci` before JavaScript targets (`tscheck`, `jsdrift`, `jstest`,
`js`) and therefore before `make check`.

- `make check` is the non-mutating CI gate: `tscheck`, `jsdrift`, `jstest`,
  `ruff`, `formatcheck`, `test`, `distcheck`, and `mypy`.
- `make fix` applies lint auto-fixes and formatting; `make check` changes no
  files.
- Run `make check` after implementation changes. Do not run runtime checks for
  prose-only changes unless executable examples changed.
- `make mypy` checks `demo.py` and `nestingdolls` using `mypy_settings.py` for
  `django-stubs`; tests do not import that file. `make ruff` and
  `make formatcheck` cover the maintained Python files in the Makefile's
  `PYTHON_FILES`.
- `make distcheck` builds both distributions from the tracked tree in a
  temporary directory, runs `twine check --strict`, and verifies that the
  sdist includes `LICENSE`; it uses `git write-tree`, so untracked build inputs
  fail the gate.
- After editing `sequence.ts`, follow the static guide's build order.
  `make check` compares `sequence.js` with the current TypeScript build using
  `cmp`, not Git.
