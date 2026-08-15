# Package guide for agents

This guide applies to work in `nestingdolls/`. The repository guide also
applies.

## Purpose

This package adds mapping and sequence fields to Django forms. It preserves
normal Django behavior and uses JavaScript only for progressive enhancement.

## Public API

- `DictField` is the primary name for a fixed mapping. The class is
  `MappingField`; `DictField`, `FormField`, and `Subform` are aliases of it.
  `NamedTupleField` and `DataclassField` subclass it to return a named tuple
  or a dataclass.
- `ListField` is the primary name for an ordered sequence. The class is
  `SequenceField`; `ListField` is its alias. `FrozenSequenceField` subclasses
  it to return a tuple, and `TupleField` is its alias. `SetField` returns a
  set, and `FrozenSetField` returns a frozenset.
- Mapping and sequence widgets and bound fields are advanced integration hooks.
- All five error classes in `errors.py` are public. `InvalidInitialValueError`
  is a `ValueError` for initial data with the wrong shape. The other four are
  `ValidationError` subclasses: `ItemValidationError`,
  `MappingInputValidationError`, `SequenceInputValidationError`, and
  `TooManyFormsValidationError`.
- `CompositeWidget`, `CompositeBoundField`, and `CompositeField` are internal.
  They hold shared behavior to avoid writing it twice.
- A class that holds one cohort of behavior is nested in the class that owns it,
  as Django nests `class Media`: `SequenceField.Limits`, `SequenceWidget.RowForm`,
  `SequenceWidget.RowFormSet`, `SequenceWidget.submission_countdown`, and the
  `RenderState` holders. These nested classes are private. Put a cohort of
  related methods in one of them instead of adding more methods to the owner.

## Invariants

### Input handling

- Preserve whole-value and prefixed input forms.
- Preserve whole-value priority over prefixed input names.
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
- The script's source file, build steps, and code rules are in
  `static/AGENTS.md`.
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
- App registration that installs the render patch at startup:
  `nestingdolls/apps.py`
- Mapping templates and tests:
  `nestingdolls/templates/nestingdolls/mapping/` and `test_dictfield.py`
- Sequence templates and tests:
  `nestingdolls/templates/nestingdolls/sequence/` and `test_listfield.py`
- Named tuple and dataclass mapping outputs: `nestingdolls/fields.py` with
  `test_namedtuplefield.py` and `test_dataclassfield.py`
- Hostile requests and the row budget: `test_hostile.py`; `pathological.py`
  measures their cost
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

Rules for comments and docstrings in implementation code:

- Do not restate what the code already says.
- Do not use a comment to excuse unclear code; make the code clear first.
- If a clear comment is hard to write, examine the code for a problem.
- A comment must remove confusion, not create it.
- Explain unidiomatic code; a reader must not "fix" it into a bug.
- Put a reference (ticket, spec, measurement) at the point where the reader
  needs it.
- When you fix a bug, leave a comment that records the cause, so the bug
  does not return.

## Input limits

Read this before you change normalization, extraction, or row counts. Do not
add a new limit before you know which part is already covered.

Django applies four settings while it parses a request. They count keys,
files, and bytes. They do not count rows.

- `DATA_UPLOAD_MAX_NUMBER_FIELDS` allows 1000 keys in each of GET and POST.
  Above that value, Django raises `TooManyFieldsSent`.
- `DATA_UPLOAD_MAX_NUMBER_FILES` allows 100 uploaded files. Above that value,
  Django raises `TooManyFilesSent`.
- `DATA_UPLOAD_MAX_MEMORY_SIZE` allows 2621440 bytes in the request body.
  Above that value, Django raises `RequestDataTooBig`. This is a byte limit. It
  does not limit rows.
- `FILE_UPLOAD_MAX_MEMORY_SIZE` allows 2621440 bytes of one upload in memory.
  Above that value, Django writes the upload to a temporary file.

