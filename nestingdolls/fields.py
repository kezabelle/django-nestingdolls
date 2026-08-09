from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from itertools import chain, islice
from typing import Self, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import BaseForm, BaseFormSet, Field
from django.forms.boundfield import BoundField
from django.forms.fields import FileField
from django.forms.formsets import DEFAULT_MAX_NUM, DEFAULT_MIN_NUM, TOTAL_FORM_COUNT
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from nestingdolls.boundfield import (
    MappingBoundField,
    SequenceBoundField,
    _ValueBoundField,
)
from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MappingInputValidationError,
    MissingManagementFormValidationError,
    SequenceInputValidationError,
    TooManyComparisonsError,
    TooManyFormsValidationError,
)
from nestingdolls.widgets import CompositeWidget, MappingWidget, SequenceWidget

__all__ = [
    "DictField",
    "FormField",
    "FrozenSequenceField",
    "FrozenSetField",
    "ListField",
    "MappingField",
    "SequenceField",
    "SetField",
    "Subform",
    "TupleField",
]


class CompositeField(Field):
    """Hold the field behavior that mapping and sequence fields share."""

    widget: CompositeWidget

    # Django keeps a widget class here, but it only ever calls this attribute:
    # BoundField.as_hidden() and BoundField._has_changed() do field.hidden_widget().
    # A composite widget needs its child configuration, so build the copy here.
    def hidden_widget(self) -> CompositeWidget:  # type: ignore[override]
        """Return an independent copy of this field's widget that renders hidden."""
        widget = copy.deepcopy(self.widget)
        widget.input_type = "hidden"
        return widget

    @staticmethod
    def _hidden_initial_to_python(field: Field, value: object, /) -> object:
        """Convert what one child's hidden initial widget submitted."""
        if isinstance(field, CompositeField):
            return field.children_from_hidden_initial(value)
        return field.to_python(value)

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert this field's children back from their hidden initial values."""
        return self.to_python(value)


