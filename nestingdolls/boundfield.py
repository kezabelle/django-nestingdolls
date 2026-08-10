from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, Field
from django.forms.boundfield import BoundField
from django.forms.fields import BooleanField
from django.forms.formsets import DELETION_FIELD_NAME, ManagementForm
from django.forms.utils import ErrorList
from django.forms.widgets import Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property
from django.utils.safestring import SafeString

from nestingdolls.errors import InvalidInitialValueError, ItemValidationError
from nestingdolls.widgets import CompositeWidget, MappingWidget, SequenceWidget

if TYPE_CHECKING:
    from nestingdolls.fields import CompositeField, MappingField, SequenceField

__all__ = ["MappingBoundField", "SequenceBoundField"]


class CompositeBoundField(BoundField):
    """Hold the bound-field behavior that mapping and sequence fields share."""

    field: CompositeField

    @property
    def _all_errors(self) -> ErrorList:
        """Return every error recorded for this field, child item errors included."""
        return super().errors

    @cached_property
    def errors(self) -> ErrorList:
        """Return only errors owned by the outer composite field.

        An item error belongs to one child. The subform or the row renders
        that error next to the input that caused it. This method removes
        child item errors from the outer field, so the user does not see
        the same problem twice.
        """
        errors = self._all_errors
        if not errors:
            return errors
        stored = errors.as_data()
        field_errors = [
            error for error in stored if not isinstance(error, ItemValidationError)
        ]
        # Compare against as_data(). ErrorList.__len__ counts rendered
        # messages. One stored error can carry several messages.
        if len(field_errors) == len(stored):
            return errors
        return self.form.error_class(
            field_errors,
            renderer=self.form.renderer,
            field_id=self.auto_id,
        )

    @cached_property
    def input(self) -> CompositeWidget.Input:
        """Cache this field's canonical submission cohort."""
        return self.field.widget.read_input(
            self.form.data, self.form.files, self.html_name
        )

    @cached_property
    def data(self) -> object:
        """Return the value extracted from the cached submission cohort."""
        return self.field.widget.value_from_input(self.input, self.html_name)

    def as_widget(
        self,
        widget: Widget | None = None,
        attrs: dict[str, str | bool] | None = None,
        only_initial: bool = False,
    ) -> SafeString:
        """Give the widget the submitted state, then let Django render it."""
        widget = widget or self.field.widget
        if isinstance(widget, CompositeWidget):
            self._prepare_widget(widget, only_initial)
        return super().as_widget(widget, attrs, only_initial)

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Put the submitted state this render needs on the widget."""
        widget.bound = widget.Bound(
            hidden_initial_value=self._hidden_initial_value(widget)
            if only_initial
            else None
        )

    def _hidden_initial_value(self, widget: CompositeWidget) -> object:
        """Return a hidden initial rebuilt from the submitted composite keys."""
        name = self.html_initial_name
        input = widget.read_input(self.form.data, self.form.files, name)
        if input.data or input.files:
            return widget.value_from_input(input, name)
        return self.value()

    def _initial_from_flat_keys(self, source: Mapping[str, object]) -> object | None:
        """Return an initial value rebuilt from flattened child keys, if present."""
        input = self.field.widget.read_input(source, {}, self.name)
        if not input.data and not input.files:
            return None
        return self.field.widget.value_from_input(input, self.name)

    def _has_changed(self) -> bool:
        """Read hidden composite initial values through the composite widget."""
        if self.field.disabled:
            return False
        if not self.field.show_hidden_initial:
            return cast(bool, super()._has_changed())  # type: ignore[misc]
        widget = self.field.hidden_widget()
        try:
            initial = self.field.children_from_hidden_initial(
                widget.value_from_datadict(
                    self.form.data, self.form.files, self.html_initial_name
                )
            )
        except ValidationError:
            return True
        return self.field.has_changed(initial, self.data)


class _ValueBoundField(BoundField):
    """Read one child value that the mapping field extracted already.

    ``MappingField.clean()`` builds the child Form from a dict of Python
    values, and that dict has no prefixed input names. Django's
    ``BoundField.data`` reads the widget of the child, so it would find
    nothing. This class reads the child name from the dict instead.

    Only two callers reach this path: a direct ``field.clean(dict)`` call,
    or a ``SequenceField`` parent that cleans one row. A bound outer form
    uses ``_clean_bound_field`` and the prefixed subform instead. So this
    path is not a hot path.
    """

    @property
    def data(self) -> object:
        return self.form.data.get(self.name)


class MappingBoundField(CompositeBoundField):
    """Bind and render the child Form of a mapping field.

    The child Form keeps its own errors beside its own fields. The outer field
    does not repeat them.
    """

    field: MappingField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        from nestingdolls.fields import MappingField

        super().__init__(form, field, name)
        if not isinstance(self.field, MappingField):
            raise TypeError("field must be a MappingField")

    @cached_property
    def initial(self) -> object:
        """Return the initial mapping, and keep an unusable value as it is.

        Initial data can use flat child keys, for example ``address-city``.
        Read those keys when the initial data of the form has no key for this
        field. Initial data uses the field's own ``name`` as its key.
        Submitted data uses ``html_name`` instead. So this method reads
        ``self.name``, while ``_data_input`` reads ``self.html_name``.
        """
        if self.form.initial and self.name not in self.form.initial:
            value = self._initial_from_flat_keys(self.form.initial)
            if isinstance(value, Mapping) and value:
                return self.field.initial_value(value)
        value = super().initial
        try:
            return self.field.initial_value(value)
        except InvalidInitialValueError:
            # Do not raise during a render. The widget can render a wrong
            # initial value, and validation reports the problem to the user.
            return value

    @cached_property
    def is_bound_subform(self) -> bool:
        """Report whether the child Form must bind the data and the files.

        A browser sends no file input when the user selects no file. If the
        initial data holds files, the Form still binds, so that the child
        ``FileField`` can keep the file or clear it.

        A value that is not a ``Mapping`` means the caller sent a scalar
        under this field's name. There are no children to distribute that
        scalar over. So the subform must not bind. ``to_python`` reports
        the "invalid" error instead.
        """
        if not self.form.is_bound:
            return False
        if self.field.disabled:
            return False
        if not isinstance(self.data, Mapping):
            return False
        if self.input.data or self.input.files:
            return True
        return (
            isinstance(self.initial, dict)
            and bool(self.initial)
            and self.field.widget.needs_multipart_form
        )

    @cached_property
    def subform(self) -> BaseForm:
        """Return the child Form for the clean step and for the render."""
        is_bound = self.is_bound_subform
        initial = self.initial
        subform = self.field.form_class(
            data=self.input.data if is_bound else None,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", self.input.files)
            if is_bound
            else None,
            initial=initial if isinstance(initial, dict) else {},
            prefix=self.html_name,
            auto_id=self.form.auto_id,
            use_required_attribute=(
                self.field.required and self.form.use_required_attribute
            ),
            renderer=self.form.renderer,
        )
        # Django does not give ``disabled`` to a child field, so set it on each
        # one. A disabled child keeps its initial value and ignores the input.
        if self.field.disabled:
            for field in subform.fields.values():
                field.disabled = True
        return subform

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the mapping widget the child Form that holds the bound data."""
        if not isinstance(widget, MappingWidget):
            return super()._prepare_widget(widget, only_initial)
        # A hidden initial render must not use the bound child Form, because
        # that Form holds the prefix and the data of the visible render.
        value = self._hidden_initial_value(widget) if only_initial else None
        widget.bound = widget.Bound(
            hidden_initial_value=value,
            subform=None if only_initial else self.subform,
        )


