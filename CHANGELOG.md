# Change history

## 1.1.0

### Sequence row names and namespaces

Sequence rows now post as `rows-0-value` rather than `rows-0`, with nested child fields sitting underneath that (like `rows-0-value-label`).

**Why the change?** Under the old naming scheme, if a subform happened to have a field named `DELETE`, its browser name became `rows-0-DELETE`. That clashed directly with Django's formset deletion control, so Django would see that key and quietly delete the entire row! Giving row values their own namespace fixes that collision.

As part of this cleanup, `SequenceWidget.RowForm` is gone, and `new_formset()` now accepts `error_messages` instead of `form_kwargs`.

### Row limits & safety

We've tightened up limits and key parsing so malformed or oversized submissions don't catch forms off guard:
- **Smarter `absolute_max` handling:** When an incoming submission exceeds `absolute_max`, we now stop building row forms immediately rather than constructing hundreds of extra forms just to throw them away. Custom `too_many_forms` error messages are now respected too.
- **Consistent budgeting:** Tuples, ranges, sets, deques, and disabled sequence rows now correctly count against the shared nested row budget.
- **Strict key parsing:** Keys like `rows-0junk` are no longer mistaken for valid row indices.

### Binding & change detection

A lot of edge cases around form binding and `has_changed()` have been ironed out so forms behave predictably in the wild:
- **Dynamic subform fields:** Any key under `<name>-...` now binds into the child form, meaning fields added or tweaked in a child form's `__init__` work seamlessly. (Tradeoff: unknown keys like `point-bogus` trigger validation errors rather than being silently dropped).
- **Compound child values & files:** `SplitDateTimeField`, multi-value file uploads, and compound rows now clean identically to browser input without triggering false `required` errors.
- **Reliable change detection:** `has_changed()` now reliably catches deleted rows, extra rows in whole lists, and changes tucked inside nested composites.
- **Reserved member names & clean defaults:** Mapping members named `DELETE` or `TOTAL_FORMS` inside sequence rows are treated as content rather than management keys, and stray keys (`rows-0_0`) or blank set members are handled correctly.

### Validation & early configuration checks

Errors and configuration issues are now caught much earlier—often when you define the form rather than when a user submits it:
- **Eager configuration checks:** `DataclassField` and `NamedTupleField` now raise `ImproperlyConfigured` right at field declaration if their output dataclass or named tuple can't accept the form's fields as keyword arguments (like `@dataclass(init=False)`), saving you from mysterious `TypeError` explosions on submission.
- **Graceful dataclass errors:** A `ValueError` raised inside your dataclass (e.g. in `__post_init__`) is now caught and turned into a normal form field validation error instead of leaking a 500 error.
- **Permissive initial values & validators:** `SetField` now accepts literal `initial` lists with duplicate entries without complaining, and validators on empty mappings run on the cleaned output (like dataclasses) just like non-empty submissions.

### Rendering & accessibility

Templates and widgets now play nicer with Django's form helpers and modern accessibility standards:
- **Persistent errors:** `form[name].errors` now correctly reflects errors added via `form.add_error()` even after the error list has been read, and hidden composites retain child errors so Django displays them at the top.
- **Consistent state & rendering:** Sequence rows consistently use the form's configured renderer, disabled sequences disable all row controls, and hidden deletions stay deleted upon re-rendering.
- **Accessibility & localisation:** Composite wrappers in `as_p()`, `as_ul()`, and `as_table()` now receive proper `role="group"`, ARIA descriptions, and ID-linked labels (matching `as_div()`), while `NumberInput` falls back to `type="text"` when `localize=True` so browsers don't wipe out comma-formatted numbers like `1,5`.

### Browser enhancements (`sequence.js`)

Client-side row interactions are now smoother and less prone to sneaky submission bugs:
- **Emptying optional sequences:** If a sequence is marked `required=False`, users can now remove all rows in the browser even if `min_length` is set, matching Django's acceptance of empty optional submissions.
- **Datalist & focus support:** Dynamically added rows update their `list` attributes for `<datalist>` suggestions, and moving focus after row removal cleanly skips disabled elements.
- **Cleaner row removal:** Removing a row now disables all of its inputs (including nested delete flags) so abandoned values never leak into the POST payload.

## 1.0.0

- Initial release. 🤷‍♀️
