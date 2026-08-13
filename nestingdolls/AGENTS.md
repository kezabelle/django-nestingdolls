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
- `CompositeWidget`, `CompositeBoundField`, and `CompositeField` are internal.
  They hold shared behavior to avoid writing it twice.
- A class that holds one cohort of behavior is nested in the class that owns it,
  as Django nests `class Media`: `SequenceField.Limits`, `SequenceWidget.RowForm`,
  `SequenceWidget.RowFormSet`, `SequenceWidget.submission_countdown`, and the
  `RenderState` holders. These nested classes are private. Put a cohort of
  related methods in one of them instead of adding more methods to the owner.

## Verification

- After an implementation change, run `make check`. It writes nothing, so it is
  also the CI gate. `make fix` applies the formatter and the lint auto-fixes.
- After a TypeScript change, run `make js`. `make check` re-runs the build and
  fails on `git diff` when the committed `sequence.js` is not the current
  output, so the compiled file must stay committed.
- For a prose-only change, do not run runtime checks unless executable examples
  changed.

## Invariants

### Input handling

- Preserve direct and dash input forms.
- Preserve direct-value priority over flat input names.
- Preserve all input forms through mapping and sequence nesting.
- Do not copy or canonicalize submission keys. A subform or row formset binds
  to the raw request data with a Django prefix and reads only its own keys.
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
- A nested class already scopes its own members: `Limits`, `RowForm`,
  `RowFormSet`, `RenderState`, and the rest. Do not add a leading underscore
  inside one of them for privacy; the nesting already provides it.
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

### Rendering layouts

- The form-layout render patch in `patches.py` and the four layout
  templates for each composite widget are a deliberate, supported
  feature. Do not propose their removal to reduce code size.
- `show_hidden_initial` and hidden composite rendering are also
  supported. Keep their cost close to Django's own: one conversion
  hook (`from_hidden_initial`) and one render-state field
  (`hidden_initial_value`). Do not grow this path.

### Collection semantics

- Preserve set deduplication and order-independent set comparison.
- Check set length limits after deduplication.

## Source map

- Public exports: `nestingdolls/__init__.py`
- Composite error types, including child-error wrapping: `nestingdolls/errors.py`
- Fields: `nestingdolls/fields.py`
- Widgets and the row formset: `nestingdolls/widgets.py`
- Bound fields: `nestingdolls/boundfield.py`
- Form-layout render patch: `nestingdolls/patches.py` and `test_patches.py`
- Mapping templates and tests:
  `nestingdolls/templates/nestingdolls/mapping/` and `test_dictfield.py`
- Sequence templates and tests:
  `nestingdolls/templates/nestingdolls/sequence/` and `test_listfield.py`
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
- The countdown's budget belongs to one field's own nested tree. It does not reach a sibling field, whether that sibling sits directly on the same form or inside one mapping's child form. Django gives each formset on a page its own `absolute_max` too, with no cap shared across formsets (`django.forms.formsets.BaseFormSet.total_form_count`). The number of sequence fields on a form is fixed by the form's author, not by a submitted request, so this field follows the same precedent: do not add cross-field or cross-form sharing to work around it.
- `SequenceWidget.submission_countdown` owns only recursive sequence row multiplication. Keep it in `widgets.py`; mappings and shared composite classes must not import, start, inspect, or extend it.
- Use its normal `__enter__`/`__exit__` lifecycle around sequence parsing, extraction, and rendering. Its context holds only remaining rows and an overflow flag. Do not add marker values, field objects, lazy cap expansion, or a separate `scope()` API.
- Reserve rows at the point a submitted count turns into built rows. Two points qualify: `RowFormSet.total_form_count`, where a `TOTAL_FORMS` value becomes the number of row forms Django builds, and the direct-value clip in `SequenceWidget.value_from_datadict`. A row nested inside an active countdown reserves from the same shared budget, so a total that is legal on its own at every level still cannot multiply across sibling rows. A later step that reads an already-built row list, such as a bound field reading its cached formset's forms, must not call `take()` on that count again. It inherits the reservation. Leave a comment that says so.
- Never put the limit in overridable field `clean()` methods. Bound extraction records overflow; bound cleaning reports `too_many_forms`; rendering clips. Direct Python or decoded JSON callers own their input size and depth limits.