class SequenceBoundField(CompositeBoundField):
    """Give the sequence widget the row state that the browser sent.

    Django gives a widget no errors when it renders a bound field. A sequence
    has one error list, but many rows and many child widgets. This class finds
    the row of each error, and it finds the rows that the user deleted. It puts
    that state on the widget before each render, so the field keeps no state of
    its own.
    """

    field: SequenceField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        from nestingdolls.fields import SequenceField

        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")

    @dataclasses.dataclass(frozen=True)
    class Submission:
        """Hold the one parsed request cohort and derived sequence state."""

        bound_field: SequenceBoundField
        deletion_field: ClassVar[BooleanField] = BooleanField(required=False)
        rows: list[object] = dataclasses.field(init=False)
        over_submission_max: bool = dataclasses.field(init=False)

        def __post_init__(self) -> None:
            bf = self.bound_field
            widget = bf.field.widget
            with widget.SubmissionCountdown(
                bf.field.limits.submission_max
            ) as countdown:
                rows = widget.value_from_input(bf.input, bf.html_name)
            object.__setattr__(self, "rows", rows)
            object.__setattr__(self, "over_submission_max", bool(countdown))

        @property
        def input(self) -> SequenceWidget.Input:
            """Return the already-cached, sequence-specific input cohort."""
            input = self.bound_field.input
            assert isinstance(input, SequenceWidget.Input)
            return input

        @property
        def management_form(self) -> ManagementForm | None:
            return self.input.management_form

        @cached_property
        def deleted(self) -> frozenset[int]:
            """Return rows marked for deletion."""
            bf = self.bound_field
            return frozenset(
                index
                for index in range(len(self.rows))
                if self.deletion_field.to_python(
                    self.input.data.get(f"{bf.html_name}-{index}-{DELETION_FIELD_NAME}")
                )
            )

        @cached_property
        def omitted(self) -> frozenset[int]:
            """Return extra rows that their child widget considers omitted."""
            if self.input.direct_rows is not None:
                return frozenset()
            bf = self.bound_field
            widget = bf.field.widget
            child_widget = widget._child_widget(widget.child_field)
            initial_count = len(bf.field.initial_values(bf.initial))
            omitted: set[int] = set()
            # A composite child's read_input() below can build its own nested
            # rows, so share one countdown across every row instead of
            # letting each one spend a fresh budget.
            with widget.SubmissionCountdown(bf.field.limits.submission_max):
                for index, (data, files) in enumerate(
                    zip(self.input.data_rows, self.input.file_rows, strict=True)
                ):
                    if index < initial_count:
                        continue
                    name = f"{bf.html_name}-{index}"
                    if isinstance(child_widget, CompositeWidget):
                        child_input = child_widget.read_input(data, files, name)
                        is_omitted = not child_input.data and not child_input.files
                    else:
                        is_omitted = child_widget.value_omitted_from_data(
                            data,
                            cast("MultiValueDict[str, UploadedFile[Any]]", files),
                            name,
                        )
                    if is_omitted:
                        omitted.add(index)
            return frozenset(omitted)

        @cached_property
        def errors(self) -> Mapping[int, list[object]]:
            """Return child error messages by row index."""
            row_errors: dict[int, list[object]] = {}
            for error in self.bound_field._all_errors.as_data():
                if isinstance(error, ItemValidationError) and isinstance(
                    error.item, int
                ):
                    row_errors.setdefault(error.item, []).append(error.child_message)
            return row_errors

    @cached_property
    def submission(self) -> Submission:
        """Return the one bound-request cohort for this sequence."""
        return self.Submission(self)

    @cached_property
    def data(self) -> list[object]:
        """Return extracted rows unless nested extraction exceeded its budget."""
        return [] if self.submission.over_submission_max else self.submission.rows

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the sequence widget its cached input, errors, and deletions."""
        if not isinstance(widget, SequenceWidget):
            super()._prepare_widget(widget, only_initial)
        elif only_initial:
            name = self.html_initial_name
            input = widget.read_input(self.form.data, self.form.files, name)
            assert isinstance(input, SequenceWidget.Input)
            widget.bound = widget.Bound(
                hidden_initial_value=(
                    widget.value_from_input(input, name)
                    if input.data or input.files
                    else self.value()
                ),
                management_input=input.data if input.data else None,
                management_form=input.management_form,
            )
        elif self.field.disabled:
            widget.bound = widget.Bound()
        else:
            submission = self.submission
            widget.bound = widget.Bound(
                management_input=submission.input.data,
                management_form=submission.management_form,
                row_errors=submission.errors,
                deleted_indexes=submission.deleted,
                submission_overflow=submission.over_submission_max,
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
        if changed or self.field.disabled or not self.submission.deleted:
            return changed
        initial_length = len(self.initial)
        return any(index < initial_length for index in self.submission.deleted)
