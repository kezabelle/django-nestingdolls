# nestingdolls

`nestingdolls` gives Django forms nested values without turning your form into
a flat-key reconstruction project. `DictField` wraps a child `Form` and returns
its cleaned values as one dictionary. `ListField` repeats one child `Field` in
rows and returns their cleaned values as one list.

Use them when a screen edits an address, an order, a schedule, or another value
your application passes around as one unit. Child fields still handle widgets,
conversion, validation, uploads, and errors. `nestingdolls` just keeps the
relevant bits together.

## Examples

### Fixed values from a browser or Python

A fixed shape belongs in a child form. A browser submits its children as
prefixed strings; application code can pass one nested Python value directly.
Either route runs the same child-field cleaning.

```python
from django import forms
from django.http import QueryDict

import nestingdolls


class TimeWindowForm(forms.Form):
    start_hour = forms.IntegerField(min_value=0, max_value=23)
    duration_minutes = forms.IntegerField(min_value=1)


class ReminderForm(forms.Form):
    window = nestingdolls.DictField(TimeWindowForm)


# These names match the rendered inputs.
browser_form = ReminderForm(QueryDict("window-start_hour=9&window-duration_minutes=45"))

# A worker, API adapter, or test can pass the whole value instead.
python_form = ReminderForm({"window": {"start_hour": 9, "duration_minutes": 45}})

for form in (browser_form, python_form):
    assert form.is_valid()
    assert form.cleaned_data["window"] == {
        "start_hour": 9,
        "duration_minutes": 45,
    }
```

### Repeated values from a browser or decoded data

A browser sequence looks like a formset submission. A decoded Python list skips
the management fields and indexed row names. Either way, the child field cleans
every row the same way.

```python
class ReorderForm(forms.Form):
    quantities = nestingdolls.ListField(
        forms.IntegerField(min_value=1),
        min_length=1,
        max_length=5,
    )


browser_form = ReorderForm(
    QueryDict(
        "quantities-TOTAL_FORMS=2&quantities-INITIAL_FORMS=0&"
        "quantities-0=2&quantities-1=3"
    )
)
python_form = ReorderForm({"quantities": [2, "3"]})

for form in (browser_form, python_form):
    assert form.is_valid()
    assert form.cleaned_data["quantities"] == [2, 3]
```

### Validate decoded JSON, YAML, or CSV

Decode external data first, then pass the resulting list under the field name.
It gets the same row conversion and length checks as a browser submission.

```python
import csv
import json

import yaml


json_form = ReorderForm(json.loads('{"quantities": [2, 3]}'))
yaml_form = ReorderForm(yaml.safe_load("quantities:\n  - 2\n  - 3"))
csv_form = ReorderForm({"quantities": next(csv.reader(["2,3"]))})

for form in (json_form, yaml_form, csv_form):
    assert form.is_valid()
    assert form.cleaned_data["quantities"] == [2, 3]
```

Use `yaml.safe_load`, not `yaml.load`. The decoder owns input-size and
whole-input limits; the field only sees decoded values.

### Return a set, dataclass, or named tuple

`FrozenSetField` cleans each row, drops duplicates, and returns a `frozenset`.
Rows must be hashable. That's simply the deal with sets.

```python
class TagsForm(forms.Form):
    tags = nestingdolls.FrozenSetField(forms.IntegerField(), min_length=1)


form = TagsForm({"tags": [1, "2", 1]})
assert form.is_valid()
assert form.cleaned_data["tags"] == frozenset({1, 2})
```

Use `output=` when your application wants a domain type rather than a plain
mapping. The output type's field names must match the child form's.

```python
from dataclasses import dataclass
from typing import NamedTuple


@dataclass
class Point:
    x: int
    y: int


class PointTuple(NamedTuple):
    x: int
    y: int


class PointForm(forms.Form):
    x = forms.IntegerField()
    y = forms.IntegerField()


class PlotForm(forms.Form):
    point = nestingdolls.DataclassField(PointForm, output=Point)
    origin = nestingdolls.NamedTupleField(PointForm, output=PointTuple)


form = PlotForm({"point": {"x": 2, "y": "3"}, "origin": {"x": 0, "y": 0}})

assert form.is_valid()
assert form.cleaned_data["point"] == Point(x=2, y=3)
assert form.cleaned_data["origin"] == PointTuple(x=0, y=0)
```

### Compose fields and show an initial value

A mapping can contain a sequence of mappings. You don't have to flatten it
again; application data stays nested at every level. The same shape works for
validation and for `initial` rendering.