A Django formset limits one level with `absolute_max`. Its default `max_num` is
1000 and its default `absolute_max` is 2000. A formset cannot contain another
formset, so Django does not multiply row counts. For Django, the key limit and
`absolute_max` are enough. Do not repeat those checks here.

This package can put a sequence inside a sequence, and Django cannot count
that recursive row product. One `TOTAL_FORMS` key can ask one level to build
`absolute_max` empty rows. A request with 998 keys can ask for 996,498 rows
across two levels: 498 outer rows that each carry a nested `TOTAL_FORMS`
claim of 2000 (the "2 levels, 498x2000 spread" case in `pathological.py`).
It stays below every Django request limit. The nested multiplication is the
only limit that belongs to this package. Two outer rows with three inner
rows spend `2 + 6 = 8` rows. Three outer rows with 900 inner rows spend
`3 + 2700 = 2703`, so the default 2,000-row cap rejects the complete
submission.

`SequenceWidget.submission_countdown` is the one limit that belongs to this
package. It protects attacker-controlled multiplication from recursive
sequence nesting, not every collection configured by an application.

- Enter `with submission_countdown(limits.submission_max)` only in sequence
  parsing, extraction, or rendering. It starts one context-local counter at
  the outer sequence; nested sequences reuse it. Do not open it in a
  mapping, `clean()`, a shared composite base class, or a field-tree walk.
  A site needs the scope only if it does one of two things: spend budget, or
  drive the lazy recursion that builds a nested level. Building a row form
  does not build the rows inside it. Those appear only when something reads
  or renders that row's value, so the scope must stay open across the read,
  and the reader is the site that must hold it. That gives exactly five
  sites, and any sixth is a duplicate. Three spend: `RowFormSet.
  total_form_count` (a submitted `TOTAL_FORMS`), `SequenceWidget.
  value_from_datadict` (a whole Python list, and it drives extraction),
  and `SequenceField.prepare_value` (server initial rows, and it drives
  preparation). Two only drive: `SequenceWidget.get_context` for a render
  and `SequenceBoundField.data` for an extraction.
  Everything else inherits. Cleaning and change detection both reach rows
  through `SequenceBoundField.data`, so `SequenceField._clean_bound_field`
  reads `bound_field.submission_overflow`, which performs that one
  extraction, instead of opening a scope of its own. A second scope there
  would find every row list already built and could only take rows twice.
  Only the scope that owns the shared counter (`owns_scope`) records
  overflow, so one oversized submission reports one `too_many_forms` error,
  not one child item error per row.
  That list is closed, and a sixth site is not a harmless addition. Only the
  owning scope reports, so a scope opened anywhere above a sequence takes
  ownership away from `SequenceBoundField.data` and silences the report.
  Rows past the budget are then dropped from a submission that still cleans
  as valid. A sequence configured for 50 rows, extracted under an outer
  scope of 20, keeps 20 rows, raises nothing, and loses the other 10. The
  first scope entered also fixes the budget for every sequence beneath it,
  so an outer scope built from anything other than that sequence's own
  `limits.submission_max` silently replaces the limit the application
  chose. This is why the scope does not belong in `CompositeBoundField`: a
  mapping reaches its children through a child `Form` and a sequence reaches
  its rows through a `BaseFormSet`, so the shared base has no row-building
  path to wrap, and it has no `absolute_max` from which to derive a budget.
- Call `take(count)` at the earliest point a submitted row count turns into
  built rows. Two points qualify for a submitted count:
  `RowFormSet.total_form_count`, where a `TOTAL_FORMS` value becomes the
  number of row forms Django builds, and the whole-value clip in
  `SequenceWidget.value_from_datadict`, where a Python list under the field's
  own name becomes rows. `SequenceField.prepare_value` also takes, but for
  server-provided initial rows rather than a submission. A row nested inside
  an active countdown reserves from the same shared budget, so a total that
  is legal on its own at every level still cannot multiply across sibling
  rows. A step that waits until after row construction to call `take()` has
  already paid to build every row a forged `TOTAL_FORMS` asked for, once for
  every sibling row that reaches it. `take(count)` returns only rows that
  fit. Cleaning reports `too_many_forms` for the complete bound submission
  when extraction ran out; rendering shows only the prefix that fits. Exact
  use succeeds. Never put the limit in an overridable field `clean()`
  method: bound extraction records overflow, bound cleaning reports the
  error, and rendering clips.
