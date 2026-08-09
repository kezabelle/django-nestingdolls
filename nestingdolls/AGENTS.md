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

## Verification

- After an implementation change, run `make check`. It writes nothing, so it is
  also the CI gate. `make fix` applies the formatter and the lint auto-fixes.
- After a TypeScript change, run `make js`. `make check` re-runs the build and
  fails on `git diff` when the committed `sequence.js` is not the current
  output, so the compiled file must stay committed.
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

### Naming

- A leading underscore means only `self`, or a subclass through
  inheritance, calls it. If a different class calls a method or property
  directly, even another class in this package, drop the underscore.
- A nested class already scopes its own members: `Keys`, `Bound`, `Limits`,
  `Match`, `Submitted`, and the rest. Do not add a leading underscore inside
  one of them for privacy; the nesting already provides it.
- Name a class-level constant like any other attribute: lower snake_case,
  never `_SHOUTY_CASE`.
- After a change that adds, renames, or moves a method, check every call
  site of that name against these rules, not just the one you touched.

### HTML and JavaScript

- Keep server-rendered HTML useful without JavaScript.
- Create add and remove controls from inert `<template>` elements.
- Treat `static/nestingdolls/sequence.ts` as the JavaScript source.
- Keep the compiled `static/nestingdolls/sequence.js` file committed.
- Do not add a status message, toast, or other notification element for row
  add or remove. Emit the `nestingdolls:sequence-change` event instead, and
  let the host page build its own announcement from it.

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
- Behavior shared by both lives on `CompositeWidget`,
  `CompositeBoundField`, and `CompositeField`; each overrides only what
  differs, and `test_composite.py` covers the shared contract for both.
- Each field, widget, and bound field overrides a small, deliberate set of
  Django methods. Read the class rather than a list of names: the docstring on
  each override states which Django method it replaces and why.

## Documentation language

Use ASD-STE100 Simplified Technical English in documentation, comments, and
docstrings.


## Recursive sequence limits

- Django owns request key, file, and byte limits and formset-style per-level `absolute_max`. Do not duplicate those controls.
- `SequenceWidget.SubmissionCountdown` owns only recursive sequence row multiplication. Keep it in `sequences.py`; mappings and shared composite classes must not import, start, inspect, or extend it.
- Use its normal `__enter__`/`__exit__` lifecycle around sequence extraction and rendering. Its context holds only remaining rows and an overflow flag. Do not add marker values, field objects, lazy cap expansion, or a separate `scope()` API.
- Never put the limit in overridable field `clean()` methods. Bound extraction records overflow; bound cleaning reports `too_many_forms`; rendering clips. Direct Python or decoded JSON callers own their input size and depth limits.
