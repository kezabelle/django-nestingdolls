# django-nestingdolls

Django's ordinary form fields are good for flat data, but fall flat as soon 
as you might want any nesting, forcing instead toward separate formset 
configuration and orchestration. 

You know that thing where a form has collected an address, an order, or a
schedule, then hands you a flat dictionary and says, good luck with that?
It works, but the awkward part is that your application has to put the related 
keys back together.

`django-nestingdolls` does that bit for you. `DictField` renders and cleans a
child Django `Form`, then returns its cleaned values as one `dict`. `ListField`
renders formset-shaped rows for one child Django `Field`, then returns their
cleaned values as one `list`. The outer form gets the value it was describing
in the first place.

The child forms and fields still do the grown-up work: widgets, type
conversion, validation, file uploads, and errors. These fields just make sure
the bits that belong together don't wander off and become loose keys.

## Install

`django-nestingdolls` needs Python 3.12+ and Django 5.2+.

```sh
python -m pip install django-nestingdolls
```

or add it to your `pyproject` and `uv sync` or whatever, poetry? pdm? you do you.

### Setup

Then add the app to your Django settings module:

```python
INSTALLED_APPS = [
    # ...
    'nestingdolls',
]
```

That's the whole thing, hopefully. Django's normal DTL form renderer finds 
the package templates and the matching composite wrappers for the  `as_div()`, 
`as_p()`, `as_table()`, and `as_ul()` form helpers.

Installing the app patches `django.forms.BaseForm.render` (and with it
`__str__` and `__html__`) process-wide at startup: the wrapper records which
form helper is rendering so composite widgets can pick the matching layout
template, and it is a pass-through for forms without composite fields.
Without the app installed, Django's default renderer fails loudly with
`TemplateDoesNotExist` at the first composite render; a `TemplatesSetting`
renderer with the package templates on `DIRS` renders, but every composite
falls back to its `div` layout regardless of the form helper.

## A quick tutorial

Let's make a `CheckoutForm`. The browser will send ordinary Django input
names; the finished form will hand us one nested `order` dictionary with
integer product IDs and quantities. Nice and tidy.

### Describe the order

Start small: a line item has two named values. An order has a customer ID and
as many of those items as it needs. Put the forms together like this:

```python
from django import forms

import nestingdolls


class LineItemForm(forms.Form):
    product_id = forms.IntegerField(min_value=1)
    quantity = forms.IntegerField(min_value=1)


class OrderFieldsForm(forms.Form):
    customer_id = forms.IntegerField(min_value=1) # Obviously not really :)
    items = nestingdolls.ListField(
        nestingdolls.DictField(LineItemForm),
        min_length=1,
        max_length=20,
    )


class CheckoutForm(forms.Form):
    order = nestingdolls.DictField(OrderFieldsForm)
```

`LineItemForm` checks products and quantities. `OrderFieldsForm` checks the
customer and item list. `CheckoutForm` gets one `order` value back, not a
scavenger hunt through keys that merely look like they are related.

### Bind browser data

Browsers only send strings, and nested child fields get prefixed names.
Sequence rows bring Django's usual formset management values along too. Here is
what a complete two-item submission looks like:

```python
from django.http import QueryDict

# This is the data the user submitted for their order form from the 
# previous section above.
submission = QueryDict(
    'order-customer_id=17&'
    'order-items-TOTAL_FORMS=2&'
    'order-items-INITIAL_FORMS=0&'
    'order-items-MIN_NUM_FORMS=0&'
    'order-items-MAX_NUM_FORMS=1000&'
    'order-items-0-product_id=42&'
    'order-items-0-quantity=2&'
    'order-items-1-product_id=73&'
    'order-items-1-quantity=1'
)

form = CheckoutForm(submission)

assert form.is_valid()
assert form.cleaned_data == {
    'order': {
        'customer_id': 17,  # example only :D
        'items': [
            {'product_id': 42, 'quantity': 2},
            {'product_id': 73, 'quantity': 1},
        ],
    }
}
```

See the hand-off? `IntegerField` turns `order-items-0-quantity` from a request
string into an integer. `CheckoutForm` then returns one `order` value ready for
order code. No reconstruction helper, properly nested into conceptual namespaces,
less hunting around hopefully.

### Render it

