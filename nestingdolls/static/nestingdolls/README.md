# Browser bits

These are the small browser-facing assets used by the `nestingdolls` widgets.
Their job is not to understand the form's data or decide whether a submission
is valid; Django still owns all of that. They just make the page behave like
the form it represents, especially when a sequence needs another row or loses
one.

The nice part is that the browser code works from the markup and data Django
already rendered. It does not try to invent another naming scheme or a second
copy of the field rules. That keeps nested forms from becoming more surprising
than they need to be, which is already enough of a hobby.