- A step that reads an already-built row list, such as a bound field
  reading its cached formset's forms, must not call `take()` on that count
  again. It inherits the reservation, and a comment at that step must say
  so. A double `take()` on the same rows halves the effective budget and can
  reject a submission that should pass.
- `Limits.submission_max` is `max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)`. The key limit covers populated rows and `absolute_max` covers empty rows. Read the setting for each submission.
- Keep the class inside `SequenceWidget`, and use its normal
  `__enter__`/`__exit__` lifecycle. Mappings and the shared composite base
  classes must not import, start, inspect, or extend it. Its `ContextVar` is
  a `ClassVar` containing only the remaining row count and overflow state. Do
  not store field objects, add sentinels or marker values, or add lazy cap
  expansion or a separate `scope()` API.
- The budget belongs to one field's own nested tree only. It does not
  reach a sibling field, on the same form or inside a mapping's child
  form. Django gives each formset on a page its own `absolute_max` with
  no cap shared across formsets (`BaseFormSet.total_form_count`); the
  number of sequence fields on a form is fixed by the form's author, not
  by a request, so this follows the same accepted precedent. Do not add
  cross-field, cross-form, or request-wide sharing to work around this.

The "Input handling" rule that no submission key is copied or canonicalized
is also a limit: a forged key such as `values-99999999` is never read. Django
builds rows `0` through `total_form_count`, which is `min(TOTAL_FORMS,
absolute_max)`, and each row form reads only its own exact keys. With no copy
step, there is no per-key memory to protect and no index grammar to enforce.

`SetField.has_changed` is linear and conservative. It pairs each converted
row with the member it hashes to, then lets the child field compare that one
pair. A row that pairs with no member reports a change unless the child says
the row is blank. There is no pairwise scan of rows against members, so no
comparison budget exists, and a comparison never fails because an earlier
extraction built rows. Ambiguity reports a change, which costs one more save.

Django applies its four settings to a request only. Python data and decoded
JSON do not go through the request parser. The limits of this package still
apply to them, and Python and decoded JSON callers own their own input size
and depth limits.

## Key scans

A loop that tests a prefix against every submitted key can run once per bound
row, so its per-key cost is load-bearing. `pathological.py` at the repository
root measures it; its docstring records one run's numbers and says the output
of a new run wins over the recorded text. The rules apply where the loop
reads every key: `SequenceWidget.has_row_keys` and
`RowFormSet.rows_with_submitted_values`. `MappingWidget._accepts_key` keeps
`removeprefix`; it measured at or below 0.002s, so it is not worth the same
treatment. The rules the measurements produced:

- Hold the prefix length in a local and compare a slice, `key[:n] == prefix`,
  rather than calling `key.startswith(prefix)`. `str.startswith` accepts
  `(prefix, start, end)`, so it is `METH_VARARGS` and every call builds an
  argument tuple; `key[:n]` is a `BINARY_SLICE` opcode and builds none. Worth
  1.1x to 1.2x. No length guard is needed: a key shorter than the prefix
  yields a shorter string, which cannot equal it.
- Write the loop out instead of putting a generator expression in `any()`. One
  frame resume per key is real cost when the loop reads every key.
- Do not reorder a cheap character test ahead of the prefix compare to skip
  calls. Measured at 0.61x: it skips 202 of 998 calls and pays a slice and
  two comparisons on all 998.

`cProfile` counts `startswith` as a call and charges per-call overhead to it,
while a slice is an opcode and is invisible. Swapping one for the other flatters
a profile more than it speeds up a request. Believe wall time.
