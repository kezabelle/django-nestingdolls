from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from contextvars import ContextVar, Token
from itertools import islice
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, Field
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
from django.forms.widgets import Widget
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property

from nestingdolls.patches import FormLayout

if TYPE_CHECKING:
    from nestingdolls.fields import SequenceField

__all__ = ["MappingWidget", "SequenceWidget"]


class CompositeWidget(Widget):
    class Keys:
        """Read the submitted input keys of one composite field.

        A composite field accepts a dash, a dot, or a bracket between its own
        name and the name of a child. This object changes each accepted
        spelling into one canonical key. It is the base for the row keys of a
        sequence and for the child keys of a mapping. It holds only the
        configuration of the field that owns it, and it does no widget work.

        This base holds no state, so each subclass can keep its own state in
        slots.
        """

        __slots__ = ()

        @staticmethod
        def split(key: object, name: str) -> tuple[str, str] | None:
            """Split one supported child key spelling into its token and suffix.

            The dash, dot, and bracket spellings all name one child of ``name``.
            This returns the text that identifies the child and the text that
            follows it, which each composite widget reads in its own way.
            """
            if not isinstance(key, str):
                return None
            for separator in ("-", ".", "["):
                prefix = f"{name}{separator}"
                if not key.startswith(prefix):
                    continue
                remainder = key.removeprefix(prefix)
                if separator != "[":
                    return (remainder, "") if remainder else None
                end = remainder.find("]")
                if end <= 0:
                    return None
                suffix = remainder[end + 1 :]
                if suffix and suffix[0] not in "_-.[":
                    return None
                return (remainder[:end], suffix)
            return None

        def canonical(self, key: object, name: str) -> object | None:
            """Return the canonical key for one accepted key spelling, or None."""
            raise NotImplementedError

        def reads_whole_value(self, data: Mapping[str, object], name: str) -> bool:
            """Report whether to read the value from the one key named ``name``.

            A composite value arrives in one of two spellings. A programmer
            gives the whole value under the field's own name, as in
            ``{"point": {"a": 1}}``. A browser gives one key for each child,
            as in ``point-a=1``. This method picks the spelling to read when
            the data holds both.

            The choice matters because a browser can send a key that is named
            after the field but holds no value of the field. A submit button
            named ``point`` sends ``point=save``. If the whole value won
            there, that button would replace every real child value. So the
            whole value wins in two cases only:

            1. The data is not a ``QueryDict``. A programmer built the data,
               and a whole value is the point of that spelling.
            2. The data holds no child key for ``name``. Nothing else can
               supply the value.
            """
            # An UploadedFile is never a composite value, and request.FILES is a
            # plain MultiValueDict, so the QueryDict test below cannot see it.
            if isinstance(data.get(name), UploadedFile):
                return False
            if not isinstance(data, QueryDict):
                return True
            return not any(self.canonical(key, name) is not None for key in data)

        def normalized(
            self, data: Mapping[str, object], name: str
        ) -> Mapping[str, object]:
            """Return the submitted data under canonical child keys."""
            raise NotImplementedError

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bound:
        """Hold the submitted state that one render of a composite widget needs.

        Widget.render() cannot give this state to get_context(), so the bound
        field puts it here first. Each render replaces the whole object, because
        a hidden initial render must not keep the state of a visible render. A
        Form deep-copies its fields, so this state stays with one field of one
        form.
        """

        hidden_initial_value: object = None

    _template_name: str
    input_type: str | None = None
    # The key reader of this widget. Each composite widget builds one when a
    # field configures it.
    keys: Keys
    # The state of the current render. Every widget starts with this one frozen
    # default. A render replaces it with a new object, and nothing can change a
    # frozen object, so no widget can pass its state to another widget.
    bound: Bound = Bound()

    def _child_widget(self, field: Field) -> Widget:
        """Return the widget one child renders with, hidden when this widget is."""
        widget: Widget = field.widget
        if self.input_type != "hidden":
            return widget
        # Test the hidden mode of this widget. Do not test is_hidden. A child
        # widget can be hidden already and keep its own attributes and choices.
        # Django's field.hidden_widget() makes a new HiddenInput and loses them.
        return field.hidden_widget()

    @property
    def template_name(self) -> str:
        # A developer can set any template name. Only a name with the
        # {layout} placeholder needs substitution. Formatting a name
        # without the placeholder can raise an error on its own braces.
        if "{layout}" not in self._template_name:
            return self._template_name
        return self._template_name.format(layout=FormLayout.current().value)

    @template_name.setter
    def template_name(self, value: str) -> None:
        self._template_name = value

    @property
    def media(self) -> WidgetMedia:
        """Merge every ``class Media`` in the MRO. Then add the children's media.

        ``MediaDefiningClass`` installs ``media_property`` only for a class
        that omits ``media`` from its body.
        A composite widget must add media from the child form or the child
        field. The metaclass cannot know about that media. So this class
        must define ``media`` itself, and must merge the declarations that
        the metaclass normally merges.
        """
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
        """Return the submitted composite value extracted by child widgets."""
        return self.value_from_normalized_data(
            self.keys.normalized(data, name),
            self.keys.normalized(files, name) if files else {},
            name,
        )

    def value_omitted_from_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> bool:
        """Report whether all supported composite inputs are absent."""
        return not (
            self.keys.normalized(data, name) or self.keys.normalized(files, name)
        )

    def value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        raise NotImplementedError

    def use_required_attribute(self, initial: object) -> bool:
        """Let child fields own HTML required attributes."""
        return False

    def id_for_label(self, id_: str) -> str:
        """Suppress label targeting, as ``MultiWidget.id_for_label`` does."""
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
            """Return the canonical child key of one accepted key, or None."""
            if (child_key := self.split(key, name)) is None:
                return None
            token, suffix = child_key
            key = f"{name}-{token}{suffix}"
            # A key that only starts with the field name is not a child key.
            # Refuse it, so that forged input cannot stay in the value.
            return (
                key
                if any(
                    key == f"{name}-{child_name}"
                    or key.startswith(f"{name}-{child_name}{separator}")
                    for child_name in self.names
                    for separator in "_-.["
                )
                else None
            )

        def reads_whole_value(self, data: Mapping[str, object], name: str) -> bool:
            """Refuse a browser value under this field's own name.

            A browser cannot submit a mapping under one key, so a key spelled
            exactly like the field name is a submit button or forged input.
            """
            return not isinstance(data, QueryDict) and super().reads_whole_value(
                data, name
            )

        def normalized(
            self, data: Mapping[str, object], name: str
        ) -> Mapping[str, object]:
            """Return the data of the children under canonical keys.

            The values stay as the caller gave them.
            """
            if not data:
                return MultiValueDict()

            if name in data and self.reads_whole_value(data, name):
                # A whole mapping value and flat child keys can both be
                # present. See reads_whole_value() for which one wins.
                value = data.get(name)
                if not isinstance(value, Mapping):
                    normalized = MultiValueDict[str, object]()
                    normalized.setlist(name, [value])
                    return normalized
                if isinstance(value, MultiValueDict):
                    # Keep every repeated value, because a child widget can
                    # read all values of one key.
                    normalized = MultiValueDict[str, object]()
                    for child_name in self.names:
                        if child_name in value:
                            normalized.setlist(
                                f"{name}-{child_name}", value.getlist(child_name)
                            )
                    return normalized
                # Copy the declared children only, so that forged keys do not
                # stay in the value.
                normalized = MultiValueDict[str, object]()
                for child_name in self.names:
                    if child_name in value:
                        normalized.setlist(f"{name}-{child_name}", [value[child_name]])
                return normalized

            if isinstance(data, MultiValueDict):
                # Keep repeated values in a MultiValueDict, as Django request
                # data does.
                normalized = MultiValueDict[str, object]()
                for source_key in data:
                    key = self.canonical(source_key, name)
                    if key is not None:
                        normalized.setlist(key, data.getlist(source_key))
                return normalized

            # Plain mappings keep one value for each child key.
            result: dict[str, object] = {}
            for source_key, value in data.items():
                key = self.canonical(source_key, name)
                if key is not None:
                    result[key] = value
            return result

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

    def value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> object:
        """Extract child values from canonical data and files."""
        # A whole value holds the whole mapping. Return it, because the caller
        # gave Python data and no child widget must read it again.
        if name in data:
            return data.get(name)
        if name in files:
            return files.get(name)
        if not data and not files:
            return {}

        files = cast("MultiValueDict[str, UploadedFile[Any]]", files)
        value: dict[str, object] = {}
        # Only a child widget knows how to read its own input, and only it
        # knows when the browser sent nothing. A child that sent nothing stays
        # out of the value, so that its initial value survives.
        for child_name, field in self.fields.items():
            child_widget = self._child_widget(field)
            child_input_name = f"{name}-{child_name}"
            if child_widget.value_omitted_from_data(data, files, child_input_name):
                continue
            value[child_name] = child_widget.value_from_datadict(
                data, files, child_input_name
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
        render parses it only once. ``row_errors`` holds the errors of
        each row. ``deleted_indexes`` holds the rows the user deleted.
        """

        management_data: Mapping[str, object] | None = None
        management_form: ManagementForm | None = None
        row_errors: Mapping[int, list[object]] = MappingProxyType({})
        deleted_indexes: Collection[int] = frozenset()

    bound: Bound = Bound()

    class Media:
        """Load the script that adds and removes rows in the browser."""

        js = ("nestingdolls/sequence.js",)

    @dataclasses.dataclass(frozen=True, slots=True)
    class Keys(CompositeWidget.Keys):
        """Read the input keys of one sequence field as row keys.

        Every row of a sequence has an index. This object changes each accepted
        key format into one canonical row key, and it gives each row its own
        input. It knows the management keys of the field. It holds the row
        limit, so it can refuse an index that is too large.
        """

        absolute_max: int
        # The longest digit run that can name a row. A longer run is forged
        # input, refused before it becomes an integer.
        max_index_digits: ClassVar[int] = 7

        def __post_init__(self) -> None:
            # An index this reader cannot spell names no row, so a limit above
            # the digit run would leave its upper rows unaddressable. Every
            # field builds one of these, so this guards every field.
            addressable = 10**self.max_index_digits
            if self.absolute_max >= addressable:
                raise ValueError(f"absolute_max must be below {addressable}")

        @staticmethod
        def management_names(name: str) -> set[str]:
            """Return the management keys for a sequence field name."""
            return {
                f"{name}-{TOTAL_FORM_COUNT}",
                f"{name}-{INITIAL_FORM_COUNT}",
                f"{name}-{MIN_NUM_FORM_COUNT}",
                f"{name}-{MAX_NUM_FORM_COUNT}",
            }

        def has_management_data(self, data: Mapping[str, object], name: str) -> bool:
            """Report whether the data carries a management key of this field."""
            return any(key in data for key in self.management_names(name))

        def reads_whole_value(self, data: Mapping[str, object], name: str) -> bool:
            """Refuse a browser value under this field's own name.

            A rendered sequence always submits management inputs. A key that is
            only spelled like the field name is then a submit button or forged
            input, never the whole collection. Data with no management input can
            still carry the repeated-value spelling of the collection.
            """
            if isinstance(data, QueryDict) and self.has_management_data(data, name):
                return False
            # ``dataclass(slots=True)`` rebuilds the class, so the zero-argument
            # ``super()`` of this body would look up the discarded original.
            return CompositeWidget.Keys.reads_whole_value(self, data, name)

        def total_forms(self, data: Mapping[str, object], name: str) -> int | None:
            """Return the submitted number of rows, or None when there is none."""
            value = data.get(f"{name}-{TOTAL_FORM_COUNT}")
            if value is None or not isinstance(value, (str, int)):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def whole_value_rows(
            self, data: Mapping[str, object], name: str
        ) -> list[object] | None:
            """Return the rows of a whole list value, or None.

            The return value has three states, and each state matters:

            - ``None`` means there is no usable whole value. The
              caller must read the flat row keys instead.
            - ``[]`` means a whole value is present, but is not a
              list. The sequence is then empty.
            - A list holds the rows themselves.

            Keep one row more than the limit. The clean step then sees
            that the input is too large. It reports too_many_forms,
            instead of silently truncating the input.
            """
            if name not in data or not self.reads_whole_value(data, name):
                return None
            value = data.get(name)
            if not isinstance(value, list):
                return []
            return value[: self.absolute_max + 1]

        def canonical(self, key: object, name: str) -> tuple[str, int] | None:
            """Return the canonical row key and the row index, or None.

            This method slices the digit run, instead of parsing it one
            digit at a time. The token can carry a suffix, as in
            ``values-2-name``. A digit run longer than
            ``max_index_digits`` is refused outright. A forged key of
            thousands of digits never becomes an integer.

            An index at or past ``absolute_max`` names no row, so this
            method refuses it. It does not clamp the index. A clamped
            index returns a plausible-looking canonical key, and two
            different forged keys can then collide on it.
            """
            if (child_key := self.split(key, name)) is None:
                return None
            token, suffix = child_key
            index_end = 0
            while index_end < len(token) and "0" <= token[index_end] <= "9":
                index_end += 1
            if not index_end:
                return None
            if index_end > self.max_index_digits:
                return None
            # A leading-zero alias is an attack. It names the same row, so the later key wins.
            digits = token[:index_end].lstrip("0")
            index = int(digits) if digits else 0
            if index >= self.absolute_max:
                return None
            suffix = token[index_end:] + suffix
            if suffix and suffix[0] not in "_-.[":
                return None
            return (f"{name}-{index}{suffix}", index)

        @staticmethod
        def dense_index_map(indexes: Collection[int]) -> dict[int, int]:
            """Return a new index for each row index, without the gaps.

            Only the unmanaged flat-key path calls this. When the
            browser sends management input, Django's management form
            owns the row count. The original indexes then stay
            unchanged.

            A plain mapping can have gaps between the indexes, for example 0 and
            1999. An index that is dense already keeps its place. A larger index
            moves down to one place after the row before it, so at most one empty
            row stays in front of it. The order of the rows survives, and a
            forged index cannot make thousands of rows. An index that
            ``canonical()`` discarded never reaches this map. It
            disappears from the dense mapping on its own.
            """
            return {
                original_index: min(original_index, dense_index + 1)
                for dense_index, original_index in enumerate(sorted(indexes))
            }

        def rows(
            self, data: Mapping[str, object], name: str, form_count: int
        ) -> list[MultiValueDict[str, object]]:
            """Return one input dict for each row, from index 0 to form_count.

            A composite child widget reads the full input of its row, so a scan
            for each row would cost the size of the input for each row. This
            method scans the input one time.
            """
            rows = [MultiValueDict[str, object]() for _ in range(form_count)]
            for key, value in data.items():
                if (row_key := self.canonical(key, name)) is None:
                    continue
                row_name, index = row_key
                if index < form_count:
                    rows[index].setlist(
                        row_name,
                        data.getlist(key)
                        if isinstance(data, MultiValueDict)
                        else [value],
                    )
            return rows

        def normalized(
            self, data: Mapping[str, object], name: str
        ) -> MultiValueDict[str, object]:
            """Canonicalize accepted row spellings into Django-style keys and dense rows.

            The result is empty for empty input. A whole value under
            ``name`` survives under that same key. Every other key of
            the result is ``name`` itself, or starts with ``name-``.
            The result holds at most two keys more than the input: the
            two management keys this method can add.
            """
            normalized = MultiValueDict[str, object]()
            if not data:
                return normalized

            def values_for(key: str) -> list[object]:
                # Read repeated input as Django request data reads it.
                if isinstance(data, MultiValueDict):
                    return list(data.getlist(key))
                value = data.get(key)
                return value if isinstance(value, list) else [value]

            # Keep the management input in the repeated-value structure that
            # Django expects.
            management_keys = {
                key for key in self.management_names(name) if key in data
            }
            for key in management_keys:
                normalized.setlist(key, values_for(key))

            if name in data and self.reads_whole_value(data, name):
                # A whole list value and flat row keys can both be present.
                # reads_whole_value() for which one wins.
                whole_value = values_for(name)
                normalized[name] = whole_value
                # A whole value owns the row count. A submitted management
                # total must not contradict the rows the clean step reads.
                normalized[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(whole_value))
                normalized[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
                return normalized

            overflowed_index = False
            row_inputs: list[tuple[int, str, list[object]]] = []
            seen_indexes: set[int] = set()
            for key in data:
                if key in management_keys:
                    continue
                if (row_key := self.canonical(key, name)) is None:
                    continue
                row_name, index = row_key
                # An index past the row limit never reaches here.
                # canonical() discards it. Only the row-count cap below
                # can overflow.
                if index not in seen_indexes:
                    if len(seen_indexes) >= self.absolute_max:
                        # Stop here. Many matching rows must not use memory
                        # without a limit.
                        overflowed_index = True
                        break
                    seen_indexes.add(index)
                row_inputs.append((index, row_name, values_for(key)))

            if management_keys:
                # The management form of Django is in control when the browser
                # sent management input. Keep the original indexes.
                if overflowed_index:
                    # Set a total above the limit, so that the field reports
                    # the usual too_many_forms error.
                    normalized.setlist(
                        f"{name}-{TOTAL_FORM_COUNT}", [str(self.absolute_max + 1)]
                    )
                for _, row_name, values in row_inputs:
                    normalized.setlist(row_name, values)
                return normalized

            if not row_inputs and not overflowed_index:
                return normalized

            dense_indexes = self.dense_index_map(seen_indexes)
            for original_index, row_name, values in row_inputs:
                # Keep the text after the index, as in ``values-2-name``, so
                # that a composite child keeps its own key.
                suffix = row_name.removeprefix(f"{name}-{original_index}")
                normalized.setlist(
                    f"{name}-{dense_indexes[original_index]}{suffix}",
                    values,
                )

            total_forms = max(dense_indexes.values(), default=-1) + 1
            if overflowed_index:
                # Set a total above the limit, so that the field reports the
                # usual too_many_forms error.
                total_forms = self.absolute_max + 1
            normalized[f"{name}-{TOTAL_FORM_COUNT}"] = str(total_forms)
            normalized[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
            return normalized

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

    def value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> list[object]:
        """Extract canonical rows without building past the shared allowance."""
        with self.SubmissionCountdown(self.limits.submission_max) as countdown:
            for source in (data, files):
                if (
                    whole_value_rows := self.keys.whole_value_rows(source, name)
                ) is not None:
                    return whole_value_rows

            counts = [
                count
                for source in (data, files)
                if (count := self.keys.total_forms(source, name)) is not None
            ]
            if not counts:
                return []
            form_count = max(counts)
            if form_count < 0 or form_count > self.limits.absolute_max:
                return []
            form_count = countdown.take(form_count)
            child_widget = self._child_widget(self.child_field)
            row_data = self.keys.rows(data, name, form_count)
            row_files = self.keys.rows(files, name, form_count)
            return [
                child_widget.value_from_datadict(
                    row_data[index],
                    cast("MultiValueDict[str, UploadedFile[Any]]", row_files[index]),
                    f"{name}-{index}",
                )
                for index in range(form_count)
            ]

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

            # A hidden initial render must show the initial rows, because change
            # detection compares them with the rows that the browser sent.
            if self.bound.hidden_initial_value is not None:
                value = cast(Sequence[object] | None, self.bound.hidden_initial_value)
            # Keep runtime initials from expanding rendering without a bound.
            value = (
                [] if value is None else list(islice(value, self.limits.absolute_max))
            )
            if self.bound.management_data is not None and self.keys.has_management_data(
                self.bound.management_data, name
            ):
                # The bound field parsed this input already. Reuse that
                # form, instead of building a second, independent set of
                # errors.
                management_form = self.bound.management_form or ManagementForm(
                    self.bound.management_data, prefix=name
                )
                # Bad management input means that the row count is not trustworthy.
                # Turn off the add and remove controls.
                management_invalid = not management_form.is_valid()
                total_forms = cast(int, management_form.cleaned_data[TOTAL_FORM_COUNT])
                # Show the rows that the management input declares, and no more.
                # A submitted total can be negative: IntegerField accepts it, so
                # ManagementForm.clean() keeps it. A negative slice bound would
                # drop rows off the end of the render, so clamp it at zero.
                value = value[: max(0, min(total_forms, self.limits.absolute_max))]
            else:
                initial_forms = len(value)
                # An unbound field with no value still needs empty rows, so that
                # the user can give one.
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
                if isinstance(child_widget, SequenceWidget):
                    # Give a nested sequence the same management input, as
                    # MultiWidget gives its own input to each child widget.
                    child_widget.bound = child_widget.Bound(
                        management_data=self.bound.management_data
                    )
                    item = cast(Sequence[object] | None, item)
                subwidget = child_widget.get_context(row_name, item, child_attrs)[
                    "widget"
                ]
                row: dict[str, object] = {
                    "index": index,
                    "delete_name": f"{row_name}-{DELETION_FIELD_NAME}",
                    "subwidget": subwidget,
                    "errors": self.bound.row_errors.get(index, [])
                    if isinstance(index, int)
                    else [],
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
            if self.bound.deleted_indexes:
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
