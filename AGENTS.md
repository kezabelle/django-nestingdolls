# Commands

When running shell commands, use `rtk` and prefer tilth for reading/searching files.

# TypeScript

- `nestingdolls/static/nestingdolls/sequence.ts` is the source of truth.
- `nestingdolls/static/nestingdolls/sequence.js` is compiled output and should stay committed.
- After editing the sequence controller, run `make js`.
- To typecheck without emitting, run `make tscheck`.

# Python checks

- Run `make test` for the Django test suite in `test_listfield.py`.
- Run `make mypy` for the strict implementation mypy check with `test_settings`.
- Run `make ruff` for linting the maintained Python files (`nestingdolls/__init__.py`, `test_listfield.py`, and `test_settings.py`).
- Run `make check` to run TypeScript, ruff, mypy, and tests together.
