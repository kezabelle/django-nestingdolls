from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from django.core.files.uploadedfile import UploadedFile
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
    from nestingdolls.fields import SequenceField


_MANAGEMENT_NAMES = (
    TOTAL_FORM_COUNT,
    INITIAL_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
)


def _getlist(data: Mapping[str, object], key: str) -> list[object]:
    """Read repeated values through Django's mapping protocol."""
    if key not in data:
        return []
    getlist = getattr(data, "getlist", None)
    if getlist is None:
        return [data[key]]
    return cast("list[object]", list(getlist(key)))


class CompositeWidget(Widget):
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
        """Report whether no supported composite input was submitted."""
        return not any(
            self._accepts_key(key, name) for source in (data, files) for key in source
        )

    def use_required_attribute(self, initial: object) -> bool:
        return False

    def id_for_label(self, id_: str) -> str:
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

    def configure(self, form_class: type[BaseForm]) -> None:
        """Store the configuration of the field that owns this widget.

        Django copies a widget before a field uses it, so the field calls this
        method on its own copy.
        """
        self.form_class = form_class

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

    def _data_from_whole_value(
        self, value: Mapping[str, object], name: str
    ) -> MultiValueDict[str, object]:
        """Give each member of a whole mapping value its own child key.

        Every composite child already reads a value under its own exact key
        as a whole value, so one expansion makes a whole-value submission bind
        exactly like a browser submission. ``getlist`` semantics survive, so
        repeated values still reach child widgets that consume all of them.
        """
        expanded = MultiValueDict[str, object]()
        for child_name in self.fields:
            if child_name in value:
                expanded.setlist(f"{name}-{child_name}", _getlist(value, child_name))
        return expanded

    def expand_whole_values(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Return the data and the files with whole values expanded to child keys."""
        data_value = data.get(name) if name in data else None
        if isinstance(data_value, Mapping):
            data = self._data_from_whole_value(data_value, name)
        files_value = files.get(name) if name in files else None
        if isinstance(files_value, Mapping):
            files = self._data_from_whole_value(files_value, name)
        return data, files

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values, or return an unreadable whole value as it is."""
        data, files = self.expand_whole_values(data, files, name)
        data_submitted = self.has_child_keys(data, name)
        if not data_submitted and name in data:
            # A scalar under the exact name has no children to distribute.
            # Return it, so that to_python() reports the "invalid" error.
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
                cast("MultiValueDict[str, UploadedFile[Any]]", files),
                input_name,
            ):
                continue
            value[child_name] = child_widget.value_from_datadict(
                data,
                cast("MultiValueDict[str, UploadedFile[Any]]", files),
                input_name,
            )
        return value

    def get_context(
        self, name: str, value: object, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build the context of the widget, with a prefixed child Form.

        The bound field supplies the child Form when the outer form is bound.
        An unbound render gets no Form, and it builds one from the value that it
        gets. The shared budget covers sequence descendants because Django
        bounds each formset level, not aggregate nested rows.
        """
        context = super().get_context(name, value, attrs)
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
        context["widget"].update(
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
    child_field: Field
    limits: SequenceField.Limits

    class RowForm(Form):
        """Wrap one child field without changing its visible key."""

        def add_prefix(self, field_name: str) -> str:
            if field_name == "value" and self.prefix:
                return self.prefix
            return super().add_prefix(field_name)

    class RowFormSet(BaseFormSet):  # type: ignore[type-arg]
        """Build rows with the owning sequence widget's shared budget."""

        sequence_widget: SequenceWidget
        submission_total_form_count: int

        def _construct_form(self, index: int, **kwargs: object) -> BaseForm:
            form = cast(BaseForm, super()._construct_form(index, **kwargs))  # type: ignore[misc]
            if form.empty_permitted and self.row_carries_submitted_value(form.prefix):
                form.empty_permitted = False
            return form

        def row_carries_submitted_value(self, prefix: str | None) -> bool:
            """Report whether the browser sent a non-blank value for this row.

            Check keys under the row's own prefix. Skip the row's own
            delete key. A rendered row always sends that key, checked or
            not. Its presence alone does not show real content.

            A rendered row also always sends its other keys, even when
            the user left them blank. A blank value is not real content
            either. Only a non-blank value shows that the user put real
            data in this row. ``Form.has_changed()`` must not skip a row
            with real data.
            """
            delete_key = f"{prefix}-{DELETION_FIELD_NAME}"
            for source in (self.data, self.files):
                for key in source:
                    if not isinstance(key, str):
                        continue
                    is_row_key = key == prefix or key.startswith(f"{prefix}-")
                    is_delete_key = key == delete_key
                    if not is_row_key or is_delete_key:
                        continue
                    values = _getlist(source, key)
                    has_non_blank_value = any(
                        value not in (None, "") for value in values
                    )
                    if has_non_blank_value:
                        return True
            return False

        def total_form_count(self) -> int:
            if hasattr(self, "submission_total_form_count"):
                return self.submission_total_form_count
            total = super().total_form_count()
            with self.sequence_widget.submission_countdown(
                self.sequence_widget.limits.submission_max
            ) as countdown:
                allowed = countdown.take(total)
            self.submission_total_form_count = allowed
            return allowed

    @dataclasses.dataclass(slots=True)
    class submission_countdown:
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
        """

        remaining: ClassVar[ContextVar[int | None]] = ContextVar(
            "nestingdolls_submission_countdown", default=None
        )

        count: int
        ran_out: bool = False
        token: Token[int | None] | None = dataclasses.field(
            default=None, init=False, repr=False
        )

        def __bool__(self) -> bool:
            """Report whether this outer scope exceeded its shared allowance."""
            return self.ran_out

        def take(self, count: int) -> int:
            """Reserve the rows that fit in the active shared allowance.

            Subtract the full requested count, not only the allowed part.
            A negative remaining value then marks that the budget ran out.
            Clamp the return value at zero: a caller must never build a
            negative number of rows.
            """
            left = self.remaining.get()
            assert left is not None, "submission_countdown must be active"
            allowed = max(0, min(count, left))
            self.remaining.set(left - count)
            return allowed

        def __enter__(self) -> Self:
            """Start the counter at the outer sequence and reuse it inside rows."""
            if self.remaining.get() is None:
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
            the owning scope, that value is ``None``. A read after the
            reset would see that old value, not the final state. The
            assertion below would then fail.

            A scope that does not own the token must not call reset.
            That scope did not open the shared context. It has no old
            value to put back. A reset with a token it did not receive
            would damage the owning scope's context.
            """
            left = self.remaining.get()
            assert left is not None, "submission_countdown must be active"
            self.ran_out = left < 0
            if self.token is not None:
                self.remaining.reset(self.token)

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState(CompositeWidget.RenderState):
        """Hold the formset that supplies one sequence render."""

        formset: BaseFormSet[Any] | None = None
        submission_overflow: bool = False

    render_state: RenderState = RenderState()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = ("nestingdolls/sequence.js",)

    def configure(self, child_field: Field, limits: SequenceField.Limits) -> None:
        """Store the configuration of this field's private widget copy."""
        self.child_field = child_field
        self.limits = limits
        self.__dict__.pop("formset_class", None)

    @cached_property
    def formset_class(self) -> type[RowFormSet]:
        """Build the row formset class from this widget's child and limits."""
        row_form = type("Row", (self.RowForm,), {"value": self.child_field})
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
        files: MultiValueDict[str, UploadedFile[Any]] | None = None,
        initial: Sequence[Mapping[str, object]] | None = None,
        prefix: str | None = None,
        auto_id: str = "id_%s",
        form_kwargs: dict[str, object] | None = None,
    ) -> RowFormSet:
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

    def data_from_whole_value(
        self, values: Sequence[object], name: str
    ) -> MultiValueDict[str, object]:
        """Give each row of a whole value its own key.

        A whole value is one Python list under this field's own name. It
        carries no per-row prefixed keys. Build one key per row instead:
        ``f"{name}-{index}"``. Every composite child already reads a
        value under its own exact key as a whole value. A mapping or
        scalar row therefore binds the normal way from this point on.

        This lets the row formset bind for real, instead of staying
        unbound with only initial rows. A bound row formset can carry
        its own validation errors. An unbound row formset never can:
        Django gives an unbound form empty errors, always, on purpose.
        """
        rows = MultiValueDict[str, object]()
        for index, value in enumerate(values):
            rows.setlist(f"{name}-{index}", [value])
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
        if child_key in _MANAGEMENT_NAMES:
            return True
        return "0" <= child_key[0] <= "9"

    def has_row_keys(self, source: Mapping[str, object], name: str) -> bool:
        """Report whether one source holds any per-row prefixed key."""
        prefix = f"{name}-"
        return any(
            isinstance(key, str)
            and len(key) > len(prefix)
            and key.startswith(prefix)
            and "0" <= key[len(prefix)] <= "9"
            for key in source
        )

    def has_management_keys(self, source: Mapping[str, object], name: str) -> bool:
        """Report whether one source holds any formset management key."""
        return any(f"{name}-{field_name}" in source for field_name in _MANAGEMENT_NAMES)

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> list[object]:
        """Extract a whole value or bound formset rows.

        Row keys outrank a value under the field's own exact name, so a
        forged exact-name key cannot replace submitted rows. Without row
        keys, a whole value wins over management keys alone.
        """
        has_rows = self.has_row_keys(data, name) or self.has_row_keys(files, name)
        if not has_rows:
            whole_values = _getlist(data, name) or _getlist(files, name)
            if whole_values:
                values = (
                    whole_values[0]
                    if len(whole_values) == 1 and isinstance(whole_values[0], list)
                    else whole_values
                )
                with self.submission_countdown(self.limits.submission_max) as countdown:
                    return values[: countdown.take(len(values))]
            if not self.has_management_keys(data, name) and not (
                self.has_management_keys(files, name)
            ):
                return []
        formset = self.new_formset(
            data=data,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", files),
            prefix=name,
        )
        return [form["value"].data for form in formset.forms]

    def initial_rows(self, value: Sequence[object] | None) -> list[dict[str, object]]:
        """Adapt public sequence values to the concrete row form's initial data."""
        return [{"value": row} for row in value or ()]

    def empty_initial_row(self) -> dict[str, object]:
        return {"value": None}

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render row forms inside one shared render budget."""
        with self.submission_countdown(self.limits.submission_max):
            context = super().get_context(name, value, attrs)
            final_attrs = context["widget"]["attrs"]
            final_attrs.pop("aria-invalid", None)
            id_ = final_attrs.get("id")
            disabled = bool(final_attrs.get("disabled"))
            if self.is_hidden and self.render_state.hidden_initial_value is not None:
                value = cast(Sequence[object], self.render_state.hidden_initial_value)
            formset = self.render_state.formset
            if formset is None:
                initial = self.initial_rows(value)
                if not initial and self.is_required and self.limits.min_length == 0:
                    initial = [self.empty_initial_row()]
                formset = self.new_formset(initial=initial, prefix=name)

            if self.render_state.submission_overflow:
                formset = self.new_formset(initial=[], prefix=name)

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

            context["widget"].update(
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
                context["widget"]["deleted_rows"] = [
                    {"delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}"}
                    for form in forms
                    if id(form) in deleted_forms
                ]
            return context

    def _row_context(
        self,
        form: BaseForm,
        index: int | str,
        attrs: dict[str, Any],
        id_: str | None,
    ) -> dict[str, object]:
        """Build the template context for one row form."""
        from nestingdolls.boundfield import CompositeBoundField

        child_attrs = attrs.copy()
        if id_:
            child_attrs["id"] = f"{id_}_{index}"
        if self.child_field.disabled:
            child_attrs["disabled"] = True
        child = form["value"]
        child_widget = self._child_widget(child.field)
        if isinstance(child, CompositeBoundField):
            child.prepare_widget(cast(CompositeWidget, child_widget))
        child_value = (
            None
            if index == "__prefix__"
            else child.initial
            if isinstance(child, CompositeBoundField)
            else child.value()
        )
        if isinstance(child_widget, MultiWidget) and isinstance(child_value, str):
            child_value = None
        subwidget = child_widget.get_context(child.html_name, child_value, child_attrs)[
            "widget"
        ]
        errors = [
            message
            for error in form.errors.as_data().get("value", [])
            for message in error.messages
        ]
        row: dict[str, object] = {
            "index": index,
            "delete_name": f"{form.prefix}-{DELETION_FIELD_NAME}",
            "subwidget": subwidget,
            "errors": errors,
        }
        if errors:
            child_id = subwidget["attrs"].get("id")
            error_id = f"{child_id}_error" if child_id else None
            if error_id:
                row["error_id"] = error_id
            self._mark_row_invalid(subwidget, error_id)
        return row

    def _mark_row_invalid(
        self, widget_context: dict[str, Any], error_id: str | None
    ) -> None:
        """Point every input of one row at that row's error list.

        A MultiWidget copies the parent attributes into each child context, so
        walk the tree and give each input the same row error reference.
        """
        child_attrs = widget_context["attrs"]
        child_attrs["aria-invalid"] = "true"
        if error_id:
            described_by = child_attrs.get("aria-describedby")
            child_attrs["aria-describedby"] = (
                f"{described_by} {error_id}" if described_by else error_id
            )
        for child_context in widget_context.get("subwidgets", []):
            self._mark_row_invalid(child_context, error_id)

    @property
    def is_hidden(self) -> bool:
        """Report whether the child widget is hidden."""
        return super().is_hidden or bool(self.child_field.widget.is_hidden)

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Report whether the child widget needs multipart form data."""
        return bool(self.child_field.widget.needs_multipart_form)

    def _child_media(self) -> WidgetMedia:
        """Return the media of the widget that renders each row."""
        return cast(WidgetMedia, self.child_field.widget.media)
