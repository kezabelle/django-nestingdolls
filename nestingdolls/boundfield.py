"""Bound-field implementations for composite mapping and sequence values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property

from nestingdolls.errors import InvalidInitialValueError, ItemValidationError
from nestingdolls.patches import FormLayout
from nestingdolls.widgets import CompositeWidget, MappingWidget, SequenceWidget

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.core.files.uploadedfile import UploadedFile
    from django.forms import BaseForm, Field
    from django.forms.boundfield import BoundWidget
    from django.forms.utils import ErrorList
    from django.forms.widgets import Widget
    from django.utils.safestring import SafeString

    from nestingdolls.fields import CompositeField, MappingField, SequenceField

__all__ = ["MappingBoundField", "SequenceBoundField"]


class CompositeBoundField(BoundField):
    """Hold the bound-field behavior that mapping and sequence fields share."""

    field: CompositeField

    @property
    def errors(self) -> ErrorList:
        """Return the errors that belong to the outer composite field.

        A visible composite hides child item errors here. Its subform or rows
        already show each one next to its input, so the user sees it once.
        A hidden composite renders no input, so it keeps them.
        """
        errors = super().errors
        if not errors or self.is_hidden:
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

    def css_classes(self, extra_classes: str | Iterable[str] | None = None) -> str:
        """Return Django's CSS classes, plus the form error class for child errors.

        Child item errors are not in ``errors``. Add the form error class when
        the form has an error for this field but ``errors`` is empty.
        """
        if (
            self.form.errors.get(self.name)
            and not self.errors
            and hasattr(self.form, "error_css_class")
        ):
            if isinstance(extra_classes, str):
                extra_classes = f"{extra_classes} {self.form.error_css_class}"
            else:
                extra_classes = (*(extra_classes or ()), self.form.error_css_class)
        return super().css_classes(extra_classes)

    @cached_property
    def data(self) -> object:
        """Extract the submitted composite value exactly once."""
        return self.field.widget.value_from_datadict(
            self.form.data, self.form.files, self.html_name
        )

    @property
    def subwidgets(self) -> list[BoundWidget]:
        """Set render state before Django gets subwidgets."""
        self.prepare_widget(self.field.widget)
        return super().subwidgets

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
                # initial spans many keys, so rebuild it here instead. Its
                # child Form or row formset uses Django's default auto_id and
                # renderer, not those of the outer form.
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

    @property
    def label_id(self) -> str:
        """Return the id of this field's label, or an empty string without one."""
        id_ = self.field.widget.attrs.get("id") or self.auto_id
        return f"{id_}_label" if id_ and self.label else ""

    def label_tag(
        self,
        contents: str | None = None,
        attrs: dict[str, str | bool] | None = None,
        label_suffix: str | None = None,
        tag: str | None = None,
    ) -> SafeString:
        """Give the label an id, so a group without a fieldset can name itself.

        A legend already names its fieldset, so it gets no id.
        """
        if tag != "legend" and self.label_id:
            attrs = {"id": self.label_id, **(attrs or {})}
        return super().label_tag(contents, attrs, label_suffix, tag)

    def build_widget_attrs(
        self, attrs: dict[str, str | bool], widget: Widget | None = None
    ) -> dict[str, str | bool]:
        """Add outer help, error, and name references when no fieldset holds them."""
        attrs = super().build_widget_attrs(attrs, widget)
        if FormLayout.current() is not FormLayout.div and not attrs.get(
            "aria-describedby"
        ):
            described_by = self.aria_describedby
            if described_by:
                attrs["aria-describedby"] = described_by
        named = {**(widget or self.field.widget).attrs, **attrs}
        if (
            FormLayout.current() is not FormLayout.div
            and self.label_id
            and not (named.get("aria-label") or named.get("aria-labelledby"))
        ):
            attrs["aria-labelledby"] = self.label_id
        return attrs

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Put the submitted state this render needs on the widget."""
        widget.render_state = widget.RenderState()

    def has_row_changes(self, initial: object) -> bool:  # noqa: ARG002
        """Report a nested change that ``field.has_changed()`` cannot see.

        An example is a deleted row. Nested composite fields override this.
        """
        return False

    def _has_changed(self) -> bool:
        """Compare the submitted value with the initial value.

        With ``show_hidden_initial``, read the initial value from the hidden
        inputs. A disabled field reports no change before a conversion can raise.
        """
        if self.field.disabled:
            return False
        initial: object
        if self.field.show_hidden_initial:
            widget = self.field.hidden_widget()
            try:
                initial = self.field.from_hidden_initial(
                    widget.value_from_datadict(
                        self.form.data, self.form.files, self.html_initial_name
                    )
                )
            except ValidationError:
                return True
        else:
            initial = self.initial
        return self.field.has_changed(initial, self.data) or self.has_row_changes(
            initial
        )


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
        exact_data = self.form.data.get(self.html_name)
        exact_files = self.form.files.get(self.html_name)
        if isinstance(exact_data, Mapping) or isinstance(exact_files, Mapping):
            return True
        if self.html_name in self.form.data or self.html_name in self.form.files:
            return False
        return (
            isinstance(self.initial, dict)
            and bool(self.initial)
            and widget.needs_multipart_form
        )

    @cached_property
    def subform(self) -> BaseForm:
        """Return the child Form for the clean step and for the render."""
        data: Mapping[str, object] | None = None
        files: Mapping[str, object] | None = None
        if self.is_bound_subform:
            data, files = self.field.widget.expand_exact_inputs(
                self.form.data, self.form.files, self.html_name
            )
        initial = self.initial
        subform = self.field.form_class(
            data=data,
            files=files,  # type: ignore[arg-type]  # Django accepts a Mapping here.
            initial=initial if isinstance(initial, dict) else {},
            prefix=self.html_name,
            auto_id=self.form.auto_id,
            error_class=self.form.error_class,
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

    def has_row_changes(self, initial: object) -> bool:
        """Find changes in nested composite child fields."""
        if self.field.disabled:
            return False
        members = self.field.initial_value(initial)
        subform = self.subform
        for name in subform.fields:
            child = subform[name]
            if isinstance(child, CompositeBoundField) and child.has_row_changes(
                members.get(name)
            ):
                return True
        return False

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
    def formset(self) -> SequenceWidget.RowFormSet:
        """Return the cached, prefix-aware row formset for cleaning and rendering."""
        widget = self.field.widget
        if self.field.disabled or (
            not self.has_exact_input and not self.is_bound_formset
        ):
            formset = widget.new_formset(
                initial=widget.default_initial_rows(self.initial),
                prefix=self.html_name,
                auto_id=self.form.auto_id,
                error_class=self.form.error_class,
                renderer=self.form.renderer,
            )
            formset.rows_disabled = self.field.disabled
            return formset

        exact_values: list[object] | None = None
        with widget.submission_countdown.open(
            self.field.limits.submission_max, raises=True
        ) as countdown:
            data: Mapping[str, object] | None = None
            files: MultiValueDict[str, UploadedFile[bytes]] | None = None
            initial = widget.default_initial_rows(self.initial)
            if self.is_bound_formset:
                data = self.form.data
                files = self.form.files
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
                                key: [part]  # type: ignore[list-item]  # Files-only input holds uploads.
                                for key, part in widget.exact_rows(
                                    value, self.html_name
                                ).items()
                            }
                        )

            formset = widget.new_formset(
                data=data,
                files=files,
                initial=initial,
                prefix=self.html_name,
                auto_id=self.form.auto_id,
                error_class=self.form.error_class,
                renderer=self.form.renderer,
                error_messages=self.field.error_messages,
                # Generated exact-list rows already used this budget.
                submission_total_form_count=(
                    len(exact_values) if exact_values is not None else None
                ),
            )
            for form in formset.forms:
                child = form[widget.row_value_name]
                if isinstance(child, CompositeBoundField):
                    _ = child.data
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
                auto_id=self.form.auto_id,
                error_class=self.form.error_class,
                renderer=self.form.renderer,
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
        return [form[self.field.widget.row_value_name].data for form in formset.forms]

    @property
    def submission_overflow(self) -> bool:
        """Report whether extracting this field's rows ran out of the budget.

        Reading ``formset`` completes extraction once, so every caller gets an
        answer about rows that the countdown already reserved.
        """
        _ = self.formset
        return self._submission_overflow

    def has_row_changes(self, initial: object) -> bool:
        """Find deletions and nested changes hidden by equal cleaned values."""
        if self.field.disabled:
            return False
        if self.submission_overflow:
            return True
        field = self.field
        formset = self.formset
        rows = field.initial_values(initial, limit=field.limits.absolute_max)
        # Cleaning keeps every exact row, even one that the child calls unchanged.
        # A bound formset without browser rows holds an exact list. It builds
        # at most absolute_max rows, so compare the submitted count.
        if (
            formset.is_bound
            and not self.is_bound_formset
            and formset.submission_total_form_count > len(rows)
        ):
            return True
        # Only initial rows can be deleted, and deleted_forms validates every row.
        if not rows:
            return False
        deleted_forms = set(formset.deleted_forms)
        for form, row in zip(formset.forms, rows, strict=False):
            child = form[self.field.widget.row_value_name]
            if form in deleted_forms or (
                isinstance(child, CompositeBoundField) and child.has_row_changes(row)
            ):
                return True
        return False

    def prepare_widget(self, widget: CompositeWidget) -> None:
        """Give the sequence widget the formset that owns row state."""
        if not isinstance(widget, SequenceWidget):
            super().prepare_widget(widget)
            return
        widget.render_state = widget.RenderState(
            formset=self.formset, submission_overflow=self.submission_overflow
        )

    def value(self) -> object:
        """Let the row formset, not Field.prepare_value(), prepare row values."""
        if self.form.is_bound:
            return self.field.bound_data(self.data, self.initial)
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
