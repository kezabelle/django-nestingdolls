from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime, time
from itertools import islice
from types import MappingProxyType
from typing import Any, Self, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, BaseFormSet, Field
from django.forms.boundfield import BoundField
from django.forms.fields import BooleanField, FileField
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
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from nestingdolls._shared import CompositeBoundField, CompositeField, CompositeWidget

__all__ = [
    "FrozenSequenceField",
    "FrozenSetField",
    "ListField",
    "SequenceBoundField",
    "SequenceField",
    "SequenceWidget",
    "SetField",
    "TupleField",
]

from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MissingManagementFormValidationError,
    SequenceInputValidationError,
    TooManyFormsValidationError,
)


class SequenceBoundField(CompositeBoundField):
    """Render indexed child errors without storing validation state on the field.

    Django passes a widget no errors when it renders a ``BoundField``. A sequence
    has one field-level error list but several visible child widgets, so this
    real ``BoundField`` subclass is the small, public adapter that places a
    child error beside the row identified by its validation index.
    """

    field: SequenceField
    # Every sequence widget extracts rows, so the bound value is always a list.
    data: list[object]

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")

    @dataclasses.dataclass(frozen=True)
    class Submitted:
        """Report what the browser sent for the rows of one bound field.

        It answers which rows the management form declares, which rows the user
        deleted, which rows the child widget omitted, and which errors belong to
        each row. It holds the bound field, and it finds each answer one time.
        It keeps each answer in its own instance dictionary, so it takes no
        slots.
        """

        bound_field: SequenceBoundField

        @cached_property
        def management_form(self) -> ManagementForm | None:
            """Build a management form from normalized sequence inputs."""
            bound_field = self.bound_field
            data_input = bound_field._data_input
            names = bound_field.field.widget.keys.management_names(
                bound_field.html_name
            )
            if not any(name in data_input for name in names):
                return None
            management_form = ManagementForm(data_input, prefix=bound_field.html_name)
            management_form.full_clean()
            return management_form

        @cached_property
        def deleted(self) -> frozenset[int]:
            """Return submitted deleted rows, as ``BaseFormSet.deleted_forms`` does."""
            bound_field = self.bound_field
            return frozenset(
                index
                for index in range(len(bound_field.data))
                if bound_field.field.widget.deletion_field.clean(
                    bound_field._data_input.get(
                        f"{bound_field.html_name}-{index}-{DELETION_FIELD_NAME}"
                    )
                )
            )

        @cached_property
        def omitted(self) -> frozenset[int]:
            """Return extra submitted rows that were omitted by the child widget."""
            bound_field = self.bound_field
            field = bound_field.field
            name = bound_field.html_name
            data_input = bound_field._data_input
            file_input = bound_field._file_input
            if name in data_input or name in file_input:
                return frozenset()
            initial_count = len(field._initial_values(bound_field.initial))
            row_count = len(bound_field.data)
            row_data = field.widget.keys.rows(data_input, name, row_count)
            row_files = field.widget.keys.rows(file_input, name, row_count)
            return frozenset(
                index
                for index in range(row_count)
                if index >= initial_count
                and field.widget.child_field.widget.value_omitted_from_data(
                    row_data[index],
                    row_files[index],
                    f"{name}-{index}",
                )
            )

        @cached_property
        def errors(self) -> Mapping[int, list[object]]:
            """Group child error messages by the row index they belong to."""
            row_errors: dict[int, list[object]] = {}
            for error in self.bound_field._all_errors.as_data():
                if isinstance(error, ItemValidationError) and isinstance(
                    error.item, int
                ):
                    row_errors.setdefault(error.item, []).append(error.message)
            return row_errors

    @cached_property
    def submitted(self) -> Submitted:
        """Return what the browser sent for these rows."""
        return self.Submitted(self)

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the sequence widget the submitted rows, errors, and deletions."""
        if not isinstance(widget, SequenceWidget):
            super()._prepare_widget(widget, only_initial)
        elif only_initial:
            # A hidden initial render shows the submitted initial rows. It shows
            # no errors, and it keeps the rows the user deleted.
            value, management_data = self._hidden_initial_value(widget)
            widget.bound = widget.Bound(
                hidden_initial_value=value, management_data=management_data
            )
        else:
            widget.bound = widget.Bound(
                management_data=self._data_input,
                row_errors=self.submitted.errors,
                deleted_indexes=self.submitted.deleted,
            )

    @cached_property
    def initial(self) -> list[object]:
        """Use Django's normal initial path unless flattened row keys need normalizing."""
        value: object = None
        if self.form.initial and self.name not in self.form.initial:
            value = self._flat_initial_value(self.form.initial)
        if value is None:
            value = super().initial
        if isinstance(value, Mapping) and (
            (normalized := self._flat_initial_value(value)) is not None
        ):
            value = normalized
        try:
            # Keep runtime initial values from growing rendering without a limit.
            value = self.field._initial_values(
                value, limit=self.field.limits.absolute_max
            )
        except InvalidInitialValueError:
            value = [value]
        if not self.field.child_field.widget.supports_microseconds:
            return [
                item.replace(microsecond=0)
                if isinstance(item, (datetime, time))
                else item
                for item in value
            ]
        return value

    def _has_changed(self) -> bool:
        """Treat deleted initial rows as a real change."""
        changed = super()._has_changed()
        if changed or self.field.disabled or not self.submitted.deleted:
            return changed
        try:
            initial_length = len(self.field._initial_values(self.initial))
        except InvalidInitialValueError:
            return True
        return any(index < initial_length for index in self.submitted.deleted)


