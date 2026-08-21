# Package guide for agents

This guide applies below `nestingdolls/`; the repository guide also applies.
Before editing `static/` or `templates/`, read that directory's `AGENTS.md`.
This package provides nested Django mapping and sequence form fields. JavaScript
is progressive enhancement only.

## Public surface and ownership

- Every name in `nestingdolls.__all__` is public. `DictField`, `FormField`, and
  `Subform` alias `MappingField`; `ListField` aliases `SequenceField`.
  `TupleField`/`FrozenSequenceField` and `SetField`/`FrozenSetField` are
  sequence variants. `NamedTupleField` and `DataclassField` are mapping
  variants.
- `MappingWidget`, `SequenceWidget`, `MappingBoundField`, and
  `SequenceBoundField` are advanced public integration hooks.
  `InvalidInitialValueError` is a `ValueError`; `ItemValidationError`,
  `MappingInputValidationError`, `SequenceInputValidationError`, and
  `TooManyFormsValidationError` are `ValidationError` subclasses.
- `CompositeField`, `CompositeWidget`, and `CompositeBoundField` are internal
  shared bases. Keep behavior cohorts in their owner nested classes, such as
  `SequenceField.Limits`, `SequenceWidget.RowForm`,
  `SequenceWidget.RowFormSet`, `SequenceWidget.submission_countdown`, and
  widget `RenderState` classes.
- Use `_` only for a member called through `self` or subclass inheritance. If
  another class calls it directly, remove `_`. Nested classes already scope
  their members; do not add `_` there for privacy. Use lower-snake-case
  class constants. After adding, renaming, or moving a member, check every
  caller against these rules.

## Typing

- `Any` is forbidden. `object` is the loosest accepted boundary type. Prove or
  narrow a value; when django-stubs contradicts Django’s runtime contract, use
  one local coded ignore rather than `cast()`.

- Public exports: `__init__.py`.
- Fields and specializations: `fields.py`.
- Widgets, row formsets, extraction, and render state: `widgets.py`.
- Bound child forms and formsets: `boundfield.py`.
- Item and input errors: `errors.py`.
- Form-layout render bridge and startup: `patches.py`, `apps.py`, and
  `tests/test_patches.py`.
- Mapping templates: `templates/nestingdolls/mapping/` and
  `tests/test_dictfield_*.py`.
- Sequence templates: `templates/nestingdolls/sequence/` and
  `tests/test_listfield_*.py`.
- Named-tuple and dataclass output: `fields.py`,
  `tests/test_namedtuplefield_*.py`, and `tests/test_dataclassfield_*.py`.
- Shared composite behavior: the three internal bases and the assertions in
  `tests/testcases.py`.
- Hostile row costs and limits: `tests/test_hostile.py` and `pathological.py`.
- Browser controller and artifact: `static/nestingdolls/sequence.ts` and the
  committed `sequence.js`.

## Behavior invariants

### Input and binding

- Preserve whole-value and prefixed input through arbitrary mapping/sequence
  nesting.
- An exact mapping expands to child keys and replaces prefixed mapping input.
  Indexed sequence row keys outrank exact input; exact input outranks
  management-only input.
- Do not copy, normalize, or aggregate submission keys. Bind raw request
  `data` and `files` with a Django prefix so each child reads only its own
  keys. Keep `data` and `files` separate through mapping nesting.

### Django contract

- Preserve child clean hooks and non-field errors. Let child widgets and fields
  extract, prepare, and compare values.
- Preserve file fields, compound widgets, multipart forms, and widget media.
  Keep child errors inline; do not duplicate them as outer errors.

### Rendering and browser contract

- Server-rendered HTML must work without JavaScript. Use inert `<template>`
  elements for row add/remove controls. See `static/AGENTS.md` for script
  rules and `templates/AGENTS.md` for template rules.
- Do not add a built-in status, toast, or notification for row changes. Emit
  `nestingdolls:sequence-change`; the host page owns announcements.
