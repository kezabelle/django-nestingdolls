# Commands

Every command below is a `make` target. Run `make help` for the list.

- `make check` runs everything and writes nothing, so it is also the CI gate:
  `tscheck`, `jsdrift`, `jstest`, `ruff`, `formatcheck`, `test`, `mypy`.
- `make fix` applies the lint auto-fixes and the formatter. `check` never does.

# TypeScript

- `nestingdolls/static/nestingdolls/sequence.ts` is the source of truth.
- `nestingdolls/static/nestingdolls/sequence.js` is compiled output and must
  stay committed.
- After editing the sequence controller, run `make js`. `make check` rebuilds
  and then fails on `git diff` if the committed file is stale, so a forgotten
  rebuild cannot pass.
- `make tscheck` type-checks without emitting; `make jstest` runs the jsdom
  tests in `test_sequence.mjs`, parameterized over all four layouts.

# Python checks

- `make test` runs `test_composite`, `test_listfield`, `test_dictfield`, and
  `test_patches`.
- `make mypy` type-checks `demo.py` and the whole `nestingdolls` package under
  the settings in `mypy_settings.py`, which exists only for `django-stubs`; no
  test imports it.
- `make ruff` and `make formatcheck` cover the maintained Python files listed in
  the Makefile's `PYTHON_FILES`. `scripts/diagnose_form_data_mappings.py` is
  deliberately absent from that list.

# Input limits

Read this before you change normalization, extraction, or row counts. Do not
add a new limit before you know which part is already covered.

Django applies four settings while it parses a request. They count keys,
files, and bytes. They do not count rows.

- `DATA_UPLOAD_MAX_NUMBER_FIELDS` allows 1000 GET keys and POST keys. Above
  that value, Django raises `TooManyFieldsSent`.
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

This package can put a sequence inside a sequence. One `TOTAL_FORMS` key can
ask one level to build `absolute_max` empty rows. A request with 500 management
keys can ask for about 996000 rows across two levels. It stays below every
Django request limit. The nested multiplication is the only limit that belongs
to this package.

`SequenceWidget.submission_countdown` is the one limit that belongs to this package. It protects attacker-controlled multiplication from recursive sequence nesting, not every collection configured by an application.

- Enter `with submission_countdown(limits.submission_max)` only in sequence
  parsing, extraction, or rendering. It starts one context-local counter at
  the outer sequence; nested sequences reuse it. Do not open it in a
  mapping, `clean()`, a shared composite base class, or a field-tree walk.
- Call `take(count)` at the earliest point a submitted row count turns into
  a built list of rows. That point is `SequenceWidget.read_input`, where a
  `TOTAL_FORMS` value becomes `data_rows`/`file_rows`, not the extraction
  step that reads that list afterward. A widget that waits until extraction
  to call `take()` has already paid to build every row a forged
  `TOTAL_FORMS` asked for, once for every sibling row that reaches it.
  `take(count)` returns only rows that fit. Cleaning reports
  `too_many_forms` for the complete bound submission when extraction ran
  out; rendering shows only the prefix that fits. Exact use succeeds.
- A step that reads an already-built row list, such as `_value_from_input`
  reading `read_input`'s `data_rows`, must not call `take()` on that count
  again. It inherits the reservation. A double `take()` on the same rows
  halves the effective budget and can reject a submission that should pass.
- `Limits.submission_max` is `max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)`. The key limit covers populated rows and `absolute_max` covers empty rows. Read the setting for each submission.
- Keep the class inside `SequenceWidget`. Its `ContextVar` is a `ClassVar` containing only the remaining row count and overflow state. Do not store field objects, add sentinels, or make mappings depend on it.
- The budget belongs to one field's own nested tree only. It does not
  reach a sibling field, on the same form or inside a mapping's child
  form. Django gives each formset on a page its own `absolute_max` with
  no cap shared across formsets (`BaseFormSet.total_form_count`); the
  number of sequence fields on a form is fixed by the form's author, not
  by a request, so this follows the same accepted precedent. Do not add
  cross-field, cross-form, or request-wide sharing to work around this.

A request can hold a few nested `TOTAL_FORMS` keys that ask for 2,000 empty rows at each sequence level. Django limits parser keys, files, bytes, and one formset level; it cannot count that recursive row product. Two outer rows with three inner rows spend `2 + 6 = 8` rows. Three outer rows with 900 inner rows spend `3 + 2700 = 2703`, so the default 2,000-row cap rejects the complete submission.

`SetField.Match` counts the members that one comparison looks at with
`members_left`, which is a plain integer. `members_to_check()` counts them as
it yields them, so no caller can read a member without paying for it. Keep this
separate from `SubmissionBudget`. The two share only the idea of a limit, and
`Match` needs none of the shared-budget behaviour. A comparison must not fail
because an earlier extraction built rows. When `members_left` reaches
zero, the field reports a change, which causes one more save.

`SequenceWidget.Keys` discards bad keys before they use memory. It discards a
row index that is not below `absolute_max`. It also discards a digit run that
is longer than `max_index_digits`, which is 7. `Keys.__post_init__` refuses an
`absolute_max` of 10000000 or more, because such a field has rows that no key
can name.

Django applies its four settings to a request only. Python data and decoded
JSON do not go through the request parser. The limits of this package still
apply to them.