```python
class SessionForm(forms.Form):
    room = forms.CharField()
    seats = forms.IntegerField(min_value=1)


class AgendaForm(forms.Form):
    host = forms.CharField()
    sessions = nestingdolls.ListField(
        nestingdolls.DictField(SessionForm),
        min_length=1,
    )


class ConferenceForm(forms.Form):
    agenda = nestingdolls.DictField(AgendaForm)


agenda = {
    "host": "Ada",
    "sessions": [
        {"room": "Aster", "seats": 20},
        {"room": "Birch", "seats": "35"},
    ],
}

bound = ConferenceForm({"agenda": agenda})
redisplay = ConferenceForm(initial={"agenda": agenda})

assert bound.is_valid()
assert bound.cleaned_data["agenda"]["sessions"][1]["seats"] == 35
assert redisplay["agenda"].initial == agenda
```

### Keep files with their row metadata

Wrap a child form in `DictField` when every repeated row needs ordinary values
and an upload side by side. Bind Django's `POST` and `FILES` as usual:

```python
class ArtifactForm(forms.Form):
    label = forms.CharField()
    blob = forms.FileField()


class ReleaseForm(forms.Form):
    artifacts = nestingdolls.ListField(
        nestingdolls.DictField(ArtifactForm),
        min_length=1,
    )


form = ReleaseForm(request.POST, request.FILES)
```

Render it inside `<form method='post' enctype='multipart/form-data'>`, and
include `{{ form.media }}` whenever the page renders a sequence.

`{{ form.media }}` loads the JavaScript that lets users add and remove rows. Without
it, every row rendered at page load still submits and validates normally, but users
cannot change the row count in the browser.

## Reference

### Mapping fields

Every mapping field takes a Django `Form` class that Django can construct with
no arguments. That form declares the names and child fields in the returned
value.

| Field | Cleaned value |
|---|---|
| `DictField` | `dict` |
| `MappingField`, `FormField`, `Subform` | Aliases for `DictField`; `dict` |
| `NamedTupleField` | Named tuple |
| `DataclassField` | Dataclass |

`NamedTupleField` and `DataclassField` accept `output=`. Its fields must match
the child form's declared names. Leave `output=` out and the field builds a
matching named tuple or dataclass for you.

An optional `DictField` returns `{}` when empty. An optional `NamedTupleField`
or `DataclassField` returns `None`; there is no useful empty instance to hand
back.

### Sequence fields

Every sequence field takes one positional Django `Field` instance and
deep-copies it for each row. Other keyword arguments are ordinary Django
`Field` configuration.

| Field | Cleaned value |
|---|---|
| `ListField`, `SequenceField` | `list` |
| `TupleField`, `FrozenSequenceField` | `tuple` |
| `SetField` | `set` |
| `FrozenSetField` | `frozenset` |

| Argument | Default | Meaning |
|---|---:|---|
| `min_length` | `0` | Minimum cleaned rows |
| `max_length` | `1000` | Maximum cleaned rows |
| `absolute_max` | `None` | Hard formset row limit; defaults to `max_length + 1000` |

`SetField` and `FrozenSetField` remove duplicates before length checks, so
`min_length` and `max_length` count distinct values, not submitted rows. Their
child values must be hashable. A set has no stable display order, so use a list
or tuple for `initial` when order matters.

### Inputs and nesting

Application code passes a mapping or list under the outer field name, and
`initial` uses that same nested Python shape. A browser request uses prefixes
instead: `point-x` for a mapping child, `values-0` for a sequence row, plus
Django's usual formset management fields for a sequence.

Submitted row keys win over a same-name scalar value. A key named `values`
cannot replace rows named `values-0`, `values-1`, and so on. Nested fields
compose their prefixes as expected. Child errors, uploads, compound widgets,
and media stay child behavior; outer-field validators only see the final
assembled mapping or collection.

### Rendering

Add `'nestingdolls'` to `INSTALLED_APPS` for the normal setup:

```python
INSTALLED_APPS = [
    # ...
    "nestingdolls",
]
```

That's enough for Django's default `django.forms.renderers.DjangoTemplates`
renderer to find the package templates. `NestingDollsConfig` also adds the
composite wrapper used by `as_div()`, `as_p()`, `as_table()`, and `as_ul()`.

Not using the app registry? Use Django's `TemplatesSetting` renderer instead.
Keep `'django.forms'` in `INSTALLED_APPS`, add the package template directory
to the DTL backend that renders your forms, then point `FORM_RENDERER` at it:

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
        # Keep existing OPTIONS and other configuration here.
    },
]

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"
```

This alternative covers template discovery only. The layout matching for
`as_p()`, `as_table()`, and `as_ul()` is installed by the app config, so with
these settings every composite renders its `div` layout regardless of the
form helper — silently, because the templates all resolve. To keep layout
matching without the app, call
`nestingdolls.patches.install_form_rendering_patch()` once at startup, for
example from your own `AppConfig.ready()`.

### Display errors

You do not need a package-specific template or a form rendering helper. A normal
manual form template renders both ordinary and composite fields:

```django
{{ form.media }}
<form method="post">
  {% csrf_token %}
  {{ form.non_field_errors }}
  {% for field in form.visible_fields %}
    {{ field.errors }}
    {{ field.label_tag }}
    {{ field }}
  {% endfor %}
  {% for field in form.hidden_fields %}{{ field }}{% endfor %}
  <button>Save</button>
