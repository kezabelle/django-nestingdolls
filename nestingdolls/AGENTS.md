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
- `CompositeWidget`, `CompositeBoundField`, and `CompositeField` in `_shared.py`
  are internal. They hold shared behavior to avoid writing it twice.
- A class that holds one cohort of behavior is nested in the class that owns it,
  as Django nests `class Media`. The owner builds one instance and keeps it under
  the lower-case name: `widget.keys`, `widget.bound`, `field.limits`, and
  `bound_field.submitted`. These nested classes are private. Put a cohort of
  related methods in one of them instead of adding more methods to the owner.

## Generated method reference

This section lists the methods that each field, widget, and bound field in this
package defines. Do not edit the text between the generated markers. Change the
source or the generator, and then run `make agents`.

<!-- BEGIN GENERATED METHOD REFERENCE -->

### CompositeField

#### Overrides parent methods

- `hidden_widget`

#### Methods introduced here

- `hidden_initial_to_python`
- `children_from_hidden_initial`

### MappingField

#### Overrides parent methods

- `__init__`
- `to_python`
- `children_from_hidden_initial`
- `clean`
- `_clean_bound_field`
- `bound_data`
- `prepare_value`
- `has_changed`

#### Methods introduced here

- `_initial_value`
- `_clean_form`

### DictField

Alias of `MappingField`. It defines no methods of its own.

### FormField

Alias of `MappingField`. It defines no methods of its own.

### Subform

Alias of `MappingField`. It defines no methods of its own.

### SequenceField

#### Overrides parent methods

- `__init__`
- `__deepcopy__`
- `to_python`
- `children_from_hidden_initial`
- `clean`
- `_clean_bound_field`
- `validate`
- `bound_data`
- `prepare_value`
- `has_changed`

#### Methods introduced here

- `min_length`
- `max_length`
- `absolute_max`
- `_initial_values`
- `_clean_values`
- `compress`

#### SequenceField.Limits

##### Methods introduced here

- `build`
- `exceeded_by`
- `bounded_count`
- `empty_count`

### ListField

Alias of `SequenceField`. It defines no methods of its own.

### FrozenSequenceField

#### Overrides parent methods

- `compress`

### TupleField

Alias of `FrozenSequenceField`. It defines no methods of its own.

### SetField

#### Overrides parent methods

- `compress`
- `has_changed`

#### SetField.Match

##### Methods introduced here

- `candidates`
- `claim`
- `complete`

### FrozenSetField

`FrozenSetField` defines no methods of its own.
It inherits `SetField` behavior.

### CompositeWidget

#### Overrides parent methods

- `value_from_datadict`
- `value_omitted_from_data`
- `use_required_attribute`
- `id_for_label`
- `media`

#### Methods introduced here

- `_child_widget`
- `template_name`
- `_value_from_normalized_data`

#### CompositeWidget.Keys

##### Methods introduced here

- `split`
- `normalized`

#### CompositeWidget.Bound

`Bound` holds data only.

### MappingWidget

#### Overrides parent methods

- `__init__`
- `_value_from_normalized_data`
- `get_context`
- `is_hidden`
- `needs_multipart_form`
- `media`

#### Methods introduced here

- `configure`
- `fields`

#### MappingWidget.Bound

`Bound` holds data only.

#### MappingWidget.Keys

##### Overrides parent methods

- `normalized`

##### Methods introduced here

- `names`
- `canonical`

### SequenceWidget

#### Overrides parent methods

- `__init__`
- `_value_from_normalized_data`
- `get_context`
- `is_hidden`
- `needs_multipart_form`
- `media`

#### Methods introduced here

- `configure`
- `_mark_row_invalid`

#### SequenceWidget.Bound

`Bound` holds data only.

#### SequenceWidget.Keys

##### Overrides parent methods

- `normalized`

##### Methods introduced here

- `management_names`
- `manages`
- `total_forms`
- `direct_rows`
- `canonical`
- `rows`

### CompositeBoundField

#### Overrides parent methods

- `errors`
- `data`
- `as_widget`
- `_has_changed`

#### Methods introduced here

- `_all_errors`
- `_data_input`
- `_file_input`
- `_prepare_widget`
- `_hidden_initial_value`
- `_flat_initial_value`

### MappingBoundField

#### Overrides parent methods

- `__init__`
- `initial`
- `_prepare_widget`

#### Methods introduced here

- `_is_bound_subform`
- `subform`

### SequenceBoundField

#### Overrides parent methods

- `__init__`
- `_prepare_widget`
- `initial`
- `_has_changed`

#### Methods introduced here

- `submitted`

#### SequenceBoundField.Submitted

##### Methods introduced here

- `management_form`
- `deleted`
- `omitted`
- `errors`

### _ValueBoundField

#### Overrides parent methods

- `data`

<!-- END GENERATED METHOD REFERENCE -->

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
- Shared composite widget, bound-field, and field behavior:
  `nestingdolls/_shared.py`
- Composite error types, including child-error wrapping: `nestingdolls/errors.py`
- Mapping fields: `nestingdolls/mappings.py`,
  `nestingdolls/templates/nestingdolls/mapping/`, `test_dictfield.py`, and
  `proof_dictfield.py`
- Sequence fields: `nestingdolls/sequences.py`,
  `nestingdolls/templates/nestingdolls/sequence/`, `test_listfield.py`, and
  `proof_listfield.py`
- Sequence JavaScript: `nestingdolls/static/nestingdolls/sequence.ts` and its
  compiled `sequence.js` file
- Generated reference: `scripts/update_package_agents.py`

## Documentation language

Use ASD-STE100 Simplified Technical English in documentation, comments, and
docstrings.
