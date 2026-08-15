"""Benchmark pathological nested-sequence submissions.

Run this with ``make pathological``. It is a measurement tool, not a test: it
records what a hostile request actually costs the server and fails only when a
case breaks a bound stated in the case itself.

Every payload is posted with Django's test client, so Django's own parser counts
the keys before a form sees them. ``DATA_UPLOAD_MAX_NUMBER_FIELDS`` stays at its
default 1000, so no case here is larger than a request a server would accept.
The point of each case is the gap between ``claimed`` and ``built``: a forged
set of nested ``TOTAL_FORMS`` keys asks for up to a million rows, and the shared
row budget must answer with a constant amount of work.

Each case declares ``max_rows``, which is the security bound. It is a multiple
of ``SequenceWidget.submission_countdown``'s budget: one budget for each entry
point the request reaches, times the number of sequence fields the form's author
declared. A request cannot change either multiplier. ``max_seconds`` is a
looser operational ceiling, and the run reports timing separately because a
machine under load can miss it without anything being wrong.

``BENCH_ABORT`` sets the per-case abort timer in seconds, default 30. A case
that trips it is reported as aborted instead of being left to run, which is what
makes this script usable against a build that has no working row budget at all.

The numbers in this docstring are stale by default
--------------------------------------------------
Everything recorded below is one run on one machine, kept so the next reader
knows roughly what to expect and can tell a regression from a fast laptop. It is
not a specification and it is not an assertion.

Re-run the script and believe its output. Where the output disagrees with this
text, the text is what is wrong. Do not copy a number from here into a test, and
do not conclude the row budget is intact because this section says it was: the
claims that must hold live in the ``Case`` entries below and in
``HostileCleanCostTestCase`` in ``test_hostile.py``.

Provenance of the recorded run: Apple M1 Pro, macOS 24.3.0, CPython 3.12.12,
Django 6.1, 2026-08-15. The "before" figures came from commit acb16e4, the last
commit before the row budget covered extraction. Rebuild that comparison rather
than trusting the figures:

    git worktree add --detach /tmp/before <commit>
    cp pathological.py pyproject.toml uv.lock /tmp/before/
    cd /tmp/before && BENCH_ABORT=6 uv run --group dev python pathological.py

The timing figures have their own "before", the commit preceding the one that
removed the repeated work described under "Two repeats that change detection
and the mapping render paid". Rebuild it the same way. Verdicts are identical
across that change, and so is every built figure except the mapping render's,
which fell from two budgets of rows to one.

What the recorded run showed
----------------------------
Thirteen cases, all inside their row bound. Before the fix, four were. The other
nine reach rows through change detection, an ``empty_permitted`` form, a render,
a hidden initial, or a mapping, and every one of them was still building rows
when the abort timer killed it, at 6s and again at 20s.

    a claim 498x wider  ->  rows built x1.0,  wall time x2.0

Rows built stayed flat at one budget per entry point. A 998-key claim for 996,498
rows was answered with 2,000 rows in 0.054s, and the same claim spread over
three or five levels cost no more, because levels share one budget instead of
each getting a fresh one. Peak allocation stayed between 4.9 and 39.3 MB.

Verdicts differ by shape and all three are correct. A plain nested sequence
reports ``too_many_forms``. A sequence inside a mapping reports ``item_invalid``,
because the mapping's child form owns that error. An ``empty_permitted`` form
whose rows are all blank cleans as valid and empty, which is Django's documented
early return: nothing was submitted, so there is nothing to clean. Rows stay
bounded in all three.

Two costs remain. Both are ceilings rather than amplification, because a request
cannot raise either bound:

- 0.054s for the widest single-field case, against 0.027s for a 4-key claim
  asking for the same number of rows. Rows built are identical, so what is left
  of the difference is per-key work. See the next section.
- 0.317s and 16,000 rows for a form with eight sibling nested sequence
  fields, which is budget x fields x entry points. The field count is fixed by
  the form's author, the same position Django takes for ``absolute_max`` per
  formset. Quote this number, not the single-field total, as the per-request ceiling.

Two ways this script had already misled its own author, both fixed here, both
worth re-checking if the numbers ever look surprising. Measuring peak allocation
in the same pass as wall time inflated every time above by about five times,
because ``tracemalloc`` costs more than this workload does. And measuring the
legitimate baseline after the hostile cases inflated it about seven times,
because by then the heap is large and collections cost more. Timing is now a
clean pass, and the baseline runs first.

Profiling the remainder
-----------------------
Profile one case, not the whole run, or the totals blend thirteen shapes. The
script does this itself, so there is no snippet here to fall out of date:

    make pathological ARGS=--profile
    uv run --group dev python pathological.py --profile
    uv run --group dev python pathological.py --profile "8 sibling"

With no argument it profiles the pair named in ``CONTRAST``: two cases that build
the same number of rows, one from 4 keys and one from 998. A label substring
profiles a different case instead. ``PROFILE_HINT`` repeats how to read the
output at the point of use.

Sort by ``tottime``, not ``cumtime``. The question is which function burns the
time itself, and the request path is deep enough that ``cumtime`` puts the test
client and the view on top and tells you nothing. The contrast pair is the whole
method: both build the same 2,000 rows, so whatever separates their profiles is
per-key cost, and per-key cost is all that is left to win.

No package function appears in the top ten of either final contrast profile.
The 0.074s concentrated profile, 0.131s spread profile, and 0.705s sibling
profile are instead dominated by Django and CPython copying. In the sibling
profile, ``copy._deepcopy_dict`` takes 0.126s of self time, ``deepcopy`` takes
0.056s, and Django ``Field.__init__`` takes 0.032s. This is Django's per-row
form construction: ``copy.deepcopy`` of ``base_fields`` in
``BaseForm.__init__`` and the ``Field.__deepcopy__`` chain under it.

That is per-row cost, not per-key cost, so the contrast pair no longer
separates it: both cases build 2,000 rows and both pay it. It is bounded by the
row budget, which is what bounds rows built. Do not try to flatten it by
sharing fields across rows. ``get_context`` writes to a management field's
widget attributes, ``_row_context`` assigns each row's ``render_state``, and
the field writes its configuration to the widget; sharing widgets between
rows is the cross-request contamination ``MappingWidget.__deepcopy__`` exists
to prevent.

What was reduced, and what is left
----------------------------------
The per-key work above is gone. Both functions now do one pass over the keys
where they did one pass per row. The final clean pass reports x2.0 wall-time
amplification without moving a single ``built`` figure or verdict.

``RowFormSet.get_form_kwargs`` answers per row with one set lookup against
``rows_with_submitted_values``, which indexes the row prefixes
carrying a non-blank value in one pass over the keys. The lifetime is the
formset, which is constructed per extraction with its own ``data`` and
``files``, so no new machinery was needed and the budget did not change. The
two homes ruled out before are still wrong, and still worth recording as
wrong: not the widget, which is built once and reused for every request, so an
index cached there serves one user another user's POST; and not a module-level
cache keyed by ``id(source)``, because an identity is reused once the first
mapping is collected and entries would collide silently.

``has_row_keys``'s repeats came from ``SequenceBoundField.has_whole_value`` and
``is_bound_formset``, one bound field per row. Both are ``cached_property``,
which is why the caching already there did not help. Both now answer in O(1)
for a submission carrying management keys and no exact-name key, by testing the
cheap predicate first: ``is_bound_formset`` tries the four management keys
before scanning for a row key, and ``has_whole_value`` tries the field's own
exact key before asking whether row keys outrank it. Neither reordering changes
an answer, because both predicates are side-effect free.

A submission that sends a value under each row's own exact name still pays the
scan, because then the exact-key test passes. That path is bounded by the row
budget and by ``DATA_UPLOAD_MAX_NUMBER_FIELDS``, and it buys fewer rows in
exchange: a 998-key version of it was measured at 0.09s against 0.31s before,
building the same 2,000 rows. That shape is what pays for the shape of
``has_row_keys``: a plain loop rather than a generator expression, and slice
comparisons rather than ``startswith`` and an index. Measured together on it,
those two are worth about 6%. Both keep the prefix length in a local, which is
the whole reason a slice is cheaper than a call here.

``submission_countdown`` was not touched and did not need to be. The judgment
call this section used to set up -- whether to widen the countdown scope to hold
an index -- did not have to be made, so nothing was traded away. It still holds
one integer, and that is still the only thing between a forged ``TOTAL_FORMS``
and unbounded work. Keep it that way.

Empty child formsets after overflow
-----------------------------------
``SequenceBoundField.data`` now reads the active shared count after it enters
``submission_countdown``. A strictly negative count means an earlier child has
already overdrawn the budget. Later children cannot add a row or change the one
error the owning outer field reports, so extraction returns their empty values
without constructing their zero-row formsets. It does not alter the count, row
budget, or error owner. Zero is not overflow: the next child still constructs
its formset and reads its claim, which can make the count negative.
``HostileCleanCostTestCase.test_claim_after_exact_budget_still_records_overflow``
holds that boundary.

The old eight-sibling request built 496 formsets: eight outer formsets and 61
child formsets for each sibling. The strict-negative shortcut builds 16: each
sibling's outer formset and its first child formset. It still builds 16,000 row
forms and returns the same response body.

Whole-run timings had more process-to-process variation than this package-side
change: five pre-change runs measured 0.278, 0.270, 0.276, 0.277, and 0.274s
(median 0.276s), while two later strict-negative batches had 0.334s and 0.321s
medians. Those sequential batches do not establish a source comparison. The
comparison therefore ran the actual ``pathological.measure`` sibling case in
ten alternating pairs of independent Python processes, with a source-equivalent
old ``data`` implementation in one process and the strict-negative source in
the other. Every request returned the same body, ``too_many_forms``, and 16,000
rows. The old median was 294.778ms; the strict-negative median was 291.440ms:
3.338ms, or 1.132%, lower. Peak allocation also fell from 39.8 to 39.3 MB.

The behavior to watch is unchanged, and ``rows_with_submitted_values``'s own
docstring is still where it is written down: a rendered row always sends its
delete key and always sends blank values, so only a non-blank value counts as
real content. ``empty_permitted`` correctness rests on that distinction. The
index preserves it by excluding each row's own delete key and nothing else, so
a nested row's delete key, ``values-3-0-DELETE``, still counts as content for
row ``values-3`` exactly as the scan did. Verify with ``make test`` and this
script, then re-record the numbers above.

Two repeats that change detection and the mapping render paid
-------------------------------------------------------------
Both fixes live in ``boundfield.py``. Both remove work whose result nothing
read, partly for performance and efficiency, and neither moves a verdict. The
only built figure that moves is the mapping render's.

``SequenceBoundField._has_changed`` read ``formset.deleted_forms`` on every
bound sequence, and Django's ``deleted_forms`` answers by running
``is_valid()`` first: a full validation pass over every row form, during
change detection. Only the deletion of an initial row can make that read
report a change, so a field with no initial rows now returns before it. A
hostile submission carries no initial rows, so that pass was waste on every
entry order this script measures: cleaning either raises ``too_many_forms``
before it reads row errors, or an ``empty_permitted`` form skips its fields
entirely. A field with initial rows still pays it, and must: deleting an
initial row is a change that nothing else reports.

The mapping render built a row formset it never read. ``BoundField.as_widget``
always computes ``value()``, and the base behavior extracts the whole mapping
to compute it -- for a nested sequence, a fresh row formset holding a full
budget of rows -- while ``MappingWidget.get_context`` renders from
``render_state.subform`` and ignores the computed value.
``MappingBoundField.value()`` now returns the initial value when the subform
owns the bound data, the same decision ``SequenceBoundField.value()`` already
made for rows. A scalar or missing submission binds no subform and keeps the
base behavior, because the user must see that submission again;
``test_dictfield`` holds that line. ``inside a mapping, changed + render``
therefore builds one budget of rows, not two.

Verify both with ``make test`` and this script, then re-record the numbers
above.

One row formset class per level, not two per row
------------------------------------------------
Every nested row form deep-copies its sequence field, and Django's
``Field.__deepcopy__`` copies the widget with ``copy.copy``, so each copy
already carried the formset class its source widget had cached -- and then
the old reconfiguration step discarded it. Every outer row therefore built
two fresh classes, a ``Row`` form class and its formset class: about 1,000
classes for the 998-key spread case and about 4,000 for the eight-sibling
case, per request. ``cProfile`` undersold this cost, because class creation
runs mostly in C; the wall clock and ``tracemalloc`` did not.

``SequenceWidget.__deepcopy__`` now copies the child field and keeps the
carried class, and ``formset_class`` builds the child sequence's class
before any row form copies the child field. The class only names the deepcopy
source of each row's field, and nothing writes to that field, so the shared
class moves no mutable state between rows. The sharing also cannot cross a
request: a cache is warm only on per-request field copies, never on a form
class's own field. Classes per request fell from two per row to two per
level, 998 -> 2 on the spread case. That was worth about 15 percent of the
spread case's wall time (0.068s -> 0.057s minimum over nine posts) and 2.6 MB
of every wide case's peak allocation (11.6 -> 9.0 MB), and the wall-time
amplification fell from x3.0 to x2.6. Verdicts and every ``built`` figure are
unchanged, which ``make test`` and this script confirmed.

No ManagementForm for a formset past the budget
-----------------------------------------------
Django's ``total_form_count`` builds and cleans the ``ManagementForm`` to read
``TOTAL_FORMS``. ``RowFormSet.total_form_count`` called it before it asked the
shared budget for rows, so a wide hostile submission paid for one full Django
form per outer row -- 499 management forms on the 998-key spread case, about a
quarter of its profiled time, four deep-copied fields and four bound fields
each -- and then clipped every one of those claims to zero rows.

``RowFormSet.total_form_count`` now reads the sign of the countdown's shared
remaining value first and skips the ``ManagementForm`` when the budget is
already overdrawn. The skip cannot change a result. Overflow is the sign of
the remaining value, which is already negative, and the magnitude is never
read, so the skipped ``take()`` subtraction changes no observable state. The
first overdrawing claim still goes through ``take()``, so exact use still
succeeds and a ``TOTAL_FORMS`` of zero on an exactly-spent budget stays
legal. ``management_form`` is a ``cached_property``, so a later reader -- a
render's ``get_context``, a formset ``full_clean`` -- still builds it on
demand.

On the recorded management-form comparison, management forms in the spread
profile fell from 499 to 2: the outer formset and the first inner formset,
which overdraws. That comparison reduced the spread case from 0.081s to
0.058s and from 9.0 to 6.2 MB. The current clean full run reports 0.054s and
5.7 MB for the spread case, 0.317s and 39.3 MB for the eight-sibling case, and
x2.0 wall-time amplification. The concentrated case does not move: its single
nested formset is the one that overdraws, so there is nothing to skip. Every
``built`` figure and verdict is unchanged, and the responses and rendered HTML
were compared byte for byte. Verify with ``make test`` and this script, then
re-record the numbers above.

Slice comparisons, not startswith
---------------------------------
A loop that tests a prefix against every submitted key is the shape this whole
file is about, so its per-key cost is worth stating concretely. Hold the prefix
length in a local and compare a slice. Do not call ``startswith``:

    start = len(prefix)
    if key[:start] == prefix and "0" <= key[start : start + 1] <= "9":

``str.startswith`` accepts ``(prefix, start, end)``, so it is ``METH_VARARGS``
and every call builds an argument tuple. ``key[:start]`` compiles to a
``BINARY_SLICE`` opcode: no method lookup, no tuple. The throwaway string comes
off pymalloc's free list and is released immediately, so the allocation the
slice appears to add does not show up as churn. Measured over the 998-key
payload of ``2 levels, 498x2000 spread``, slicing wins in every profile:

    prefix matches almost no key (the hot call)   58.5us -> 48.3us   x1.21
    prefix matches every key                       0.43us ->  0.39us  x1.11
    the full rows_with_submitted_values pass       192us  -> 174us    x1.10

Neither slice needs a length guard. A key shorter than the prefix yields a
shorter string, which cannot equal it. A key that ends at the prefix yields
``""``, which sorts below ``"0"``.

This applies where the length is already in hand and the loop reads every key:
``SequenceWidget.has_row_keys`` and ``RowFormSet.rows_with_submitted_values``.
``MappingWidget._accepts_key`` still calls ``removeprefix``; it measured at or
below 0.002s here, so it is not worth the same treatment on this evidence.

One rearrangement that looks like a further win is not one. Testing the cheap
digit character before the prefix, to skip ``startswith`` calls, measured x0.61:
it avoids only 202 of 998 calls and pays a slice plus two comparisons on all
998. Do not do it.

Finally, a trap specific to this script. ``cProfile`` counts ``startswith`` as a
call and charges its own per-call overhead to it, while a slice is an opcode and
is invisible. Replacing one with the other therefore improves a profile by more
than it improves the request, and removes the ``ncalls`` line that made the
remaining prefix tests easy to find. Believe wall time, not the disappearance of
a ``startswith`` row.

Where the peak allocation lives
-------------------------------
The row budget bounds rows, and rows bound memory. One tracemalloc pass over
the eight-sibling case attributes its 41.4 MB peak like this: about 75 percent
is Django's per-row form construction -- ``BaseForm.__init__`` deep-copying
``base_fields``, ``Field.__deepcopy__``, ``Widget.__deepcopy__``, and formset
plumbing -- and about 19 percent is stdlib ``copy``/``copyreg`` machinery that
those same Django ``__deepcopy__`` hooks drive through the generic
``__reduce_ex__`` path. About 5 percent lands on this package's lines, and
most of that 5 percent is a trap, not a cost.

tracemalloc charges an allocation to the innermost Python line that was
executing, so Django's own call-setup allocation for ``_construct_form``
appeared as 1.9 MB, about 117 bytes per row, on this package's old
``RowFormSet._construct_form`` override line. Removing the override moved that
block onto Django's ``formsets.py`` line and left the peak identical within
10 KB on every case (6.14 MB spread, 41.36 MB sibling). There is no
package-side peak-memory win. The one lever on peak allocation is rows built,
and the shared row budget already holds it. Do not spend another pass hunting
package allocations below Django's per-row deepcopy.

Removing the override still bought time, because the override chain cost one
Python frame, one ``typing.cast`` frame, one ``super`` object, and one kwargs
dict per row. ``RowFormSet.get_form_kwargs`` now denies ``empty_permitted`` to
a row whose keys carry a non-blank value, on a call Django already makes once
per row, and ``row_carries_submitted_value`` went with its one caller. Ten
alternating pairs of independent processes, nine posts each: spread medians
41.08 -> 41.07 ms with the median of per-process minimums 40.08 -> 39.54 ms,
and sibling medians 379.0 -> 368.2 ms. Peaks were equal,
every response body was sha256-identical, and rows built stayed at 2,000 and
16,000. The win is small and real; the reason to record it is the memory
conclusion above.

One read in the same family was measured twice, and the two verdicts
differ. Inlining the read into the loop body, past the shared ``_getlist``
helper, measured x1.21 for the full ``rows_with_submitted_values`` pass and
stays rejected: the pass runs once per bound formset, not per row, about
0.14 ms of the 40 ms spread request, and the inlined read is safe only on
facts local to that one loop. Optimizing the helper itself was worth it,
because every caller gets it. The ``cast`` it carried was already trust,
not a check -- the values can be anything, and the annotation asserts they
arrive as a list -- so the helper stops paying to look defensive.
``MultiValueDict.getlist`` returns a fresh list (``force_list=True``) and
``[]`` for a missing key, so the old ``list()`` wrapper was a second copy,
the old ``in`` pre-check re-tested a key ``getlist`` already handles, and
the ``cast`` was one Python frame per call. ``_getlist`` now asks for
``getlist`` first and returns its result directly: 316 -> 237 ns per
present-key call on the spread payload's QueryDict, and the full pass fell
406 -> 355 us, x1.14, most of the inline gap, with no special case. Two
shapes measured worse and stay rejected. Dropping the miss guard entirely
makes a missing key cost 304 ns against 82 through ``getlist``'s own
``KeyError`` handling, which is fine where it landed -- only the
whole-value branch of ``value_from_datadict`` can miss, at most twice per
extraction, and every hot caller reads a present key -- but is the reason
the plain-``dict`` path keeps its ``in`` test: ``try``/``except`` there
costs 192 ns against 93 on a miss. And ``try``/``except AttributeError``
instead of ``getattr`` wins 9 ns on ``MultiValueDict`` sources and loses
228 ns on every plain-``dict`` call, and Python data is a supported
source.
Verify with ``make test`` and this script, then re-record the numbers above.
"""

