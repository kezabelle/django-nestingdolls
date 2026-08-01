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

## Generated Field Method Reference

<!-- BEGIN GENERATED FIELD METHODS -->

### SequenceField

#### Overrides parent methods

- `__init__(self, child_field: 'Field', /, *, min_length: 'int' = 0, max_length: 'int' = 1000, required: 'bool' = True, widget: 'SequenceWidget | type[SequenceWidget] | None' = None, label: 'str | Promise | None' = None, initial: 'object | Callable[[], object] | None' = None, help_text: 'str | Promise' = '', error_messages: 'Mapping[str, str | Promise] | None' = None, show_hidden_initial: 'bool' = False, validators: 'Sequence[Callable[..., Any]]' = (), localize: 'bool' = False, disabled: 'bool' = False, label_suffix: 'str | None' = None, template_name: 'str | None' = None, bound_field_class: 'type[BoundField] | None' = None) -> 'None'`
- `__deepcopy__(self, memo: 'dict[int, object]') -> 'Self'`
- `to_python(self, value: 'object') -> 'list[object]'`
- `clean(self, value: 'object') -> 'Collection[object]'`
- `_clean_bound_field(self, bound_field: 'BoundField') -> 'Collection[object]'`
- `validate(self, value: 'Collection[object]') -> 'None'`
- `bound_data(self, data: 'object', initial: 'object') -> 'Collection[object]'`
- `prepare_value(self, value: 'object') -> 'list[object]'`
- `has_changed(self, initial: 'object', data: 'object') -> 'bool'`
#### Methods introduced here

- `_clean_values(self, values: 'list[object]', initial_values: 'list[object]', deleted_indexes: 'frozenset[int]' = frozenset(), omitted_indexes: 'frozenset[int]' = frozenset()) -> 'list[object]'`
- `compress(self, data_list: 'list[object]') -> 'Collection[object]'`

### ListField

Alias of `SequenceField`. It defines no methods of its own.

### FrozenSequenceField

#### Overrides parent methods

- `compress(self, data_list: 'list[object]') -> 'tuple[object, ...]'`

### FrozenSequenceField

Alias of `TupleField`. It defines no methods of its own.

### SetField

#### Overrides parent methods

- `compress(self, data_list: 'list[object]') -> 'set[object] | frozenset[object]'`
- `has_changed(self, initial: 'object', data: 'object') -> 'bool'`

### FrozenSetField

`FrozenSetField` defines no methods of its own.
It inherits `SetField` behavior.

<!-- END GENERATED FIELD METHODS -->

## Checks

Run these checks after behavior-sensitive changes:

- `make check` updates docs and then runs `tscheck`, `ruff`, `mypy`, and `test`

Also run this when changes touch normalization, change detection, or collection semantics:

- `make crosshair`

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

## Doc Notes

Keep user docs `ListField`-first.
Describe the current exported field family.
Do not promise behavior that is not present in source and tests.
Use ASD-STE100 Simplified Technical English (STE).
