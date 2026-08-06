# Template Guide

This directory contains package-owned Django templates.

## Main rule

Keep the template tree easy to read.
Prefer small obvious templates over clever template abstraction.

## What lives here

- `nestingdolls/mapping/`
  Helper-specific templates for mapping widgets.
- `nestingdolls/sequence/`
  Helper-specific templates for sequence widgets.
- `nestingdolls/shared/`
  Small generic fragments shared by more than one widget family.

## Design rules

Keep the public top-level template names stable.
These are the helper-specific entry points selected by Python rendering code.

Use Django built-in templates or rendering paths when they already produce the correct HTML.
Examples:
- `subform.as_div`
- `subform.as_table`
- `subform.as_ul`
- `field.label_tag`
- default `{{ errors }}` rendering

Do not force reuse when it makes the HTML harder to understand.
Do not build fake widget context only to reuse one tiny Django widget template.

## Shared fragment rules

Move a fragment into `shared/` only if it is truly generic across widget families.

Keep widget-specific structure local.

## Editing workflow

When changing templates:
1. Reuse existing shared fragments before adding new ones.
2. Check whether Django already has a correct built-in template or render path.
3. Prefer simple includes with explicit `only` context.
4. Keep whitespace handling simple.
5. Re-run the focused rendering tests.
