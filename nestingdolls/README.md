# nestingdolls

`DictField` puts a child Django `Form` back together as one mapping. `ListField`
repeats a child Django `Field` in rows and hands back one list. Use them when an
address, order, schedule, or other value ought to stay together after the form
has done its bit.

Child forms and fields still behave as you'd expect, we're just plugging the gap
where Django doesn't handle more than one level of depth.

## Start here

A sequence can repeat any field, including a `DictField`; a mapping can hold a
sequence of mappings. It all plays together nicely. Your application data stays
nested, and that same shape works for validation and `initial` rendering.

```python
from django import forms

import nestingdolls


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


## Reference

### Fields

#### Key:value shaped data

Pass these fields a Django `Form` class Django can construct without arguments.
The form's child fields name the value you get back.

If you want to handle `{"key": {"subkey": 1}}` you're looking for these.


| Field | Cleaned value | Notes |
|---|---|---|
| `DictField` | `dict` | The usual choice for a mapping. |
| `NamedTupleField` | `NamedTuple` | Takes `output=` or builds a matching named tuple. |
| `DataclassField` | `dataclass` | Takes `output=` or builds a matching dataclass. |

`MappingField`, `FormField`, and `Subform` are aliases for `DictField`.

##### What you pass in

| Argument | Meaning |
| --- | --- |
| `form_class` | The child Django `Form` with the named fields. |
| `output` | The class used to build the returned value. |

`NamedTupleField` and `DataclassField` take `output=`. Its field names need to
match the child form's declared names. An optional `DictField` returns `{}` when
empty; optional `NamedTupleField` and `DataclassField` return `None`.

#### Sequences and repeated values

A sequence field takes one Django `Field` and makes a copy for each row. Its
other keyword arguments are the ordinary Django `Field` options.

If you're after `{"key": [1.0, 2.3, 0.2]}` then you want one of these.


| Field | Cleaned value | Notes |
|---|---|---|
| `ListField` | `list` | The usual choice when order matters. |
| `TupleField` | `tuple` | Ordered, but immutable. |
| `SetField` | `set` | Drops duplicates. |
| `FrozenSetField` | `frozenset` | Drops duplicates and stays immutable. |

`SequenceField` is an alias for `ListField`.

##### What you pass in

| Argument | Default | Meaning |
|---|---:|---|
| `min_length` | `0` | Fewest cleaned rows allowed. |
| `max_length` | `1000` | Most cleaned rows allowed. |
| `absolute_max` | `None` | Hard ceiling for submitted rows; defaults to `max_length + 1000`. |

`SetField` and `FrozenSetField` remove duplicates before length checks, so
`min_length` and `max_length` count distinct values rather than submitted rows.
Child values must be hashable. That's simply the deal with sets. A set has no
stable display order, so use a list or tuple for `initial` when order matters.

### Rendering, errors, and uploads

For the usual setup, add `'nestingdolls'` to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "nestingdolls",
]
```

That is enough for Django's default `django.forms.renderers.DjangoTemplates`
renderer to find the package templates. `NestingDollsConfig` also makes the
composite wrapper match `as_div()`, `as_p()`, `as_table()`, and `as_ul()`.

A plain old manual form template works for ordinary and composite fields:

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

For a composite field, `{{ field }}` renders its nested inputs and child-field
errors. `{{ field.errors }}` is for errors on the outer field, such as an outer
validator error. Child errors stay out of it, so they do not show up twice.

#### Where a child failure is recorded

A child failure is recorded on the *outer* field as an `ItemValidationError`
with `code="item_invalid"`. Its `params` carry the locator:

| Key | Value |
| --- | --- |
| `item` | The child field name for a mapping, or the row index for a sequence. |
| `message` | The rendered child message. |
| `child_code` | The child field's own error code, such as `"required"`. |

Read them through `form.errors.as_data()`:

```python
form = PointForm({"point-x": ""})  # x is required, y is not submitted
form.is_valid()  # False
form.errors["point"]  # ['This field is required.']
form["point"].errors  # [] — the subform renders it inline
form.errors.as_data()["point"][0].params
# {'item': 'x', 'message': 'This field is required.', 'child_code': 'required'}
```

`form[name].errors` deliberately omits these, so the subform or the row renders
each child error exactly once next to the input that caused it. Django's
`ErrorDict.as_json()` keeps only `message` and `code`, so an API that needs the
locator must use `as_data()`.

Include `{{ form.media }}` on any page with a sequence. It loads the JavaScript
for adding and removing rows. Leave it out and the rows on the page still submit
and validate just fine; people just cannot change their number in the browser.

### Browser events

`form.media` includes `nestingdolls/sequence.js`. Each sequence root fires
these bubbling `CustomEvent`s:

| Event | Timing | `detail` | Cancelable |
|---|---|---|---|
| `nestingdolls:sequence-add` | Before cloning a row | `{index}` | Yes |
| `nestingdolls:sequence-remove` | Before hiding a row | `{index, row}` | Yes |
| `nestingdolls:sequence-change` | After an add or remove synchronizes controls and focus | `{action: 'add' or 'remove', index, row}` | No |
| `nestingdolls:sequence-ready` | Once, when enhancement starts | `null` | No |

