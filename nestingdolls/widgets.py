from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from contextvars import ContextVar, Token
from itertools import islice
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, Field
from django.forms.fields import BooleanField
from django.forms.formsets import (
    DEFAULT_MAX_NUM,
    DEFAULT_MIN_NUM,
    DELETION_FIELD_NAME,
    INITIAL_FORM_COUNT,
    MAX_NUM_FORM_COUNT,
    MIN_NUM_FORM_COUNT,
    TOTAL_FORM_COUNT,
    ManagementForm,
)
from django.forms.widgets import Media as WidgetMedia
from django.forms.widgets import MultiWidget, Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property

from nestingdolls.errors import ItemValidationError
from nestingdolls.patches import FormLayout

if TYPE_CHECKING:
    from nestingdolls.fields import SequenceField

__all__ = ["MappingWidget", "SequenceWidget"]


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
    keys: Keys
    limits: SequenceField.Limits

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
        """Hold the submitted rows that one render of a sequence widget needs.

        ``management_data`` holds the submitted management inputs. These
        inputs limit how many rows to render. ``management_form`` is the
        form the bound field already built from that input, so one
        render parses it only once. ``item_errors`` holds every item
        error of this field, at any nesting depth. ``item_depth`` is how
        many item-path steps a render already used, so a nested sequence
        reads its own step next. ``deleted_indexes`` holds the rows the
        user deleted.
        """

        management_input: MultiValueDict[str, object] | None = None
        management_form: ManagementForm | None = None
        item_errors: Sequence[ItemValidationError] = ()
        item_depth: int = 0
        deleted_indexes: Collection[int] = frozenset()
        submission_overflow: bool = False

    bound: Bound = Bound()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = ("nestingdolls/sequence.js",)

    deletion_field: ClassVar[BooleanField] = BooleanField(required=False)

    def deleted_row_indexes(
        self, data: Mapping[str, object], name: str, row_count: int
    ) -> frozenset[int]:
        """Return the index of each row in this widget marked for deletion."""
        return frozenset(
            index
            for index in range(row_count)
            if self.deletion_field.to_python(
                data.get(f"{name}-{index}-{DELETION_FIELD_NAME}")
            )
        )

    @dataclasses.dataclass(frozen=True, slots=True)
    class Input(CompositeWidget.Input):
        """Hold one complete, parsed sequence submission."""

        management_form: ManagementForm | None
        direct_rows: list[object] | None
        data_rows: list[MultiValueDict[str, object]]
        file_rows: list[MultiValueDict[str, object]]

    @dataclasses.dataclass(frozen=True)
    class Keys(CompositeWidget.Keys):
        """Hold the bounded dash-index parser for one sequence widget."""

        absolute_max: int
        max_index_digits: ClassVar[int] = 7

        def __post_init__(self) -> None:
            addressable = 10**self.max_index_digits
            if self.absolute_max >= addressable:
                raise ValueError(f"absolute_max must be below {addressable}")

        def parsed(self, key: object, name: str) -> tuple[str, int] | None:
            """Parse a dash-indexed key before applying its row bound."""
            if (child_key := self._split(key, name)) is None:
                return None
            token, suffix = child_key
            index_end = 0
            while index_end < len(token) and "0" <= token[index_end] <= "9":
                index_end += 1
            if not index_end:
                return None
            digits = token[:index_end]
            if len(digits) > self.max_index_digits:
                return None
            digits = digits.lstrip("0")
            index = int(digits) if digits else 0
            suffix = token[index_end:] + suffix
            if suffix and suffix[0] not in ("_", "-"):
                return None
            return f"{name}-{index}{suffix}", index

        def canonical(self, key: object, name: str) -> tuple[str, int] | None:
            """Return one in-range canonical row key, or ``None``."""
            if (row_key := self.parsed(key, name)) is None:
                return None
            return row_key if row_key[1] < self.absolute_max else None

    def __init__(
        self,
        child_field: Field | None = None,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Store the settings of the child widget for a sequence field.

        A field can supply the widget class only. Django then builds the widget
        with no child field, and the field configures that copy.
        """
        from nestingdolls.fields import SequenceField

        self.limits = SequenceField.Limits.build(min_length, max_length, absolute_max)
        self.keys = self.Keys(self.limits.absolute_max)
        if child_field is not None:
            self.child_field = child_field
        super().__init__(dict(attrs) if attrs is not None else None)

    def configure(self, child_field: Field, limits: SequenceField.Limits) -> None:
        """Store the configuration of the field that owns this widget.

        Django copies a widget before a field uses it, so the field calls this
        method on its own copy. This method makes a new key reader, because a
        key reader must hold the row limit of this field only.
        """
        self.child_field = child_field
        self.limits = limits
        self.keys = self.Keys(limits.absolute_max)

    def _management_form_data(
        self, input_data: MultiValueDict[str, object], name: str
    ) -> MultiValueDict[str, object]:
        """Build Django's management input from data-channel controls only."""
        result = MultiValueDict[str, object]()
        for field_name in (TOTAL_FORM_COUNT, INITIAL_FORM_COUNT):
            key = f"{name}-{field_name}"
            if key in input_data:
                self.keys._copy_key(result, input_data, key, key)
        result[f"{name}-{MIN_NUM_FORM_COUNT}"] = str(self.limits.min_length)
        result[f"{name}-{MAX_NUM_FORM_COUNT}"] = str(self.limits.max_length)
        return result

    def read_input(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> Input:
        """Parse canonical channels, management state, and row buckets once.

        Reserve this call's rows against the shared recursive-nesting budget
        before building them. This is the earliest point one call can turn a
        submitted row count into unbounded work.
        """
        input_data = MultiValueDict[str, object]()
        input_files = MultiValueDict[str, object]()

        def direct_rows(source: Mapping[str, object]) -> list[object] | None:
            values = self.keys._values(source, name)
            if not values:
                return None
            return (
                values[0]
                if len(values) == 1 and isinstance(values[0], list)
                else values
            )

        data_direct = direct_rows(data)
        file_direct = direct_rows(files)
        data_keys: list[tuple[str, int, str]] = []
        file_keys: list[tuple[str, int, str]] = []
        indexed = False

        for field_name in (TOTAL_FORM_COUNT, INITIAL_FORM_COUNT):
            key = f"{name}-{field_name}"
            if key in data:
                self.keys._copy_key(input_data, data, key, key)
        for source, result, collected in (
            (data, input_data, data_keys),
            (files, input_files, file_keys),
        ):
            for source_key in source:
                if self.keys.parsed(source_key, name) is not None:
                    indexed = True
                if (row_key := self.keys.canonical(source_key, name)) is None:
                    continue
                canonical_key, index = row_key
                self.keys._copy_key(result, source, source_key, canonical_key)
                collected.append((canonical_key, index, source_key))

        has_management = any(
            f"{name}-{field_name}" in input_data
            for field_name in (TOTAL_FORM_COUNT, INITIAL_FORM_COUNT)
        )
        if not indexed and data_direct is not None:
            self.keys._copy_key(input_data, data, name, name)
            return self.Input(input_data, input_files, None, data_direct, [], [])
        if not indexed and file_direct is not None:
            self.keys._copy_key(input_files, files, name, name)
            return self.Input(input_data, input_files, None, file_direct, [], [])
        if not indexed and not has_management:
            return self.Input(input_data, input_files, None, None, [], [])

        management_form = ManagementForm(
            self._management_form_data(input_data, name), prefix=name
        )
        management_form.full_clean()
        if not management_form.is_valid():
            return self.Input(input_data, input_files, management_form, None, [], [])
        total = management_form.cleaned_data[TOTAL_FORM_COUNT]
        if not isinstance(total, int) or total < 0 or total > self.limits.absolute_max:
            return self.Input(input_data, input_files, management_form, None, [], [])
        # Entering the countdown reserves these rows: it starts one here if
        # none is active yet, or spends the one this call already inherited.
        with self.SubmissionCountdown(self.limits.submission_max) as countdown:
            allowed = countdown.take(total)
        data_rows = [MultiValueDict[str, object]() for _ in range(allowed)]
        file_rows = [MultiValueDict[str, object]() for _ in range(allowed)]
        for source, collected, rows in (
            (data, data_keys, data_rows),
            (files, file_keys, file_rows),
        ):
            for canonical_key, index, source_key in collected:
                if index < allowed:
                    self.keys._copy_key(rows[index], source, source_key, canonical_key)
        return self.Input(
            input_data, input_files, management_form, None, data_rows, file_rows
        )

    def value_from_datadict(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Read once and extract a standalone sequence submission."""
        return self.value_from_input(self.read_input(data, files, name), name)

    def value_from_input(self, input: CompositeWidget.Input, name: str) -> list[object]:
        """Extract rows under an active sequence scope, creating a root if needed."""
        assert isinstance(input, self.Input), (
            "SequenceWidget requires SequenceWidget.Input"
        )
        # This call takes nothing itself. It only makes sure one countdown
        # is active, so read_input() and _value_from_input() below can
        # take() from it. A standalone call starts the root scope here; a
        # nested call joins the scope its caller already opened.
        with self.SubmissionCountdown(self.limits.submission_max):
            return self._value_from_input(input, name)

    def _value_from_input(self, input: Input, name: str) -> list[object]:
        """Extract rows from a parsed sequence cohort under the active budget."""
        if input.direct_rows is not None:
            return input.direct_rows[
                : self.SubmissionCountdown(self.limits.submission_max).take(
                    len(input.direct_rows)
                )
            ]
        if input.management_form is None or not input.management_form.is_valid():
            return []
        child_widget = self._child_widget(self.child_field)
        # read_input() already reserved these rows against the shared
        # countdown when it built data_rows/file_rows. Inherit that count
        # instead of spending the budget a second time.
        allowed = len(input.data_rows)
        rows: list[object] = []
        for index in range(allowed):
            row_name = f"{name}-{index}"
            if isinstance(child_widget, CompositeWidget):
                child_input = child_widget.read_input(
                    input.data_rows[index], input.file_rows[index], row_name
                )
                rows.append(child_widget.value_from_input(child_input, row_name))
            else:
                rows.append(
                    child_widget.value_from_datadict(
                        input.data_rows[index],
                        cast(
                            "MultiValueDict[str, UploadedFile[Any]]",
                            input.file_rows[index],
                        ),
                        row_name,
                    )
                )
        return rows

    def get_context(
        self,
        name: str,
        value: Sequence[object] | None,
        attrs: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render only rows admitted by the shared aggregate budget.

        Django limits parser input and individual formsets, not aggregate nested
        row work. The scope's lazy maximum reuses parent allowance without a
        field-tree walk; rendering clips rather than raising on exhaustion.
        """
        with self.SubmissionCountdown(self.limits.submission_max) as countdown:
            context = super().get_context(name, value, attrs)
            child_widget = self._child_widget(self.child_field)
            if self.is_localized:
                # Sticky by design. The child widget belongs to this field
                # alone. is_localized comes from the field's own
                # `localize` value. SequenceField.__init__ sets that value
                # once.
                child_widget.is_localized = True

            final_attrs = context["widget"]["attrs"]
            # The error state of the outer field must not go on every input. Each
            # row gets its own marker in _mark_row_invalid().
            final_attrs.pop("aria-invalid", None)
            id_ = final_attrs.get("id")
            disabled = bool(final_attrs.get("disabled"))

            bound_management_input = self.bound.management_input
            if self.bound.submission_overflow:
                # A rejected aggregate submission must not pay to render itself again.
                value = None
                bound_management_input = None
            elif self.bound.hidden_initial_value is not None:
                value = cast(Sequence[object] | None, self.bound.hidden_initial_value)
            value = (
                [] if value is None else list(islice(value, self.limits.absolute_max))
            )
            management_form = self.bound.management_form
            if bound_management_input is not None and management_form is not None:
                management_invalid = not management_form.is_valid()
                if management_invalid:
                    value = []
                else:
                    total_forms = cast(
                        int, management_form.cleaned_data[TOTAL_FORM_COUNT]
                    )
                    value = value[: max(0, min(total_forms, self.limits.absolute_max))]
            else:
                initial_forms = len(value)
                if not value:
                    value = [None] * self.limits.empty_count(self.is_required)
                management_form = ManagementForm(
                    prefix=name,
                    initial={
                        TOTAL_FORM_COUNT: len(value),
                        INITIAL_FORM_COUNT: initial_forms,
                        MIN_NUM_FORM_COUNT: self.limits.min_length,
                        MAX_NUM_FORM_COUNT: self.limits.max_length,
                    },
                )
                management_invalid = False
            if not self.is_hidden:
                # The browser script finds the total input by this attribute. It
                # does not need to know the name of the field.
                management_form.fields[TOTAL_FORM_COUNT].widget.attrs[
                    "data-sequence-total"
                ] = ""
            # A disabled sequence must not let the browser change its row count.
            if disabled:
                for management_field in management_form.fields.values():
                    management_field.widget.attrs["disabled"] = True

            def make_row(index: int | str, item: object | None) -> dict[str, object]:
                """Build the template context of one row, or of the empty row."""
                row_name = f"{name}-{index}"
                child_attrs = final_attrs.copy()
                if id_:
                    child_attrs["id"] = f"{id_}_{index}"
                if self.child_field.disabled:
                    child_attrs["disabled"] = True
                if isinstance(item, (str, bytes, bytearray)) and isinstance(
                    child_widget, (MultiWidget, SequenceWidget)
                ):
                    # These widgets have no scalar browser representation. Keep the
                    # validation error, but never feed a forged scalar to decompress().
                    item = None
                depth = self.bound.item_depth
                own_messages: list[object] = []
                nested_item_errors: list[ItemValidationError] = []
                if isinstance(index, int):
                    for error in self.bound.item_errors:
                        path = error.item_path
                        if len(path) <= depth or path[depth] != index:
                            continue
                        if len(path) == depth + 1:
                            own_messages.append(error.child_message)
                        elif isinstance(path[depth + 1], int):
                            nested_item_errors.append(error)
                if isinstance(child_widget, SequenceWidget):
                    # Give the nested sequence the same management input.
                    # MultiWidget gives its own input to each child widget
                    # in the same way.
                    # Also give the nested sequence its own errors and its
                    # own deleted rows.
                    nested_deleted = (
                        child_widget.deleted_row_indexes(
                            bound_management_input, row_name, len(item)
                        )
                        if bound_management_input is not None and isinstance(item, list)
                        else frozenset()
                    )
                    child_widget.bound = child_widget.Bound(
                        management_input=bound_management_input,
                        item_errors=nested_item_errors,
                        item_depth=depth + 1,
                        deleted_indexes=nested_deleted,
                    )
                    item = cast(Sequence[object] | None, item)
                subwidget = child_widget.get_context(row_name, item, child_attrs)[
                    "widget"
                ]
                row: dict[str, object] = {
                    "index": index,
                    "delete_name": f"{row_name}-{DELETION_FIELD_NAME}",
                    "subwidget": subwidget,
                    "errors": own_messages,
                }
                if row["errors"]:
                    child_id = subwidget["attrs"].get("id")
                    error_id = f"{child_id}_error" if child_id else None
                    if error_id:
                        row["error_id"] = error_id
                    self._mark_row_invalid(subwidget, error_id)
                return row

            # Rendering keeps only rows that fit. Unlike cleaning, it does not
            # raise when the shared cap is empty.
            value = value[: countdown.take(len(value))]
            try:
                rows = [
                    make_row(index, item)
                    for index, item in enumerate(value)
                    if index not in self.bound.deleted_indexes
                ]
                # The template renders one inert row under the __prefix__ index.
                # The browser script copies that row when the user adds a row.
                empty_row = make_row("__prefix__", None)
            finally:
                if isinstance(child_widget, SequenceWidget):
                    # make_row() put this render's management data on the shared
                    # child widget. Clear it, so no later render inherits it.
                    child_widget.bound = child_widget.Bound()

            context["widget"].update(
                {
                    "rows": rows,
                    "empty_row": empty_row,
                    "management_form": management_form,
                    "minimum_forms": self.limits.min_length,
                    "maximum_forms": self.limits.max_length,
                    "absolute_maximum_forms": self.limits.absolute_max,
                    "disabled": disabled or management_invalid,
                }
            )
            # Keep one hidden delete input for each deleted row, so that the
            # deletion survives the next submission.
            if self.bound.deleted_indexes and not self.bound.submission_overflow:
                context["widget"]["deleted_rows"] = [
                    {"delete_name": f"{name}-{index}-{DELETION_FIELD_NAME}"}
                    for index in sorted(self.bound.deleted_indexes)
                ]
            return context

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
