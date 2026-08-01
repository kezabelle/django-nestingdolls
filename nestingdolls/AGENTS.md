# Package Guide For Agents

This file adds package-local guidance for work in `nestingdolls/`.
It supplements the repo-root `AGENTS.md`.

## Package Purpose

This package implements Django sequence form fields.
It supports variable-length collections with one child field type.
It keeps the server-side HTML useful without JavaScript.
It adds JavaScript only for progressive enhancement.

## Public API Map

The generally used exports are:

- `ListField = SequenceField`
- `TupleField = FrozenSequenceField`
- `SetField`
- `FrozenSetField`

Additional exports which are infrequently necessary:

- `SequenceWidget`
- `SequenceBoundField`
- `InvalidInitialValueError`

Relationship notes:

- `SequenceField` is the base field implementation.
- `ListField` is the main user entry point.
- `TupleField` changes the cleaned result to a tuple.
- `SetField` changes the cleaned result to a deduplicated set-like value.
- `FrozenSetField` is the immutable set variant.
- `SequenceWidget` is the composite widget for repeated rows.
- `SequenceBoundField` customizes bound data, row errors, and row deletion state.

## Checks

Run these checks after behavior-sensitive changes:

- `make check` (runs all of `tsc` + `ruff` + `mypy` + `test`)

## Documented User Guarantees

Current source and tests document these behaviors:

- child validation errors stay inline at the failing row
- normal server HTML works without JavaScript
- JavaScript adds row add/remove controls from inert templates
- nested sequence children are supported
- file child fields are supported
- compound child widgets are supported
- `has_changed()` uses child-field semantics
- `SetField` and `FrozenSetField` ignore row order for semantic equality
- set cardinality is checked after deduplication

## Do Not Regress

- Preserve direct, dash, dot, and bracket input support.
- Preserve both original keys and canonical keys during normalization.
- Keep child errors inline.
- Do not promote row errors into field-level `Item N:` text.
- Keep server-rendered HTML useful without JavaScript.
- Keep add/remove controls in inert `<template>` nodes.
- Treat `static/nestingdolls/sequence.ts` as the source of truth.
- Keep `sequence.js` committed as compiled output.
- Preserve child-field semantics in `prepare_value()`, `bound_data()`, and `has_changed()`.
- Preserve semantic set comparison and deduplication behavior.

## Primary Source Files

- `nestingdolls/__init__.py`
- `nestingdolls/static/nestingdolls/sequence.ts`
- `nestingdolls/templates/django/forms/widgets/sequence.html`
- `test_listfield.py`


Also run this when changes touch normalization, change detection, or collection semantics:

- `make crosshair`

## Doc Notes

Keep user docs `ListField`-first.
Describe the current exported field family.
Do not promise behavior that is not present in source and tests.
Use ASD-STE100 Simplified Technical English (STE)
