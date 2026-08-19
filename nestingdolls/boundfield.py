"""Bound-field implementations for composite mapping and sequence values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import TYPE_CHECKING, cast

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property

from nestingdolls.errors import InvalidInitialValueError, ItemValidationError
from nestingdolls.widgets import (
    CompositeWidget,
    MappingWidget,
    SequenceWidget,
    row_value_name,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
    from django.forms import BaseForm, BaseFormSet, Field
    from django.forms.utils import ErrorList
    from django.forms.widgets import Widget
    from django.utils.safestring import SafeString

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
        only_initial: bool = False,  # noqa: FBT001, FBT002
    ) -> SafeString:
        """Give the widget the submitted state, then let Django render it."""
        widget = widget or self.field.widget
        if isinstance(widget, CompositeWidget):
            if only_initial:
                # Django propagates a hidden initial only when the exact
                # html_initial_name key was submitted. A composite hidden
                # initial spans many keys, so rebuild it here instead.
                name = self.html_initial_name
                if widget.value_omitted_from_data(
                    self.form.data, self.form.files, name
                ):
                    value = self.value()
                else:
                    value = widget.value_from_datadict(
                        self.form.data, self.form.files, name
                    )
                widget.render_state = widget.RenderState(hidden_initial_value=value)
            else:
                self.prepare_widget(widget)
        return super().as_widget(widget, attrs, only_initial)

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Put the submitted state this render needs on the widget."""
        widget.render_state = widget.RenderState()

    def _has_changed(self) -> bool:
        """Read hidden composite initial values through the composite widget.

        This mirrors ``BoundField._has_changed`` with ``from_hidden_initial``
        in place of ``to_python``. The ``disabled`` early return must stay:
        a disabled field reports no change before the conversion can raise.
        """
        if self.field.disabled:
            return False
        if not self.field.show_hidden_initial:
            return cast("bool", super()._has_changed())  # type: ignore[misc]
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
        from nestingdolls.fields import MappingField  # noqa: PLC0415

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
        mapping accepts files and has initial data, the Form still binds.
        A child ``FileField`` can then keep its file or clear it.

        A value that is not a ``Mapping`` means the caller sent a scalar
        under this field's name. There are no children to distribute that
        scalar over. So the subform must not bind. ``to_python`` reports
        the "invalid" error instead.
        """
        if not self.form.is_bound or self.field.disabled:
            return False
        widget = self.field.widget
        if widget.has_child_keys(self.form.data, self.form.files, self.html_name):
            return True
        # An exact value is the value under this field's own name.
        exact_value = None
        if self.html_name in self.form.data:
            exact_value = self.form.data.get(self.html_name)
        elif self.html_name in self.form.files:
            exact_value = self.form.files.get(self.html_name)
        if exact_value is not None:
            return isinstance(exact_value, Mapping)
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
        data: Mapping[str, object] | None = None
        files: Mapping[str, object] | None = None
        if is_bound:
            data, files = self.field.widget.expand_exact_inputs(
                self.form.data, self.form.files, self.html_name
            )
        subform = self.field.form_class(
            data=data,
            files=files,  # type: ignore[arg-type]  # Django accepts a Mapping here.
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

    @cached_property
    def data(self) -> object:
        """Read bound child values through the subform that owns them."""
        if self.is_bound_subform:
            return {name: self.subform[name].data for name in self.subform.fields}
        return super().data

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
            super().prepare_widget(widget)
            return
        initial_error = None
        if self.initial is not None and not isinstance(self.initial, Mapping):
            initial_error = str(self.field.error_messages["invalid"])
        widget.render_state = widget.RenderState(
            subform=self.subform, initial_error=initial_error
        )

    def value(self) -> object:
        """Let the child Form, not Field.bound_data(), prepare bound values.

        ``MappingWidget.get_context`` renders bound values from ``subform``
        and does not read the value from this method. The base behavior
        extracts the exact mapping to compute that unread value, and the
        extraction builds a second row formset for each nested sequence.
        Return the initial value instead to remove that unnecessary work.
        ``SequenceBoundField.value`` makes the same decision for rows.

        A scalar or missing submission binds no subform. Keep the base
        behavior for it: the user must see that submission again.
        """
        if self.is_bound_subform:
            return self.initial
        return super().value()


class SequenceBoundField(CompositeBoundField):
    """Bind one sequence to its Django row formset."""

    field: SequenceField

    # Cleaning and rendering both ask about overflow after extraction closed
    # its countdown scope, so extraction leaves this one answer behind. A
    # sequence with no input at all renders its initial rows without
    # extracting, so the answer must exist before extraction runs.
    _submission_overflow = False

    def __init__(self, form: BaseForm, field: Field, name: str) -> None:
        from nestingdolls.fields import SequenceField  # noqa: PLC0415

        super().__init__(form, field, name)
        if not isinstance(self.field, SequenceField):
            raise TypeError("field must be a SequenceField")

    @cached_property
    def is_bound_formset(self) -> bool:
        """Report whether the browser submission binds the row formset."""
        if not self.form.is_bound or self.field.disabled:
            return False
        return self.field.widget.is_bound_formset(
            self.form.data, self.form.files, self.html_name
        )

    @cached_property
    def has_exact_input(self) -> bool:
        """Report whether input exists under this field's exact name.

        Indexed row keys outrank exact input, but exact input still decides
        whether management keys alone bind the formset.
        """
        return self.html_name in self.form.data or self.html_name in self.form.files

    @cached_property
    def formset(self) -> BaseFormSet[BaseForm]:
        """Return the cached, prefix-aware row formset for cleaning and rendering."""
        widget = self.field.widget
        if self.field.disabled or (
            not self.has_exact_input and not self.is_bound_formset
        ):
            return widget.new_formset(
                initial=widget.default_initial_rows(self.initial),
                prefix=self.html_name,
                auto_id=cast("str", self.form.auto_id),
                form_kwargs={"use_required_attribute": False},
            )

        exact_values: list[object] | None = None
        with widget.submission_countdown.open(
            self.field.limits.submission_max, raises=True
        ) as countdown:
            data: Mapping[str, object] | None = None
            files: MultiValueDict[str, UploadedFile[bytes]] | None = None
            initial = widget.default_initial_rows(self.initial)
            if self.is_bound_formset:
                data = self.form.data
                files = cast(
                    "MultiValueDict[str, UploadedFile[bytes]]", self.form.files
                )
                initial = widget.initial_rows(self.initial)
            else:
                value = widget.value_from_datadict(
                    self.form.data, self.form.files, self.html_name
                )
                if isinstance(value, list):
                    exact_values = value
                    data = widget.data_from_exact_list(value, self.html_name)
                    # Exact data wins over files. Copy files only from their source.
                    files = MultiValueDict()
                    if (
                        self.html_name not in self.form.data
                        and self.html_name in self.form.files
                    ):
                        files = MultiValueDict(
                            {
                                f"{self.html_name}-{index}": [file]
                                for index, file in enumerate(value)
                            }
                        )

            formset = widget.new_formset(
                data=data,
                files=files,
                initial=initial,
                prefix=self.html_name,
                auto_id=cast("str", self.form.auto_id),
                form_kwargs={"use_required_attribute": False},
                # Generated exact-list rows already used this budget.
                submission_total_form_count=(
                    len(exact_values) if exact_values is not None else None
                ),
            )
            for form in formset.forms:
                _ = form[row_value_name].data
        if countdown.overflowed:
            # The forged claim's rows were never finished. Replace them with a
            # bound zero-row formset, so no later reader can rebuild them:
            # TOTAL_FORMS=0 keeps the formset bound, which keeps the data
            # property's exact-input branch inert. Only the owning open()
            # records overflow, and a nested overdraw unwinds past this point,
            # so cleaning raises one error for the whole submission instead of
            # one child item error per row.
            formset = widget.new_formset(
                data=widget.data_from_exact_list([], self.html_name),
                prefix=self.html_name,
                auto_id=cast("str", self.form.auto_id),
                form_kwargs={"use_required_attribute": False},
                submission_total_form_count=0,
            )
        self._submission_overflow = countdown.overflowed
        return formset

    @cached_property
    def data(self) -> object:
        """Return exact input or formset row values.

        The formset owns bound extraction and reads nested row data while its
        countdown is open. These cached reads do not reserve the rows again,
        and extraction replaced a forged claim's rows with a bound zero-row
        formset, so there is no overflow case to test here.
        """
        if not self.has_exact_input and not self.is_bound_formset:
            return []
        formset = self.formset
        if self.has_exact_input and not formset.is_bound:
            return self.field.widget.value_from_datadict(
                self.form.data, self.form.files, self.html_name
            )
        return [form[row_value_name].data for form in formset.forms]

    @property
    def submission_overflow(self) -> bool:
        """Report whether extracting this field's rows ran out of the budget.

        Reading ``formset`` completes extraction once, so every caller gets an
        answer about rows that the countdown already reserved.
        """
        _ = self.formset
        return self._submission_overflow

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Give the sequence widget the formset that owns row state."""
        if not isinstance(widget, SequenceWidget):
            super().prepare_widget(widget)
            return
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
        """Return the initial value as a list of rows.

        This replaces ``BoundField.initial`` because a sequence initial is
        a collection, not one value. Read no more than ``absolute_max``
        rows. Keep an unusable value as one row, as the render path does.
        Remove microseconds from each row when the child widget does not
        support them, as Django does for one value (ticket #22502).
        """
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
        """Report exact-input edits and row-formset deletions."""
        if self.field.disabled:
            return False
        if self.has_exact_input and not self.is_bound_formset:
            changed = self.field.has_changed(self.initial, self.data)
        else:
            changed = super()._has_changed()
        if changed or self.submission_overflow:
            return True
        if not self.initial:
            # Only the deletion of an initial row is a change, and this
            # field has no initial rows. Django's deleted_forms validates
            # every row form before it answers, and here that validation
            # cannot change the answer. Return early to remove that
            # unnecessary work, partly for performance and efficiency.
            return False
        deleted_forms = set(self.formset.deleted_forms)
        return any(
            index < len(self.initial)
            for index, form in enumerate(self.formset.forms)
            if form in deleted_forms
        )
