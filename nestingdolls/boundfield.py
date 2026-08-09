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
    def _data_input(self) -> Mapping[str, object]:
        """Cache normalized submitted form data for this field."""
        return self.field.widget.keys.normalized(self.form.data, self.html_name)

    @cached_property
    def _file_input(self) -> Mapping[str, object]:
        """Cache normalized submitted files for this field."""
        if not self.form.files:
            return MultiValueDict()
        return self.field.widget.keys.normalized(self.form.files, self.html_name)

    @cached_property
    def data(self) -> object:
        """Return the bound value extracted from normalized data and files."""
        return self.field.widget.value_from_normalized_data(
            self._data_input,
            self._file_input,
            self.html_name,
        )

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
            hidden_initial_value=(
                self._hidden_initial_value(widget)[0] if only_initial else None
            )
        )

    def _hidden_initial_value(
        self, widget: CompositeWidget
    ) -> tuple[object, Mapping[str, object] | None]:
        """Return the submitted hidden initial value and the data it came from.

        Django only propagates a hidden initial when the initial name is a key of
        the submitted data. A composite submits child names instead, so read the
        value here. Django's value would be the current data, which would replace
        the hidden initial and hide a change.

        Only ``SequenceBoundField._prepare_widget`` uses the second element.
        It passes that normalized input into ``SequenceWidget.Bound`` as
        the management data for the hidden initial render. Every other
        caller discards the second element.
        """
        name = self.html_initial_name
        data_input = widget.keys.normalized(self.form.data, name)
        file_input = (
            widget.keys.normalized(self.form.files, name) if self.form.files else {}
        )
        if data_input or file_input:
            return (
                widget.value_from_normalized_data(data_input, file_input, name),
                data_input,
            )
        return self.value(), None

    def _initial_from_flat_keys(self, source: Mapping[str, object]) -> object | None:
        """Return an initial value rebuilt from flattened child keys, if any match."""
        normalized = self.field.widget.keys.normalized(source, self.name)
        if not normalized:
            return None
        value: object = self.field.widget.value_from_normalized_data(
            normalized, {}, self.name
        )
        return value

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
        if self._data_input or self._file_input:
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
            data=self._data_input if is_bound else None,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", self._file_input)
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
        value, _ = self._hidden_initial_value(widget) if only_initial else (None, None)
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

    _over_submission_max: bool = False

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        from nestingdolls.fields import SequenceField

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
