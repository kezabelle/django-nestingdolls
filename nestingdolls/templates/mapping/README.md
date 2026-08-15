# Mapping widget

A mapping is a small group of named values that wants to travel around as one
thing. Maybe it is contact details, maybe a point, maybe it is just a bit of
form-specific data that would be hard to explain as a handful of unrelated
fields on the parent form.

You can obviously put all of those inputs directly on that parent form, but
once they really describe one value, it is nicer when they stay together. That
is the bit the mapping widget is for. It gives the child inputs a little form
of their own, while the outer form still gets one field to validate, clean,
and hand back to the application.

The useful part is that neither side has to pretend. A person filling in the
form sees the ordinary named inputs that fit the value. The Python code sees
one structured value, not a collection of sibling fields that happen to be
related by convention.

A mapping has a fixed shape. If the thing can grow another row whenever
someone clicks add, it is not really a mapping any more; that is what the
sequence widget is for.