If a host replaces sequence markup after the first page load, it can request
enhancement with:

```js
document.dispatchEvent(new Event("nestingdolls:sequence-enhance"))
```

Dispatch the event on `document` after insertion. The controller scans the
document and enhances every sequence widget that it has not enhanced before.

A sequence nested in a freshly added row sends its own
`nestingdolls:sequence-ready` before the outer sequence sends
`nestingdolls:sequence-change`.

A disabled sequence widget gets no browser enhancement. The server renders
every control disabled and ignores its input, so the script leaves it alone and
fires no `nestingdolls:sequence-ready` event.

### Row limits and failure behavior

A sequence on its own follows Django's usual limits. `max_length` and
`absolute_max` cover that field's rows. If one is too large, Django gives you the
submitted rows, values, and working controls back with `too_many_forms`.

A sequence inside another sequence has one extra guardrail. Django limits request
keys, files, and bytes while parsing a request, and `absolute_max` limits one
level of rows. A few outer rows can still each ask for a great many inner rows.

`SequenceWidget.submission_countdown` gives the whole nested tree one row budget:

```text
submission_max = max(absolute_max, DATA_UPLOAD_MAX_NUMBER_FIELDS)
```

Rows at every level spend that budget before Django builds them. Right on the
limit works; one row over puts `too_many_forms` on the outer sequence field.
Separate `ListField` definitions get separate budgets. If two of them should
share one, a custom `Form` can call `submission_countdown.open()` around both.

Once the shared budget is spent, the field comes back as a zero-row disabled
widget: `TOTAL_FORMS=0`, disabled add and remove controls, and
`data-sequence-disabled` so `sequence.js` politely stays out of the way. The
remaining rows are not built or echoed back. Bound extraction raises, so an
over-budget submission never looks like a saved value with some rows missing.
Hopefully.

Python lists and decoded JSON bypass Django's request parser. The sequence field
still applies its own row limits, but code accepting arbitrary decoded structures
still needs a total-size and depth limit of its own.

## How-to

### Validate decoded JSON, YAML, or CSV

Decode external data first, then put the resulting list under the field name.
The sequence field cleans and checks those rows just as it does browser input.

```python
import csv
import json

import yaml


class ReorderForm(forms.Form):
    quantities = nestingdolls.ListField(
        forms.IntegerField(min_value=1),
        min_length=1,
        max_length=5,
    )


json_form = ReorderForm(json.loads('{"quantities": [2, 3]}'))
yaml_form = ReorderForm(yaml.safe_load("quantities:\n  - 2\n  - 3"))
csv_form = ReorderForm({"quantities": next(csv.reader(["2,3"]))})

for form in (json_form, yaml_form, csv_form):
    assert form.is_valid()
    assert form.cleaned_data["quantities"] == [2, 3]
```

Use `yaml.safe_load`, not `yaml.load`. The decoder owns whole-input limits; the
field only sees the decoded values.

### Keep an upload with its row data

When each repeated row has ordinary values and an upload, wrap its child form
in `DictField`.

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

Render it inside `<form method="post" enctype="multipart/form-data">`.
The list keeps each upload beside its label. They arrived together, so they can
leave together.

### Return a domain value

Use `output=` when a mapping should come back as one of your domain objects
rather than a plain `dict`. Its field names must match the child form's.

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

For unique repeated values, use `SetField` or `FrozenSetField`; their exact
length semantics are in [Fields](#fields).

### Use package templates without app registration

If your setup does not use the app registry, use Django's `TemplatesSetting`
renderer. Keep `'django.forms'` in `INSTALLED_APPS`, add the package template
directory to the DTL backend that renders forms, then set `FORM_RENDERER`:

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

This only finds the templates. The app config is what makes `as_p()`,
`as_table()`, and `as_ul()` pick matching layouts. Without it, composite fields
all use the `div` layout because every template resolves. If you still want the
matching layouts without the app, call
`nestingdolls.patches.install_form_rendering_patch()` once at startup - your own
`AppConfig.ready()` is a good place.

## Design notes

### Why a `Form` for mappings and a `Field` for sequences

A mapping needs names, per-field errors, and form-wide cleaning. Django already
gives a `Form` those jobs, so `DictField` uses one. A sequence repeats one value.
Django gives a `Field` the job of turning one input into one Python value, so
`ListField` repeats one across formset-shaped rows.

You can put every child field directly on the parent form. That is right when
they really are siblings on that screen. Once they make up an order, an address,
or another value passed around together, one outer field makes the result match
the thing it represents.

### The browser is not a second form system

`sequence.js` can add and remove rendered rows, but Django still decides which
row names it reads and whether submitted values pass. With JavaScript off, the
rows already on the page still submit fine; their count is simply fixed.

### Why an oversized nested submission stops early

Django reports an oversized formset through `formset.non_form_errors()` and
still renders every row up to `absolute_max`. Two keys plus `TOTAL_FORMS=5000`
can come back as 2,000 rows and roughly 300 KB of HTML. Fine for one formset;
less fine when nested sequences turn a few row counts into a much larger tree.

The shared budget stops that before it grows teeth. Not perfect, but better than
accidentally DoSing yourself.
