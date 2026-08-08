# Template guide

This directory holds the package-owned Django templates. The repository guide
and the package guide also apply.

## Why the structure looks like this

Django renders a form through one of four helpers — `as_div()`, `as_p()`,
`as_table()`, `as_ul()` — and a composite widget has to match the one that
rendered the parent form. So each widget family has one top-level template per
layout, selected by `CompositeWidget.template_name`:

- `nestingdolls/mapping/` — mapping widgets
- `nestingdolls/sequence/` — sequence widgets
- `nestingdolls/shared/` — small fragments used by both families

Keep the top-level template names stable. Python selects them by name.

## Rules

- Prefer Django's own templates and render paths when they already produce the
  correct HTML: `subform.as_div`, `subform.as_table`, `subform.as_ul`,
  `field.label_tag`, default `{{ errors }}` rendering. `mapping/p.html` is the
  one place that cannot: `<p>` does not nest and Django offers no
  `as_p`-without-`<p>` hook, so that file duplicates Django's field loop and
  carries a comment saying so.
- Do not force reuse when it makes the HTML harder to follow, and do not build
  fake widget context to reuse one tiny Django widget template.
- Move a fragment to `shared/` only when it is genuinely generic across both
  families. Keep widget-specific structure local.
- Prefer small, obvious templates with explicit `only` includes over clever
  template abstraction. Keep whitespace handling simple.

## Safety invariants

Two templates carry invariants that a refactor can silently break. Both are
commented in place; do not remove those comments.

- `sequence/row.html` interpolates `row_tag` and `body_tag` into markup. Every
  caller must pass a hard-coded literal resolved in Python from a closed set.
- `sequence/row_content.html` and `sequence/hidden.html` `{% include %}` a
  variable template path. The value always comes from `Widget.template_name`,
  i.e. developer code. A data-derived value there is a path traversal.

## Editing workflow

1. Reuse an existing shared fragment before adding one.
2. Check whether Django already has a correct built-in path.
3. Re-run the focused rendering tests, then `make check`.
