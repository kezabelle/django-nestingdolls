# Commands

Every command below is a `make` target. Run `make help` for the list.

- `make check` runs everything and writes nothing, so it is also the CI gate:
  `tscheck`, `jsdrift`, `jstest`, `ruff`, `formatcheck`, `test`, `mypy`.
- `make fix` applies the lint auto-fixes and the formatter. `check` never does.
- `make crosshair` confirms the three semantic models in `proof_listfield.py`
  and `proof_dictfield.py`. It is slow and is not part of `check`. Run it after
  a change to normalization, change detection, or collection semantics.

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

`SubmissionCountdown` limits rows for one extraction or render. Follow these
rules:

- Start the outer scope with
  `with SubmissionCountdown(limits.submission_max) as countdown`. It stores
  the counter in its context. An inner scope gets the same counter. All levels
  spend one cap. `absolute_max` already limits one level. Do not add another
  per-level limit.
- Use `Limits.submission_max`. It is
  `max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)`. Do not use a constant
  and do not walk the field tree. The key limit covers populated rows.
  `absolute_max` covers empty rows. The default result is 2000, not 1000,
  because one `TOTAL_FORMS` key can ask for 2000 unchecked checkbox rows.
- Read the setting for each submission. Do not cache it on the field. A higher
  Django key limit gives a higher shared cap.
- A counter at zero must be safe. Extraction stops row building. Cleaning raises
  `too_many_forms` for the complete submission. Do not remove rows without an
  error. Rendering only shows rows that fit and does not raise.
- Keep the class inside `SequenceWidget`. It owns the row extraction and render
  lifetimes. `SequenceBoundField` reaches it through its configured widget. The
  class owns its `ContextVar` as a `ClassVar`. Do not move this state to
  `SequenceField`.

Example: three outer rows with 900 inner rows each need 3 + 2700 = 2703 rows.
The default shared cap of 2000 refuses the complete submission. Two outer rows
with three inner rows each use 2 + 6 = 8 rows. Parent rows and child rows both
use the shared cap.

`SetField.Match` counts the members that one comparison looks at with
`members_left`, which is a plain integer. `members_to_check()` counts them as
it yields them, so no caller can read a member without paying for it. Keep this
separate from `SubmissionCountdown`. The two share only the idea of a limit,
and `Match` needs none of the shared-countdown behaviour. A comparison must not
fail because an earlier extraction built rows. When `members_left` reaches
zero, the field reports a change, which causes one more save.

`SequenceWidget.Keys` discards bad keys before they use memory. It discards a
row index that is not below `absolute_max`. It also discards a digit run that
is longer than `max_index_digits`, which is 7. `Keys.__post_init__` refuses an
`absolute_max` of 10000000 or more, because such a field has rows that no key
can name.

Django applies its four settings to a request only. Python data and decoded
JSON do not go through the request parser. The limits of this package still
apply to them.
