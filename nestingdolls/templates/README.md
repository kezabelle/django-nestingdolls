# Template Layout

This directory contains the HTML templates for custom field rendering for the
composite widgets:
- `mapping`
- `sequence`

## Why the structure looks like this

Django can render a form in different helper styles:
- `as_div()`
- `as_p()`
- `as_table()`
- `as_ul()`

Our composite widgets need to match the helper that rendered the parent form.
Because of that, each widget has helper-specific top-level templates.

## Reuse rules

Prefer normal Django templates when they already produce the correct HTML.

Current examples:
- mapping `div`, `table`, and `ul` layouts reuse Django form helper output
- normal label rendering uses Django `label_tag`
- normal error rendering uses Django error output where possible

## Editing guidance

If a fragment is shared by both mapping and sequence, move it to `shared/`.