- Keep the supported form-layout patch and four layout templates for each
  composite. Keep hidden-initial work to `from_hidden_initial` and
  `RenderState.hidden_initial_value`; do not add passes or render state.

### Collections and documentation

- Deduplicate sets before length checks and compare sets without order.
  Keep `SetField.has_changed` linear and conservative: pair a converted row
  with its hashed member, and report ambiguity as a change. Do not add a
  pairwise scan or comparison budget.
- Use ASD-STE100 in comments and docstrings. A comment must explain a
  non-obvious reason, an unidiomatic construct, or a bug cause; it must not
  restate code or excuse unclear code. Put a needed ticket, specification, or
  measurement at its use site.

## Recursive sequence row budget

Read this before changing normalization, extraction, formset construction, or
row rendering. Django already limits request keys, files, bytes, and one
formset level with `absolute_max`; do not duplicate those limits. This package
only limits attacker-controlled row multiplication across nested sequences.
Python and decoded JSON bypass request-parser limits, but their rows still use
this budget; their callers own byte and depth limits.

- `SequenceWidget.submission_countdown` is the sole recursive-row guard. The
  outer `open(limits.submission_max)` creates one context-local budget; nested
  opens reuse it, and its owner clears it on exit. Do not import, open,
  inspect, or extend it from mappings, composite bases, `clean()`, field-tree
  walks, or cross-field/request-wide paths. Store only the countdown in its
  `ContextVar`: no default, sentinel, field/widget/formset reference, or lazy
  cap expansion.
- Only these scopes may call `open()`: `SequenceWidget.RowFormSet.total_form_count`,
  `SequenceWidget.value_from_datadict`, `SequenceField.prepare_value`,
  `SequenceWidget.get_context`, and `SequenceBoundField.formset`. A sixth
  scope is a bug: the first owner fixes the budget and mode for descendants.
- `SequenceBoundField.formset` is the only `raises=True` owner. An overdraw
  unwinds, is recorded once, reports one `too_many_forms` error, and renders
  a zero-row bound formset. The other four scopes clip to the allowed prefix;
  do not let a clipped submitted form clean as valid.
- Call `take()` only before rows are built: in `RowFormSet.total_form_count`
  for submitted `TOTAL_FORMS`, in whole-list `SequenceWidget.value_from_datadict`,
  and in `SequenceField.prepare_value` for initial rows. Do not take cached
  rows again; pass an exact-list reservation through `new_formset` with
  `submission_total_form_count` and document the inherited reservation.
  `take(count <= 0)` returns zero and never spends or refunds capacity.
- `Limits.submission_max` is `max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)`
  for each submission. It covers one sequence field's nested tree only, never
  sibling fields, forms, or requests.

## Hot submission-key scans

Apply these rules when changing `SequenceWidget.has_row_input` or
`SequenceWidget.RowFormSet.rows_with_submitted_values`. Use `pathological.py`
for a scan-cost change; its fresh wall-time measurement overrides historical
numbers.

- Use one explicit key loop, cache the prefix length, and compare
  `key[:prefix_length] == prefix`. Do not use `any(generator)`, scan keys once
  per row, prefilter before the prefix comparison, or switch to `startswith`
  without new benchmark evidence. The goal is to avoid `O(rows × keys)` work.
- On a source with `getlist`, call it once and use its result. On a plain
  mapping, use `get`. Do not copy, pre-check, cast, or wrap values only to
  scan them.
- A row's structural keys are not content, at any nesting depth. Compare the
  key's last segment with the management names and the delete name. Do not read
  the segment after this row's own prefix: a rendered row also sends the four
  management keys of every nested formset, and treating those as content pins
  every outer row to `empty_permitted=False`.
- Keep `MappingWidget._accepts_key` on its measured `removeprefix` path unless
  a new measurement finds a material regression. Use wall time, not a
  `cProfile` call count that hides slice-opcode cost.
