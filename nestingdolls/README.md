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
flat field names.

The child form runs its normal `clean_<field>()` methods and its `clean()`
method. The widget displays the child form inside the parent field. A
non-field error stays inside the child form.

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

### Empty values

Set `required=False` to permit an empty value. `DictField` then returns `{}`.
`ListField` then returns `[]`.

If the user supplies a child value, the child field applies its normal
required rules.

### Input forms

Both fields accept direct input. Give `DictField` a mapping. Give `ListField`
a list.

Both fields also accept flat input names. Use a child name for `DictField`.
Use a numeric row index for `ListField`:

- Dash style: `point-x` or `values-0`
- Dot style: `point.x` or `values.0`
- Bracket style: `point[x]` or `values[0]`

These name styles work for form data and initial values. They also work in
nested fields.

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
