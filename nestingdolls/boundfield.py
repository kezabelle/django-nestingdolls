from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm, BaseFormSet, Field
from django.forms.boundfield import BoundField
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
        widget.render_state = widget.RenderState(
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
        input = self.input
        if (
            self.html_name in input.data
            and not isinstance(input.data.get(self.html_name), Mapping)
        ) or (
            self.html_name in input.files
            and not isinstance(input.files.get(self.html_name), Mapping)
        ):
            return False
        if input.data or input.files:
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

    def _has_changed(self) -> bool:
        """Delegate change detection to the mapping's own bound child Form."""
        if self.field.disabled:
            return False
        if self.field.show_hidden_initial:
            return super()._has_changed()
        return self.subform.has_changed()

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the mapping widget the child Form that holds the bound data."""
        if not isinstance(widget, MappingWidget):
            return super()._prepare_widget(widget, only_initial)
        # A hidden initial render must not use the bound child Form, because
        # that Form holds the prefix and the data of the visible render.
        value = self._hidden_initial_value(widget) if only_initial else None
        widget.render_state = widget.RenderState(
            hidden_initial_value=value,
            subform=None if only_initial else self.subform,
            initial_error=(
                str(self.field.error_messages["invalid"])
                if not only_initial
                and self.initial is not None
                and not isinstance(self.initial, Mapping)
                else None
            ),
        )


class SequenceBoundField(CompositeBoundField):
    """Bind one sequence to its Django row formset."""

    field: SequenceField

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        from nestingdolls.fields import SequenceField

        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")
        self.submission_overflow = False

    @cached_property
    def is_bound_formset(self) -> bool:
        """Report whether the narrowed browser submission binds a formset."""
        input = self.input
        return (
            self.form.is_bound
            and not self.field.disabled
            and self.html_name not in input.data
            and self.html_name not in input.files
            and bool(input.data or input.files)
        )

    @cached_property
    def formset(self) -> BaseFormSet[Any]:
        """Return the cached, prefix-aware row formset for cleaning and rendering."""
        input = self.input
        has_unflattened_value = (
            self.html_name in input.data or self.html_name in input.files
        )
        initial_values = self.data if has_unflattened_value else self.initial
        initial = self.field.widget._initial_formset_rows(initial_values)
        if (
            not initial
            and self.field.required
            and self.field.limits.min_length == 0
            and not self.is_bound_formset
        ):
            initial = [self.field.widget._empty_formset_row()]
        formset = self.field.widget._new_formset(
            data=input.data if self.is_bound_formset else None,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", input.files)
            if self.is_bound_formset
            else None,
            initial=initial,
            prefix=self.html_name,
            auto_id=cast(str, self.form.auto_id),
            form_kwargs={"use_required_attribute": False},
        )
        return formset

    @cached_property
    def data(self) -> list[object]:
        """Return a whole sequence value or formset row values."""
        input = self.input
        has_unflattened_value = (
            self.html_name in input.data or self.html_name in input.files
        )
        if has_unflattened_value:
            return self.field.widget.value_from_input(input, self.html_name)
        if not self.is_bound_formset:
            return []
        values: list[object] = []
        for form in self.formset.forms:
            values.append(form["value"].data)
        return values

    def _prepare_widget(self, widget: CompositeWidget, only_initial: bool) -> None:
        """Give the sequence widget the formset that owns row state."""
        if not isinstance(widget, SequenceWidget):
            return super()._prepare_widget(widget, only_initial)
        if only_initial:
            widget.render_state = widget.RenderState(
                hidden_initial_value=self._hidden_initial_value(widget)
            )
        elif self.field.disabled:
            widget.render_state = widget.RenderState()
        else:
            widget.render_state = widget.RenderState(
                formset=self.formset, submission_overflow=self.submission_overflow
            )

    def value(self) -> object:
        """Let the row formset, not Field.prepare_value(), prepare row values."""
        return self.initial

    @cached_property
    def initial(self) -> list[object]:
        """Return the initial rows of this field."""
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
            value = self.field.initial_values(
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
        """Report whole-value edits and row-formset deletions."""
        input = self.input
        has_unflattened_value = (
            self.html_name in input.data or self.html_name in input.files
        )
        changed = (
            self.field.has_changed(self.initial, self.data)
            if has_unflattened_value
            else super()._has_changed()
        )
        if changed or self.field.disabled:
            return changed
        deleted_forms = set(self.formset.deleted_forms)
        return any(
            index < len(self.initial)
            for index, form in enumerate(self.formset.forms)
            if form in deleted_forms
        )
