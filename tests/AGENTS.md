# Test suite guide for agents

This guide applies to everything in `tests/` and is the canonical guide for
writing and running tests. Tests must also follow the relevant source guide:

- `../nestingdolls/AGENTS.md` for package behavior and input limits.
- `../nestingdolls/templates/AGENTS.md` for template structure and safety.
- `../nestingdolls/static/AGENTS.md` for the sequence controller and build.

## Suite layout

| Path | Role |
| --- | --- |
| `test_*.py` | Python tests discovered by `make test`. |
| `test_sequence.mjs` | jsdom tests for the compiled sequence controller. |
| `support.py` | Shared Django configuration, fixtures, probe views, and form-binding helpers. |
| `testcases.py` | Shared composite-rendering and error-display assertions. |

Keep each Python module to one behavior cohort:

- `test_dictfield_*.py` covers mapping behavior; `test_listfield_*.py` covers
  sequence behavior.
- `test_namedtuplefield_*.py` and `test_dataclassfield_*.py` cover output
  specialization construction, cleaning, and rendering.
- `test_tuplefield.py` and `test_setfield.py` cover collection variants.
- `test_composite_widgets.py` covers shared behavior; `test_patches.py` covers
  the form-layout bridge; `test_hostile.py` covers hostile input and row limits.

## Writing Python tests

- Use `unittest` and `django.test.SimpleTestCase`; existing tests need no
  database fixtures. Name files `test_*.py`, classes `*TestCase`, and methods
  `test_*`. Match the nearest cohort's imports, module setup, docstring, and
  `unittest.main()` guard.
- Import configuration, fixtures, and common types from `.support`. Reuse its
  probe views, fixtures, `QueryDict` helpers, and
  `ListFormBindingUnitTestCase` or `MappingFormBindingUnitTestCase`; do not add
  another Django settings bootstrap.
- Keep one-use forms, fields, and exceptions local. Move a shared fixture or
  assertion to `support.py` or `testcases.py` only after reuse.
- Pair `setUpModule()` with `tearDownModule()` when the cohort needs Django's
  instrumented template environment; `assertTemplateUsed()` depends on it.
- Prefer end-to-end tests through `self.client`. When no client request can
  exercise the behavior, instantiate the form and bind the actual input data.
- Use a direct field, widget, or helper unit test only when neither functional
  path can exercise and demonstrate the behavior as correct.
- Model browser submissions with prefixed input through `build_querydict_form()`
  and decoded whole values through `build_whole_value_form()`. Keep `data` and
  files separate with `MultiValueDict` when the behavior does.
- Test the observable contract: validity and cleaned values, markup, error
  messages and codes, changed state, media, or responses. Include the changed
  failure, boundary, or hostile-input path when it can diverge from success.
- Prefer Django's specialized `self.assertXyz()` methods when they fit the
  assertion. Never use `assertTrue()` or `assertFalse()`; assert boolean
  results with `self.assertIs(actual, True)` or `self.assertIs(actual, False)`.
- Change observable behavior with its test in the same commit.
- For template behavior, assert both template selection and rendered HTML.
  Reuse `CompositeRenderingAssertions` and
  `CompositeErrorDisplayAssertions` where they fit.

## Writing sequence-controller tests

`test_sequence.mjs` is plain `node:test` and `jsdom` JavaScript. It evaluates
the committed `sequence.js` with `dom.window.eval`; do not convert it to
TypeScript.

- Assert DOM state and dispatched events; the script has no test API.
- Reuse the four layout fixtures, `row()`, `rowsContainer()`, and `build()`.
  A row-markup behavior must run against every layout through a shared helper.
- Use `enhancementFailure()` when malformed markup or a widget can fail
  enhancement.

## Running tests

A fresh clone needs `npm ci` before JavaScript checks.

| Command | Result |
| --- | --- |
| `make test` | Runs all Python tests under coverage with deprecations as errors. |
| `make jstest` | Runs the jsdom tests against committed `sequence.js`. |
| `make check` | Runs the non-mutating CI gate. |

For a focused Python test, preserve `make test`'s warning policy:

```sh
uv run --group dev python \
  -W error::DeprecationWarning \
  -W error::PendingDeprecationWarning \
  -m unittest tests.test_tuplefield.TupleFieldTestCase
```

Run the focused test while developing, then its cohort. After a TypeScript
change, run `make js`, `make jstest`, and `make check` in order. After any
implementation change, run `make check`; prose-only guide changes need none.
