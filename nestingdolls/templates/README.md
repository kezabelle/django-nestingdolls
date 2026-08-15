# Template bits

This directory holds the little HTML templates that make the composite widgets
look like the rest of a Django form. There are two such widgets:

- `mapping`
- `sequence`

The awkward bit is that Django does not render every form the same way. A
parent form might use `as_div()`, `as_p()`, `as_table()`, or `as_ul()`, and a
composite widget has to fit whichever one it was handed. That is why each
widget has a top-level template for each helper style rather than one template
trying to be clever about all four.

## Reuse the boring bits

Django already knows how to render most ordinary form parts, so let it.
Duplicating those templates here only gives us another copy to keep in step
with Django for no useful reason, which is a slog.

In particular:

- the mapping `div`, `table`, and `ul` layouts reuse Django's form-helper
  output
- ordinary labels use Django's `label_tag`
- ordinary errors use Django's own error output where that is enough

The widget-specific templates should own only the markup Django cannot provide:
nesting the child fields, arranging sequence rows, and the bits around those
things.

## Shared fragments

When a fragment belongs to both `mapping` and `sequence`, put it in `shared/`.
That leaves each widget directory for the layout it actually owns, rather than
turning one widget into the other one's accidental template library.
