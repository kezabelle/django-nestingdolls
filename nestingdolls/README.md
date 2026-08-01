# nestingdolls

## Sequence Fields

`ListField` is a Django form field for a variable-length list of child fields.
It lets one form field contain zero or more rows of the same child field type.
It works with normal Django form validation and widget rendering, and can
be used in place of separate formsets in many cases.

Use `ListField` for most cases. The package also exports:

- `TupleField`: returns a tuple
- `SetField`: returns a deduplicated set
- `FrozenSetField`: returns a deduplicated frozenset

### When To Use 

Use `ListField` when a form needs repeated values.

Common cases:

- a list of email addresses
- a list of integer IDs
- a list of JSON fragments
- a list of uploaded files
- a list of fixed-size pairs with `TupleField`
- an unordered set of values with `SetField`
- nested lists or tuples inside a larger sequence

### Basic Examples

#### List of Integers

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
```

#### List of Pairs

```python
from django import forms
import nestingdolls


class ExampleForm(forms.Form):
    pairs = nestingdolls.ListField(
        nestingdolls.TupleField(
            forms.IntegerField(),
            min_length=2,
            max_length=2,
        ),
        required=False,
    )
```

#### Deduplicated Set of Email addresses

```python
from django import forms
import nestingdolls


class ExampleForm(forms.Form):
    tags = nestingdolls.SetField(
        forms.EmailField(),
        required=False,
    )
```

### Input Forms

The field accepts these row styles for both `data` and `initial`:

- direct list input such as `{"values": ["1", "2"]}`
- dash style such as `values-0`, `values-1`
- dot style such as `values.0`, `values.1`
- bracket style such as `values[0]`, `values[1]`

### JavaScript

JavaScript is optional. 
It only enhances add and remove controls through progressive enhancement.
The widget template stores these controls in inert `<template>` nodes.

### Limits and Rules

- One field has one child field type.
- `min_length` and `max_length` apply to row count.
- `SetField` checks cardinality **after** deduplication.

### Use-Cases By Type

- Use `ListField` for ordered repeated values.
- Use `TupleField` when each row has a fixed number of items.
- Use `SetField` when duplicate submitted rows should collapse to one member.
- Use `FrozenSetField` when the cleaned result must be immutable.