class SequenceField(CompositeField):
    """Validate a variable-length collection with one homogeneous child field."""

    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a list of values."),
        "missing_management_form": BaseFormSet.default_error_messages[
            "missing_management_form"
        ],
        "too_many_forms": BaseFormSet.default_error_messages["too_many_forms"],
        "min_length": ngettext_lazy(
            "Ensure this value has at least %(limit_value)d item (it has %(show_value)d).",
            "Ensure this value has at least %(limit_value)d items (it has %(show_value)d).",
            "limit_value",
        ),
        "max_length": ngettext_lazy(
            "Ensure this value has at most %(limit_value)d item (it has %(show_value)d).",
            "Ensure this value has at most %(limit_value)d items (it has %(show_value)d).",
            "limit_value",
        ),
    }
    bound_field_class: type[SequenceBoundField] = SequenceBoundField
    widget: SequenceWidget

    @dataclasses.dataclass(frozen=True, slots=True)
    class Limits:
        """Hold the row limits of one sequence field.

        min_length and max_length are the limits the user gives. absolute_max is
        the limit on submitted rows, which stops hostile input before it makes
        work. This object makes sure that the three agree, and it does the
        arithmetic that the field and its widget both need.
        """

        min_length: int
        max_length: int
        absolute_max: int

        def __post_init__(self) -> None:
            if self.min_length < 0 or self.max_length < self.min_length:
                raise ValueError(
                    "min_length and max_length must be non-negative integers"
                )
            if self.max_length > self.absolute_max:
                raise ValueError(
                    "'absolute_max' must be greater or equal to 'max_length'."
                )

        @classmethod
        def build(
            cls, min_length: int, max_length: int, absolute_max: int | None
        ) -> Self:
            """Return the limits, with the default limit on submitted rows."""
            if absolute_max is None:
                absolute_max = max_length + DEFAULT_MAX_NUM
            return cls(min_length, max_length, absolute_max)

        def exceeded_by(self, count: int) -> bool:
            """Report whether a row count is above the limit on submitted rows."""
            return count > self.absolute_max

        def bounded_count(self, count: int) -> int:
            """Return a submitted row count inside the limit on submitted rows."""
            return max(0, min(count, self.absolute_max))

        def empty_count(self, required: bool) -> int:
            """Return how many empty rows to render for a field with no value."""
            return min(max(self.min_length, int(required)), self.max_length)

    limits: Limits

    @property
    def min_length(self) -> int:
        """Return the smallest number of items this field accepts."""
        return self.limits.min_length

    @property
    def max_length(self) -> int:
        """Return the largest number of items this field accepts."""
        return self.limits.max_length

    @property
    def absolute_max(self) -> int:
        """Return the limit on the number of submitted rows."""
        return self.limits.absolute_max

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_length: int = DEFAULT_MIN_NUM,
        max_length: int = DEFAULT_MAX_NUM,
        absolute_max: int | None = None,
        required: bool = True,
        widget: SequenceWidget | type[SequenceWidget] | None = None,
        label: str | Promise | None = None,
        initial: object | Callable[[], object] | None = None,
        help_text: str | Promise = "",
        error_messages: Mapping[str, str | Promise] | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Callable[[Collection[object]], None]] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[SequenceBoundField] | None = None,
    ) -> None:
        """Configure a homogeneous variable-length field."""
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        self.limits = self.Limits.build(min_length, max_length, absolute_max)
        if (
            initial is not None
            and not callable(initial)
            and not isinstance(initial, Mapping)
            and len(self._initial_values(initial)) > max_length
        ):
            raise ValueError("initial must not contain more than max_length values")

        self.child_field = copy.deepcopy(child_field)
        self.child_field.localize = localize

        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, SequenceBoundField):
            raise TypeError("bound_field_class must inherit from SequenceBoundField")
        super().__init__(
            required=required,
            # Django builds a widget class and copies a widget instance. The
            # configuration below then makes that copy match this field.
            widget=widget or SequenceWidget,
            label=label,  # type: ignore[arg-type]
            initial=initial,
            help_text=help_text,  # type: ignore[arg-type]
            error_messages=error_messages,  # type: ignore[arg-type]
            show_hidden_initial=show_hidden_initial,
            validators=validators,
            localize=localize,
            disabled=disabled,
            label_suffix=label_suffix,
            template_name=template_name,
            bound_field_class=bound_field_class,
        )
        if not isinstance(self.widget, SequenceWidget):
            raise TypeError("widget must be a SequenceWidget instance or subclass")
        # Django copies the widget. Configure that copy to match this field.
        self.widget.configure(self.child_field, self.limits)

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy the field and its child field together."""
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def _initial_values(value: object, *, limit: int | None = None) -> list[object]:
        """Normalize supported initial collections into a list."""
        if value is None or value == "":
            return []
        if (
            isinstance(value, Collection)
            and not isinstance(value, Mapping)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            if limit is not None:
                # Keep collection initials from using unbounded memory while rendering.
                return list(islice(value, limit))
            return list(value)
        raise InvalidInitialValueError("initial must be a collection of values")

    def to_python(self, value: object) -> list[object]:
        """Require sequence input to already be list-shaped."""
        if value is None or value == "":
            return []
        if not isinstance(value, list):
            raise SequenceInputValidationError(self.error_messages["invalid"])
        return value

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert each row back from its hidden initial value."""
        # to_python() gives a list of rows here, or raises for other input.
        value = cast(list[object], super().children_from_hidden_initial(value))
        if isinstance(self.child_field, FileField):
            return value
        return [self.hidden_initial_to_python(self.child_field, row) for row in value]

    def _clean_values(
        self,
        values: list[object],
        initial_values: list[object],
        deleted_indexes: frozenset[int] = frozenset(),
        omitted_indexes: frozenset[int] = frozenset(),
    ) -> Collection[object]:
        """Clean each row, then validate the result, as ``MultiValueField`` does."""
        if self.limits.exceeded_by(len(values)):
            # Reject oversized direct input before it multiplies child validation work.
            raise TooManyFormsValidationError(
                self.error_messages["too_many_forms"], num=self.limits.max_length
            )
        cleaned_data: list[object] = []
        errors = []
        for index, value in enumerate(values):
            if index in deleted_indexes or index in omitted_indexes:
                continue
            initial = initial_values[index] if index < len(initial_values) else None
            try:
                if self.child_field.disabled:
                    cleaned = self.child_field.clean(initial)
                elif isinstance(self.child_field, FileField):
                    cleaned = self.child_field.clean(value, initial)
                else:
                    cleaned = self.child_field.clean(value)
            except ValidationError as error:
                errors.extend(ItemValidationError.for_messages_of(index, error))
            else:
                cleaned_data.append(cleaned)
        if errors:
            raise ValidationError(errors)
        result = self.compress(cleaned_data)
        self.validate(result)
        self.run_validators(result)
        return result

    def clean(self, value: object) -> Collection[object]:
        """Clean an already-collected sequence value."""
        return self._clean_values(self.to_python(value), [])

    def _clean_bound_field(self, bound_field: BoundField) -> Collection[object]:
        """Validate Django's management form and retain FileField initial values.

        ``ManagementForm`` owns management-input validation. ``FileField.clean()``
        is deliberately called with ``(data, initial)``; that public API
        implements Django's upload, clear, and contradiction semantics. Ordinary
        child fields continue to use their normal one-value ``clean()`` API.
        """
        assert isinstance(bound_field, SequenceBoundField)
        if self.disabled:
            return cast(
                Collection[object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        submitted = bound_field.submitted
        management_form = submitted.management_form
        if (
            management_form is None
            and not submitted.deleted
            and not submitted.omitted
            and not isinstance(self.child_field, FileField)
        ):
            return cast(
                Collection[object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )

        if management_form is not None:
            if not management_form.is_valid():
                raise MissingManagementFormValidationError(
                    self.error_messages["missing_management_form"],
                    field_names=", ".join(
                        management_form.add_prefix(field_name)
                        for field_name in management_form.errors
                    ),
                )
            submitted_total = management_form.cleaned_data[TOTAL_FORM_COUNT]
            if isinstance(submitted_total, int) and self.limits.exceeded_by(
                submitted_total
            ):
                raise TooManyFormsValidationError(
                    self.error_messages["too_many_forms"], num=self.limits.max_length
                )

        initial = self._initial_values(bound_field.initial)
        data = self.to_python(bound_field.data)
        if (
            management_form is None
            and isinstance(self.child_field, FileField)
            and not data
            and initial
        ):
            data = [None] * len(initial)
        return self._clean_values(data, initial, submitted.deleted, submitted.omitted)

    def validate(self, value: Collection[object]) -> None:
        """Apply required, minimum, and maximum length checks."""
        if not value:
            super().validate([])
            return
        length = len(value)
        if length < self.limits.min_length:
            raise ValidationError(
                self.error_messages["min_length"],
                code="min_length",
                params={"limit_value": self.limits.min_length, "show_value": length},
            )
        if length > self.limits.max_length:
            raise ValidationError(
                self.error_messages["max_length"],
                code="max_length",
                params={"limit_value": self.limits.max_length, "show_value": length},
            )

    def compress(self, data_list: list[object]) -> Collection[object]:
        """Return the cleaned list unchanged."""
        return data_list

    def bound_data(self, data: object, initial: object) -> Collection[object]:
        """Bind each submitted row against its matching initial value."""
        if self.disabled:
            return self._initial_values(initial)
        if isinstance(data, list) and self.limits.exceeded_by(len(data)):
            return []
        initial = self._initial_values(initial)
        values = []
        for index, value in enumerate(self.to_python(data)):
            initial_value = initial[index] if index < len(initial) else None
            try:
                value = self.child_field.bound_data(value, initial_value)
            except (InvalidInitialValueError, ValidationError):
                # BoundField.value() calls this while rendering. Composite children
                # may reject a hostile row shape here after cleaning has already
                # recorded a form error. Django's base contract for an enabled field
                # is to redisplay the submitted value; prepare_value() mirrors this
                # fallback so no widget-specific replacement value is needed.
                value = super().bound_data(value, initial_value)
            values.append(value)
        return values

    def prepare_value(self, value: object) -> list[object]:
        """Prepare each row for widget rendering."""
        values = []
        for row in self._initial_values(value, limit=self.limits.absolute_max):
            try:
                row = self.child_field.prepare_value(row)
            except (InvalidInitialValueError, ValidationError):
                row = super().prepare_value(row)
            values.append(row)
        return values

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare submitted rows using child-field change semantics."""
        if self.disabled:
            return False
        if isinstance(data, list) and self.limits.exceeded_by(len(data)):
            return True
        try:
            initial = self._initial_values(initial)
        except InvalidInitialValueError:
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True
        shared_length = min(len(initial), len(data))
        for index in range(shared_length):
            try:
                if self.child_field.has_changed(initial[index], data[index]):
                    return True
            except ValidationError:
                return True
        if len(initial) > len(data):
            return True
        for value in data[shared_length:]:
            try:
                if self.child_field.has_changed(None, value):
                    return True
            except ValidationError:
                return True
        return False


ListField = SequenceField


class FrozenSequenceField(SequenceField):
    """Collect cleaned rows into an immutable tuple."""

    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        """Return cleaned rows as a tuple."""
        return tuple(data_list)


TupleField = FrozenSequenceField


class SetField(SequenceField):
    """Collect cleaned rows into a deduplicated set-like value."""

    default_error_messages = {  # noqa: RUF012
        "unhashable": _("Set items must be hashable."),
    }

    collection_type: Callable[[list[object]], set[object] | frozenset[object]] = set

    def compress(self, data_list: list[object]) -> set[object] | frozenset[object]:
        """Return cleaned rows in the configured set type."""
        try:
            return self.collection_type(data_list)
        except TypeError as error:
            raise ValidationError(
                self.error_messages["unhashable"], code="unhashable"
            ) from error

    @dataclasses.dataclass(slots=True)
    class Match:
        """Match the submitted rows of a set field to its initial members.

        A set has no order, so each submitted row can answer for any initial
        member. The child field decides whether a row and a member are the same,
        because only it knows how it reads its own input. This object claims one
        member for each row it can, and reports whether every member was
        claimed. It holds the members of one comparison, so a field builds one
        for each comparison it makes. Claiming a member changes it, so it is the
        one holder that is not frozen.
        """

        child_field: Field
        members: list[object]
        claimed: set[int] = dataclasses.field(default_factory=set)
        indexed: dict[object, list[int]] = dataclasses.field(init=False, repr=False)

        def __post_init__(self) -> None:
            # compress() already rejected unhashable members, so index them all.
            self.indexed = {}
            for index, member in enumerate(self.members):
                self.indexed.setdefault(member, []).append(index)

        def candidates(self, value: object) -> Collection[int]:
            """Return the members that hash equal to one submitted row."""
            try:
                return self.indexed.get(value, ())
            except TypeError:
                # A compound child value can be unhashable. Scan for it instead.
                return ()

        def claim(self, row: object, candidates: Collection[int]) -> bool:
            """Claim one member for a submitted row, and report the success.

            Prefer a member that no row claimed, and prefer a member that hashes
            equal to the row.
            """
            for claimed in (False, True):
                for indexes in (candidates, range(len(self.members))):
                    for index in indexes:
                        if (index in self.claimed) != claimed:
                            continue
                        if not self.child_field.has_changed(self.members[index], row):
                            self.claimed.add(index)
                            return True
            return False

        @property
        def complete(self) -> bool:
            """Report whether the submitted rows claimed every member."""
            return len(self.claimed) == len(self.members)

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare semantic set members, not raw row order or raw row spelling.

        ``has_changed()`` receives raw submitted row data but initial members are
        already cleaned Python values. A plain ``==`` comparison would therefore
        be wrong for child fields that coerce input or use compound widget data.
        """
        if self.disabled:
            return False
        if isinstance(data, list) and self.limits.exceeded_by(len(data)):
            return True
        try:
            members = list(self.compress(self._initial_values(initial)))
        except (InvalidInitialValueError, ValidationError):
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True

        try:
            match = self.Match(self.child_field, members)
            for row in data:
                try:
                    value = self.child_field.to_python(row)
                except (TypeError, ValidationError):
                    return True
                if not match.claim(row, match.candidates(value)) and (
                    self.child_field.has_changed(None, row)
                ):
                    return True
        except (TypeError, ValidationError):
            return True
        return not match.complete


class FrozenSetField(SetField):
    """Collect cleaned rows into a frozenset."""

    collection_type = frozenset


class SequenceWidget(CompositeWidget):
    """Render dynamic homogeneous rows while delegating each row to one widget."""

    _template_name = "nestingdolls/sequence/{layout}.html"
    use_fieldset = True
    deletion_field = BooleanField(required=False)
    child_field: Field
    keys: Keys
    limits: SequenceField.Limits

    @dataclasses.dataclass(frozen=True, slots=True)
    class Bound(CompositeWidget.Bound):
        """Hold the submitted rows that one render of a sequence widget needs.

        management_data holds the submitted management inputs, which limit how
        many rows to render. row_errors holds the errors of each row, and
        deleted_indexes holds the rows the user deleted.
        """

        management_data: Mapping[str, object] | None = None
        row_errors: Mapping[int, list[object]] = MappingProxyType({})
        deleted_indexes: Collection[int] = frozenset()

    bound: Bound = Bound()

    class Media:
        """Load the client-side row add/remove controller."""

        js = ("nestingdolls/sequence.js",)

    @dataclasses.dataclass(frozen=True, slots=True)
    class Keys(CompositeWidget.Keys):
        """Read the submitted input keys of one sequence field as row keys.

        Every row of a sequence has an index. This object changes each accepted
        key spelling into one canonical row key, gives each row its own input,
        and knows the management keys of the field. It holds the row limit, so
        it can refuse an index that is too large.
        """

        absolute_max: int

        @staticmethod
        def management_names(name: str) -> set[str]:
            """Return the management keys for a sequence field name."""
            return {
                f"{name}-{TOTAL_FORM_COUNT}",
                f"{name}-{INITIAL_FORM_COUNT}",
                f"{name}-{MIN_NUM_FORM_COUNT}",
                f"{name}-{MAX_NUM_FORM_COUNT}",
            }

        def canonical(self, key: object, name: str) -> tuple[str, int] | None:
            """Normalize one supported row key into its canonical name and index."""
            if (child_key := self.split(key, name)) is None:
                return None
            token, suffix = child_key
            index_end = 0
            index = 0
            while index_end < len(token) and "0" <= token[index_end] <= "9":
                digit = ord(token[index_end]) - ord("0")
                # Avoid an unbounded integer from a hostile row index.
                index = min(self.absolute_max, index * 10 + digit)
                index_end += 1
            if not index_end:
                return None
            suffix = token[index_end:] + suffix
            if suffix and suffix[0] not in "_-.[":
                return None
            return (f"{name}-{index}{suffix}", index)

        def rows(
            self, data: Mapping[str, object], name: str, form_count: int
        ) -> list[MultiValueDict[str, object]]:
            """Avoid repeated full-input scans when rows use composite child widgets."""
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

            post[]:
                implies(not data, not __return__)
                implies(name in data, name in __return__)
                all(key == name or key.startswith(f"{name}-") for key in __return__)
                len(__return__) <= len(data) + 2
            """
            normalized = MultiValueDict[str, object]()
            if not data:
                return normalized

            def values_for(key: str) -> list[object]:
                # Treat repeated input the same way Django request data does.
                if isinstance(data, MultiValueDict):
                    return list(data.getlist(key))
                value = data.get(key)
                return value if isinstance(value, list) else [value]

            # Keep formset control fields in the repeated-value shape Django expects.
            management_keys = {
                key for key in self.management_names(name) if key in data
            }
            for key in management_keys:
                normalized.setlist(key, values_for(key))

            if name in data:
                # Use the direct list value when both shapes are present.
                direct_value = values_for(name)
                normalized[name] = direct_value
                if not management_keys:
                    # Build missing control fields for a direct Python list.
                    normalized[f"{name}-{TOTAL_FORM_COUNT}"] = str(len(direct_value))
                    normalized[f"{name}-{INITIAL_FORM_COUNT}"] = "0"
                return normalized

            overflowed_index = False
            row_inputs: list[tuple[int, str, list[object]]] = []
            for key in data:
                if key in management_keys:
                    continue
                if (row_key := self.canonical(key, name)) is None:
                    continue
                row_name, index = row_key
                if index >= self.absolute_max:
                    # Do not let a forged index bypass the row limit.
                    overflowed_index = True
                    continue
                if len(row_inputs) >= self.absolute_max:
                    # Prevent many matching keys from growing memory without limit.
                    overflowed_index = True
                    break
                row_inputs.append((index, row_name, values_for(key)))

            if management_keys:
                # Keep Django's management validation authoritative for managed rows.
                if overflowed_index:
                    # Reject excess input through Django's standard validation error.
                    normalized.setlist(
                        f"{name}-{TOTAL_FORM_COUNT}", [str(self.absolute_max + 1)]
                    )
                for _, row_name, values in row_inputs:
                    normalized.setlist(row_name, values)
                return normalized

            if not row_inputs and not overflowed_index:
                return normalized

            # Renumber sparse rows so plain mappings bind like form input.
            row_indexes = sorted({index for index, _, _ in row_inputs})
            remapped_indexes = {
                original_index: min(original_index, dense_index + 1)
                for dense_index, original_index in enumerate(row_indexes)
            }
            for original_index, row_name, values in row_inputs:
                suffix = row_name.removeprefix(f"{name}-{original_index}")
                normalized.setlist(
                    f"{name}-{remapped_indexes[original_index]}{suffix}",
                    values,
                )

            total_forms = max(remapped_indexes.values(), default=-1) + 1
            if overflowed_index:
                # Reject excess input through Django's standard validation error.
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
        """Store child-widget settings for a sequence field.

        Django builds this widget from its class, and gives it no child field,
        when a field supplies only the class. The field configures the copy.
        """
        self.limits = SequenceField.Limits.build(min_length, max_length, absolute_max)
        self.keys = self.Keys(self.limits.absolute_max)
        if child_field is not None:
            self.child_field = child_field
        super().__init__(dict(attrs) if attrs is not None else None)

    def configure(self, child_field: Field, limits: SequenceField.Limits) -> None:
        """Take the configuration of the field that owns this widget.

        Django copies a widget before a field can use it, so the field calls
        this on its own copy. The key reader is built here, because it holds the
        row limit and must never hold an old one.
        """
        self.child_field = child_field
        self.limits = limits
        self.keys = self.Keys(limits.absolute_max)

    def _value_from_normalized_data(
        self,
        data: Mapping[str, object],
        files: Mapping[str, object],
        name: str,
    ) -> list[object]:
        """Extract row values from canonicalized data and files."""

        def direct_sequence_value(
            source: Mapping[str, object],
        ) -> list[object] | None:
            if name not in source:
                return None
            value = source.get(name)
            # Keep direct Python or JSON input from multiplying child work past the limit.
            return (
                value[: self.limits.absolute_max + 1] if isinstance(value, list) else []
            )

        def submitted_total_forms(source: Mapping[str, object]) -> int | None:
            value = source.get(f"{name}-{TOTAL_FORM_COUNT}")
            if value is None or not isinstance(value, (str, int)):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        for source in (data, files):
            if (direct_value := direct_sequence_value(source)) is not None:
                return direct_value

        counts = [
            count
            for source in (data, files)
            if (count := submitted_total_forms(source)) is not None
        ]
        if not counts:
            return []
        form_count = max(counts)
        if form_count < 0 or form_count > self.limits.absolute_max:
            # Reject forged totals before they allocate rows or call child widgets.
            return []
        child_widget = self._child_widget(self.child_field)
        row_data = self.keys.rows(data, name, form_count)
        row_files = self.keys.rows(files, name, form_count)
        return [
            child_widget.value_from_datadict(
                row_data[index],
                cast(MultiValueDict[str, UploadedFile], row_files[index]),
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
        """Build rows and use bound management data when it is available."""
        context = super().get_context(name, value, attrs)
        child_widget = self._child_widget(self.child_field)
        if self.is_localized:
            child_widget.is_localized = True

        final_attrs = context["widget"]["attrs"]
        final_attrs.pop("aria-invalid", None)
        id_ = final_attrs.get("id")
        disabled = bool(final_attrs.get("disabled"))

        if self.bound.hidden_initial_value is not None:
            value = cast(Sequence[object] | None, self.bound.hidden_initial_value)
        # Keep runtime initials from expanding rendering without a bound.
        value = [] if value is None else list(islice(value, self.limits.absolute_max))
        if self.bound.management_data is not None and any(
            key in self.bound.management_data
            for key in self.keys.management_names(name)
        ):
            management_form = ManagementForm(self.bound.management_data, prefix=name)
            management_invalid = not management_form.is_valid()
            total_forms = cast(int, management_form.cleaned_data[TOTAL_FORM_COUNT])
            value = value[: self.limits.bounded_count(total_forms)]
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
            management_form.fields[TOTAL_FORM_COUNT].widget.attrs[
                "data-sequence-total"
            ] = ""
        if disabled:
            for management_field in management_form.fields.values():
                management_field.widget.attrs["disabled"] = True

        def make_row(index: int | str, item: object | None) -> dict[str, object]:
            row_name = f"{name}-{index}"
            child_attrs = final_attrs.copy()
            if id_:
                child_attrs["id"] = f"{id_}_{index}"
            if self.child_field.disabled:
                child_attrs["disabled"] = True
            if isinstance(child_widget, SequenceWidget):
                # Give a nested sequence the same management data, as
                # MultiWidget gives its own input type to each subwidget.
                child_widget.bound = child_widget.Bound(
                    management_data=self.bound.management_data
                )
                item = cast(Sequence[object] | None, item)
            subwidget = child_widget.get_context(row_name, item, child_attrs)["widget"]
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

        context["widget"].update(
            {
                "rows": [
                    make_row(index, item)
                    for index, item in enumerate(value)
                    if index not in self.bound.deleted_indexes
                ],
                "empty_row": make_row("__prefix__", None),
                "management_form": management_form,
                "minimum_forms": self.limits.min_length,
                "maximum_forms": self.limits.max_length,
                "absolute_maximum_forms": self.limits.absolute_max,
                "disabled": disabled or management_invalid,
            }
        )
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
        """Expose whether the child widget is hidden."""
        return super().is_hidden or bool(self.child_field.widget.is_hidden)

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        """Expose whether the child widget needs multipart form data."""
        return bool(self.child_field.widget.needs_multipart_form)

    @property
    def media(self) -> WidgetMedia:
        """Return widget media including the sequence controller script."""
        media: WidgetMedia = super().media + WidgetMedia(self.Media)
        media += self.child_field.widget.media
        return media
