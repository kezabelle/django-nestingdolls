"""Widgets that render and bind composite mapping and sequence fields."""

from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Collection, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import islice
from typing import TYPE_CHECKING, ClassVar, Self, cast

from django.forms import BaseForm, BaseFormSet, Field, Form
from django.forms.formsets import (
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    formset_factory,
)
from django.forms.utils import ErrorList
from django.forms.widgets import Media as WidgetMedia
from django.forms.widgets import MultiWidget, Script, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.safestring import mark_safe

from nestingdolls.patches import FormLayout

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.core.files.uploadedfile import UploadedFile
    from django.forms import BoundField
    from django.forms.renderers import BaseRenderer

    from nestingdolls.fields import SequenceField


__all__ = ["MappingWidget", "SequenceWidget"]


class CompositeWidget(Widget):
    """Base widget for composite mapping and sequence values."""

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState:
        """Hold the submitted state that one render of a composite widget needs."""

        hidden_initial_value: object = None

    _template_name: str
    input_type: str | None = None
    render_state: RenderState = RenderState()

    def format_value(self, value: object) -> object:  # type: ignore[override]
        """Leave composite values intact until child row limits apply."""
        return value

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

    @property
    def media(self) -> WidgetMedia:
        """Add this widget's own class ``Media`` to its children's media.

        Django's ``MediaDefiningClass`` metaclass already installs a ``media``
        property on every subclass that merges each ``class Media`` up the
        MRO (``django.forms.widgets.media_property``); ``super().media``
        reaches that chain. This only adds what Django's own mechanism does
        not know about: the media of the child widgets this widget renders.
        """
        return super().media + self._child_media()

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

    def _exact_child_items(
        self, widget: Widget, key: str, value: object
    ) -> Iterator[tuple[str, object]]:
        """Expand an exact child value to the submission keys its widget reads."""
        if isinstance(widget, MultiWidget) and isinstance(value, (list, tuple)):
            # django-stubs omits widgets_names; MultiWidget.__init__ sets it.
            # A short value gives its last parts no key, so they read as missing.
            names: list[str] = widget.widgets_names  # type: ignore[attr-defined]
            for subwidget, suffix, part in zip(
                widget.widgets, names, value, strict=False
            ):
                yield from self._exact_child_items(subwidget, f"{key}{suffix}", part)
            return
        yield key, value


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
        """Report whether the key is this field's own name or a key under its prefix."""
        if not isinstance(key, str):
            return False
        if key == name:
            return True
        child_key = key.removeprefix(f"{name}-")
        return child_key != key and bool(child_key)

    def has_child_keys(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether either source holds any child key."""
        return any(
            key != name and self._accepts_key(key, name)
            for source in (data, files)
            for key in source
        )

    def is_control_key(self, key: str) -> bool:
        """Report whether a key under this mapping's name is a nested formset control.

        A member is content, even when it is named ``DELETE`` or ``TOTAL_FORMS``.
        Only a nested sequence has controls, so look for the member that owns the key.
        """
        return any(
            isinstance(field.widget, (MappingWidget, SequenceWidget))
            and key.startswith(f"{name}-")
            and field.widget.is_control_key(key[len(name) + 1 :])
            for name, field in self.fields.items()
        )

    def _data_from_exact_mapping(
        self, value: Mapping[object, object], name: str
    ) -> Mapping[str, object]:
        """Give each member of an exact mapping its own child key.

        Cleaning ignores a member whose name is not a string. Skip it here too,
        because its formatted key can replace the key of a string member.
        """
        getlist = getattr(value, "getlist", None)
        if getlist is not None:
            expanded = MultiValueDict[str, object]()
            for child_name in value:
                if not isinstance(child_name, str):
                    continue
                key = f"{name}-{child_name}"
                field = self.fields.get(child_name)
                child_widget = None if field is None else self._child_widget(field)
                if not isinstance(child_widget, MultiWidget):
                    expanded.setlist(key, getlist(child_name))
                    continue
                # Repeated values have no meaning for a MultiWidget, so its
                # compound value is the member's one value, as for a dict.
                for part_key, part in self._exact_child_items(
                    child_widget, key, value[child_name]
                ):
                    expanded[part_key] = part
            return expanded
        data: dict[str, object] = {}
        for child_name, member in value.items():
            if not isinstance(child_name, str):
                continue
            key = f"{name}-{child_name}"
            field = self.fields.get(child_name)
            if field is None:
                data[key] = member
            else:
                data.update(
                    self._exact_child_items(self._child_widget(field), key, member)
                )
        return data

    def expand_exact_inputs(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Return data and files with exact mappings expanded to child keys."""
        value = data.get(name)
        if isinstance(value, Mapping):
            data = self._data_from_exact_mapping(value, name)
        value = files.get(name)
        if isinstance(value, Mapping):
            files = self._data_from_exact_mapping(value, name)
        return data, files

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values. Return exact input when the widget cannot read it.

        Check child keys in ``data`` and ``files`` before exact scalar input.
        Use the same check as ``MappingBoundField.is_bound_subform``.
        This keeps change detection and cleaning on the same input.
        """
        data, files = self.expand_exact_inputs(data, files, name)
        if not self.has_child_keys(data, files, name):
            if name in data:
                return data.get(name)
            if name in files:
                return files.get(name)
            return {}
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
        """Build context with a supplied or value-backed prefixed child Form."""
        context = super().get_context(name, value, attrs)
        widget_context: dict[str, object] = context["widget"]
        widget_attrs: dict[str, object] = widget_context["attrs"]  # type: ignore[assignment]
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
        layout = FormLayout.current()
        # The div, table, and ul templates delegate to subform.as_*().
        visible_fields: list[BoundField] = []
        hidden_fields: list[object] = []
        non_field_errors: ErrorList | list[object] = []
        if self.is_hidden:
            hidden_fields = [field.as_hidden() for field in subform]
        elif layout is FormLayout.p:
            # mapping/p.html loops over the fields itself. Django's context
            # also adds the error of each hidden child to the top errors.
            paragraph = subform.get_context()
            visible_fields = [field for field, _errors in paragraph["fields"]]
            hidden_fields = paragraph["hidden_fields"]
            non_field_errors = paragraph["errors"]
        initial_errors: ErrorList | None = None
        if initial_error:
            initial_errors = subform.error_class(
                [initial_error],
                error_class="nonfield",
                renderer=subform.renderer,
            )
            non_field_errors = subform.error_class(
                [initial_error, *non_field_errors],
                error_class="nonfield",
                renderer=subform.renderer,
            )
        wrapper_attrs = widget_attrs.copy()
        wrapper_attrs.pop("id", None)
        if layout is FormLayout.div:
            wrapper_attrs.pop("aria-invalid", None)
        else:
            wrapper_attrs["role"] = "group"
        widget_context.update(
            {
                "subform": subform,
                "visible_fields": visible_fields,
                "hidden_fields": hidden_fields,
                "initial_errors": initial_errors,
                "non_field_errors": non_field_errors,
                "wrapper_attrs": wrapper_attrs,
            }
        )
        return context

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
        """Return media from the cached child fields."""
        media = WidgetMedia()
        for field in self.fields.values():
            media += field.widget.media
        return media

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

    management_names = (
        TOTAL_FORM_COUNT,
        INITIAL_FORM_COUNT,
        MIN_NUM_FORM_COUNT,
        MAX_NUM_FORM_COUNT,
    )
    row_value_name = "value"
    # One or more ASCII digits, then a row separator or the key end.
    row_index = re.compile(r"[0-9]++(?:-|\Z)")

    _template_name = "nestingdolls/sequence/{layout}.html"
    use_fieldset = True
    _child_field: Field
    limits: SequenceField.Limits

    class RowFormSet(BaseFormSet):  # type: ignore[type-arg]
        """Build rows with the owning sequence widget's shared budget."""

        sequence_widget: SequenceWidget
        submission_total_form_count: int
        # A disabled sequence sets this. Django does not give ``disabled`` to a row field.
        rows_disabled = False
        # new_formset can set these from the parent form.
        form_renderer: BaseRenderer | None
        renderer: BaseRenderer

        def get_form_kwargs(self, index: int | None) -> dict[str, object]:
            """Keep a submitted row when its value equals its initial value."""
            kwargs = super().get_form_kwargs(index)
            if (
                index is not None
                and self.add_prefix(index) in self.rows_with_submitted_values
            ):
                kwargs["empty_permitted"] = False
            return kwargs

        def add_fields(self, form: BaseForm, index: int | None) -> None:
            """Disable the value field of each row of a disabled sequence.

            Do this as each row builds. A loop over ``forms`` before the render
            would build the rows outside its shared budget.
            """
            super().add_fields(form, index)
            if self.rows_disabled:
                form.fields[self.sequence_widget.row_value_name].disabled = True

        @cached_property
        def rows_with_submitted_values(self) -> set[str]:
            """Return the prefixes of rows that have a non-blank submitted value.

            A rendered row always posts its delete key and blank values, so only
            a non-blank value counts as content. Skip delete and management keys,
            including those of nested formsets, but not a mapping member that
            has such a name.
            """
            prefix = f"{self.prefix}-"
            start = len(prefix)
            found: set[str] = set()
            for source in (self.data, self.files):
                getlist = getattr(source, "getlist", None)
                for key in source:
                    if key[:start] != prefix:
                        continue
                    last_name = key.rpartition("-")[2]
                    if (
                        last_name in self.sequence_widget.management_names
                        or last_name == DELETION_FIELD_NAME
                    ) and self.sequence_widget.is_control_key(key[start:]):
                        continue
                    end = key.find("-", start)
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
                # Exact rows already reserved their budget; keep the original
                # management total for validation while capping built rows.
                return min(self.submission_total_form_count, self.absolute_max)
            with self.sequence_widget.submission_countdown.open(
                self.sequence_widget.limits.submission_max
            ) as countdown:
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

        A countdown is the budget. ``open()`` builds it at the outermost
        sequence of one operation and stores it in the shared context; a
        nested ``open()`` yields that same object and owns nothing.
        ``take()`` reserves the rows that fit. When the owning ``open()``
        passed ``raises=True``, an overdraw raises ``OverdrawError`` instead
        of clipping. The exception unwinds every nested frame, and only
        the owning ``open()`` catches it and records ``overflowed``, so
        one oversized submission produces one answer in one place.
        """

        class OverdrawError(Exception):
            """One extraction asked for more rows than the budget holds."""

        active: ClassVar[ContextVar[SequenceWidget.submission_countdown]] = ContextVar(
            "nestingdolls_submission_countdown"
        )

        remaining: int
        raises: bool = False
        overflowed: bool = dataclasses.field(default=False, init=False)

        def take(self, count: int) -> int:
            """Reserve the rows that fit; raise or clip on an overdraw.

            A claim of zero or less buys nothing and refunds nothing.
            Django's bound ``total_form_count`` is
            ``min(TOTAL_FORMS, absolute_max)`` with no lower clamp, so a
            forged negative ``TOTAL_FORMS`` reaches this method. An earlier
            version subtracted the full claim, so a negative claim grew the
            budget and cleared a recorded overdraw: 42 keys then bought
            8005 rows and cleaned as valid.
            """
            if count <= 0:
                return 0
            if count > self.remaining:
                if self.raises:
                    raise self.OverdrawError
                count = self.remaining
            self.remaining -= count
            return count

        @classmethod
        @contextmanager
        def open(
            cls, count: int, *, raises: bool = False
        ) -> Iterator[SequenceWidget.submission_countdown]:
            """Yield the shared budget, starting one when none is open.

            The first ``open()`` of an operation owns the budget: it
            fixes ``count`` and ``raises`` for everything beneath it,
            catches ``OverdrawError``, and releases the context variable. A
            nested ``open()`` yields the owner's budget unchanged, so an
            ``OverdrawError`` raised in its body flies through to the owner.
            """
            budget = cls.active.get(None)
            if budget is not None:
                yield budget
                return
            budget = cls(count, raises=raises)
            token = cls.active.set(budget)
            try:
                yield budget
            except cls.OverdrawError:
                budget.overflowed = True
            finally:
                cls.active.reset(token)

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState(CompositeWidget.RenderState):
        """Hold the formset that supplies one sequence render."""

        formset: BaseFormSet[BaseForm] | None = None
        submission_overflow: bool = False

    render_state: RenderState = RenderState()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = (
            Script(
                "nestingdolls/sequence.js",
                defer=True,
                id="nestingdolls-sequence",
                **{"hx-preserve": "true", "up-keep": "true"},
            ),
        )

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
        # Django's own add_prefix names the row value "<row>-value", apart from
        # the formset's "<row>-DELETE" control.
        row_form = type("Row", (Form,), {self.row_value_name: self.child_field})
        return formset_factory(
            row_form,
            formset=self.RowFormSet,
            extra=0,
            can_delete=True,
            min_num=self.limits.min_length,
            max_num=self.limits.max_length,
            absolute_max=self.limits.absolute_max,
            validate_min=False,
            validate_max=False,
        )  # type: ignore[return-value]

    def new_formset(
        self,
        *,
        data: Mapping[str, object] | None = None,
        files: MultiValueDict[str, UploadedFile[bytes]] | None = None,
        initial: Sequence[Mapping[str, object]] | None = None,
        prefix: str | None = None,
        auto_id: str | bool = "id_%s",
        error_class: type[ErrorList] = ErrorList,
        renderer: BaseRenderer | None = None,
        submission_total_form_count: int | None = None,
        error_messages: Mapping[str, str | Promise] | None = None,
    ) -> RowFormSet:
        """Build a row formset for this widget.

        submission_total_form_count avoids charging rows twice.
        Use a supplied error class and renderer from the parent form.
        """
        formset = self.formset_class(
            data=data,
            files=files,
            initial=initial,
            prefix=prefix,
            # django-stubs accepts only str. Django passes bool auto_id values to rows.
            auto_id=auto_id,  # type: ignore[arg-type]
            error_class=error_class,
            error_messages=error_messages,  # type: ignore[arg-type]  # Django accepts lazy messages.
        )
        if renderer is not None:
            formset.form_renderer = renderer
            formset.renderer = renderer
        formset.sequence_widget = self
        if submission_total_form_count is not None:
            formset.submission_total_form_count = submission_total_form_count
        return formset

    def exact_rows(self, values: list[object], name: str) -> dict[str, object]:
        """Expand exact rows to the prefixed keys their row widgets read."""
        child_widget = self.child_field.widget
        rows: dict[str, object] = {}
        for index, value in enumerate(islice(values, self.limits.absolute_max)):
            rows.update(
                self._exact_child_items(
                    child_widget, f"{name}-{index}-{self.row_value_name}", value
                )
            )
        return rows

    def data_from_exact_list(
        self, values: list[object], name: str
    ) -> dict[str, object]:
        """Expand exact rows to row keys, with management keys for the formset."""
        rows = self.exact_rows(values, name)
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
        if child_key in self.management_names:
            return True
        return self.row_index.match(child_key) is not None

    def is_control_key(self, key: str) -> bool:
        """Report whether a key under this sequence's name is a formset control.

        A control is a management key, a row delete key, or a control of a
        nested sequence. A row value that has no nested sequence has none.
        """
        if key in self.management_names:
            return True
        row = self.row_index.match(key)
        if row is None:
            return False
        rest = key[row.end() :]
        value_prefix = f"{self.row_value_name}-"
        child_widget = self.child_field.widget
        return rest == DELETION_FIELD_NAME or (
            isinstance(child_widget, (MappingWidget, SequenceWidget))
            and rest.startswith(value_prefix)
            and child_widget.is_control_key(rest[len(value_prefix) :])
        )

    def has_row_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether either source has a key for an indexed row.

        A row index is ASCII digits, then ``-`` or the end of the key. This
        reads every submitted key, so it uses a plain loop and a slice compare.
        Both cost less per key than ``any()`` and ``startswith()``.
        """
        prefix = f"{name}-"
        start = len(prefix)
        for source in (data, files):
            for key in source:
                if key[:start] == prefix and self.row_index.match(key, start):
                    return True
        return False

    def has_management_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether either source holds a formset management key."""
        return any(
            f"{name}-{field_name}" in source
            for source in (data, files)
            for field_name in self.management_names
        )

    def is_bound_formset(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether row or management keys bind the row formset.

        Indexed row keys always bind. Without them, an exact value under the
        field's own name blocks bare management keys.
        """
        if self.has_row_input(data, files, name):
            return True
        if name in data or name in files:
            return False
        return self.has_management_input(data, files, name)

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract the rows, within the shared row budget.

        Indexed row keys outrank an exact value under the field's own name.
        An exact value outranks management keys alone. A Django multi-value
        mapping gives an exact value through ``getlist``.
        """
        source: Mapping[str, object] | None
        if name in data:
            source = data
        elif name in files:
            source = files
        else:
            source = None
        # For exact input, SequenceBoundField already did this scan.
        # Do it again. Do not add a parameter for its result.
        # Custom SequenceWidget classes can override this public Django method
        # with three arguments. An added argument would break those classes.
        has_row_input = self.has_row_input(data, files, name)
        if (
            source is None
            and not has_row_input
            and not self.has_management_input(data, files, name)
        ):
            return []
        with self.submission_countdown.open(self.limits.submission_max) as countdown:
            if source is not None and not has_row_input:
                getlist = getattr(source, "getlist", None)
                values = source.get(name) if getlist is None else getlist(name)
                if isinstance(values, Collection) and not isinstance(
                    values, (Mapping, str, bytes, bytearray)
                ):
                    return list(islice(values, countdown.take(len(values))))
                return values
            # A hidden sequence posts every input as text, so a file child reads data.
            formset = self.new_formset(
                data=data,
                files=cast(
                    "MultiValueDict[str, UploadedFile[bytes]]",
                    data if self.is_hidden else files,
                ),
                prefix=name,
            )
            return [form[self.row_value_name].data for form in formset.forms]

    def initial_rows(self, value: Sequence[object] | None) -> list[dict[str, object]]:
        """Adapt public sequence values to the concrete row form's initial data."""
        return [{self.row_value_name: row} for row in value or ()]

    def default_initial_rows(
        self, value: Sequence[object] | None
    ) -> list[dict[str, object]]:
        """Return initial rows, or one placeholder row for an empty required sequence.

        A required sequence with ``min_length == 0`` must still show one
        row, so the user can give a value.
        """
        initial = self.initial_rows(value)
        if not initial and self.is_required and self.limits.min_length == 0:
            initial = [{self.row_value_name: None}]
        return initial

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, object] | None,
    ) -> dict[str, object]:
        """Render row forms inside one shared render budget."""
        with self.submission_countdown.open(self.limits.submission_max):
            context = super().get_context(name, value, attrs)
            widget_context: dict[str, object] = context["widget"]
            final_attrs: dict[str, object] = widget_context["attrs"]  # type: ignore[assignment]
            container_invalid = final_attrs.pop("aria-invalid", None)
            group_attrs: dict[str, object] = {}
            if FormLayout.current() is not FormLayout.div:
                # mapping/attrs.html skips a False value. The rows do not
                # repeat what the group holds.
                group_attrs = {
                    "role": "group",
                    "aria-invalid": container_invalid or False,
                    "aria-label": final_attrs.pop("aria-label", False),
                    "aria-labelledby": final_attrs.pop("aria-labelledby", False),
                    "aria-describedby": final_attrs.pop("aria-describedby", False),
                }
                container_invalid = None
            id_value = final_attrs.get("id")
            id_ = id_value if isinstance(id_value, str) else None
            disabled = bool(final_attrs.get("disabled"))
            if self.is_hidden and self.render_state.hidden_initial_value is not None:
                value = cast("Sequence[object]", self.render_state.hidden_initial_value)
            formset = self.render_state.formset or self.new_formset(
                initial=self.default_initial_rows(value), prefix=name
            )
            if self.render_state.hidden_initial_value is not None:
                # Hidden initial rows use the formset's default ID scheme.
                id_ = formset.auto_id % name
            management_form = formset.management_form
            if not self.is_hidden:
                management_form.fields[TOTAL_FORM_COUNT].widget.attrs[
                    "data-sequence-total"
                ] = ""

            help_text = self.child_field.help_text
            help_text_id = f"{id_}_rows_helptext" if id_ and help_text else None
            if help_text_id:
                described_by = final_attrs.get("aria-describedby")
                final_attrs["aria-describedby"] = (
                    f"{described_by} {help_text_id}" if described_by else help_text_id
                )

            forms = formset.forms
            if formset.is_bound:
                # A hidden render may precede outer validation. Clean once
                # before selecting rows so posted DELETE flags survive rebind.
                _ = formset.errors
            deleted_forms = {
                id(form)
                for form in forms
                if getattr(form, "cleaned_data", {}).get(DELETION_FIELD_NAME)
            }

            visible_forms = [
                (index, form)
                for index, form in enumerate(forms)
                if id(form) not in deleted_forms
            ]
            # The fieldset already refers to the field error list. When no
            # row has an error of its own, mark each row input invalid.
            rows_invalid = bool(container_invalid) and not any(
                form[self.row_value_name].errors for _index, form in visible_forms
            )
            rows = [
                self._row_context(
                    form, index, final_attrs, id_, mark_invalid=rows_invalid
                )
                for index, form in visible_forms
            ]
            # A hidden render has no <template> for the empty row.
            empty_row = (
                None
                if self.is_hidden
                else self._row_context(
                    formset.empty_form, "__prefix__", final_attrs, id_
                )
            )

            widget_context.update(
                {
                    "rows": rows,
                    "empty_row": empty_row,
                    "management_form": management_form,
                    # The script keeps this many rows. An optional sequence
                    # can lose every row, because it accepts an empty value.
                    "minimum_forms": (
                        self.limits.min_length if self.is_required else 0
                    ),
                    "maximum_forms": self.limits.max_length,
                    "absolute_maximum_forms": self.limits.absolute_max,
                    "disabled": disabled or self.render_state.submission_overflow,
                    "child_help_text": help_text,
                    "child_help_text_id": help_text_id,
                    "group_attrs": group_attrs,
                }
            )
            if deleted_forms and not self.render_state.submission_overflow:
                widget_context["deleted_rows"] = [
                    {"delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}"}
                    for form in forms
                    if id(form) in deleted_forms
                ]
            return context

    @staticmethod
    def _child_value(widget: Widget, value: object) -> object:
        """Decompress a string for a compound widget; malformed input renders blank."""
        if not isinstance(widget, MultiWidget) or not isinstance(value, str):
            return value
        try:
            return widget.decompress(value)
        except (AttributeError, TypeError, ValueError):
            # The child field still reports the row error.
            return None

    def _row_context(
        self,
        form: BaseForm,
        index: int | str,
        attrs: dict[str, object],
        id_: str | None,
        *,
        mark_invalid: bool = False,
    ) -> dict[str, object]:
        """Build the template context for one row form."""
        from nestingdolls.boundfield import CompositeBoundField  # noqa: PLC0415

        child_attrs = attrs.copy()
        if id_:
            child_attrs["id"] = f"{id_}_{index}"
        if self.child_field.disabled:
            child_attrs["disabled"] = True
        child = form[self.row_value_name]
        child_widget = self._child_widget(child.field)
        if isinstance(child, CompositeBoundField):
            if not isinstance(child_widget, CompositeWidget):
                raise TypeError("composite field must have a composite widget")
            child.prepare_widget(child_widget)
        if index == "__prefix__":
            child_value = None
        elif isinstance(child, CompositeBoundField):
            child_value = child.initial
        else:
            child_value = child.value()
        context = child_widget.get_context(
            child.html_name, self._child_value(child_widget, child_value), child_attrs
        )
        subwidget: dict[str, object] = context["widget"]
        errors = list(child.errors)
        row: dict[str, object] = {
            "index": index,
            "delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}",
            "errors": errors,
        }
        if errors:
            child_attrs = subwidget["attrs"]  # type: ignore[assignment]
            id_value = child_attrs.get("id")
            child_id = id_value if isinstance(id_value, str) else None
            # Use the form error class and renderer for row errors.
            # django-stubs excludes lazy translation promises that Django accepts.
            row["errors"] = form.error_class(
                errors,  # type: ignore[arg-type]
                renderer=form.renderer,
                field_id=child_id,
            )
            error_id = f"{child_id}_error" if child_id else None
            self._mark_row_invalid(child_widget, subwidget, error_id)
        elif mark_invalid:
            self._mark_row_invalid(child_widget, subwidget, None)
        # Render the marked context with the row form's renderer, as
        # Django's Widget._render does.
        row["widget_html"] = mark_safe(  # noqa: S308
            form.renderer.render(child_widget.template_name, context)  # type: ignore[arg-type]
        )
        return row

    def _mark_row_invalid(
        self, widget: Widget, widget_context: dict[str, object], error_id: str | None
    ) -> None:
        """Point every input of one row at that row's error list.

        A MultiWidget copies the parent attributes into each child context, so
        walk the tree and give each input the same row error reference. Mark
        an option only where Django gives options the widget attributes: a
        radio or checkbox option is an input, but a select option is not.
        """
        child_attrs: dict[str, object] = widget_context["attrs"]  # type: ignore[assignment]
        marked = [child_attrs]
        subwidgets: list[dict[str, object]] = widget_context.get("subwidgets", [])  # type: ignore[assignment]
        for child_widget, child_context in zip(
            getattr(widget, "widgets", ()), subwidgets, strict=False
        ):
            self._mark_row_invalid(child_widget, child_context, error_id)
        if getattr(widget, "option_inherits_attrs", False):
            optgroups = cast(
                "list[tuple[object, list[dict[str, dict[str, object]]], object]]",
                widget_context.get("optgroups", []),
            )
            marked += [
                option["attrs"]
                for _label, options, _index in optgroups
                for option in options
            ]
        for attrs in marked:
            attrs["aria-invalid"] = "true"
            if error_id:
                described_by = attrs.get("aria-describedby")
                attrs["aria-describedby"] = (
                    f"{described_by} {error_id}" if described_by else error_id
                )

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
