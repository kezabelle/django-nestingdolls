# Template guide

This directory holds the package-owned Django templates. The repository guide
and the package guide also apply.

## Why the structure looks like this

Django renders a form through one of four helpers — `as_div()`, `as_p()`,
`as_table()`, `as_ul()` — and a composite widget has to match the one that
rendered the parent form. So each widget family has one top-level template per
layout, selected by `CompositeWidget.template_name`:

- `nestingdolls/mapping/` — the four mapping layout templates
- `nestingdolls/sequence/` — the four sequence layout templates and the
  fragments they include
- `nestingdolls/shared/` — small fragments used by both widget families; no
  layout template lives here

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
  widgets. Keep widget-specific structure local.
- Prefer small, obvious templates with explicit `only` includes over clever
  template abstraction. Keep whitespace handling simple.
- `as_div()` puts a composite in Django's `<fieldset>`, which holds the outer
  help and error references. The other layouts have no fieldset, so their
  composite wrapper gets `role="group"` and those references instead, from
  `wrapper_attrs` or `group_attrs`. Rows and child controls do not repeat them.
- Sequence rows print `row.widget_html`, which `SequenceWidget` renders with
  the row form's renderer. Do not include the child template instead.

## Safety invariant

One template carries an invariant that a refactor can silently break. It is
commented in place; do not remove that comment.

- `sequence/row.html` interpolates `row_tag` and `body_tag` into markup. The
  only callers are the four layout templates in `sequence/`, and each passes
  a hard-coded literal from a closed set (`div`, `span`, `li`, `tr` and
  `td` or empty). Never add a caller that passes a non-literal value.

## Editing workflow

- Reuse an existing shared fragment before adding one.
- Check whether Django already has a correct built-in path or file.