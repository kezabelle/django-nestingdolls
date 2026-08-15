# Sequence widget

A sequence is the form version of `one of these, then another one of these`.
It represents an ordered collection of the same kind of value: perhaps a list
of simple values, perhaps a run of small structured records, but always a
value that can have another row beside it.

You could try to flatten that into a fixed set of inputs, but then the form has
to guess how many there will be before anyone has filled it in. A sequence
widget does the more honest thing. It gives the collection a run of rows that
can grow or shrink, then hands Django one ordered value to validate and clean.

Each row is still an ordinary child field, which is the nice bit. It can be
something simple or another composite value; the collection machinery does not
need to know. The parent form gets one field, and the person using it gets a
form that looks like the repeating thing they are actually editing.

If the value is really a small, fixed group of differently named parts, a
mapping is the boring and better fit.
