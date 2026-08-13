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

    @cached_property
    def errors(self) -> ErrorList:
        """Return only errors owned by the outer composite field.

        An item error belongs to one child. The subform or the row renders
        that error next to the input that caused it. This method removes
        child item errors from the outer field, so the user does not see
        the same problem twice. ``super().errors`` holds every recorded
        error, child item errors included.
        """
        errors = super().errors
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
    def data(self) -> object:
        """Extract the submitted composite value exactly once."""
        return self.field.widget.value_from_datadict(
            self.form.data, self.form.files, self.html_name
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
            if only_initial:
                # Django propagates a hidden initial only when the exact
                # html_initial_name key was submitted. A composite hidden
                # initial spans many keys, so rebuild it here instead.
                widget.render_state = widget.RenderState(
                    hidden_initial_value=self._hidden_initial_value(widget)
                )
            else:
                self.prepare_widget(widget)
        return super().as_widget(widget, attrs, only_initial)

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Put the submitted state this render needs on the widget."""
        widget.render_state = widget.RenderState()

    def _hidden_initial_value(self, widget: CompositeWidget) -> object:
        """Return a hidden initial rebuilt from the submitted composite keys."""
        name = self.html_initial_name
        if widget.value_omitted_from_data(self.form.data, self.form.files, name):
            return self.value()
        return widget.value_from_datadict(self.form.data, self.form.files, name)

    def _has_changed(self) -> bool:
        """Read hidden composite initial values through the composite widget.

        This mirrors ``BoundField._has_changed`` with ``from_hidden_initial``
        in place of ``to_python``. The ``disabled`` early return must stay:
        a disabled field reports no change before the conversion can raise.
        """
        if self.field.disabled:
            return False
        if not self.field.show_hidden_initial:
            return cast(bool, super()._has_changed())  # type: ignore[misc]
        widget = self.field.hidden_widget()
        try:
            initial = self.field.from_hidden_initial(
                widget.value_from_datadict(
                    self.form.data, self.form.files, self.html_initial_name
                )
            )
        except ValidationError:
            return True
        return self.field.has_changed(initial, self.data)


class ValueBoundField(BoundField):
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
        """Return the initial mapping, and keep an unusable value as it is."""
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
        widget = self.field.widget
        if widget.has_child_keys(self.form.data, self.html_name) or (
            widget.has_child_keys(self.form.files, self.html_name)
        ):
            return True
        # A whole value is the value under this field's own exact key.
        whole_value = None
        if self.html_name in self.form.data:
            whole_value = self.form.data.get(self.html_name)
        elif self.html_name in self.form.files:
            whole_value = self.form.files.get(self.html_name)
        if whole_value is not None:
            return isinstance(whole_value, Mapping)
        return (
            isinstance(self.initial, dict)
            and bool(self.initial)
            and widget.needs_multipart_form
        )

    @cached_property
    def subform(self) -> BaseForm:
        """Return the child Form for the clean step and for the render."""
        is_bound = self.is_bound_subform
        initial = self.initial
        data, files = self.field.widget.expand_whole_values(
            self.form.data, self.form.files, self.html_name
        )
        subform = self.field.form_class(
            data=data if is_bound else None,
            files=cast("MultiValueDict[str, UploadedFile[Any]]", files)
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

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Give the mapping widget the child Form that holds the bound data."""
        if not isinstance(widget, MappingWidget):
            return super().prepare_widget(widget)
        widget.render_state = widget.RenderState(
            subform=self.subform,
            initial_error=(
                str(self.field.error_messages["invalid"])
                if self.initial is not None and not isinstance(self.initial, Mapping)
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
        self._submission_overflow = False

    @cached_property
    def is_bound_formset(self) -> bool:
        """Report whether the browser submission binds the row formset."""
        if not self.form.is_bound or self.field.disabled or self.has_whole_value:
            return False
        widget = self.field.widget
        return any(
            widget.has_row_keys(source, self.html_name)
            or widget.has_management_keys(source, self.html_name)
            for source in (self.form.data, self.form.files)
        )

    @cached_property
    def has_whole_value(self) -> bool:
        """Report whether a whole value sits under this field's own exact key.

        Submitted row keys outrank the exact key, so a forged exact-name
        key cannot replace real rows.
        """
        widget = self.field.widget
        if widget.has_row_keys(self.form.data, self.html_name) or (
            widget.has_row_keys(self.form.files, self.html_name)
        ):
            return False
        return self.html_name in self.form.data or self.html_name in self.form.files

    @cached_property
    def formset(self) -> BaseFormSet[Any]:
        """Return the cached, prefix-aware row formset for cleaning and rendering."""
        initial_values = self.data if self.has_whole_value else self.initial
        initial = self.field.widget.initial_rows(initial_values)
        if (
            not initial
            and self.field.required
            and self.field.limits.min_length == 0
            and not self.is_bound_formset
        ):
            initial = [self.field.widget.empty_initial_row()]
        data: Mapping[str, object] | None
        files: MultiValueDict[str, UploadedFile[Any]] | None
        if self.has_whole_value and self.form.is_bound and not self.field.disabled:
            # A whole value carries no prefixed row keys, so the row
            # formset would otherwise stay unbound and could never show
            # its own row errors: Django gives an unbound form empty
            # errors, always, on purpose. Give each row its own key
            # instead, so the formset binds for real.
            data = self.field.widget.data_from_whole_value(self.data, self.html_name)
            files = MultiValueDict()
        else:
            data = self.form.data if self.is_bound_formset else None
            files = self.form.files if self.is_bound_formset else None
        formset = self.field.widget.new_formset(
            data=data,
            files=files,
            initial=initial,
            prefix=self.html_name,
            auto_id=cast(str, self.form.auto_id),
            form_kwargs={"use_required_attribute": False},
        )
        return formset

    @cached_property
    def data(self) -> list[object]:
        """Return a whole sequence value or formset row values."""
        if self.has_whole_value:
            return self.field.widget.value_from_datadict(
                self.form.data, self.form.files, self.html_name
            )
        if not self.is_bound_formset:
            return []
        with self.field.widget.submission_countdown(
            self.field.limits.submission_max
        ) as countdown:
            rows = [form["value"].data for form in self.formset.forms]
        if countdown.owns_scope and countdown:
            # Extraction ran out. Only the scope that owns the shared
            # counter records it, so cleaning reports one error for the
            # whole submission instead of one child item error per row.
            self._submission_overflow = True
        return rows

    @property
    def submission_overflow(self) -> bool:
        """Report whether extracting this field's rows ran out of the budget.

        Reading ``data`` is the step that reserves rows, so read it here.
        Every caller therefore gets an answer about a finished extraction,
        and no caller can clean or render rows that nothing reserved. The
        read is cached, so asking twice costs nothing and reserves nothing
        a second time.
        """
        _ = self.data
        return self._submission_overflow

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Give the sequence widget the formset that owns row state."""
        if not isinstance(widget, SequenceWidget):
            return super().prepare_widget(widget)
        if self.field.disabled:
            widget.render_state = widget.RenderState()
            return
        widget.render_state = widget.RenderState(
            formset=self.formset, submission_overflow=self.submission_overflow
        )

    def value(self) -> object:
        """Let the row formset, not Field.prepare_value(), prepare row values."""
        return self.initial

    @cached_property
    def initial(self) -> list[object]:
        """Return the initial rows of this field."""
        value: object = super().initial
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
        changed = (
            self.field.has_changed(self.initial, self.data)
            if self.has_whole_value
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