class MappingField(CompositeField):
    """Clean and validate the fixed set of children that one Form declares.

    A mapping has named child fields. It has no row count. A sequence child
    starts and owns its row count.
    """

    widget: MappingWidget
    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a mapping of values."),
    }
    bound_field_class: type[MappingBoundField] = MappingBoundField

    def __init__(
        self,
        form_class: type[BaseForm],
        /,
        *,
        required: bool = True,
        widget: MappingWidget | type[MappingWidget] | None = None,
        label: str | Promise | None = None,
        initial: object | Callable[[], object] | None = None,
        help_text: str | Promise = "",
        error_messages: Mapping[str, str | Promise] | None = None,
        show_hidden_initial: bool = False,
        validators: Sequence[Callable[[dict[str, object]], None]] = (),
        localize: bool = False,
        disabled: bool = False,
        label_suffix: str | None = None,
        template_name: str | None = None,
        bound_field_class: type[MappingBoundField] | None = None,
    ) -> None:
        """Configure a fixed mapping field."""
        if not isinstance(form_class, type) or not issubclass(form_class, BaseForm):
            raise ImproperlyConfigured(
                "form_class argument for MappingField must be a BaseForm subclass"
            )
        # Build the Form one time now. A Form class that needs arguments would
        # fail later, in the middle of a render, and the reason would be hard
        # to find.
        try:
            form_class()
        except TypeError as exc:
            raise ImproperlyConfigured(
                "form_class argument for MappingField must be default-constructible"
            ) from exc
        if initial is not None and not callable(initial):
            self.initial_value(initial)

        self.form_class = form_class
        bound_field_class = bound_field_class or self.bound_field_class
        if not issubclass(bound_field_class, MappingBoundField):
            raise TypeError("bound_field_class must inherit from MappingBoundField")
        super().__init__(
            required=required,
            # Django accepts a widget class and copies the instance. The call
            # to configure() below makes that copy match this field.
            widget=widget or MappingWidget,
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
        if not isinstance(self.widget, MappingWidget):
            raise TypeError("widget must be a MappingWidget instance or subclass")
        # Configure the copy that Django made, not the widget that the caller
        # gave.
        self.widget.configure(form_class)

    @staticmethod
    def initial_value(value: object) -> dict[str, object]:
        """Return the initial value as a dict, or raise ``InvalidInitialValueError``."""
        if value is None or value == "":
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        raise InvalidInitialValueError("initial must be a mapping of values")

    def to_python(self, value: object) -> dict[str, object]:
        """Return the value as a dict, and refuse a value that is not a mapping.

        The widget extracted the children already, so this method does no work
        on keys.
        """
        if value is None or value == "":
            return {}
        if not isinstance(value, Mapping):
            raise MappingInputValidationError(self.error_messages["invalid"])
        return dict(value)

    def children_from_hidden_initial(self, value: object, /) -> object:
        """Convert each member back from its hidden initial value."""
        # to_python() gives a mapping of members here, or raises for other input.
        value = cast(dict[str, object], super().children_from_hidden_initial(value))
        for name, child_field in self.widget.fields.items():
            # A file has no text form in a hidden input, so keep the value of a
            # FileField child as it is.
            if name in value and not isinstance(child_field, FileField):
                value[name] = self._hidden_initial_to_python(child_field, value[name])
        return value

    def _clean_form(self, form: BaseForm) -> dict[str, object]:
        """Return the cleaned data of the child Form, or raise its errors.

        Django keeps the leaf messages of a composite error only, so this
        method makes one ``ItemValidationError`` for each message. Each message
        then keeps the name of the child that it came from.
        """
        if not form.is_valid():
            raise ValidationError(
                [
                    item_error
                    for name, errors in form.errors.as_data().items()
                    for error in errors
                    for item_error in ItemValidationError.for_messages_of(name, error)
                ]
            )
        result: dict[str, object] = form.cleaned_data
        self.validate(result)
        self.run_validators(result)
        return result

    def clean(self, value: object) -> dict[str, object]:
        """Clean a mapping of values that a caller collected.

        The child Form gets ``_ValueBoundField``, because this input holds
        Python values under child names and no prefixed input names. The shared
        budget protects nested sequence rows that bypass Django request parsing.
        """
        value = self.to_python(value)
        if not value:
            return cast(dict[str, object], super().clean(value))
        return self._clean_form(
            self.form_class(
                data=value,
                bound_field_class=_ValueBoundField,
            )
        )

    def _clean_bound_field(self, bound_field: BoundField) -> dict[str, object]:
        """Clean the prefixed child Form of a bound outer form.

        The child Form cleans the input when the browser sent data. It
        also cleans the input when the initial data holds files only.
        Two other cases go back to the normal Django path:

        - A value that is not a mapping. The base field turns this into
          the "invalid" error.
        - An empty value with no bound subform. The base field turns
          this into "required", or into the empty default.

        A nested sequence, not this mapping, owns the aggregate-row budget.
        Django formsets cap each level but not nested-row work.
        """
        assert isinstance(bound_field, MappingBoundField), "for mypy"
        if self.disabled:
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        value = bound_field.data
        if not isinstance(value, Mapping) or (
            not value and not bound_field.is_bound_subform
        ):
            return cast(
                dict[str, object],
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        return self._clean_form(bound_field.subform)

    def bound_data(self, data: object, initial: object) -> object:
        """Bind submitted members with their matching initial values."""
        try:
            initial = self.initial_value(initial)
            if self.disabled:
                return initial
            data = self.to_python(data)
            return {
                name: field.bound_data(data.get(name), initial.get(name))
                for name, field in self.widget.fields.items()
            }
        except (InvalidInitialValueError, ValidationError):
            # BoundField.value() calls this method during a render of an
            # invalid form. Keep forged input in the normal Django channel, so
            # that the user sees what the browser sent.
            return super().bound_data(data, initial)

    def prepare_value(self, value: object) -> object:
        """Prepare each mapping member for widget rendering.

        A nested sequence owns its own render budget before recursive
        preparation, which Django's per-formset limits cannot do.
        """
        try:
            value = self.initial_value(value)
            return {
                name: field.prepare_value(value[name])
                for name, field in self.widget.fields.items()
                if name in value
            }
        except (InvalidInitialValueError, ValidationError):
            return super().prepare_value(value)

    def has_changed(self, initial: object, data: object) -> bool:
        """Compare mapping members using child-field change semantics."""
        if self.disabled:
            return False
        # A value that no field can read counts as a change. A change that the
        # form misses would lose data, and an extra change costs one save.
        try:
            initial = self.initial_value(initial)
            data = self.to_python(data)
        except (InvalidInitialValueError, ValidationError):
            return True
        for name, field in self.widget.fields.items():
            try:
                if field.has_changed(initial.get(name), data.get(name)):
                    return True
            except ValidationError:
                return True
        return False


DictField = MappingField
FormField = MappingField
Subform = MappingField


class SequenceField(CompositeField):
    """Validate a variable-length collection with one homogeneous child field."""

    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a list of values."),
        "missing_management_form": BaseFormSet.default_error_messages[
            "missing_management_form"
        ],
        "too_many_forms": BaseFormSet.default_error_messages["too_many_forms"],
        "submission_too_many_forms": _(
            "Please submit at most %(num)d rows across nested sequences."
        ),
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
        submission = bound_field.submission
        if submission.over_submission_max:
            raise TooManyFormsValidationError(
                self.error_messages["submission_too_many_forms"],
                num=self.limits.submission_max,
            )
        management_form = submission.management_form
        if (
            management_form is None
            and not submission.deleted
            and not submission.omitted
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
        return self._clean_values(data, initial, submission.deleted, submission.omitted)

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
