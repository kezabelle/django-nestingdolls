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


class CompositeWidget(Widget):
    class Keys:
        """Namespace the key operations shared by composite widgets."""

        __slots__ = ()

        @staticmethod
        def child_key(key: object, name: str) -> str | None:
            """Return the dash-prefixed child part of a composite key."""
            if not isinstance(key, str):
                return None
            prefix = f"{name}-"
            if not key.startswith(prefix):
                return None
            child_key = key.removeprefix(prefix)
            return child_key or None

        @staticmethod
        def values_for(data: Mapping[str, object], key: str) -> list[object]:
            """Read repeated values through Django's mapping protocol."""
            if key not in data:
                return []
            try:
                return list(data.getlist(key))  # type: ignore[attr-defined]
            except AttributeError:
                return [data.get(key)]

        def copy_values(
            self,
            result: MultiValueDict[str, object],
            data: Mapping[str, object],
            source: str,
            target: str,
        ) -> None:
            """Copy input values from one key to another."""
            result.setlist(target, self.values_for(data, source))

    @dataclasses.dataclass(frozen=True, slots=True)
    class Input:
        """Hold the canonical data and file values of one submission."""

        data: MultiValueDict[str, object]
        files: MultiValueDict[str, object]

    @dataclasses.dataclass(frozen=True, slots=True)
    class RenderState:
        """Hold the submitted state that one render of a composite widget needs."""

        hidden_initial_value: object = None

    _template_name: str
    input_type: str | None = None
    render_state: RenderState = RenderState()

    def read_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> Input:
        """Read one submission into this widget's canonical input cohort."""
        raise NotImplementedError

    def value_from_input(self, input: Input, name: str) -> object:
        """Extract this widget's value from a canonical input cohort."""
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

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Read once and extract the submitted composite value."""
        return self.value_from_input(self.read_input(data, files, name), name)

    def value_omitted_from_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether no supported composite input was submitted."""
        input = self.read_input(data, files, name)
        return not input.data and not input.files

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

    @dataclasses.dataclass(frozen=True)
    class Keys(CompositeWidget.Keys):
        """Normalize the declared child keys of one mapping field.

        It holds the child Form class and gets its names from an instance, so
        the names include fields that ``__init__`` adds. This dataclass has no
        ``slots``, because ``cached_property`` needs the instance dictionary.
        """

        form_class: type[BaseForm]

        @cached_property
        def names(self) -> tuple[str, ...]:
            """Return the declared child names of the child Form."""
            return tuple(self.form_class().fields)

        def canonical(self, key: object, name: str) -> str | None:
            """Return a canonical declared-child key, or ``None``."""
            child_key = self.child_key(key, name)
            if child_key is None:
                return None
            key = f"{name}-{child_key}"
            return (
                key
                if any(
                    key == f"{name}-{child_name}"
                    or key.startswith(f"{name}-{child_name}{separator}")
                    for child_name in self.names
                    for separator in ("_", "-")
                )
                else None
            )

    keys: Keys

    def configure(self, form_class: type[BaseForm]) -> None:
        """Store the configuration of the field that owns this widget.

        Django copies a widget before a field uses it, so the field calls this
        method on its own copy. This method makes a new key reader, because a
        key reader must read the child names of this Form class only.
        """
        self.form_class = form_class
        self.keys = self.Keys(form_class)

    @cached_property
    def fields(self) -> dict[str, Field]:
        """Return the fields of one instance of the child Form."""
        return self.form_class().fields

    def read_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> CompositeWidget.Input:
        """Canonicalize declared children in each input channel once."""

        def canonicalize(source: Mapping[str, object]) -> MultiValueDict[str, object]:
            result = MultiValueDict[str, object]()
            if name in source and isinstance(source.get(name), Mapping):
                value = source.get(name)
                assert isinstance(value, Mapping)
                for child_name in self.keys.names:
                    if child_name in value:
                        self.keys.copy_values(
                            result, value, child_name, f"{name}-{child_name}"
                        )
                return result
            for source_key in source:
                if (target := self.keys.canonical(source_key, name)) is None:
                    continue
                previous = result.getlist(target)
                self.keys.copy_values(result, source, source_key, target)
                if previous:
                    previous.extend(result.getlist(target))
                    result.setlist(target, previous)
            if not result and name in source:
                self.keys.copy_values(result, source, name, name)
            return result

        return self.Input(canonicalize(data), canonicalize(files))

    def value_from_input(self, input: CompositeWidget.Input, name: str) -> object:
        """Extract child values from canonical data and files."""
        if name in input.data:
            return input.data.get(name)
        if name in input.files and not input.data:
            return input.files.get(name)
        if not input.data and not input.files:
            return {}

        value: dict[str, object] = {}
        for child_name, field in self.fields.items():
            child_widget = self._child_widget(field)
            input_name = f"{name}-{child_name}"
            if isinstance(child_widget, CompositeWidget):
                child_input = child_widget.read_input(
                    input.data, input.files, input_name
                )
                if not child_input.data and not child_input.files:
                    continue
                value[child_name] = child_widget.value_from_input(
                    child_input, input_name
                )
            elif not child_widget.value_omitted_from_data(
                input.data,
                cast("MultiValueDict[str, UploadedFile[Any]]", input.files),
                input_name,
            ):
                value[child_name] = child_widget.value_from_datadict(
                    input.data,
                    cast("MultiValueDict[str, UploadedFile[Any]]", input.files),
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
        context["widget"].update(
            {
                "subform": subform,
                "visible_fields": subform.visible_fields(),
                "hidden_fields": (
                    [field.as_hidden() for field in subform]
                    if self.is_hidden
                    else subform.hidden_fields()
                ),
                "non_field_errors": (
                    (
                        [self.render_state.initial_error]
                        if self.render_state.initial_error
                        else []
                    )
                    + list(subform.non_field_errors())
                ),
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
        _submission_total_form_count: int

        def _construct_form(self, index: int, **kwargs: object) -> BaseForm:
            form = cast(BaseForm, super()._construct_form(index, **kwargs))  # type: ignore[misc]
            if form.empty_permitted and (
                any(
                    isinstance(key, str)
                    and (key == form.prefix or key.startswith(f"{form.prefix}-"))
                    and key != f"{form.prefix}-{DELETION_FIELD_NAME}"
                    for source in (self.data, self.files)
                    for key in source
                )
                or (
                    not form.is_multipart()
                    and any(
                        not field.required
                        for name, field in form.fields.items()
                        if name != DELETION_FIELD_NAME
                    )
                )
            ):
                form.empty_permitted = False
            return form

        def total_form_count(self) -> int:
            if hasattr(self, "_submission_total_form_count"):
                return self._submission_total_form_count
            total = super().total_form_count()
            with self.sequence_widget.submission_countdown(
                self.sequence_widget.limits.submission_max
            ) as countdown:
                allowed = countdown.take(total)
            self._submission_total_form_count = allowed
            return allowed

    @dataclasses.dataclass(frozen=True, slots=True)
    class Keys(CompositeWidget.Keys):
        """Accept only row keys a configured sequence can build.

        A nested sequence receives untrusted row indexes. This parser rejects
        indexes outside the formset hard cap and digit runs too long to name a
        permitted row before the widget copies them into its narrowed input.
        """

        absolute_max: int

        max_index_digits: ClassVar[int] = 7

        def __post_init__(self) -> None:
            if self.absolute_max >= 10**self.max_index_digits:
                raise ValueError("absolute_max must be less than 10000000")

        def canonical(self, key: object, name: str) -> str | None:
            """Return an accepted management or row key unchanged."""
            child_key = self.child_key(key, name)
            if child_key is None:
                return None
            key = f"{name}-{child_key}"
            if child_key in (
                TOTAL_FORM_COUNT,
                INITIAL_FORM_COUNT,
                MIN_NUM_FORM_COUNT,
                MAX_NUM_FORM_COUNT,
            ):
                return key
            end = 0
            while end < len(child_key) and "0" <= child_key[end] <= "9":
                end += 1
                if end > self.max_index_digits:
                    return None
            if end == 0 or (end < len(child_key) and child_key[end] not in "-_"):
                return None
            return key if int(child_key[:end]) < self.absolute_max else None

    @dataclasses.dataclass(slots=True)
    class submission_countdown:
        """Limit rows built by one recursively nested sequence extraction or render.

        Django limits request keys, files, and bytes before a form sees them, and a
        formset caps one level. A few nested ``TOTAL_FORMS`` keys can still multiply
        empty rows across sequence levels. This small context-local counter is only
        for that attacker-controlled recursive work. It is intentionally not a
        mapping or form-wide policy.
        """

        _current: ClassVar[ContextVar[tuple[int, bool] | None]] = ContextVar(
            "nestingdolls_submission_countdown", default=None
        )

        count: int
        _ran_out: bool = False
        _token: Token[tuple[int, bool] | None] | None = dataclasses.field(
            default=None, init=False, repr=False
        )

        def __bool__(self) -> bool:
            """Report whether this outer scope exceeded its shared allowance."""
            return self._ran_out

        def take(self, count: int) -> int:
            """Reserve the rows that fit in the active shared allowance."""
            state = self._current.get()
            assert state is not None, "submission_countdown must be active"
            remaining, ran_out = state
            allowed = min(count, remaining)
            self._current.set((remaining - allowed, ran_out or allowed < count))
            return allowed

        def __enter__(self) -> Self:
            """Start the counter at the outer sequence and reuse it inside rows."""
            if self._current.get() is None:
                self._token = self._current.set((self.count, False))
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            """Remember outer overflow and restore the preceding context."""
            if self._token is not None:
                state = self._current.get()
                assert state is not None, "submission_countdown must be active"
                self._ran_out = state[1]
                self._current.reset(self._token)

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
        self.keys = self.Keys(limits.absolute_max)
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

    def _new_formset(
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

    def read_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> CompositeWidget.Input:
        """Narrow both request channels to this sequence exactly once."""
        input_data = MultiValueDict[str, object]()
        input_files = MultiValueDict[str, object]()
        prefix = f"{name}-"
        has_flattened_rows = False
        has_formset_data = False

        for source, target in ((data, input_data), (files, input_files)):
            for key in source:
                if key == name:
                    self.keys.copy_values(target, source, key, key)
                    continue
                canonical = self.keys.canonical(key, name)
                if canonical is not None:
                    self.keys.copy_values(target, source, key, canonical)
                    has_formset_data = True
                if (
                    isinstance(key, str)
                    and len(key) > len(prefix)
                    and key.startswith(prefix)
                    and "0" <= key[len(prefix)] <= "9"
                ):
                    has_flattened_rows = True
                    has_formset_data = True

        if has_flattened_rows:
            input_data.pop(name, None)
            input_files.pop(name, None)
        if not has_formset_data:
            if self.keys.values_for(input_data, name) or self.keys.values_for(
                input_files, name
            ):
                return self.Input(input_data, input_files)
            return self.Input(MultiValueDict(), MultiValueDict())
        for field_name, value in (
            (MIN_NUM_FORM_COUNT, self.limits.min_length),
            (MAX_NUM_FORM_COUNT, self.limits.max_length),
        ):
            input_data[f"{name}-{field_name}"] = str(value)
        return self.Input(input_data, input_files)

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Read a whole sequence value or flattened browser rows once."""
        return self.value_from_input(self.read_input(data, files, name), name)

    def value_from_input(self, input: CompositeWidget.Input, name: str) -> list[object]:
        """Extract a whole sequence value or flattened formset rows."""
        unflattened_values = self.keys.values_for(input.data, name)
        if not unflattened_values:
            unflattened_values = self.keys.values_for(input.files, name)
        if unflattened_values:
            values = (
                unflattened_values[0]
                if len(unflattened_values) == 1
                and isinstance(unflattened_values[0], list)
                else unflattened_values
            )
            with self.submission_countdown(self.limits.submission_max) as countdown:
                return values[: countdown.take(len(values))]
        if not input.data and not input.files:
            return []
        formset = self._new_formset(
            data=input.data,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", input.files),
            prefix=name,
        )
        return [form["value"].data for form in formset.forms]

    def _initial_formset_rows(
        self, value: Sequence[object] | None
    ) -> list[dict[str, object]]:
        """Adapt public sequence values to the concrete row form's initial data."""
        return [{"value": row} for row in value or ()]

    def _empty_formset_row(self) -> dict[str, object]:
        return {"value": None}

    def _get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render row forms while keeping the established template context shape."""
        context = super().get_context(name, value, attrs)
        final_attrs = context["widget"]["attrs"]
        final_attrs.pop("aria-invalid", None)
        id_ = final_attrs.get("id")
        disabled = bool(final_attrs.get("disabled"))
        if self.is_hidden and self.render_state.hidden_initial_value is not None:
            value = cast(Sequence[object], self.render_state.hidden_initial_value)
        formset = self.render_state.formset
        if formset is None:
            initial = self._initial_formset_rows(value)
            if not initial and self.is_required and self.limits.min_length == 0:
                initial = [self._empty_formset_row()]
            formset = self._new_formset(initial=initial, prefix=name)

        if self.render_state.submission_overflow:
            formset = self._new_formset(initial=[], prefix=name)

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

        def make_row(form: BaseForm, index: int | str) -> dict[str, object]:
            child_attrs = final_attrs.copy()
            if id_:
                child_attrs["id"] = f"{id_}_{index}"
            if self.child_field.disabled:
                child_attrs["disabled"] = True
            from nestingdolls.boundfield import CompositeBoundField

            child = form["value"]
            child_widget = (
                child.field.hidden_widget()
                if self.input_type == "hidden"
                else child.field.widget
            )
            if isinstance(child, CompositeBoundField):
                child._prepare_widget(cast(CompositeWidget, child_widget), False)
            child_value = (
                None
                if index == "__prefix__"
                else child.initial
                if isinstance(child, CompositeBoundField)
                else child.value()
            )
            if isinstance(child_widget, MultiWidget) and isinstance(child_value, str):
                child_value = None
            subwidget = child_widget.get_context(
                child.html_name, child_value, child_attrs
            )["widget"]
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

        try:
            rows = [
                make_row(form, index)
                for index, form in enumerate(forms)
                if id(form) not in deleted_forms
            ]
            empty_row = make_row(formset.empty_form, "__prefix__")
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

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Keep nested row construction inside one shared render budget."""
        with self.submission_countdown(self.limits.submission_max):
            return self._get_context(name, value, attrs)

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