</form>
```

For a composite field, `{{ field }}` renders its nested inputs and the errors
from its child fields. `{{ field.errors }}` renders errors attached to the outer
field, such as an outer validator error. It intentionally excludes child errors
to prevent duplicate messages.

Use a custom widget template only when you need to replace the markup inside a
composite field.

### Browser events

`form.media` includes `nestingdolls/sequence.js`, and every sequence root sends
these bubbling `CustomEvent`s:

| Event | Timing | `detail` | Cancelable |
|---|---|---|---|
| `nestingdolls:sequence-add` | Before cloning a row | `{index}` | Yes |
| `nestingdolls:sequence-remove` | Before hiding a row | `{index, row}` | Yes |
| `nestingdolls:sequence-change` | After an add or remove synchronizes controls and focus | `{action: 'add' or 'remove', index, row}` | No |
| `nestingdolls:sequence-ready` | Once, when enhancement starts | `null` | No |

A sequence nested in a freshly added row sends its own
`nestingdolls:sequence-ready` before the outer sequence sends
`nestingdolls:sequence-change`.

A disabled sequence widget is not enhanced at all: the server renders every
control disabled and ignores the widget's input, so the script leaves it
alone and sends no `nestingdolls:sequence-ready` event for it.

## Why two field types?

A mapping needs names, per-field errors, and form-wide cleaning. Django already
puts those jobs on a `Form`, so `DictField` uses one. A sequence repeats one
kind of value. Django puts the job of turning one input into one Python value
on a `Field`, so `ListField` repeats one across formset-shaped rows.

You can put every child field directly on the parent form. That's right when
the values really are siblings on that screen. Once they make up an order, an
address, or another value passed around as a unit, one outer field makes the
form result match the thing it represents.

The browser is a convenience, not a second form system. `sequence.js` can add
and remove rendered rows, but Django still decides which row names it reads and
whether submitted values pass. With JavaScript off, rendered rows still submit
fine; their count is simply fixed at page load.

## Nested row limits

The package adds one resource limit, and it only matters when a sequence sits
inside another sequence. Django already limits request keys, files, and bytes
while parsing a request, and a formset's `absolute_max` limits one level of
rows. Neither catches a few outer rows that each ask for lots of inner rows.

`SequenceWidget.submission_countdown` shares one row budget across an outer
sequence's whole tree:

```text
submission_max = max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)
```

Parent and child rows spend that budget before Django builds them. A submission
right at the limit works; one over it gets `too_many_forms` for the whole
submission. Sibling sequence fields get separate budgets because the form
author chose how many siblings exist. Sharing a countdown across separate
`ListField` definitions needs a custom `Form` subclass that calls
`submission_countdown.open()` around both fields.

Python lists and decoded JSON never go through Django's request parser. The
sequence field still applies its own row limits, but code accepting arbitrary
decoded structures still needs its own total-size and depth limit.

## Caveats and differences from Django

Here is the one deliberate difference: nested row limits fail fast. Django
reports an oversized formset through `formset.non_form_errors()` and still
renders every row up to `absolute_max`. Two keys plus `TOTAL_FORMS=5000` can
come back as 2,000 rows and roughly 300 KB of HTML. That is reasonable for one
formset; nested sequences can turn a few row counts into a much larger tree.

When the shared budget runs out, `nestingdolls` stops there. It puts
`too_many_forms` on the outer sequence field and redisplays a zero-row,
disabled widget: `TOTAL_FORMS=0`, disabled add and remove controls, and
`data-sequence-disabled` so `sequence.js` politely stays out of the way. Rows
after the overdraw are never built or echoed back. Building or returning them 
is the amplification this limit exists to avoid. It's not ideal, but it is
safer than accidentally DoSing yerself.

The ordinary one-field limits stay Django-like. A `max_length` violation or a
row count over that field's `absolute_max` redisplays the submitted rows,
values, and working controls. Those errors use Django's `too_many_forms` code
and Django's message. The shared-budget error reuses the code but has its own
message, because it counts rows spent across nested sequences rather than rows
in one formset.

A render, including server-provided `initial` rows, shows the prefix that 
fits because failing halfway through a page render helps nobody. Bound extraction
raises on an overdraw instead, so an over-budget submission fails outright and 
never looks like a saved value with rows quietly missing. Hopefully.
