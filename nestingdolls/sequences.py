from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar, Token
from datetime import datetime, time
from itertools import chain, islice
from types import MappingProxyType, TracebackType
from typing import Any, ClassVar, Self, cast

from django.conf import settings
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
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from nestingdolls._shared import CompositeBoundField, CompositeField, CompositeWidget
from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MissingManagementFormValidationError,
    SequenceInputValidationError,
    TooManyComparisonsError,
    TooManyFormsValidationError,
)

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


class SequenceBoundField(CompositeBoundField):
    """Give the sequence widget the row state that the browser sent.

    Django gives a widget no errors when it renders a bound field. A sequence
    has one error list, but many rows and many child widgets. This class finds
    the row of each error, and it finds the rows that the user deleted. It puts
    that state on the widget before each render, so the field keeps no state of
    its own.
    """

    field: SequenceField

    _over_submission_max: bool = False

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")

    @dataclasses.dataclass(frozen=True)
    class Submitted:
        """Report what the browser sent for the rows of one bound field.

        It reports the rows that the management form declares. It reports the
        rows that the user deleted, the rows that the child widget did not
        find, and the errors of each row. It holds the bound field, and it
        finds each answer one time only. This dataclass has no ``slots``,
        because ``cached_property`` needs the instance dictionary.
        """

        bound_field: SequenceBoundField
        # to_python() is a pure function of value; required=False is
        # unused by it. One shared instance avoids rebuilding a Field
        # for every row.
        deletion_field: ClassVar[BooleanField] = BooleanField(required=False)

        @cached_property
        def management_form(self) -> ManagementForm | None:
            """Build a management form from the canonical sequence input.

            Return None when the input holds no management key. The field then
            uses the normal Django path and does no formset work.
            """
            bf = self.bound_field
            data = bf._data_input
            if not bf.field.widget.keys.has_management_data(data, bf.html_name):
                return None
            management_form = ManagementForm(data, prefix=bf.html_name)
            management_form.full_clean()
            return management_form

        @cached_property
        def deleted(self) -> frozenset[int]:
            """Return submitted deleted rows, as ``BaseFormSet.deleted_forms`` does."""
            bf = self.bound_field
            return frozenset(
                index
                for index in range(len(bf.data))
                if self.deletion_field.to_python(
                    bf._data_input.get(f"{bf.html_name}-{index}-{DELETION_FIELD_NAME}")
                )
            )

        @cached_property
        def omitted(self) -> frozenset[int]:
            """Return the extra rows that the child widget did not find.

            A row can have keys in the input but no value for the child widget.
            Django's formsets ignore such an extra row, and this field does the
            same. A row that matches an initial row stays, because its value
            must not disappear.
            """
            bf = self.bound_field
            field = bf.field
            name = bf.html_name
            data_input = bf._data_input
            file_input = bf._file_input
            if name in data_input or name in file_input:
                return frozenset()
            initial_count = len(field.initial_values(bf.initial))
            row_count = len(bf.data)
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
            """Return the child error messages of each row, by row index."""
            row_errors: dict[int, list[object]] = {}
            for error in self.bound_field._all_errors.as_data():
                if isinstance(error, ItemValidationError) and isinstance(
                    error.item, int
                ):
                    row_errors.setdefault(error.item, []).append(error.child_message)
            return row_errors

    @cached_property
    def submitted(self) -> Submitted:
        """Return what the browser sent for these rows."""
        return self.Submitted(self)

    @cached_property
    def data(self) -> list[object]:
        """Extract rows and retain whether recursive extraction reached its cap."""
        widget = self.field.widget
        with widget.SubmissionCountdown(self.field.limits.submission_max) as countdown:
            rows = widget.value_from_normalized_data(
                self._data_input, self._file_input, self.html_name
            )
        self._over_submission_max = bool(countdown)
        return rows

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the sequence widget the submitted rows, errors, and deletions."""
        if not isinstance(widget, SequenceWidget):
            super()._prepare_widget(widget, only_initial)
        elif only_initial:
            # A hidden initial render must show the initial rows. It shows no
            # errors, and it keeps a row that the user deleted, because
            # _has_changed() compares the current rows with these rows.
            value, management_data = self._hidden_initial_value(widget)
            widget.bound = widget.Bound(
                hidden_initial_value=value, management_data=management_data
            )
        elif self.field.disabled:
            # A disabled field ignores the input everywhere else. The render must
            # ignore it too, or the page contradicts the value that is saved.
            widget.bound = widget.Bound()
        else:
            widget.bound = widget.Bound(
                management_data=self._data_input,
                # The hidden initial branch above must not reuse this
                # field. Its data is the initial input, under a different
                # name.
                management_form=self.submitted.management_form,
                row_errors=self.submitted.errors,
                deleted_indexes=self.submitted.deleted,
            )

    @cached_property
    def initial(self) -> list[object]:
        """Return the initial rows of this field.

        Initial data can use flat row keys, for example ``values-0``. Read
        those keys when the initial data of the form has no key for this field,
        or when the value of that key is a mapping.
        """
        value: object = None
        if self.form.initial and self.name not in self.form.initial:
            value = self._initial_from_flat_keys(self.form.initial)
        if value is None:
            value = super().initial
        if isinstance(value, Mapping) and (
            (normalized := self._initial_from_flat_keys(value)) is not None
        ):
            value = normalized
        try:
            # Read no more than absolute_max rows. A large initial collection
            # must not make a large page.
            value = self.field.initial_values(
                value, limit=self.field.limits.absolute_max
            )
        except InvalidInitialValueError:
            value = [value]
        # A widget that does not show microseconds would send back a different
        # value, and every render would report a change. Django's
        # BoundField.initial removes them for the same reason.
        if not self.field.child_field.widget.supports_microseconds:
            return [
                item.replace(microsecond=0)
                if isinstance(item, (datetime, time))
                else item
                for item in value
            ]
        return value

    def _has_changed(self) -> bool:
        """Report a change when the user deleted a row that the initial holds.

        The rows that the browser sent do not contain a deleted row, and the
        two row counts can still agree. Compare the deleted indexes with the
        number of initial rows instead.
        """
        changed = super()._has_changed()
        if changed or self.field.disabled or not self.submitted.deleted:
            return changed
        # `initial` is a list on every path, so it needs no re-wrapping.
        initial_length = len(self.initial)
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
        """Hold the row limits for one sequence field.

        ``min_length`` and ``max_length`` are user validation limits.
        ``absolute_max`` is the maximum rows that one sequence level can build.
        It stops a forged ``TOTAL_FORMS`` value before child work starts.
        ``submission_max`` is the shared cap for all nested levels in one
        extraction or render.

        Django formsets use ``DEFAULT_MAX_NUM`` as the default ``max_num``.
        They use ``max_num + DEFAULT_MAX_NUM`` as the default ``absolute_max``.
        This field uses the same defaults. Django request limits count keys and
        bytes. Only this field can count rows across nested levels.
        """

        min_length: int
        max_length: int
        absolute_max: int

        def __post_init__(self) -> None:
            if self.min_length < 0:
                raise ValueError("min_length must be non-negative")
            if self.max_length < self.min_length:
                raise ValueError(
                    "max_length must be greater than or equal to min_length"
                )
            if self.max_length > self.absolute_max:
                raise ValueError(
                    "'absolute_max' must be greater or equal to 'max_length'."
                )

        @classmethod
        def build(
            cls, min_length: int, max_length: int, absolute_max: int | None
        ) -> Self:
            """Build limits and use Django's default hard row cap.

            When no cap is given, Django formsets use
            ``max_length + DEFAULT_MAX_NUM``.
            """
            if absolute_max is None:
                absolute_max = max_length + DEFAULT_MAX_NUM
            return cls(min_length, max_length, absolute_max)

        def over_hard_cap(self, count: int) -> bool:
            """Report whether a row count is above the limit on submitted rows."""
            return count > self.absolute_max

        @property
        def submission_max(self) -> int:
            """Return the shared cap for all rows in one submission.

            Django rejects a request with more than
            ``DATA_UPLOAD_MAX_NUMBER_FIELDS`` keys. A populated row needs a
            key, so that setting limits populated rows. It does not limit empty
            rows. One ``TOTAL_FORMS`` key can ask for ``absolute_max`` empty
            rows, such as 2000 unchecked checkbox rows.

            The cap is the larger of ``absolute_max`` and the Django key limit.
            It covers both cases. Read the setting for each submission. If the
            setting is off, use ``DEFAULT_MAX_NUM`` as its fallback.
            """
            # Zero and None are not supported here. Both use Django's default row cap.
            keys = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS or DEFAULT_MAX_NUM
            return max(self.absolute_max, keys)

        def empty_count(self, required: bool) -> int:
            """Return the number of empty rows for a field that has no value.

            A required field shows one row, so that the user can give a value.
            ``min_length`` can ask for more rows, and ``max_length`` limits the
            count.
            """
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
        """Configure a field that holds many values of one child field."""
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        self.limits = self.Limits.build(min_length, max_length, absolute_max)
        if required and max_length == 0:
            # empty_count() renders zero rows and zero controls when
            # max_length is 0. A required field can never be satisfied
            # then. Limits does not know about `required`. So this check
            # belongs here.
            raise ValueError("max_length=0 requires required=False")
        if (
            initial is not None
            and not callable(initial)
            # A mapping initial holds flat row keys, not a collection of
            # rows. SequenceBoundField.initial reads those flat keys.
            and not isinstance(initial, Mapping)
        ):
            try:
                initial_values = self.initial_values(initial)
            except InvalidInitialValueError:
                # Agree with the render path. That path wraps a scalar
                # into one row instead of raising an error during a
                # render.
                initial_values = [initial]
            if len(initial_values) > max_length:
                raise ValueError("initial must not contain more than max_length values")

        # Copy the child field. Two fields must not share one field instance,
        # because a field holds its widget and its own configuration.
        self.child_field = copy.deepcopy(child_field)
        self.child_field.localize = localize

        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, SequenceBoundField):
            raise TypeError("bound_field_class must inherit from SequenceBoundField")
        super().__init__(
            required=required,
            # Django accepts a widget class and copies the instance. The call
            # to configure() below makes that copy match this field.
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
        # Configure the copy that Django made, not the widget that the caller
        # gave.
        self.widget.configure(self.child_field, self.limits)

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy this field, its child field, and the link between them.

        Django deep-copies each field for each form. ``Widget.__deepcopy__``
        makes only a shallow copy. It does not follow ``child_field``.
        ``Field.__deepcopy__`` alone returns a widget that still points
        at the original child field. Two forms then share one child
        field and its widget. This method re-points the copy, to break
        that sharing.

        ``result.widget.limits`` and ``.keys`` need no such fix. Both
        are frozen ``slots`` dataclasses, and neither holds per-form
        state.
        """
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def initial_values(value: object, *, limit: int | None = None) -> list[object]:
        """Return the initial value as a list, or raise ``InvalidInitialValueError``."""
        if value is None or value == "":
            return []
        if (
            isinstance(value, Collection)
            and not isinstance(value, Mapping)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            if limit is not None:
                # Read no more than limit rows, because a large collection must
                # not use memory without a limit.
                return list(islice(value, limit))
            return list(value)
        raise InvalidInitialValueError("initial must be a collection of values")

    def to_python(self, value: object) -> list[object]:
        """Return the value as a list, and refuse a value of another type.

        The widget builds the list of rows. Another type shows that a caller
        gave whole data of the wrong structure.
        """
        if value is None or value == "":
            return []
        if not isinstance(value, list):
            raise SequenceInputValidationError(self.error_messages["invalid"])
        return value

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert each row back from its hidden initial value."""
        # to_python() gives a list of rows here, or raises for other input.
        value = cast(list[object], super().children_from_hidden_initial(value))
        # A file has no text form in a hidden input, so keep the rows of a
        # FileField child as they are.
        if isinstance(self.child_field, FileField):
            return value
        return [self._hidden_initial_to_python(self.child_field, row) for row in value]

    def _clean_values(
        self,
        values: list[object],
        initial_values: list[object],
        deleted_indexes: frozenset[int] = frozenset(),
        omitted_indexes: frozenset[int] = frozenset(),
    ) -> Collection[object]:
        """Clean each row, then validate the result, as ``MultiValueField`` does."""
        if self.limits.over_hard_cap(len(values)):
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
        """Clean caller-supplied values with this field's normal row rules."""
        return self._clean_values(self.to_python(value), [])

    def _clean_bound_field(self, bound_field: BoundField) -> Collection[object]:
        """Clean rows already extracted by the sequence-owned countdown."""
        assert isinstance(bound_field, SequenceBoundField), "for mypy"
        if self.disabled:
            return cast(
                Collection[object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        rows = bound_field.data
        if bound_field._over_submission_max:
            raise TooManyFormsValidationError(
                self.error_messages["too_many_forms"], num=self.limits.max_length
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
            if isinstance(submitted_total, int) and self.limits.over_hard_cap(
                submitted_total
            ):
                raise TooManyFormsValidationError(
                    self.error_messages["too_many_forms"], num=self.limits.max_length
                )
        initial = bound_field.initial
        data = self.to_python(rows)
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

    def compress(self, data: list[object]) -> Collection[object]:
        """Return the cleaned rows as a list.

        A subclass changes the type of the collection here.
        """
        return data

    def bound_data(self, data: object, initial: object) -> Collection[object]:
        """Bind each submitted row against its matching initial value."""
        if self.disabled:
            return self.initial_values(initial)

        data = self.to_python(data)
        # Show no rows for a submission that is too large. The clean step
        # records the too_many_forms error, and no row must reach a child
        # widget.
        if self.limits.over_hard_cap(len(data)):
            return []
        initial = self.initial_values(initial)
        values = []
        for index, value in enumerate(data):
            initial_value = initial[index] if index < len(initial) else None
            try:
                value = self.child_field.bound_data(value, initial_value)
            except (InvalidInitialValueError, ValidationError):
                # BoundField.value() calls this method during a render. A
                # composite child can refuse a bad row here, for example a
                # nested MappingField row submitted as a scalar. The clean
                # step already recorded that error. Django shows the
                # value of an enabled field again, so this method falls
                # back to the base behavior. prepare_value() does the
                # same.
                value = super().bound_data(value, initial_value)
            values.append(value)
        return values

    def prepare_value(self, value: object) -> list[object]:
        """Prepare admitted initial rows for widget rendering.

        Server-provided initial values bypass Django request parsing, so reserve
        before recursive preparation. Rendering clips to the lazy shared maximum
        rather than raising, without discovering every nested field first.
        """
        rows = self.initial_values(value, limit=self.limits.absolute_max)
        with SequenceWidget.SubmissionCountdown(
            self.limits.submission_max
        ) as countdown:
            rows = rows[: countdown.take(len(rows))]
            values = []
            for row in rows:
                try:
                    row = self.child_field.prepare_value(row)
                except (InvalidInitialValueError, ValidationError):
                    # Same render-time fallback as bound_data(). A composite
                    # child can refuse a bad row, for example a nested
                    # MappingField row given as a scalar. Show the row the
                    # way Django does, instead of raising an error
                    # mid-render.
                    row = super().prepare_value(row)
                values.append(row)
            return values

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare submitted rows using child-field change semantics."""
        if self.disabled:
            return False
        if isinstance(data, list) and self.limits.over_hard_cap(len(data)):
            return True
        # A value that no field can read counts as a change. A change that the
        # form misses would lose data, and an extra change costs one save.
        try:
            initial = self.initial_values(initial)
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
        """Match the rows that the browser sent to the initial members.

        A set has no order, so one row can agree with any member. The child
        field decides whether a row and a member are the same, because only it
        knows how it reads its own input. This object claims one member for
        each row that it can match, and it reports whether the rows claimed
        every member. A field builds a new object for each comparison, because
        a claim changes the object. This is the one holder that is not frozen.

        ``members_left`` is the number of members the comparison may still
        look at. An
        attacker controls the rows, up to ``absolute_max``. The members come
        from the server. Without this count, the scan cost is quadratic in a
        number that the attacker picks. This count belongs to one comparison
        only. It is deliberately not the row count of an extraction: a
        comparison must not fail because an earlier extraction built rows.
        """

        child_field: Field
        members: list[object]
        members_left: int = 0
        claimed: set[int] = dataclasses.field(default_factory=set)
        # Members come from a set. They are unique under __hash__/__eq__.
        # So one index per key is enough.
        indexed: dict[object, int] = dataclasses.field(init=False, repr=False)

        def __post_init__(self) -> None:
            # compress() refused an unhashable member already, so every member
            # can go into the index.
            self.indexed = {member: index for index, member in enumerate(self.members)}

        def candidate(self, value: object) -> int | None:
            """Return the member index that hashes equal to one row, if there is one.

            The index only helps when the child's ``to_python()`` agrees with
            its ``clean()``. Members hold cleaned values, and this lookup uses
            the converted row. A coercing child, such as ``TypedChoiceField``
            or ``ModelChoiceField``, always misses the index. It falls back to
            the full scan.

            Return None when the row is unhashable, or matches no member.
            ``claim()`` then reads every member.
            """
            try:
                return self.indexed.get(value)
            except TypeError:
                # A compound child value can be unhashable. Give no candidate,
                # and let claim() do the full scan.
                return None

        def claim(self, row: object, candidate: int | None) -> bool:
            """Claim one member for a row, and report whether it found one.

            Look at an unclaimed member first, so two equal rows never
            compete for the same member. If none of those match, look at
            the claimed members too: duplicate rows collapse into one set
            member, so a repeat of an already-matched row must still count
            as matched, even though it claims nothing new.

            Raise ``TooManyComparisonsError`` when the comparison has looked
            at ``members_left`` members already.
            """
            for index in self.members_to_check(candidate):
                if index in self.claimed:
                    continue
                if self.member_matches(index, row):
                    self.claimed.add(index)
                    return True
            for index in self.members_to_check(candidate):
                if index not in self.claimed:
                    continue
                if self.member_matches(index, row):
                    return True
            return False

        def members_to_check(self, candidate: int | None) -> Iterator[int]:
            """Yield each member index to check, and count each one.

            The hash candidate comes first, because it is usually the only
            member a row has to check. ``has_changed()`` against every member
            is expensive.

            This is lazy on purpose. A row that matches its candidate never
            walks the other members, and it never builds a list of them. The
            count lives here, so no caller can read a member without paying
            for it.
            """
            if candidate is None:
                order: Iterable[int] = range(len(self.members))
            else:
                order = chain(
                    (candidate,),
                    (i for i in range(len(self.members)) if i != candidate),
                )
            for index in order:
                if not self.members_left:
                    raise TooManyComparisonsError("comparison limit reached")
                self.members_left -= 1
                yield index

        def member_matches(self, index: int, row: object) -> bool:
            """Report whether one member equals a row."""
            return not self.child_field.has_changed(self.members[index], row)

        @property
        def complete(self) -> bool:
            """Report whether the submitted rows claimed every member."""
            return len(self.claimed) == len(self.members)

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare semantic set members, not raw row order or raw row spelling.

        This method gets the raw rows of the browser, but the initial members
        are Python values that the field cleaned already. A comparison with
        ``==`` would be wrong for a child field that changes its input, or that
        uses a compound widget.
        """
        if self.disabled:
            return False
        if isinstance(data, list) and self.limits.over_hard_cap(len(data)):
            return True
        try:
            members = list(self.compress(self.initial_values(initial)))
        except (InvalidInitialValueError, ValidationError):
            return True
        try:
            data = self.to_python(data)
        except ValidationError:
            return True

        match = self.Match(
            self.child_field,
            members,
            # Headroom over the hash fast path. A submission that needs more
            # steps than this counts as changed. That is the safe direction.
            # A missed change loses data. An extra change only costs one save.
            members_left=4 * (len(members) + len(data)) + 32,
        )
        try:
            for row in data:
                try:
                    value = self.child_field.to_python(row)
                except (TypeError, ValidationError):
                    return True
                if not match.claim(row, match.candidate(value)) and (
                    self.child_field.has_changed(None, row)
                ):
                    return True
        except (TypeError, ValidationError, TooManyComparisonsError):
            return True
        return not match.complete


class FrozenSetField(SetField):
    """Collect cleaned rows into a frozenset."""

    collection_type = frozenset


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
