# Commands

Every command below is a `make` target. Run `make help` for the list.

- `make check` runs everything and writes nothing, so it is also the CI gate:
  `tscheck`, `jsdrift`, `jstest`, `ruff`, `formatcheck`, `test`, `mypy`.
- `make fix` applies the lint auto-fixes and the formatter. `check` never does.
- `make crosshair` confirms the three semantic models in `proof_listfield.py`
  and `proof_dictfield.py`. It is slow and is not part of `check`. Run it after
  a change to normalization, change detection, or collection semantics.

# TypeScript

- `nestingdolls/static/nestingdolls/sequence.ts` is the source of truth.
- `nestingdolls/static/nestingdolls/sequence.js` is compiled output and must
  stay committed.
- After editing the sequence controller, run `make js`. `make check` rebuilds
  and then fails on `git diff` if the committed file is stale, so a forgotten
  rebuild cannot pass.
- `make tscheck` type-checks without emitting; `make jstest` runs the jsdom
  tests in `test_sequence.mjs`, parameterized over all four layouts.

# Python checks

- `make test` runs `test_composite`, `test_listfield`, `test_dictfield`, and
  `test_patches`.
- `make mypy` type-checks `demo.py` and the whole `nestingdolls` package under
  the settings in `mypy_settings.py`, which exists only for `django-stubs`; no
  test imports it.
- `make ruff` and `make formatcheck` cover the maintained Python files listed in
  the Makefile's `PYTHON_FILES`. `scripts/diagnose_form_data_mappings.py` is
  deliberately absent from that list.
