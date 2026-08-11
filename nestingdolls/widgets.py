from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, BaseFormSet, Field
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DEFAULT_MIN_NUM,
    DELETION_FIELD_NAME,
    TOTAL_FORM_COUNT,
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
        """Hold static parsing configuration for one composite widget."""

        __slots__ = ()

        @staticmethod
        def _split(key: object, name: str) -> tuple[str, str] | None:
            """Split Django's dash-prefixed child grammar."""
            if not isinstance(key, str):
                return None
            prefix = f"{name}-"
            if not key.startswith(prefix):
                return None
            remainder = key.removeprefix(prefix)
            return (remainder, "") if remainder else None

        @staticmethod
        def _values(data: Mapping[str, object], key: str) -> list[object]:
            """Read repeated values through Django's mapping protocol."""
            if key not in data:
                return []
            try:
                return list(data.getlist(key))  # type: ignore[attr-defined]
            except AttributeError:
                return [data.get(key)]

        @staticmethod
        def _copy_key(
            result: MultiValueDict[str, object],
            data: Mapping[str, object],
            source: str,
            target: str,
        ) -> None:
            """Copy one key without depending on its concrete mapping type."""
            result.setlist(target, CompositeWidget.Keys._values(data, source))

    @dataclasses.dataclass(frozen=True, slots=True)
    class Input:
        """Hold the canonical data and file values of one submission."""

        data: MultiValueDict[str, object]
        files: MultiValueDict[str, object]

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bound:
        """Hold the submitted state that one render of a composite widget needs."""

        hidden_initial_value: object = None

    _template_name: str
    input_type: str | None = None
    keys: Keys
    bound: Bound = Bound()

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

    @property
    def media(self) -> WidgetMedia:
        """Merge every ``class Media`` in the MRO and the children's media."""
        media = WidgetMedia()
        for klass in reversed(type(self).__mro__):
            if (definition := klass.__dict__.get("Media")) is not None:
                media += WidgetMedia(definition)
        return media + self._child_media()

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
    class Bound(CompositeWidget.Bound):
        """Hold the child Form that one render of a mapping widget needs.

        The bound field builds the child Form, because only the bound field
        holds the data that the browser sent and the errors of that Form. A
        render that gets no child Form builds a new one from the value that it
        gets.
        """

        subform: BaseForm | None = None

    bound: Bound = Bound()

    @dataclasses.dataclass(frozen=True)
    class Keys(CompositeWidget.Keys):
        """Read the input keys of one mapping field as child keys.

        Every child of a mapping has a declared name. This object changes each
        accepted key format into one canonical child key. It drops a key that
        no child declares. It holds the child Form class, and it reads the
        child names from an instance of that class, so the names contain the
        fields that ``__init__`` adds. This dataclass has no ``slots``, because
        ``cached_property`` needs the instance dictionary.
        """

        form_class: type[BaseForm]

        @cached_property
        def names(self) -> tuple[str, ...]:
            """Return the declared child names of the child Form."""
            return tuple(self.form_class().fields)

        def canonical(self, key: object, name: str) -> str | None:
            """Return the canonical declared-child key, or ``None``."""
            if (child_key := self._split(key, name)) is None:
                return None
            token, suffix = child_key
            key = f"{name}-{token}{suffix}"
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

    def __init__(
        self,
        form_class: type[BaseForm] | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store the child Form class that this widget renders.

        A field can supply the widget class only. Django then builds the widget
        with no Form class, and the field configures that copy.
        """
        if form_class is not None:
            self.configure(form_class)
        super().__init__(dict(attrs) if attrs is not None else None)

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
                        self.keys._copy_key(
                            result, value, child_name, f"{name}-{child_name}"
                        )
                return result
            for source_key in source:
                if (target := self.keys.canonical(source_key, name)) is None:
                    continue
                previous = result.getlist(target)
                self.keys._copy_key(result, source, source_key, target)
                if previous:
                    previous.extend(result.getlist(target))
                    result.setlist(target, previous)
            if not result and name in source:
                self.keys._copy_key(result, source, name, name)
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
        subform = self.bound.subform
        if subform is None:
            # A hidden initial render must show the initial value, because
            # change detection compares it with the value that the browser
            # sent.
            if self.bound.hidden_initial_value is not None:
                value = self.bound.hidden_initial_value
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
                "non_field_errors": subform.non_field_errors(),
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
    formset_class: type[BaseFormSet[Any]]

    @dataclasses.dataclass(slots=True)
    class SubmissionCountdown:
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
            assert state is not None, "SubmissionCountdown must be active"
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
                assert state is not None, "SubmissionCountdown must be active"
                self._ran_out = state[1]
                self._current.reset(self._token)

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bound(CompositeWidget.Bound):
        """Hold the formset that supplies one sequence render."""

        formset: BaseFormSet[Any] | None = None
        submission_overflow: bool = False

    bound: Bound = Bound()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = ("nestingdolls/sequence.js",)

    @dataclasses.dataclass(frozen=True, slots=True)
    class Input(CompositeWidget.Input):
        """Hold narrowed sequence input and an optional direct Python value."""

        direct_rows: list[object] | None

    def __init__(
        self,
        child_field: Field | None = None,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store the child widget and its row limits."""
        from nestingdolls.fields import SequenceField

        self.limits = SequenceField.Limits.build(min_length, max_length, absolute_max)
        if child_field is not None:
            self.child_field = child_field
        super().__init__(dict(attrs) if attrs is not None else None)

    def configure(
        self,
        child_field: Field,
        limits: SequenceField.Limits,
        formset_class: type[BaseFormSet[Any]],
    ) -> None:
        """Store the configuration of this field's private widget copy."""
        self.child_field = child_field
        self.limits = limits
        self.formset_class = formset_class

    def read_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> Input:
        """Narrow both request channels to this sequence exactly once."""
        input_data = MultiValueDict[str, object]()
        input_files = MultiValueDict[str, object]()
        prefix = f"{name}-"

        for source, target in ((data, input_data), (files, input_files)):
            for key in source:
                if key == name or (isinstance(key, str) and key.startswith(prefix)):
                    self.Keys._copy_key(target, source, key, key)

        def direct_rows(source: Mapping[str, object]) -> list[object] | None:
            values = self.Keys._values(source, name)
            if not values:
                return None
            return (
                values[0]
                if len(values) == 1 and isinstance(values[0], list)
                else values
            )

        data_direct = direct_rows(data)
        file_direct = direct_rows(files)
        has_row_values = any(
            isinstance(key, str)
            and key.startswith(prefix)
            and key.removeprefix(prefix)
            and "0" <= key.removeprefix(prefix)[0] <= "9"
            for source in (data, files)
            for key in source
        )
        if data_direct is not None and not has_row_values:
            return self.Input(input_data, input_files, data_direct)
        if file_direct is not None and not has_row_values:
            return self.Input(input_data, input_files, file_direct)
        management_names = {
            "TOTAL_FORMS",
            "INITIAL_FORMS",
            "MIN_NUM_FORMS",
            "MAX_NUM_FORMS",
        }
        has_formset_data = any(
            isinstance(key, str)
            and key.startswith(prefix)
            and (
                key.removeprefix(prefix) in management_names
                or (
                    key.removeprefix(prefix)
                    and "0" <= key.removeprefix(prefix)[0] <= "9"
                )
            )
            for source in (data, files)
            for key in source
        )
        if not has_formset_data:
            return self.Input(MultiValueDict(), MultiValueDict(), None)
        for field_name, value in (
            ("MIN_NUM_FORMS", self.limits.min_length),
            ("MAX_NUM_FORMS", self.limits.max_length),
        ):
            input_data.setlist(f"{name}-{field_name}", [str(value)])
        return self.Input(input_data, input_files, None)

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Read once and extract a standalone direct sequence submission."""
        return self.value_from_input(self.read_input(data, files, name), name)

    def value_from_input(self, input: CompositeWidget.Input, name: str) -> list[object]:
        """Extract direct rows or flattened initial rows from the row formset."""
        assert isinstance(input, self.Input), (
            "SequenceWidget requires SequenceWidget.Input"
        )
        if input.direct_rows is not None:
            with self.SubmissionCountdown(self.limits.submission_max) as countdown:
                return input.direct_rows[: countdown.take(len(input.direct_rows))]
        if not input.data and not input.files:
            return []
        formset = self.formset_class(
            data=input.data,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", input.files),
            prefix=name,
        )
        values: list[object] = []
        for form in formset.forms:
            if "value" in form.fields:
                values.append(form["value"].data)
            else:
                values.append(
                    {field_name: form[field_name].data for field_name in form.fields}
                )
        return values

    def _initial_formset_rows(
        self, value: Sequence[object] | None
    ) -> list[dict[str, object]]:
        """Adapt public sequence values to the concrete row form's initial data."""
        values = [] if value is None else list(value)
        from nestingdolls.fields import MappingField

        if isinstance(self.child_field, MappingField):
            return [dict(row) if isinstance(row, Mapping) else {} for row in values]
        return [{"value": row} for row in values]

    def _empty_formset_row(self) -> dict[str, object]:
        from nestingdolls.fields import MappingField

        return {} if isinstance(self.child_field, MappingField) else {"value": None}

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
        if self.is_hidden and self.bound.hidden_initial_value is not None:
            value = cast(Sequence[object], self.bound.hidden_initial_value)
        formset = self.bound.formset
        if formset is None:
            initial = self._initial_formset_rows(value)
            if not initial and self.is_required and self.limits.min_length == 0:
                initial = [self._empty_formset_row()]
            formset = self.formset_class(initial=initial, prefix=name)

        if self.bound.submission_overflow:
            formset = self.formset_class(initial=[], prefix=name)

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

            if "value" in form.fields:
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
                if isinstance(child_widget, MultiWidget) and isinstance(
                    child_value, str
                ):
                    child_value = None
                subwidget = child_widget.get_context(
                    child.html_name, child_value, child_attrs
                )["widget"]
                errors = (
                    [str(self.child_field.error_messages["invalid"])]
                    if index in getattr(formset, "invalid_mapping_rows", frozenset())
                    else [
                        message
                        for error in form.errors.as_data().get("value", [])
                        for message in error.messages
                    ]
                )
            else:
                child_widget = self._child_widget(self.child_field)
                assert isinstance(child_widget, MappingWidget)
                child_widget.bound = child_widget.Bound(subform=form)
                subwidget = child_widget.get_context(
                    cast(str, form.prefix), form.initial, child_attrs
                )["widget"]
                errors = (
                    [str(self.child_field.error_messages["invalid"])]
                    if index in getattr(formset, "invalid_mapping_rows", frozenset())
                    else [str(error) for error in form.non_field_errors()]
                )
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
            if isinstance(child_widget, MappingWidget):
                child_widget.bound = child_widget.Bound()

        context["widget"].update(
            {
                "rows": rows,
                "empty_row": empty_row,
                "management_form": management_form,
                "minimum_forms": self.limits.min_length,
                "maximum_forms": self.limits.max_length,
                "absolute_maximum_forms": self.limits.absolute_max,
                "disabled": disabled or self.bound.submission_overflow,
            }
        )
        if deleted_forms and not self.bound.submission_overflow:
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
        with self.SubmissionCountdown(self.limits.submission_max):
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
