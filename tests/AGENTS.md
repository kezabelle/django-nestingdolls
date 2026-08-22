# Test suite guide for agents

This guide applies to everything in `tests/` and is the canonical guide for
writing and running tests. Tests must also follow the relevant source guide:

- `../nestingdolls/AGENTS.md` for package behavior and input limits.
- `../nestingdolls/templates/AGENTS.md` for template structure and safety.
- `../nestingdolls/static/AGENTS.md` for the sequence controller and build.

## Suite layout and names

`make test` discovers `test_*.py`; `test_sequence.mjs` is the jsdom suite for
the compiled sequence controller. Each Python module owns one concrete contract.
Name it `test_<subject>_<surface>.py`: `<subject>` is the semantic owner and
`<surface>` is the observable contract. Use a one-part specialization name only
for the indivisible `test_tuplefield.py` and `test_setfield.py` contracts.

- **Mapping**
  - Binding: `test_mappingfield_binding.py`.
  - Submission: `test_mappingfield_submission.py`.
  - Rendering: `test_mappingfield_rendering.py`.
  - Nesting: `test_mappingfield_nesting.py`.
- **Sequence**
  - Binding: `test_sequencefield_binding.py`.
  - Configuration: `test_sequencefield_configuration.py`.
  - Widget: `test_sequencefield_widget.py`.
  - Nesting: `test_sequencefield_nesting.py`.
  - Request limits: `test_sequencefield_limits.py`.
- **Composite bases**
  - Widget: `test_composite_widget.py`.
  - Bound-field preparation: `test_composite_boundfield.py`.
  - Hidden initial: `test_composite_hidden_initial.py`.
- **Form-layout patch**
  - `test_form_layout_patch.py`.
- **Hostile input and row limits**
  - `test_hostile_input.py`.
- **Output specializations**
  - `test_dataclassfield_*.py`.
  - `test_namedtuplefield_*.py`.
- **Collection variants**
  - `test_tuplefield.py`.
  - `test_setfield.py`.
- **Browser controller**
  - `test_sequence.mjs`.

Use `MappingField` and `SequenceField` in filenames and class names. `DictField`
and `ListField` are public compatibility aliases; use one only in a concretely
named alias-compatibility test that proves that alias contract. Keep
`TupleField`, `SetField`, `NamedTupleField`, and `DataclassField` when that
specialized public type is the subject.

- Do not use `core`, plural `widgets`, `behavior`, or a generic public-API
  cohort as a surface.
- Name each top-level Python test class `<Subject><Surface>TestCase`. Its
  `test_` methods are lower-snake observable assertions and may omit only the
  class subject.
- Custom `unittest` assertions use `assertXxx`; non-assertion helpers use lower
  snake case. Keep a leading underscore only for a state/setup helper called
  only through `self` or subclasses.
- `test_sequence.mjs` uses lower-case observable `node:test` descriptions and
  lower-camel reusable helpers. Do not rename it for Python taxonomy.

## Shared test infrastructure

`support/` contains the Django bootstrap, reusable fixtures, probe views,
URLconf, and composite testcase helpers. Put reused infrastructure there, not
in a `test_*.py` module.

| Owner | Fixture module |
| --- | --- |
| Sequence fields, tuple/set variants, rows, limits, hidden initial | `tests.support.forms.sequence` |
| Mapping fields, child forms, uploads, and mapping records | `tests.support.forms.mapping` |
| Dataclass and named-tuple output values | `tests.support.forms.outputs` |
| Cross-family composite fixtures | `tests.support.forms.composite` |
| Hostile-only input fixture graph | `tests.support.forms.hostile` |

Import every reusable form directly from its owner module. `forms/__init__.py`
is a package marker only and must never re-export fixtures. Do not import from a
catch-all `tests.support.forms` module. If one fixture serves multiple cohorts,
place it with its outermost field owner and import that owner directly; do not
duplicate or re-export it.

Reusable HTTP views and URL patterns belong in `tests.support.views` and
`tests.support.urls`. A test module may keep a one-use form, field, exception,
or helper local. Move it to support only after reuse. When splitting a class,
move its local fixtures, helpers, and only its needed imports with the class.
Functional cohorts use `ROOT_URLCONF="tests.support.urls"`; do not define
reusable forms, views, or URL patterns in a test module.

## Writing Python tests

- Use `unittest` and `django.test.SimpleTestCase`; existing tests need no
database fixtures. Name files `test_*.py`, classes `*TestCase`, and methods
  `test_*`. Match the destination cohort's imports, module setup, docstring,
  and `unittest.main()` guard.
- Pair `setUpModule()` with `tearDownModule()` when the cohort needs Django's
  instrumented template environment; `assertTemplateUsed()` depends on it.
- Prefer end-to-end tests through `self.client`. When no client request can
  exercise the behavior, instantiate the form and bind the actual input data.
- Model browser submissions with prefixed input through `build_querydict_form()`
  and decoded whole values through `build_whole_value_form()`. Keep `data` and
  files separate with `MultiValueDict` when the behavior does.
- Test the observable contract: validity and cleaned values, markup, error
  messages and codes, changed state, media, or responses. Include the changed
  failure, boundary, or hostile-input path when it can diverge from success.
- Prefer Django's specialized `self.assertXyz()` methods when they fit. Never
  use `assertTrue()` or `assertFalse()`; assert booleans with `assertIs()`.
- For template behavior, assert both template selection and rendered HTML.
  Reuse `CompositeFieldTestCase` from `tests.support.testcases` where it fits.

## Writing sequence-controller tests

`test_sequence.mjs` is plain `node:test` and `jsdom`. It evaluates the committed
`sequence.js` with `dom.window.eval`; do not convert it to TypeScript.

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
| `make jstest` | Runs jsdom tests against committed `sequence.js`. |
| `make check` | Runs the non-mutating CI gate. |

For a focused Python test, preserve `make test`'s warning policy:

```sh
uv run --group dev python \
  -W error::DeprecationWarning \
  -W error::PendingDeprecationWarning \
  -m unittest tests.test_sequencefield_binding.SequenceFieldBindingTestCase
```

Run the focused test while developing, then its cohort. After a TypeScript
change, run `make js`, `make jstest`, and `make check` in order. After any
implementation change, run `make check`; prose-only guide changes need none.
