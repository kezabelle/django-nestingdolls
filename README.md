# django-nesting-dolls

`nestingdolls` adds fields for nested data to Django forms. Use these two
primary entry points:

- `DictField` validates a fixed group of named values. It returns a `dict`.
- `ListField` validates a variable number of values of one type. It returns a
  `list`.

These two names are the recommended spellings. The package exports aliases for
the same behaviours, kept for readability in code that prefers a different
word. Use the recommended name unless you have a reason not to:

| Behaviour | Recommended | Aliases |
|---|---|---|
| fixed group of named values | `DictField` | `MappingField`, `FormField`, `Subform` |
| variable-length list | `ListField` | `SequenceField` |
| variable-length tuple | `TupleField` | `FrozenSequenceField` |
| deduplicated set | `SetField` | — |
| deduplicated frozenset | `FrozenSetField` | — |

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

After a row is added or removed, the sequence root emits a bubbling
`nestingdolls:sequence-change` `CustomEvent`. Its `detail` contains an `action`
of `"add"` or `"remove"` and the row `index`. Consumers can listen for this
event when they need their own announcements or other interface updates.

The event fires after the script has synchronised the add and remove controls
and moved focus, so a listener always observes the settled state. It is not
`cancelable`: a listener cannot veto the change.

Without JavaScript there are no add or remove controls at all. Both live inside
inert `<template>` elements, so a browser with scripting disabled renders the
rows the server sent and nothing else. That is deliberate: the server never
depends on the controls existing.

### Safety notes

`ListField` uses the same row count pattern that Django formsets use.

If row count fields are present, Django validates them. `ListField` also
rejects a submitted row count above its hard upper bound. Refer to
[Resource limits](#resource-limits) for each bound and its value.

### Related types

Use these related fields when you need a different cleaned value:

- `TupleField` returns a tuple.
- `SetField` removes duplicate values and returns a set.
- `FrozenSetField` removes duplicate values and returns a frozenset.

`min_length` and `max_length` apply after `SetField` or `FrozenSetField` removes
duplicate values. The count in the error message is that post-deduplication
count, so three visible rows can report "at least 3 items (it has 2)" when two
of them are equal.

`SetField` row order is not deterministic. The widget renders the initial value
in iteration order, and a `set` of strings iterates in an order that varies with
`PYTHONHASHSEED`, so two servers can render the same form's rows in different
orders. Pass `initial` as a list or a tuple when the order matters. The package
does not sort: set members are not necessarily orderable.

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

Application code can supply the whole value under the field name: a mapping
for `DictField` or a list for `ListField`. Browser requests use prefixed input names
when they carry child or management controls; a legacy exact-name `ListField`
request with no such control supplies its repeated scalar rows.

Both fields also accept prefixed input names. Use a child name for `DictField`.
Use a numeric row index for `ListField`, joined to the field name with a
dash: `point-x` or `values-0`. These prefixed names work for form data, and they
work in nested fields. Initial values use nested Python shapes only.

A scalar mapping child keeps the last submitted value in iteration order; a
multi-value mapping child receives every repeated value under that key. A
request value under the field name itself is not composite data, so a submit
button or forged key cannot discard prefixed child input. Whole-value precedence
is reserved for application-built data, such as
`ExampleForm({"point": {"x": "1"}})`.

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

A nested field can build more rows than a Django formset can. Django request
limits count keys, files, and bytes, but they do not count rows. Refer to
[Resource limits](#resource-limits) for the limits that Django applies, and for
the limits that this package adds.


## Optional helper-aware rendering patch

Optional but recommended. Add `"nestingdolls"` to `INSTALLED_APPS` to enable it:

```python
INSTALLED_APPS = [
    # ...
    "nestingdolls",
]
```
If `"nestingdolls"` is not in `INSTALLED_APPS`, the package does not patch
`BaseForm.render`. `ListField` and `DictField` can work without the patch, but
each composite widget then uses its default inner layout.

The patch y records which standard helper renders the form. Composite widgets 
use that to select their inner layout.

This patch is included because Django does not tell a widget which helper method
rendered the parent form. If the parent form uses `as_p()`, `as_table()`,
`as_ul()`, or `as_div()`, the widget does not know that by default.


## Resource limits

Django and this package have different jobs. Django limits request parsing before a form sees data; this package adds one narrow guard for row work that Django cannot see. It does not replace Django's parser limits or formset-style limits.

### Limits that Django applies

Django applies these settings while parsing a request. If a parser limit rejects the request, the form does not receive its data.

| Setting | Default | What it counts | Result above the limit |
|---|---:|---|---|
| `DATA_UPLOAD_MAX_NUMBER_FIELDS` | 1000 | GET and POST keys | Django raises `TooManyFieldsSent` |
| `DATA_UPLOAD_MAX_NUMBER_FILES` | 100 | Uploaded files | Django raises `TooManyFilesSent` |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | 2621440 (2.5 MB) | Request-body bytes | Django raises `RequestDataTooBig` |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | 2621440 (2.5 MB) | One upload held in memory | Django writes the upload to a temporary file |

Those limits count parser input, not rows. One small `TOTAL_FORMS` management key can ask a sequence to construct many rows. This is valid for unchecked checkbox rows: each unchecked row sends no value key, but the server must still construct it. Django formsets separately enforce `max_num` and `absolute_max` for one level; their defaults are 1000 and 2000. A Django formset cannot contain another formset, so it has no nested-row multiplication to limit.

### Nested sequence rows

`ListField` follows Django's per-level `absolute_max`, then adds exactly one aggregate guard for **a sequence nested in a sequence**. A request can use 498 outer management entries and 2,000 inner empty-checkbox rows per outer entry: fewer than Django's default 1,000 parsed keys request about 996,000 rows. Each individual level is within its 2,000-row cap. That attacker-controlled multiplication is the gap this package owns.

`SequenceWidget.submission_countdown` is deliberately small. The outer sequence extraction or render enters it with `SequenceField.Limits.submission_max`:

```
submission_max = max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)
```

Nested `SequenceWidget` calls reuse the same context-local integer counter and charge both parent and child rows. Cleaning rejects the complete submission with `too_many_forms` if the counter runs out. Rendering clips ordinary input but redisplays no submitted rows after that rejection, so it cannot repeat the rejected work. Exact use of the counter is valid. The configured limit is read for each submission.

`DictField` has no rows and does not participate in this counter. A mapping may contain one or many independent `ListField` values, just as an ordinary Django form may. Their number is application structure chosen by the developer, not an attacker-created nesting level; each keeps its own per-level hard cap. The package intentionally does not add a global form-tree walker or a mapping-specific policy.

### Data that does not come from a request

Django's parser settings apply only to requests. Python lists or mappings passed directly to a form, and decoded JSON, bypass them. The sequence field still enforces its normal per-level `absolute_max`; callers accepting arbitrary decoded or programmatic structures must also set their own size and depth limits before creating the form.
