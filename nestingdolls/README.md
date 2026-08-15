# nestingdolls

`nestingdolls` adds fields for nested data to Django forms. Use these two
primary entry points:

- `DictField` validates a fixed group of named values. It returns a `dict`.
- `ListField` validates a variable number of values of one type. It returns a
  `list`.

## DictField

### Purpose

Use `DictField` for one object that has a fixed set of named values. Examples
include coordinates, postal addresses, and settings.

`DictField` takes a Django form class as its first argument. The child form
defines the names, fields, and validation rules.

### Basic use

This example defines and validates a point that has two integer values:

```python
from django import forms
import nestingdolls


class PointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()


class ExampleForm(forms.Form):
    point = nestingdolls.DictField(PointForm)


form = ExampleForm({"point": {"x": "1", "y": "2"}})

assert form.is_valid()
assert form.cleaned_data == {"point": {"x": 1, "y": 2}}
```

### Field-specific behavior

If the input contains an exact mapping, the exact mapping has priority over
prefixed field names.

The child form runs its normal `clean_<field>()` methods and its `clean()`
method. The widget displays the child form inside the parent field. A
non-field error stays inside the child form.

### Safety notes

If a child widget needs repeated values, `DictField` keeps the same repeated
value behavior that Django already uses for request data.

### Related names

`MappingField`, `FormField`, and `Subform` are aliases for `DictField`. All four
names have the same behavior.

## ListField

### Purpose

Use `ListField` for an ordered group of repeated values. Examples include
email addresses, integer identifiers, and uploaded files.

`ListField` takes a Django field instance as its first argument. The child
field defines the widget, conversion, and validation for each row.

### Basic use

This example defines and validates a list that contains no more than five
integers:

```python
from django import forms
import nestingdolls


class ExampleForm(forms.Form):
    values = nestingdolls.ListField(
        forms.IntegerField(),
        required=False,
        min_length=0,
        max_length=5,
    )


form = ExampleForm({"values": ["1", "2"]})

assert form.is_valid()
assert form.cleaned_data == {"values": [1, 2]}
```

### Field-specific behavior

Use `min_length` and `max_length` to control the number of rows.

The server displays usable rows without JavaScript. JavaScript adds controls
that add and remove rows. The widget keeps these controls in inert `<template>`
elements until JavaScript starts.

The widget includes its JavaScript in Django form media. Render `form.media`
when you want the add and remove controls.

The script emits bubbling `CustomEvent`s from the sequence root, so a host
page can hook row changes without patching this package:

- `nestingdolls:sequence-add` fires before the script clones a new row.
  `detail` contains the `index` the new row will receive. The event is
  `cancelable`: `preventDefault()` stops the add.
- `nestingdolls:sequence-remove` fires before the script hides a row. `detail`
  contains the row `index` and the `row` element. The event is `cancelable`:
  `preventDefault()` stops the removal.
- `nestingdolls:sequence-change` fires after a row was added or removed.
  `detail` contains an `action` of `"add"` or `"remove"`, the row `index`, and
  the `row` element. It fires after the script has synchronised the controls
  and moved focus, so a listener observes the settled state. Use it to
  initialise third-party widgets inside an added `row`. It is not
  `cancelable`.
- `nestingdolls:sequence-ready` fires once per sequence widget after the
  script attaches its controls. For a widget in the initial page it fires when
  the script starts, so register that listener before the script runs. For a
  nested sequence inside an added row it fires during the add, before that
  row's `nestingdolls:sequence-change`.

### Safety notes

`ListField` uses the same row count pattern that Django formsets use.

If row count fields are present, Django validates them. `ListField` also
rejects a submitted row count above its hard upper bound.

### Related types

Use these related fields when you need a different cleaned value:

- `TupleField` returns a tuple.
- `SetField` removes duplicate values and returns a set.
- `FrozenSetField` removes duplicate values and returns a frozenset.

`min_length` and `max_length` apply after `SetField` or `FrozenSetField` removes
duplicate values.

## Behavior that both fields share

### Django integration

Both fields use standard Django fields, widgets, and validation. Each child
field keeps its normal conversion and validation rules.

Both fields support file uploads, compound widgets, multipart forms, and
widget media. Each validation error stays near the child value that caused
the error.

The optional helper-aware rendering patch only changes package-owned wrapper
markup. It does not rewrite Django child widgets or third-party child widgets.

### Form renderer scope

The app does not currently supply or support Django's Jinja2 form renderer. 
It only supports normal Django Template Language via `DjangoTemplates` or
`TemplatesSetting` when that renderer loads the templates through
a DTL backend.

