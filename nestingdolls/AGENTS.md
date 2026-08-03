# Package guide for agents

This guide applies to work in `nestingdolls/`. The repository guide also
applies.

## Purpose

This package adds mapping and sequence fields to Django forms. It preserves
normal Django behavior and uses JavaScript only for progressive enhancement.

## Public API

- `DictField` is the primary field for a fixed mapping. `MappingField`,
  `FormField`, and `Subform` are aliases.
- `ListField` is the primary field for an ordered sequence. `SequenceField` is
  its implementation name.
- `TupleField`, `SetField`, and `FrozenSetField` return other collection types.
- Mapping and sequence widgets and bound fields are advanced integration hooks.
- `InvalidInitialValueError` reports an invalid initial value.

## Generated method reference

Do not edit the text between the generated markers. Change the source or the
generator, and then run `make agents`.

<!-- BEGIN GENERATED FIELD METHODS -->

### MappingField

#### Overrides parent methods

- `__init__(self, form_class: 'type[BaseForm]', /, *, required: 'bool' = True, widget: 'MappingWidget | type[MappingWidget] | None' = None, label: 'str | Promise | None' = None, initial: 'object | Callable[[], object] | None' = None, help_text: 'str | Promise' = '', error_messages: 'Mapping[str, str | Promise] | None' = None, show_hidden_initial: 'bool' = False, validators: 'Sequence[Callable[..., Any]]' = (), localize: 'bool' = False, disabled: 'bool' = False, label_suffix: 'str | None' = None, template_name: 'str | None' = None, bound_field_class: 'type[MappingBoundField] | None' = None) -> 'None'`
- `to_python(self, value: 'object') -> 'dict[str, object]'`
- `clean(self, value: 'object') -> 'dict[str, object]'`
- `_clean_bound_field(self, bound_field: 'BoundField') -> 'dict[str, object]'`
- `bound_data(self, data: 'object', initial: 'object') -> 'object'`
- `prepare_value(self, value: 'object') -> 'object'`
- `has_changed(self, initial: 'object', data: 'object') -> 'bool'`
#### Methods introduced here

- `_clean_form(self, form: 'BaseForm') -> 'dict[str, object]'`

### DictField

Alias of `MappingField`. It defines no methods of its own.

### FormField

Alias of `MappingField`. It defines no methods of its own.

### Subform

Alias of `MappingField`. It defines no methods of its own.

### SequenceField

#### Overrides parent methods

- `__init__(self, child_field: 'Field', /, *, min_length: 'int' = 0, max_length: 'int' = 1000, absolute_max: 'int | None' = None, required: 'bool' = True, widget: 'SequenceWidget | type[SequenceWidget] | None' = None, label: 'str | Promise | None' = None, initial: 'object | Callable[[], object] | None' = None, help_text: 'str | Promise' = '', error_messages: 'Mapping[str, str | Promise] | None' = None, show_hidden_initial: 'bool' = False, validators: 'Sequence[Callable[..., Any]]' = (), localize: 'bool' = False, disabled: 'bool' = False, label_suffix: 'str | None' = None, template_name: 'str | None' = None, bound_field_class: 'type[SequenceBoundField] | None' = None) -> 'None'`
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

## Verification

- After an implementation change, run `make check`. This target can fix Python
  files and update the generated method reference.
- After a TypeScript change, run `make js` before `make check`. Keep the
  generated `sequence.js` file committed.
- After a change to normalization, change detection, or collection semantics,
  also run `make crosshair`.
- For a prose-only change, do not run runtime checks unless executable examples
  changed.

## Invariants

### Input handling

- Preserve direct, dash, dot, and bracket input forms.
- Preserve direct-value priority over flat input names.
- Preserve all input forms through mapping and sequence nesting.
- Retain original keys and canonical keys during normalization.
- Keep mapping `data` and `files` separate through nested widgets.

### Django behavior

- Preserve child form clean hooks and non-field errors.
- Delegate value extraction, preparation, bound data, and change detection to
  child widgets and fields.
- Preserve file fields, compound widgets, multipart forms, and widget media.
- Keep child errors inline. Do not duplicate them as outer field errors.

### HTML and JavaScript

- Keep server-rendered HTML useful without JavaScript.
- Create add and remove controls from inert `<template>` elements.
- Treat `static/nestingdolls/sequence.ts` as the JavaScript source.
- Keep the compiled `static/nestingdolls/sequence.js` file committed.

### Collection semantics

- Preserve set deduplication and order-independent set comparison.
- Check set length limits after deduplication.

## Source map

- Public exports: `nestingdolls/__init__.py`
- Mapping fields: `nestingdolls/mappings.py`,
  `nestingdolls/templates/django/forms/widgets/dictwidget.html`,
  `test_dictfield.py`, and `proof_dictfield.py`
- Sequence fields: `nestingdolls/sequences.py`,
  `nestingdolls/templates/django/forms/widgets/sequence.html`,
  `test_listfield.py`, and `proof_listfield.py`
- Sequence JavaScript: `nestingdolls/static/nestingdolls/sequence.ts` and its
  compiled `sequence.js` file
- Generated reference: `scripts/update_package_agents.py`

## Documentation language

Use ASD-STE100 Simplified Technical English in documentation, comments, and
docstrings.
