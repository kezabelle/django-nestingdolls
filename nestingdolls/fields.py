"""Django fields that clean nested mappings and variable-length collections."""

from __future__ import annotations

import copy
import dataclasses
from collections import namedtuple
from collections.abc import Callable, Collection, Mapping, Sequence
from itertools import islice
from typing import TYPE_CHECKING, Self, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import BaseForm, BaseFormSet, Field
from django.forms.fields import FileField
from django.forms.formsets import DEFAULT_MAX_NUM, DEFAULT_MIN_NUM
from django.utils.functional import Promise, cached_property
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from nestingdolls.boundfield import (
    MappingBoundField,
    SequenceBoundField,
    ValueBoundField,
)
from nestingdolls.errors import (
    InvalidInitialValueError,
    ItemValidationError,
    MappingInputValidationError,
    SequenceInputValidationError,
    TooManyFormsValidationError,
)
from nestingdolls.widgets import CompositeWidget, MappingWidget, SequenceWidget

if TYPE_CHECKING:
    from django.forms.boundfield import BoundField

__all__ = [
    "DataclassField",
    "DictField",
    "FormField",
    "FrozenSequenceField",
    "FrozenSetField",
    "ListField",
    "MappingField",
    "NamedTupleField",
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

    def from_hidden_initial(self, value: object, /) -> object:
        """Convert this field's submitted hidden initial back to Python values."""
        return self.to_python(value)

    @staticmethod
    def _child_from_hidden_initial(field: Field, value: object, /) -> object:
        """Convert one child's hidden initial. A file has no text form; keep it."""
        if isinstance(field, FileField):
            return value
        if isinstance(field, CompositeField):
            return field.from_hidden_initial(value)
        return field.to_python(value)


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

    @cached_property
    def _declared_field_names(self) -> tuple[str, ...]:
        """Return the form's declared field names."""
        return tuple(
            cast("Mapping[str, Field]", self.form_class.base_fields)  # type: ignore[attr-defined]
        )

    output: Callable[..., object]

    def _build_output(
        self, output: Callable[..., object] | None
    ) -> Callable[..., object]:
        """Return the callable that builds cleaned output."""
        if output is None:
            return dict
        if not callable(output):
            raise TypeError("output must be callable")
        return output

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
        output: Callable[..., object] | None = None,
        validators: Sequence[Callable[[object], None]] = (),
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
            # Django accepts a widget class and copies the instance. The
            # assignment below makes that copy match this field.
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
        self.widget.form_class = form_class
        self.output = self._build_output(output)

    def initial_value(self, value: object) -> dict[str, object]:
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

    def from_hidden_initial(self, value: object, /) -> object:
        """Convert each member back from its hidden initial value."""
        # to_python() gives a mapping of members here, or raises for other input.
        members = cast("dict[str, object]", super().from_hidden_initial(value))
        for name, child_field in self.widget.fields.items():
            if name in members:
                members[name] = self._child_from_hidden_initial(
                    child_field, members[name]
                )
        return members

    def compress(self, data: dict[str, object]) -> object:
        """Build the cleaned output from the child form data."""
        return self.output(data)

    def _compress_with_defaults(self, data: dict[str, object]) -> object | None:
        """Call ``self.output`` with every declared name filled from ``data``.

        ``NamedTupleField`` and ``DataclassField`` both build their output this
        way: every declared name gets ``None`` unless ``data`` supplies it.
        """
        if not data:
            return None
        return self.output(**(dict.fromkeys(self._declared_field_names) | data))

    def _clean_child_form(self, form: BaseForm) -> object:
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
        result = self.compress(form.cleaned_data)
        self.validate(result)
        self.run_validators(result)
        return result

    def clean(self, value: object) -> object:
        """Clean a mapping of values that a caller collected.

        The child Form gets ``ValueBoundField``, because this input holds
        Python values under child names and no prefixed input names. The shared
        budget protects nested sequence rows that bypass Django request parsing.
        """
        value = self.to_python(value)
        if not value:
            return self.compress(cast("dict[str, object]", super().clean(value)))
        return self._clean_child_form(
            self.form_class(
                data=value,
                bound_field_class=ValueBoundField,
            )
        )

    def _clean_bound_field(self, bound_field: BoundField) -> object:
        """Clean the prefixed child Form of a bound outer form.

        The child Form owns both the narrowed input and its cleaned state. A
        missing or scalar submission has no bound subform, so the base field
        reports the ordinary "invalid" or "required" error.
        """
        if not isinstance(bound_field, MappingBoundField):
            raise TypeError("bound field must be a MappingBoundField")
        if self.disabled:
            return super()._clean_bound_field(bound_field)  # type: ignore[misc]
        if not bound_field.is_bound_subform:
            return super()._clean_bound_field(bound_field)  # type: ignore[misc]
        return self._clean_child_form(bound_field.subform)

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
            # invalid form. Keep forged input in Django's normal redisplay path, so
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


class NamedTupleField(MappingField):
    """Clean a child form into a named tuple."""

    def _build_output(
        self, output: Callable[..., object] | None
    ) -> Callable[..., object]:
        """Return the named tuple class that builds cleaned output."""
        if output is None:
            # A runtime field list cannot be expressed through typing.NamedTuple.
            return cast(
                "type[tuple[object, ...]]",
                namedtuple(  # noqa: PYI024
                    f"{self.form_class.__name__}Value",
                    self._declared_field_names,
                    defaults=(None,) * len(self._declared_field_names),
                ),
            )
        if not (
            isinstance(output, type)
            and issubclass(output, tuple)
            and hasattr(output, "_fields")
        ):
            raise ImproperlyConfigured(
                "output argument for NamedTupleField must be a named tuple class"
            )
        if frozenset(self.widget.fields) != frozenset(
            cast("tuple[str, ...]", output._fields)
        ):
            raise ImproperlyConfigured(
                "form_class fields must match output._fields exactly"
            )
        return output

    def initial_value(self, value: object) -> dict[str, object]:
        """Normalize a named tuple initial value into named child values."""
        as_dict = getattr(value, "_asdict", None)
        return super().initial_value(as_dict() if callable(as_dict) else value)

    def compress(self, data: dict[str, object]) -> tuple[object, ...] | None:
        """Build a named tuple from cleaned child values."""
        return cast("tuple[object, ...] | None", self._compress_with_defaults(data))


class DataclassField(MappingField):
    """Clean a child form into a dataclass."""

    def _build_output(
        self, output: Callable[..., object] | None
    ) -> Callable[..., object]:
        """Return the dataclass that builds cleaned output."""
        if output is None:
            return cast(
                "type[object]",
                dataclasses.make_dataclass(
                    f"{self.form_class.__name__}Value",
                    [
                        (name, object, dataclasses.field(default=None))
                        for name in self._declared_field_names
                    ],
                ),
            )
        if not isinstance(output, type) or not dataclasses.is_dataclass(output):
            raise ImproperlyConfigured(
                "output argument for DataclassField must be a dataclass"
            )
        if any(not field.init for field in dataclasses.fields(output)):
            raise ImproperlyConfigured(
                "output argument for DataclassField must not have init=False fields"
            )
        if frozenset(self.widget.fields) != frozenset(
            field.name for field in dataclasses.fields(output)
        ):
            raise ImproperlyConfigured(
                "form_class fields must match output fields exactly"
            )
        return output

    def initial_value(self, value: object) -> dict[str, object]:
        """Normalize a dataclass initial value into named child values."""
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            value = {
                field.name: getattr(value, field.name)
                for field in dataclasses.fields(value)
            }
        return super().initial_value(value)

    def compress(self, data: dict[str, object]) -> object | None:
        """Build a dataclass from cleaned child values."""
        return self._compress_with_defaults(data)


class SequenceField(CompositeField):
    """Validate a variable-length collection with one homogeneous child field."""

    default_error_messages = {  # noqa: RUF012
        "invalid": _("Enter a list of values."),
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
        ``submission_max`` is the shared cap for all nested levels reached
        from this one field's own extraction or render. It does not reach a
        sibling field. Django gives each formset on a page its own
        ``absolute_max`` too, with no cap shared across formsets; this field
        follows the same precedent for its own sibling fields.

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

        @property
        def submission_max(self) -> int:
            """Return the shared cap for all rows in one field's own submission.

            Django rejects a request with more than
            ``DATA_UPLOAD_MAX_NUMBER_FIELDS`` keys. A populated row needs a
            key, so that setting limits populated rows. It does not limit empty
            rows. One ``TOTAL_FORMS`` key can ask for ``absolute_max`` empty
            rows, such as 2000 unchecked checkbox rows.

            The cap is the larger of ``absolute_max`` and the Django key limit.
            It covers both cases. Read the setting for each submission. If the
            setting is off, use ``DEFAULT_MAX_NUM`` as its fallback.

            This cap belongs to one field's own nested levels only. A form
            with several sequence fields, whether siblings on the form or
            siblings inside one mapping's child form, gives each one its own
            budget. Django does the same: each formset on a page carries its
            own ``absolute_max``, and nothing coordinates a cap across
            formsets. The number of sequence fields on a form is fixed by
            the form's author, not by a submitted request, so this matches
            Django's own accepted cost model rather than adding a new one.
            """
            # Zero and None are not supported here. Both use Django's default row cap.
            keys = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS or DEFAULT_MAX_NUM
            return max(self.absolute_max, keys)

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
        if absolute_max is None:
            # Django formsets use max_num + DEFAULT_MAX_NUM as the default
            # absolute_max. Use the same default here.
            absolute_max = max_length + DEFAULT_MAX_NUM
        self.limits = self.Limits(min_length, max_length, absolute_max)
        if required and max_length == 0:
            # A required field must always be able to show at least one row,
            # so a user can give a value. With max_length=0 it never can.
            # Limits does not know about `required`, so this check belongs
            # here.
            raise ValueError("max_length=0 requires required=False")
        if initial is not None and not callable(initial):
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
            # Django accepts a widget class and copies the instance. The
            # assignments below make that copy match this field.
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
        # gave. Assign limits before child_field: the child_field setter
        # drops the cached row formset class, and the next build reads these
        # limits.
        self.widget.limits = self.limits
        self.widget.child_field = self.child_field

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Copy this field and keep it linked to its widget's child copy.

        ``Field.__deepcopy__`` makes a shallow copy of the field, so the
        copy still names the source child field. The widget deep-copies
        its child through ``memo`` (``SequenceWidget.__deepcopy__``), so
        the deepcopy below returns that same object, and the field and
        its widget copy share one new child.
        """
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        return result

    def initial_values(
        self, value: object, *, limit: int | None = None
    ) -> list[object]:
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

    def from_hidden_initial(self, value: object, /) -> object:
        """Convert each row back from its hidden initial value."""
        # to_python() gives a list of rows here, or raises for other input.
        rows = cast("list[object]", super().from_hidden_initial(value))
        return [self._child_from_hidden_initial(self.child_field, row) for row in rows]

    def _clean_values(
        self,
        values: list[object],
        initial_values: list[object],
    ) -> Collection[object]:
        """Clean each row, then validate the result, as ``MultiValueField`` does."""
        if len(values) > self.limits.absolute_max:
            raise TooManyFormsValidationError(
                self.error_messages["too_many_forms"], num=self.limits.max_length
            )
        cleaned_data: list[object] = []
        errors = []
        for index, value in enumerate(values):
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
        """Clean browser submissions through Django's real row formset."""
        if not isinstance(bound_field, SequenceBoundField):
            raise TypeError("bound field must be a SequenceBoundField")
        if self.disabled:
            return cast(
                "Collection[object]",
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )
        if bound_field.has_whole_value:
            return self._clean_values(bound_field.data, bound_field.initial)
        if not bound_field.is_bound_formset:
            if isinstance(self.child_field, FileField) and bound_field.initial:
                return self._clean_values(
                    [None] * len(bound_field.initial), bound_field.initial
                )
            return cast(
                "Collection[object]",
                super()._clean_bound_field(bound_field),  # type: ignore[misc]
            )

        # Reserve rows once, at extraction, then clean what extraction
        # produced. Reading this flag performs that extraction, so cleaning
        # is never the step that discovers a forged row count: Django's own
        # has_changed() already reaches extraction first on any form that
        # permits empty values. A second scope here would find every row
        # list already built and could only take rows twice.
        if bound_field.submission_overflow:
            raise TooManyFormsValidationError(
                self.error_messages["submission_too_many_forms"],
                num=self.limits.submission_max,
            )
        formset = bound_field.formset
        valid = formset.is_valid()
        if not valid:
            errors: list[ValidationError] = list(formset.non_form_errors().as_data())
            errors.extend(
                item_error
                for index, form in enumerate(formset.forms)
                for field_errors in form.errors.as_data().values()
                for error in field_errors
                for item_error in ItemValidationError.for_messages_of(index, error)
            )
            raise ValidationError(errors)

        deleted_forms = {id(form) for form in formset.deleted_forms}
        cleaned_data: list[object] = []
        for form in formset.forms:
            if id(form) in deleted_forms or (
                form.empty_permitted and not form.has_changed()
            ):
                continue
            cleaned_data.append(form.cleaned_data["value"])
        result = self.compress(cleaned_data)
        self.validate(result)
        self.run_validators(result)
        return result

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
        if len(data) > self.limits.absolute_max:
            return []
        initial = self.initial_values(initial)
        values = []
        for index, value in enumerate(data):
            initial_value = initial[index] if index < len(initial) else None
            try:
                value = self.child_field.bound_data(value, initial_value)  # noqa: PLW2901
            except (InvalidInitialValueError, ValidationError):
                # BoundField.value() calls this method during a render. A
                # composite child can refuse a bad row here, for example a
                # nested MappingField row submitted as a scalar. The clean
                # step already recorded that error. Django shows the
                # value of an enabled field again, so this method falls
                # back to the base behavior. prepare_value() does the
                # same.
                value = super().bound_data(value, initial_value)  # noqa: PLW2901
            values.append(value)
        return values

    def prepare_value(self, value: object) -> list[object]:
        """Prepare admitted initial rows for widget rendering.

        Server-provided initial values bypass Django request parsing, so reserve
        before recursive preparation. Rendering clips to the lazy shared maximum
        rather than raising, without discovering every nested field first.
        """
        rows = self.initial_values(value, limit=self.limits.absolute_max)
        with self.widget.submission_countdown(self.limits.submission_max) as countdown:
            rows = rows[: countdown.take(len(rows))]
            values = []
            for row in rows:
                try:
                    row = self.child_field.prepare_value(row)  # noqa: PLW2901
                except (InvalidInitialValueError, ValidationError):
                    # Same render-time fallback as bound_data(). A composite
                    # child can refuse a bad row, for example a nested
                    # MappingField row given as a scalar. Show the row the
                    # way Django does, instead of raising an error
                    # mid-render.
                    row = super().prepare_value(row)  # noqa: PLW2901
                values.append(row)
            return values

    def has_changed(self, initial: object, data: object) -> bool:  # noqa: C901, PLR0911
        """Compare submitted rows using child-field change semantics."""
        if self.disabled:
            return False
        if isinstance(data, list) and len(data) > self.limits.absolute_max:
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

    def has_changed(self, initial: object, data: object) -> bool:  # noqa: PLR0911
        """Compare set members; anything ambiguous counts as a change.

        Pair each row with the member its converted value hashes to, then
        let the child field compare the pair, because only the child knows
        how it reads its own input. A row that pairs with no member is a
        change, unless the child says the row is blank. The safe direction
        is "changed": a missed change loses data, an extra change costs one
        save. A coercing or compound child, whose converted rows never hash
        to a member (``TypedChoiceField``, ``MultipleChoiceField``),
        therefore reports changed.
        """
        if self.disabled:
            return False
        if isinstance(data, list) and len(data) > self.limits.absolute_max:
            return True
        try:
            members = self.compress(self.initial_values(initial))
            rows = self.to_python(data)
        except (InvalidInitialValueError, ValidationError):
            return True
        # Members are unique under __hash__/__eq__, so one key per member
        # is enough. The dict returns the stored member, not the probe
        # value: JSONField must compare True against "1", not 1.
        paired = {member: member for member in members}
        matched: set[object] = set()
        unmatched = object()
        for row in rows:
            try:
                member = paired.get(self.child_field.to_python(row), unmatched)
            except (TypeError, ValidationError):
                return True
            if member is unmatched:
                if self.child_field.has_changed(None, row):
                    return True
                continue
            if self.child_field.has_changed(member, row):
                return True
            matched.add(member)
        return len(matched) != len(members)


class FrozenSetField(SetField):
    """Collect cleaned rows into a frozenset."""

    collection_type = frozenset