### Empty values

Set `required=False` to permit an empty value. `DictField` then returns `{}`.
`ListField` then returns `[]`.

If the user supplies a child value, the child field applies its normal
required rules.

### Input forms

Both fields accept a whole value. Give `DictField` a mapping. Give `ListField`
a list.

Both fields also accept prefixed input names. Use a child name for `DictField`.
Use a numeric row index for `ListField`, joined to the field name with a
dash: `point-x` or `values-0`. These prefixed names work for form data, and they
work in nested fields. Initial values use nested Python shapes only.

### Nested fields

You can put either primary field inside the other primary field. This example
defines a list of items. Each item has a name and a list of tags.

```python
from django import forms
import nestingdolls


class ItemForm(forms.Form):
    name = forms.CharField()
    tags = nestingdolls.ListField(
        forms.CharField(),
        required=False,
    )


class ExampleForm(forms.Form):
    owner = forms.CharField()
    items = nestingdolls.ListField(
        nestingdolls.DictField(ItemForm),
        required=False,
    )
```

After validation, `items` is a list of dictionaries. The `tags` value in each
dictionary is a list:

```python
cleaned_data = {
    "owner": "kezabelle",
    "items": [
        {
            "name": "Example item",
            "tags": ["one", "two"],
        },
        {
            "name": "Another item",
            "tags": ["a", "b"],
        },
    ],
}
```

### Safety notes

Nested fields still use the normal child form and child field validation that
Django already provides.

The fields still respect Django request and upload limits such as
`DATA_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_NUMBER_FIELDS`,
`DATA_UPLOAD_MAX_NUMBER_FILES`, and `FILE_UPLOAD_MAX_MEMORY_SIZE`.


## Rendering configuration

### Recommended: install the app

Add `"nestingdolls"` to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "nestingdolls",
]
```

This is the recommended configuration. Django's default
`django.forms.renderers.DjangoTemplates` renderer discovers the package templates
through the app registry. `NestingDollsConfig.ready()` also installs the
helper-aware patch, so `as_p()`, `as_table()`, `as_ul()`, and `as_div()` select
matching composite widget wrappers. No `TEMPLATES` or `FORM_RENDERER` change is
needed.

### Without the app registry

If you cannot add `"nestingdolls"` to `INSTALLED_APPS`, configure template
loading explicitly. Package templates are included in the distribution, but the
default `DjangoTemplates` form renderer does not use the project `TEMPLATES`
setting. Adding the package directory to a backend `DIRS` list alone therefore
does not make the widgets render.

Use Django's built-in `TemplatesSetting` form renderer, not a custom renderer.
Keep `"django.forms"` in `INSTALLED_APPS` so that renderer can load Django's
own form templates. Add the package template directory to the Django Template
Language backend that renders your forms; keep your other template directories,
backends, and options unchanged. For example:

```python
from pathlib import Path

import nestingdolls

NESTINGDOLLS_TEMPLATE_DIR = Path(nestingdolls.__file__).parent / "templates"

INSTALLED_APPS = [
    # ...
    "django.forms",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
            NESTINGDOLLS_TEMPLATE_DIR,
        ],
        "APP_DIRS": True,
        # Keep your existing OPTIONS and other configuration here.
    },
]

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"
```

This configuration renders the composite widgets, but it does not install the
helper-aware patch. Every helper therefore uses the widgets' default `div`
wrapper; `as_p()`, `as_table()`, and `as_ul()` do not select their matching
inner layouts.


## Resource limits

Django limits request parsing before a form receives data. `DATA_UPLOAD_MAX_NUMBER_FIELDS` limits keys, the file setting limits uploads, and the memory settings limit bytes. Django formsets also enforce `max_num` and `absolute_max` for one level. These limits are necessary but do not bound a recursive `ListField`: a small set of nested `TOTAL_FORMS` keys can request many empty rows without exceeding the request-key limit.

`ListField` therefore has one narrow extra guard. `SequenceWidget.submission_countdown` starts at the outer sequence extraction or render with `max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)`. Nested sequences share its context-local remaining-row count and spend both parent and child rows. If extraction runs out, validation rejects the complete submission with `too_many_forms`; rendering shows only the rows that fit. Exact use of the count succeeds.

`DictField` has no rows and does not participate. A mapping can contain independent list fields, just as an ordinary Django form can. Their number is application structure, not an attacker-created sequence level, so this package does not add a mapping policy or a global form-tree walk. Python values and decoded JSON bypass Django's request parser; callers accepting arbitrary structures must set their own size and depth limits before creating the form.