Render it with Django's normal form helpers:

```django
<form method='post'>
  {% csrf_token %}
  {{ form.media }}
  {{ form.as_div }}
  <button type='submit'>Place order</button>
</form>
```

`form.media` loads `nestingdolls/sequence.js`, so people can add and remove
item rows without a reload. Kinda like in the Django admin inlines. Django still
names the controls, builds the rows, and does all the validation on submitted values.

## Show a saved order again

Give `initial` the nested Python value you saved, not prefixed browser names:

```python
saved_order = {
    'customer_id': 17,
    'items': [
        {'product_id': 42, 'quantity': 2},
        {'product_id': 73, 'quantity': 1},
    ],
}

form = CheckoutForm(initial={'order': saved_order})
```

`order-items-0-product_id` is an HTTP submission name. It only exists after
Django has rendered and named real controls. `initial` wants ordinary Python
data, from before that whole naming circus starts.

## More ways to use the fields

The checkout example follows the full browser path. The same fields should also
provide value at other boundaries: an API, an import job, or a background worker.

### Bind decoded application data

Got data from an API client or worker? Hand over the saved order directly.
Unlike `initial`, this is a submission, so Django validates it and puts it in
`cleaned_data` with everything else.

```python
form = CheckoutForm({'order': saved_order})

assert form.is_valid()
assert form.cleaned_data['order'] == saved_order
```

### Validate an imported JSON, YAML, or CSV list

Decode the import to normal Python data first. Then let the child field do its
thing: convert and validate every value.

```python
import csv
import json

import yaml


class ProductImportForm(forms.Form):
    product_ids = nestingdolls.ListField(forms.IntegerField(min_value=1))


json_form = ProductImportForm(json.loads('{"product_ids": [42, 73]}'))
yaml_form = ProductImportForm(
    yaml.safe_load('product_ids:\n  - 42\n  - 73')
)
# The list could come from a csv.DictReader row etc. too.
csv_form = ProductImportForm({'product_ids': next(csv.reader(['42,73']))})

for form in (json_form, yaml_form, csv_form):
    assert form.is_valid()
    assert form.cleaned_data['product_ids'] == [42, 73]
```

Don't forget you'd want to use `yaml.safe_load`, not `yaml.load`. The field checks 
the values it gets; the decoder still owns input-size and safety limits before that point.

### Return immutable and domain values

You don't have to settle for a mutable `list` or `dict` on the way out. Give
the field a domain type instead, and that is what comes back.

```python
from dataclasses import dataclass
from typing import NamedTuple


@dataclass
class Dimensions:
    width: int
    height: int


class Limits(NamedTuple):
    low: int
    high: int


class DimensionsForm(forms.Form):
    width = forms.IntegerField(min_value=1)
    height = forms.IntegerField(min_value=1)


class LimitsForm(forms.Form):
    low = forms.IntegerField()
    high = forms.IntegerField()


class PreferencesForm(forms.Form):
    pinned_product_ids = nestingdolls.FrozenSetField(forms.IntegerField())
    dimensions = nestingdolls.DataclassField(DimensionsForm, output=Dimensions)
    limits = nestingdolls.NamedTupleField(LimitsForm, output=Limits)


form = PreferencesForm(
    {
        'pinned_product_ids': [42, '73', 42],
        'dimensions': {'width': '10', 'height': 20},
        'limits': {'low': 1, 'high': '5'},
    }
)

assert form.is_valid()
assert form.cleaned_data['pinned_product_ids'] == frozenset({42, 73})
assert form.cleaned_data['dimensions'] == Dimensions(width=10, height=20)
assert form.cleaned_data['limits'] == Limits(low=1, high=5)
```

## Keep uploads with their row

When a repeated row has ordinary values and an upload, make that row a child
form. Then bind it the normal multipart way:

```python
class AttachmentForm(forms.Form):
    description = forms.CharField()
    document = forms.FileField()


class EvidenceForm(forms.Form):
    attachments = nestingdolls.ListField(
        nestingdolls.DictField(AttachmentForm),
        min_length=1,
    )


form = EvidenceForm(request.POST, request.FILES)
```

Render it with `enctype='multipart/form-data'`. `FileField` handles the
upload; the list field keeps every file beside its description. They arrived
together, so they can leave together.