import contextlib
import cProfile
import dataclasses
import os
import pstats
import signal
import sys
import time
import tracemalloc

import django
from django import forms
from django.conf import settings
from django.forms.formsets import INITIAL_FORM_COUNT, TOTAL_FORM_COUNT
from django.http import JsonResponse
from django.test import Client
from django.test.utils import setup_test_environment
from django.urls import path
from django.views import View

import nestingdolls
from nestingdolls.widgets import SequenceWidget

if not settings.configured:
    settings.configure(
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        INSTALLED_APPS=("nestingdolls",),
        ROOT_URLCONF=__name__,
        USE_I18N=False,
        TIME_ZONE="UTC",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()

# The budget a single entry point may spend, for a field left at its defaults.
BUDGET = 2000
ABORT_SECONDS = float(os.environ.get("BENCH_ABORT", "30"))

# Row forms built during the case being measured; see counting_rows().
ROWS_BUILT = [0]

# The pair --profile compares by default. Both build the same number of rows,
# one from 4 keys and one from 998, so a function whose tottime differs between
# them is per-key cost rather than row-building cost.
CONTRAST = ("2 levels, 1x2000 concentrated", "2 levels, 498x2000 spread")

PROFILE_HINT = """
Sort key is tottime: the time a function burns itself. Do not sort by cumtime
here, because the request path is deep enough that the test client and the view
sit on top of everything and tell you nothing.

The two cases above build the same number of rows from 4 keys and from 998. Any
function whose tottime differs between them is per-key cost, and per-key cost is
what is left to win. Pass a label substring to profile a different case.
""".strip()


def nested_list_field(depth):
    """Return a ListField nested ``depth`` levels deep over a CharField."""
    field = forms.CharField(required=False)
    for _ in range(depth):
        field = nestingdolls.ListField(field, required=False)
    return field


class TwoLevelForm(forms.Form):
    values = nested_list_field(2)


class ThreeLevelForm(forms.Form):
    values = nested_list_field(3)


class FiveLevelForm(forms.Form):
    values = nested_list_field(5)


class HiddenInitialForm(forms.Form):
    values = nested_list_field(2)
    values.show_hidden_initial = True


class MappingWrappedForm(forms.Form):
    class InnerForm(forms.Form):
        values = nested_list_field(2)

    value = nestingdolls.DictField(InnerForm, required=False)


class EightSiblingsForm(forms.Form):
    locals().update({name: nested_list_field(2) for name in "abcdefgh"})


class ProbeView(View):
    """Bind one form the way a view would, in one of the orders Django allows."""

    form_class = None
    mode = "clean"

    def post(self, request):
        kwargs = {}
        if self.mode == "empty_permitted":
            # Django calls has_changed() itself for such a form, before it
            # cleans any field, so this needs no unusual application code.
            kwargs = {"empty_permitted": True, "use_required_attribute": False}
        form = self.form_class(request.POST, request.FILES, **kwargs)
        if self.mode in ("changed_first", "changed_then_render"):
            form.has_changed()
        valid = form.is_valid()
        body = {
            "valid": valid,
            "errors": {
                name: sorted({error.code for error in errors})
                for name, errors in form.errors.as_data().items()
            },
        }
        if self.mode == "changed_then_render":
            # A rejected submission goes back to the browser as HTML, so the
            # render is part of what the request costs.
            body["rendered_bytes"] = len(form.as_p())
        return JsonResponse(body)


def route(name, form_class, mode):
    return path(name, ProbeView.as_view(form_class=form_class, mode=mode))


urlpatterns = [
    route("two-clean/", TwoLevelForm, "clean"),
    route("two-changed/", TwoLevelForm, "changed_first"),
    route("two-empty-permitted/", TwoLevelForm, "empty_permitted"),
    route("two-render/", TwoLevelForm, "changed_then_render"),
    route("three-clean/", ThreeLevelForm, "clean"),
    route("three-changed/", ThreeLevelForm, "changed_first"),
    route("five-changed/", FiveLevelForm, "changed_first"),
    route("hidden-changed/", HiddenInitialForm, "changed_first"),
    route("mapping-changed/", MappingWrappedForm, "changed_first"),
    route("mapping-render/", MappingWrappedForm, "changed_then_render"),
    route("siblings-changed/", EightSiblingsForm, "changed_first"),
]


@dataclasses.dataclass(frozen=True)
class Case:
    """One hostile request, with the bounds its result must respect."""

    label: str
    url: str
    totals: tuple[int, ...]
    max_rows: int
    max_seconds: float
    prefixes: tuple[str, ...] = ("values",)
    # The error code the user must see. None means the case is about bounded
    # work rather than a particular verdict.
    expect: str | None = "too_many_forms"

    @property
    def payload(self):
        payload = {}
        for prefix in self.prefixes:
            payload.update(amplify(prefix, self.totals))
        return payload

    @property
    def claimed(self):
        return len(self.prefixes) * rows_claimed(self.totals)


def amplify(prefix, totals):
    """Forge management keys claiming ``totals[level]`` rows at each level.

    No row value is sent. Empty rows are the cheapest way to ask for work, and
    Django's key limit counts these management keys like any others.
    """
    payload = {}

    def emit(node, level):
        total = totals[level]
        payload[f"{node}-{TOTAL_FORM_COUNT}"] = str(total)
        payload[f"{node}-{INITIAL_FORM_COUNT}"] = "0"
        if level + 1 < len(totals):
            for index in range(total):
                emit(f"{node}-{index}", level + 1)

    emit(prefix, 0)
    return payload


def rows_claimed(totals):
    """Count the row forms such a payload asks the server to build."""
    total = 0
    reached = 1
    for level in totals:
        reached *= level
        total += reached
    return total


CASES = (
    # The cheapest claim, and the widest claim a request can carry. Both ask
    # for about the same number of rows, so both must cost about the same.
    Case("2 levels, 1x2000 concentrated", "/two-clean/", (1, BUDGET), 2 * BUDGET, 5.0),
    Case("2 levels, 498x2000 spread", "/two-clean/", (498, BUDGET), 2 * BUDGET, 5.0),
    # The entry points that reach rows before cleaning does.
    Case(
        "2 levels, 498x2000, has_changed first",
        "/two-changed/",
        (498, BUDGET),
        2 * BUDGET,
        5.0,
    ),
    Case(
        "2 levels, 498x2000, empty_permitted",
        "/two-empty-permitted/",
        (498, BUDGET),
        2 * BUDGET,
        5.0,
        expect=None,
    ),
    Case(
        "2 levels, 498x2000, changed + render",
        "/two-render/",
        (498, BUDGET),
        3 * BUDGET,
        5.0,
    ),
    # Depth must not multiply the cost, at any shape.
    Case("3 levels, 1x498x2000", "/three-clean/", (1, 498, BUDGET), 2 * BUDGET, 5.0),
    Case(
        "3 levels, 1x498x2000, has_changed first",
        "/three-changed/",
        (1, 498, BUDGET),
        2 * BUDGET,
        5.0,
    ),
    Case("3 levels, 20x20x2000", "/three-clean/", (20, 20, BUDGET), 2 * BUDGET, 5.0),
    Case(
        "5 levels, 4x4x4x4x2000",
        "/five-changed/",
        (4, 4, 4, 4, BUDGET),
        2 * BUDGET,
        5.0,
    ),
    # A hidden initial value spans many keys, so it is rebuilt, not copied.
    Case(
        "hidden initial, 498x2000", "/hidden-changed/", (498, BUDGET), 3 * BUDGET, 5.0
    ),
    # A sequence inside a mapping reports through the mapping's child form, so
    # the outer field shows an item error rather than the row-count error.
    Case(
        "inside a mapping, 498x2000",
        "/mapping-changed/",
        (498, BUDGET),
        2 * BUDGET,
        5.0,
        prefixes=("value-values",),
        expect="item_invalid",
    ),
    Case(
        "inside a mapping, changed + render",
        "/mapping-render/",
        (498, BUDGET),
        3 * BUDGET,
        5.0,
        prefixes=("value-values",),
        expect="item_invalid",
    ),
    # Sibling fields hold independent budgets, which matches Django giving each
    # formset its own absolute_max. The form's author fixes the sibling count,
    # so this multiplier is not attacker-controlled.
    Case(
        "8 sibling fields, 61x2000 each",
        "/siblings-changed/",
        (61, BUDGET),
        8 * 2 * BUDGET,
        20.0,
        prefixes=tuple("abcdefgh"),
    ),
)


class Aborted(Exception):
    """Raised by the abort timer when one case runs far past its bound."""


def measure(client, case):
    """Post one case twice: once clean for timing, once traced for memory.

    ``tracemalloc`` costs roughly five times the workload itself here, so one
    instrumented pass would report a wall time five times the truth and invite
    exactly the wrong conclusion about how fast a rejection is. Timing comes
    from a clean pass. Peak allocation comes from a second pass, whose own
    timing is discarded.
    """
    payload = case.payload
    ROWS_BUILT[0] = 0
    signal.setitimer(signal.ITIMER_REAL, ABORT_SECONDS)
    start = time.perf_counter()
    aborted = False
    try:
        response = client.post(case.url, payload)
        elapsed = time.perf_counter() - start
        body = response.json()
        codes = sorted({code for codes in body["errors"].values() for code in codes})
        outcome = ",".join(codes) if codes else "valid" if body["valid"] else "invalid"
    except Aborted:
        elapsed = time.perf_counter() - start
        outcome = f">{ABORT_SECONDS:.0f}s ABORTED"
        aborted = True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    rows = ROWS_BUILT[0]

    peak = 0
    if not aborted:
        # A case that already ran past its bound would only do so again.
        tracemalloc.start()
        signal.setitimer(signal.ITIMER_REAL, ABORT_SECONDS)
        try:
            client.post(case.url, payload)
        except Aborted:
            pass
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()

    return {
        "case": case,
        "keys": len(payload),
        "rows": rows,
        "seconds": elapsed,
        "peak_mb": peak / 1024 / 1024,
        "outcome": outcome,
        "rows_ok": rows <= case.max_rows,
        "time_ok": elapsed <= case.max_seconds,
        "verdict_ok": case.expect is None or case.expect in outcome,
    }


def legitimate_baseline(client):
    """Measure an ordinary submission of the same shape, for scale."""
    payload = amplify("values", (20, 20))
    for outer in range(20):
        for inner in range(20):
            payload[f"values-{outer}-{inner}"] = f"r{outer}c{inner}"
    ROWS_BUILT[0] = 0
    start = time.perf_counter()
    response = client.post("/two-clean/", payload)
    return {
        "keys": len(payload),
        "rows": ROWS_BUILT[0],
        "seconds": time.perf_counter() - start,
        "valid": response.json()["valid"],
    }


def report(results, baseline):
    """Print the table, the amplification, and the failures."""
    header = (
        f"{'case':40s} {'keys':>5s} {'claimed':>10s} {'built':>7s} "
        f"{'sec':>7s} {'MB':>6s}  verdict"
    )
    print(header)
    print("-" * len(header))
    for result in results:
        case = result["case"]
        ok = result["rows_ok"] and result["time_ok"] and result["verdict_ok"]
        print(
            f"{case.label:40s} {result['keys']:>5d} {case.claimed:>10,d} "
            f"{result['rows']:>7,d} {result['seconds']:>7.3f} "
            f"{result['peak_mb']:>6.1f}  {'PASS' if ok else 'FAIL'} "
            f"{result['outcome']}"
        )

    by_label = {result["case"].label: result for result in results}
    small = by_label["2 levels, 1x2000 concentrated"]
    large = by_label["2 levels, 498x2000 spread"]
    print()
    print("amplification, cheapest claim -> widest claim a request can carry")
    print(f"  rows claimed  x{large['case'].claimed / small['case'].claimed:>8.1f}")
    print(f"  rows built    x{large['rows'] / max(small['rows'], 1):>8.1f}")
    print(f"  wall time     x{large['seconds'] / small['seconds']:>8.1f}")

    print()
    print("for scale, a legitimate 20x20 submission with every row filled")
    print(
        f"  {baseline['keys']} keys, {baseline['rows']} rows built, "
        f"{baseline['seconds']:.3f}s, valid={baseline['valid']}"
    )
    worst = max(result["seconds"] for result in results)
    print(
        f"  the worst case above costs x{worst / baseline['seconds']:.0f} that request"
    )

    failures = [
        result for result in results if not (result["rows_ok"] and result["verdict_ok"])
    ]
    slow = [result for result in results if not result["time_ok"]]
    print()
    print(f"{len(results) - len(failures)}/{len(results)} cases within their row bound")
    for result in failures:
        case = result["case"]
        print(
            f"  FAIL {case.label}: built {result['rows']:,} of at most "
            f"{case.max_rows:,}, verdict {result['outcome']}"
        )
    for result in slow:
        case = result["case"]
        print(
            f"  SLOW {case.label}: {result['seconds']:.3f}s over the "
            f"{case.max_seconds:.0f}s operational ceiling"
        )
    return failures


def _abort_case(_signum, _frame):
    """Stop a case that has run far past its bound."""
    raise Aborted


@contextlib.contextmanager
def counting_rows():
    """Count row forms built inside the block.

    Counting construction is the only honest measure of the work a forged
    ``TOTAL_FORMS`` key buys. Wall time also carries request parsing and
    template rendering, which is exactly the confusion this separates out.
    """
    original = SequenceWidget.RowFormSet._construct_form

    def counting(formset, index, **kwargs):
        ROWS_BUILT[0] += 1
        return original(formset, index, **kwargs)

    SequenceWidget.RowFormSet._construct_form = counting
    try:
        yield
    finally:
        SequenceWidget.RowFormSet._construct_form = original


def profile_case(client, case, rows=10):
    """Print the functions that burn the most time serving one case."""
    ROWS_BUILT[0] = 0
    profiler = cProfile.Profile()
    profiler.runctx("client.post(case.url, case.payload)", globals(), locals())
    print()
    print(
        f"===== {case.label}: {len(case.payload)} keys, "
        f"{ROWS_BUILT[0]:,} rows built ====="
    )
    pstats.Stats(profiler).sort_stats("tottime").print_stats(rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    profiling = "--profile" in argv
    if profiling:
        argv.remove("--profile")
    setup_test_environment()
    signal.signal(signal.SIGALRM, _abort_case)
    with counting_rows():
        client = Client()
        if profiling:
            wanted = argv[0] if argv else None
            if wanted is None:
                cases = [case for case in CASES if case.label in CONTRAST]
            else:
                cases = [case for case in CASES if wanted in case.label]
            if not cases:
                print(f"no case label contains {wanted!r}; labels are:")
                for case in CASES:
                    print(f"  {case.label}")
                return 2
            for case in cases:
                profile_case(client, case)
            print(PROFILE_HINT)
            return 0
        print(f"budget per entry point: {BUDGET} rows")
        print(f"abort timer: {ABORT_SECONDS:.0f}s per case")
        print("Django's parser limits are at their defaults for every case.")
        print()
        # Measure the honest request first. Run last, it reads several times
        # slower, because by then the pathological cases have grown the heap
        # and every garbage collection costs more.
        baseline = legitimate_baseline(client)
        results = [measure(client, case) for case in CASES]
    return 1 if report(results, baseline) else 0


if __name__ == "__main__":
    raise SystemExit(main())
