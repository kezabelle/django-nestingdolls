"""Widgets that render and bind composite mapping and sequence fields."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from django.forms import BaseForm, BaseFormSet, Field, Form
from django.forms.formsets import (
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    formset_factory,
)
from django.forms.widgets import Media as WidgetMedia
from django.forms.widgets import MultiWidget, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property

from nestingdolls.patches import FormLayout

if TYPE_CHECKING:
    from types import TracebackType

    from django.core.files.uploadedfile import UploadedFile

    from nestingdolls.fields import SequenceField


__all__ = ["MappingWidget", "SequenceWidget"]


MANAGEMENT_NAMES = (
    TOTAL_FORM_COUNT,
    INITIAL_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
)


# The name of the one child field inside each row form. boundfield.py and
# fields.py read row data under this name too, so it has no underscore.
row_value_name = "value"


class CompositeWidget(Widget):
    """Base widget for composite mapping and sequence values."""

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState:
        """Hold the submitted state that one render of a composite widget needs."""

        hidden_initial_value: object = None

    _template_name: str
    input_type: str | None = None
    render_state: RenderState = RenderState()

    def _accepts_key(self, key: object, name: str) -> bool:
        """Report whether one submitted key belongs to this composite."""
        raise NotImplementedError

    def _child_widget(self, field: Field) -> Widget:
        """Return the widget one child renders with, hidden when this widget is."""
        widget: Widget = field.widget
        if self.input_type != "hidden":
            return widget
        return field.hidden_widget()

    @property
    def template_name(self) -> str:
        """Resolve this widget's template for the active Django form layout."""
        if "{layout}" not in self._template_name:
            return self._template_name
        return self._template_name.format(layout=FormLayout.current().value)

    @template_name.setter
    def template_name(self, value: str) -> None:
        self._template_name = value

    def _get_media(self) -> WidgetMedia:
        """Add this widget's own class ``Media`` to its children's media.

        Django's ``MediaDefiningClass`` metaclass already installs a ``media``
        property on every subclass that merges each ``class Media`` up the
        MRO (``django.forms.widgets.media_property``); ``super().media``
        reaches that chain. This only adds what Django's own mechanism does
        not know about: the media of the child widgets this widget renders.
        """
        return super().media + self._child_media()

    media = property(_get_media)

    def _child_media(self) -> WidgetMedia:
        """Return the media of the children this widget renders."""
        raise NotImplementedError

    def value_omitted_from_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether no supported composite input was submitted.

        This replaces ``Widget.value_omitted_from_data`` because Django
        tests only the exact field name, and a composite reads many
        prefixed keys.
        """
        return not any(
            self._accepts_key(key, name) for source in (data, files) for key in source
        )

    def use_required_attribute(self, initial: object) -> bool:  # noqa: ARG002
        """Report that the browser required attribute never applies.

        This replaces ``Widget.use_required_attribute`` because the
        composite renders no input of its own. The child Form and the row
        forms set the attribute for their own inputs.
        """
        return False

    def id_for_label(self, id_: str) -> str:  # noqa: ARG002
        """Suppress a label target because this widget renders multiple inputs."""
        return ""


class MappingWidget(CompositeWidget):
    """Render one child Form as the widget of a mapping field."""

    _template_name = "nestingdolls/mapping/{layout}.html"
    use_fieldset = True
    form_class: type[BaseForm]

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState(CompositeWidget.RenderState):
        """Hold the child Form that one mapping render needs.

        The bound field builds the child Form, because only the bound field
        holds the data that the browser sent and the errors of that Form. A
        render that gets no child Form builds a new one from the value that it
        gets.
        """

        subform: BaseForm | None = None
        initial_error: str | None = None

    render_state: RenderState = RenderState()

    @cached_property
    def fields(self) -> dict[str, Field]:
        """Return the fields of one instance of the child Form."""
        return self.form_class().fields

    def _accepts_key(self, key: object, name: str) -> bool:
        """Report whether the key is this field's own name or a declared child key."""
        if not isinstance(key, str):
            return False
        if key == name:
            return True
        child_key = key.removeprefix(f"{name}-")
        if child_key == key:
            return False
        # A widget may extend its own name, such as ``birthday_day`` or
        # ``time_0``, so accept a declared name with a suffix too.
        return any(
            child_key == child_name
            or child_key.startswith((f"{child_name}-", f"{child_name}_"))
            for child_name in self.fields
        )

    def has_child_keys(self, source: Mapping[str, object], name: str) -> bool:
        """Report whether one source holds any declared child key."""
        return any(key != name and self._accepts_key(key, name) for key in source)

    def _data_from_exact_mapping(
        self, value: Mapping[str, object], name: str
    ) -> Mapping[str, object]:
        """Give each member of an exact mapping its own child key."""
        getlist = getattr(value, "getlist", None)
        if getlist is not None:
            expanded = MultiValueDict[str, object]()
            for child_name in self.fields:
                if child_name in value:
                    expanded.setlist(f"{name}-{child_name}", getlist(child_name))
            return expanded
        return {
            f"{name}-{child_name}": value[child_name]
            for child_name in self.fields
            if child_name in value
        }

    def expand_exact_inputs(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Return data and files with exact mappings expanded to child keys."""
        data_value = data.get(name) if name in data else None
        if isinstance(data_value, Mapping):
            data = self._data_from_exact_mapping(data_value, name)
        files_value = files.get(name) if name in files else None
        if isinstance(files_value, Mapping):
            files = self._data_from_exact_mapping(files_value, name)
        return data, files

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values, or return unreadable exact input unchanged."""
        data, files = self.expand_exact_inputs(data, files, name)
        data_submitted = self.has_child_keys(data, name)
        if not data_submitted and name in data:
            return data.get(name)
        if data_submitted or self.has_child_keys(files, name):
            return self._extract_children(data, files, name)
        if name in files:
            return files.get(name)
        return {}

    def _extract_children(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> dict[str, object]:
        """Collect each submitted child value under its declared name."""
        value: dict[str, object] = {}
        for child_name, field in self.fields.items():
            child_widget = self._child_widget(field)
            input_name = f"{name}-{child_name}"
            if child_widget.value_omitted_from_data(
                data,
                cast("MultiValueDict[str, UploadedFile[bytes]]", files),
                input_name,
            ):
                continue
            value[child_name] = child_widget.value_from_datadict(
                data,
                cast("MultiValueDict[str, UploadedFile[bytes]]", files),
                input_name,
            )
        return value

    def get_context(
        self, name: str, value: object, attrs: dict[str, object] | None
    ) -> dict[str, object]:
        """Build the context of the widget, with a prefixed child Form.

        The bound field supplies the child Form when the outer form is bound.
        An unbound render gets no Form, and it builds one from the value that it
        gets. Each sequence descendant opens its own shared budget when it
        renders. Django limits each formset level only, not the rows that
        nesting multiplies.
        """
        context = super().get_context(name, value, attrs)
        widget_context = cast("dict[str, object]", context["widget"])
        subform = self.render_state.subform
        if subform is None:
            # A hidden initial render must show the initial value, because
            # change detection compares it with the value that the browser
            # sent.
            if self.render_state.hidden_initial_value is not None:
                value = self.render_state.hidden_initial_value
            subform = self.form_class(
                initial=dict(value) if isinstance(value, Mapping) else {},
                prefix=name,
                use_required_attribute=self.is_required,
            )
        initial_error = self.render_state.initial_error
        errors: list[object] = [initial_error] if initial_error else []
        errors += subform.non_field_errors()
        widget_context.update(
            {
                "subform": subform,
                "visible_fields": subform.visible_fields(),
                "hidden_fields": (
                    [field.as_hidden() for field in subform]
                    if self.is_hidden
                    else subform.hidden_fields()
                ),
                "non_field_errors": errors,
            }
        )
        return cast("dict[str, object]", context)

    @property
    def is_hidden(self) -> bool:
        """Report whether the mapping or every child widget is hidden."""
        return super().is_hidden or all(
            field.widget.is_hidden for field in self.fields.values()
        )

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Report whether any child widget accepts files."""
        return any(field.widget.needs_multipart_form for field in self.fields.values())

    def _child_media(self) -> WidgetMedia:
        """Return the media of the child Form.

        ``BaseForm.media`` already aggregates every child widget's media.
        """
        return self.form_class().media

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy this widget. Do not share its cached child widgets.

        ``Widget.__deepcopy__`` makes only a shallow ``copy.copy``. A
        warmed ``fields`` cache holds child ``Field`` and ``Widget``
        objects. This method clears that cache, so no two forms share it.

        ``ClearableFileInput.value_from_datadict`` changes
        ``self.checked`` on its widget. A shared cache turns that change
        into a cross-request bug. ``MultiValueField.__deepcopy__`` clears
        its own cache for the same reason.
        """
        result = super().__deepcopy__(memo)
        result.__dict__.pop("fields", None)
        return result


class SequenceWidget(CompositeWidget):
    """Render the rows of a sequence field. One child widget renders each row."""

    _template_name = "nestingdolls/sequence/{layout}.html"
    use_fieldset = True
    _child_field: Field
    limits: SequenceField.Limits

    class RowForm(Form):
        """Wrap one child field without changing its visible key."""

        def add_prefix(self, field_name: str) -> str:
            """Keep the value field on its row prefix."""
            if field_name == row_value_name and self.prefix:
                return self.prefix
            return super().add_prefix(field_name)

    class RowFormSet(BaseFormSet):  # type: ignore[type-arg]
        """Build rows with the owning sequence widget's shared budget."""

        sequence_widget: SequenceWidget
        submission_total_form_count: int

        def get_form_kwargs(self, index: int | None) -> dict[str, Any]:
            """Deny ``empty_permitted`` to a row whose keys carry a non-blank value.

            ``Form.has_changed()`` must not skip a row with real data, so
            such a row must not stay ``empty_permitted``. Django applies
            these kwargs after its own ``empty_permitted`` default, so
            this flips exactly the rows a ``_construct_form`` override
            would flip, without one Python frame, one ``super`` object,
            and one kwargs dict per row; pathological.py records the
            measurement. ``None`` is the ``empty_form`` path, which has
            no row prefix to look up. What counts as a non-blank value
            is written down on ``rows_with_submitted_values``.
            """
            kwargs = super().get_form_kwargs(index)
            if (
                index is not None
                and self.add_prefix(index) in self.rows_with_submitted_values
            ):
                kwargs["empty_permitted"] = False
            return kwargs

        @cached_property
        def rows_with_submitted_values(self) -> set[str]:
            """Index the row prefixes whose keys carry a non-blank value.

            One pass over the submitted keys answers every row of this
            formset. Asking each row to scan the keys itself is
            ``O(rows x keys)``, and a forged ``TOTAL_FORMS`` key buys that
            product more cheaply than it buys anything else.

            Derive each key's row from this formset's own prefix: the
            segment after it, up to the next ``-``. ``values-3``,
            ``values-3-0`` and ``values-3-TOTAL_FORMS`` all belong to row
            ``values-3``; ``values-31`` does not. A key that yields no real
            row prefix, such as ``values-TOTAL_FORMS``, lands in the set
            under its own name and is never looked up.

            Only a non-blank value counts as content. A rendered row
            always sends its delete key, checked or not, and always
            sends its other keys, even when the user left them blank.
            Neither shows real content, and a row with real content must
            not clean as an empty permitted row.

            Compare a slice rather than calling ``startswith``: the prefix
            length is already in hand, and ``str.startswith`` builds an
            argument tuple on every call where a slice comparison builds
            none. A key shorter than the prefix yields a shorter string,
            which cannot equal it, so the slice needs no length guard.
            """
            prefix = f"{self.prefix}-"
            start = len(prefix)
            found: set[str] = set()
            for source in (self.data, self.files):
                getlist = getattr(source, "getlist", None)
                for key in source:
                    if not isinstance(key, str) or key[:start] != prefix:
                        continue
                    end = key.find("-", start)
                    if end >= 0 and key[end + 1 :] == DELETION_FIELD_NAME:
                        # The row's own delete key. A rendered row
                        # always sends it, so it shows no content.
                        continue
                    row = key if end < 0 else key[:end]
                    if row in found:
                        continue
                    if getlist is None:
                        value = source.get(key)
                        if value is not None and value != "":
                            found.add(row)
                        continue
                    for value in getlist(key):
                        if value is not None and value != "":
                            found.add(row)
                            break
            return found

        def total_form_count(self) -> int:
            """Build and reserve only the submitted rows within the shared budget.

            Read ``TOTAL_FORMS`` inside the scope: Django's own
            ``total_form_count`` builds and cleans the ``ManagementForm``
            to read it, and that form holds four ``IntegerField``s, so it
            cannot re-enter the countdown.
            """
            if hasattr(self, "submission_total_form_count"):
                return self.submission_total_form_count
            with self.sequence_widget.submission_countdown(
                self.sequence_widget.limits.submission_max
            ) as countdown:
                # A negative remaining value means the shared budget
                # already ran out, so take() returns zero for any claim
                # and the ManagementForm buys nothing. Do not build it: on
                # a wide hostile submission that form is one full Django
                # form per outer row, about 28 percent of the request's
                # wall time (measured in pathological.py). The skipped
                # take() is safe because __exit__ reads only the sign of
                # the remaining value, and the first overdrawing claim
                # still goes through take(). The ManagementForm stays
                # lazily available: get_context and full_clean build it on
                # demand, so no reader changes.
                if countdown.remaining.get() < 0:
                    allowed = 0
                else:
                    allowed = countdown.take(super().total_form_count())
            self.submission_total_form_count = allowed
            return allowed

    @dataclasses.dataclass(slots=True)
    class submission_countdown:  # noqa: N801
        """Limit rows built by one recursively nested sequence extraction or render.

        Django limits request keys, files, and bytes before a form sees them, and a
        formset caps one level. A few nested ``TOTAL_FORMS`` keys can still multiply
        empty rows across sequence levels. This small context-local counter is only
        for that attacker-controlled recursive work. It is intentionally not a
        mapping or form-wide policy.

        The shared context holds one signed integer: the remaining row
        budget. ``take`` always subtracts the full requested count, not
        only the allowed part. This lets the remaining value fall below
        zero. A negative value means some caller already asked for more
        rows than the budget had left. One value thus carries two facts:
        how many rows are left, and whether any caller ran out. A second
        stored flag is not needed.

        The variable has no default. A read outside an open scope
        raises ``LookupError`` from the unset variable itself, so no
        read site tests for a missing value. Only ``__enter__`` must
        see the unset state, and it passes a call-site default.
        """

        remaining: ClassVar[ContextVar[int]] = ContextVar(
            "nestingdolls_submission_countdown"
        )

        count: int
        ran_out: bool = False
        token: Token[int] | None = dataclasses.field(
            default=None, init=False, repr=False
        )

        def __bool__(self) -> bool:
            """Report whether the shared budget ran out while this scope was open."""
            return self.ran_out

        @property
        def owns_scope(self) -> bool:
            """Report whether this scope started the shared counter.

            Only the outermost scope of one extraction owns the counter.
            A nested scope found the shared context already open, so it
            must not report the shared overflow as its own field's
            overflow. The outer field reports it once for the whole
            submission.

            ``__exit__`` resets the token but does not clear it, so this
            stays readable after the ``with`` block ends.
            """
            return self.token is not None

        def take(self, count: int) -> int:
            """Reserve the rows that fit in the active shared allowance.

            Subtract the full requested count, not only the allowed part.
            A negative remaining value then marks that the budget ran out.
            Clamp the return value at zero: a caller must never build a
            negative number of rows. A call outside an open scope
            raises ``LookupError`` from the unset variable.
            """
            left = self.remaining.get()
            allowed = max(0, min(count, left))
            self.remaining.set(left - count)
            return allowed

        def __enter__(self) -> Self:
            """Start the counter at the outer sequence and reuse it inside rows.

            This is the one read that must see "no scope open yet".
            The variable has no default, so give this read one:
            ``None`` cannot collide with a stored count.
            """
            if self.remaining.get(None) is None:
                self.token = self.remaining.set(self.count)
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            """Remember overflow. Reset the token only if this scope owns it.

            Read the shared state on every exit. Copy the overflow flag on
            every exit. Do this even if this scope does not own the token.
            A nested scope never owns the token. Its own ``__enter__``
            method found the shared context already open.

            An earlier version read the state only inside the token check
            below. Then a nested scope could not update its own overflow
            flag. The flag stayed at its default value. Do not move this
            read back inside the token check. Find a different fix for
            that other problem.

            Reset the token only if this scope owns it. Do the reset
            after the read above, not before it. The reset puts back the
            value from before this scope opened the shared context. For
            the owning scope, that is the unset state. A read after the
            reset would then raise ``LookupError`` instead of returning
            the final state.

            A scope that does not own the token must not call reset.
            That scope did not open the shared context. It has no old
            value to put back. A reset with a token it did not receive
            would damage the owning scope's context.
            """
            self.ran_out = self.remaining.get() < 0
            if self.token is not None:
                self.remaining.reset(self.token)

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState(CompositeWidget.RenderState):
        """Hold the formset that supplies one sequence render."""

        formset: BaseFormSet[BaseForm] | None = None
        submission_overflow: bool = False

    render_state: RenderState = RenderState()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = ("nestingdolls/sequence.js",)

    @property
    def child_field(self) -> Field:
        """Return the field that builds each row."""
        return self._child_field

    @child_field.setter
    def child_field(self, value: Field) -> None:
        """Point this widget at a new child field and drop the cached class.

        The cached row formset class names the old child field and its
        old limits, so assign ``limits`` before ``child_field``: the
        next build after this pop must read the new values.
        ``__deepcopy__`` writes ``_child_field`` directly to keep the
        cache; its docstring says why that one path is safe.
        """
        self._child_field = value
        self.__dict__.pop("formset_class", None)

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy this widget, its child field, and the cached class together.

        ``Widget.__deepcopy__`` makes only a shallow ``copy.copy``. It
        does not follow ``child_field``, so two forms would share one
        child field and its widget. Copy the child through ``memo``
        here, so a field copy that deep-copies its own child in the
        same pass gets this same object back and stays linked to its
        widget.

        Write ``_child_field`` directly: the ``child_field`` setter
        drops the cached row formset class, and this copy must keep it.
        The class only names the deepcopy source of the new child, and
        each row form deep-copies that field again, so the shared class
        moves no mutable state between forms. A rebuild instead costs
        about 15 percent of the widest hostile request's wall time and
        2.6 MB of its peak allocation; pathological.py records the
        measurement. ``limits`` needs no copy: it is a frozen slots
        dataclass with no per-form state, and the shallow copy already
        carries it. A widget with no child field yet copies clean,
        because ``Field.__init__`` deep-copies a supplied widget
        instance before the field assigns its configuration.
        """
        result = super().__deepcopy__(memo)
        try:
            child_field = self._child_field
        except AttributeError:
            return result
        result._child_field = copy.deepcopy(child_field, memo)  # noqa: SLF001
        return result

    @cached_property
    def formset_class(self) -> type[RowFormSet]:
        """Build the row formset class from this widget's child and limits."""
        child_widget = self.child_field.widget
        if isinstance(child_widget, SequenceWidget):
            # This read is only for speed. The code is correct without it.
            # The read builds the child sequence's class and caches it
            # before any row form deep-copies the child field.
            # SequenceField.__deepcopy__ then gives each copy that one
            # cached class. Without this, each row builds two new classes.
            _ = child_widget.formset_class
        row_form = type("Row", (self.RowForm,), {row_value_name: self.child_field})
        return cast(
            "type[SequenceWidget.RowFormSet]",
            formset_factory(
                row_form,
                formset=self.RowFormSet,
                extra=0,
                can_delete=True,
                min_num=self.limits.min_length,
                max_num=self.limits.max_length,
                absolute_max=self.limits.absolute_max,
                validate_min=False,
                validate_max=False,
            ),
        )

    def new_formset(
        self,
        *,
        data: Mapping[str, object] | None = None,
        files: MultiValueDict[str, UploadedFile[bytes]] | None = None,
        initial: Sequence[Mapping[str, object]] | None = None,
        prefix: str | None = None,
        auto_id: str = "id_%s",
        form_kwargs: dict[str, object] | None = None,
    ) -> RowFormSet:
        """Build a row formset bound to this widget's child field and limits."""
        formset = self.formset_class(
            data=data,
            files=files,
            initial=initial,
            prefix=prefix,
            auto_id=auto_id,
            form_kwargs=form_kwargs,
        )
        formset.sequence_widget = self
        return formset

    def data_from_exact_list(
        self, values: list[object], name: str
    ) -> dict[str, object]:
        """Give each row of an exact list its own key.

        An exact list carries no per-row prefixed keys. Build one key per row
        so the row formset binds and can render row errors. A plain mapping
        keeps a nested list as one sequence value, instead of treating it as
        repeated request input.
        """
        rows: dict[str, object] = {
            f"{name}-{index}": value for index, value in enumerate(values)
        }
        total = str(len(values))
        rows[f"{name}-{TOTAL_FORM_COUNT}"] = total
        rows[f"{name}-{INITIAL_FORM_COUNT}"] = total
        return rows

    def _accepts_key(self, key: object, name: str) -> bool:
        """Report whether the key is this field's own name, a management key, or a row key."""
        if not isinstance(key, str):
            return False
        if key == name:
            return True
        child_key = key.removeprefix(f"{name}-")
        if child_key == key or not child_key:
            return False
        if child_key in MANAGEMENT_NAMES:
            return True
        return "0" <= child_key[0] <= "9"

    def has_row_keys(self, source: Mapping[str, object], name: str) -> bool:
        """Report whether one source holds any per-row prefixed key.

        A plain loop, not a generator expression: this reads every key of
        a submission, so one frame resume per key is real cost. Two slice
        comparisons for the same reason, rather than ``startswith`` and an
        index: the prefix length is already in hand, and ``str.startswith``
        builds an argument tuple on every call where a slice builds none.
        Neither slice needs a length guard. A key shorter than the prefix
        yields a shorter string, which cannot equal it, and a key that ends
        at the prefix yields ``""``, which sorts below ``"0"``.
        """
        prefix = f"{name}-"
        start = len(prefix)
        for key in source:
            if (
                isinstance(key, str)
                and key[:start] == prefix
                and "0" <= key[start : start + 1] <= "9"
            ):
                return True
        return False

    def has_management_keys(self, source: Mapping[str, object], name: str) -> bool:
        """Report whether one source holds any formset management key."""
        for field_name in MANAGEMENT_NAMES:
            if f"{name}-{field_name}" in source:
                return True
        return False

    def is_bound_formset(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether row or management keys bind the row formset."""
        if name in data or name in files:
            return self.has_row_keys(data, name) or self.has_row_keys(files, name)
        return (
            self.has_management_keys(data, name)
            or self.has_management_keys(files, name)
            or self.has_row_keys(data, name)
            or self.has_row_keys(files, name)
        )

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract exact input, or bound formset rows when none exists.

        Indexed row keys outrank exact input. Without indexed rows, exact
        input outranks management keys and keeps its source shape: an ordinary
        mapping supplies its value directly, and a Django multi-value mapping
        supplies its repeated values through ``getlist``.
        """
        source: Mapping[str, object] | None
        if name in data:
            source = data
        elif name in files:
            source = files
        else:
            source = None
        with self.submission_countdown(self.limits.submission_max) as countdown:
            if source is not None:
                has_rows = self.has_row_keys(data, name) or self.has_row_keys(
                    files, name
                )
                getlist = getattr(source, "getlist", None)
                values = source.get(name) if getlist is None else getlist(name)
                if not has_rows:
                    if isinstance(values, list):
                        return values[: countdown.take(len(values))]
                    return values
            elif not self.is_bound_formset(data, files, name):
                return []
            formset = self.new_formset(
                data=data,
                files=cast("MultiValueDict[str, UploadedFile[bytes]]", files),
                prefix=name,
            )
            return [form[row_value_name].data for form in formset.forms]

    def initial_rows(self, value: Sequence[object] | None) -> list[dict[str, object]]:
        """Adapt public sequence values to the concrete row form's initial data."""
        return [{row_value_name: row} for row in value or ()]

    def default_initial_rows(
        self, value: Sequence[object] | None
    ) -> list[dict[str, object]]:
        """Return initial rows, or one placeholder row for an empty required sequence.

        A required sequence with ``min_length == 0`` must still show one
        row, so the user can give a value.
        """
        initial = self.initial_rows(value)
        if not initial and self.is_required and self.limits.min_length == 0:
            initial = [self.empty_initial_row()]
        return initial

    def empty_initial_row(self) -> dict[str, object]:
        """Return the placeholder data for one empty row."""
        return {row_value_name: None}

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, object] | None,
    ) -> dict[str, object]:
        """Render row forms inside one shared render budget."""
        with self.submission_countdown(self.limits.submission_max):
            context = super().get_context(name, value, attrs)
            widget_context = cast("dict[str, object]", context["widget"])
            final_attrs = cast("dict[str, object]", widget_context["attrs"])
            final_attrs.pop("aria-invalid", None)
            id_value = final_attrs.get("id")
            id_ = id_value if isinstance(id_value, str) else None
            disabled = bool(final_attrs.get("disabled"))
            if self.is_hidden and self.render_state.hidden_initial_value is not None:
                value = cast("Sequence[object]", self.render_state.hidden_initial_value)
            formset = self.render_state.formset
            if self.render_state.submission_overflow:
                formset = self.new_formset(initial=[], prefix=name)
            elif formset is None:
                formset = self.new_formset(
                    initial=self.default_initial_rows(value), prefix=name
                )

            management_form = formset.management_form
            if not self.is_hidden:
                management_form.fields[TOTAL_FORM_COUNT].widget.attrs[
                    "data-sequence-total"
                ] = ""
            if disabled:
                for management_field in management_form.fields.values():
                    management_field.widget.attrs["disabled"] = True

            forms = formset.forms
            deleted_forms = {
                id(form)
                for form in forms
                if getattr(form, "cleaned_data", {}).get(DELETION_FIELD_NAME)
            }

            try:
                rows = [
                    self._row_context(form, index, final_attrs, id_)
                    for index, form in enumerate(forms)
                    if id(form) not in deleted_forms
                ]
                empty_row = self._row_context(
                    formset.empty_form, "__prefix__", final_attrs, id_
                )
            finally:
                child_widget = self._child_widget(self.child_field)
                if isinstance(child_widget, CompositeWidget):
                    child_widget.render_state = child_widget.RenderState()

            widget_context.update(
                {
                    "rows": rows,
                    "empty_row": empty_row,
                    "management_form": management_form,
                    "minimum_forms": self.limits.min_length,
                    "maximum_forms": self.limits.max_length,
                    "absolute_maximum_forms": self.limits.absolute_max,
                    "disabled": disabled or self.render_state.submission_overflow,
                }
            )
            if deleted_forms and not self.render_state.submission_overflow:
                widget_context["deleted_rows"] = [
                    {"delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}"}
                    for form in forms
                    if id(form) in deleted_forms
                ]
            return cast("dict[str, object]", context)

    def _row_context(
        self,
        form: BaseForm,
        index: int | str,
        attrs: dict[str, object],
        id_: str | None,
    ) -> dict[str, object]:
        """Build the template context for one row form."""
        from nestingdolls.boundfield import CompositeBoundField  # noqa: PLC0415

        child_attrs = attrs.copy()
        if id_:
            child_attrs["id"] = f"{id_}_{index}"
        if self.child_field.disabled:
            child_attrs["disabled"] = True
        child = form[row_value_name]
        child_widget = self._child_widget(child.field)
        if isinstance(child, CompositeBoundField):
            child.prepare_widget(cast("CompositeWidget", child_widget))
        if index == "__prefix__":
            child_value = None
        elif isinstance(child, CompositeBoundField):
            child_value = child.initial
        else:
            child_value = child.value()
        if isinstance(child_widget, MultiWidget) and isinstance(child_value, str):
            child_value = None
        subwidget = cast(
            "dict[str, object]",
            child_widget.get_context(child.html_name, child_value, child_attrs)[
                "widget"
            ],
        )
        errors = [
            message
            for error in form.errors.as_data().get(row_value_name, [])
            for message in error.messages
        ]
        row: dict[str, object] = {
            "index": index,
            "delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}",
            "subwidget": subwidget,
            "errors": errors,
        }
        if not errors:
            return row
        child_attrs = cast("dict[str, object]", subwidget["attrs"])
        child_id = child_attrs.get("id")
        error_id = f"{child_id}_error" if child_id else None
        if error_id:
            row["error_id"] = error_id
        self._mark_row_invalid(subwidget, error_id)
        return row

    def _mark_row_invalid(
        self, widget_context: dict[str, object], error_id: str | None
    ) -> None:
        """Point every input of one row at that row's error list.

        A MultiWidget copies the parent attributes into each child context, so
        walk the tree and give each input the same row error reference.
        """
        child_attrs = cast("dict[str, object]", widget_context["attrs"])
        child_attrs["aria-invalid"] = "true"
        if error_id:
            described_by = child_attrs.get("aria-describedby")
            child_attrs["aria-describedby"] = (
                f"{described_by} {error_id}" if described_by else error_id
            )
        for child_context in cast(
            "list[dict[str, object]]", widget_context.get("subwidgets", [])
        ):
            self._mark_row_invalid(child_context, error_id)

    @property
    def is_hidden(self) -> bool:
        """Report whether the sequence or its child widget is hidden."""
        return super().is_hidden or bool(self.child_field.widget.is_hidden)

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Report whether the child widget needs multipart form data."""
        return bool(self.child_field.widget.needs_multipart_form)

    def _child_media(self) -> WidgetMedia:
        """Return the media of the widget that renders each row."""
        return cast("WidgetMedia", self.child_field.widget.media)
