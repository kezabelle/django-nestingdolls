from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.forms import Field
from django.forms.boundfield import BoundField
from django.forms.widgets import Media, MultipleHiddenInput, Widget
from django.utils.translation import gettext_lazy as _, ngettext_lazy

__all__ = [
    "SequenceField",
    "FrozenSequenceField",
    "ListField",
    "TupleField",
    "SetField",
    "SequenceWidget",
]


@dataclass
class _SequenceItem:
    index: int
    value: object
    deleted: bool = False


@dataclass
class _SequenceSubmission:
    items: list[_SequenceItem]
    total_forms: int
    management_error: ValidationError | None = None


class _SequenceItemBoundField:
    """The small part of BoundField used by Django's Field cleaning hooks."""

    def __init__(self, form, field, name, initial, data):
        self.form = form
        self.field = field
        self.name = name
        self.html_name = name
        self.initial = initial
        self.data = data


class _SequenceHiddenWidget(MultipleHiddenInput):
    def format_value(self, value):
        if isinstance(value, _SequenceSubmission):
            return [item.value for item in value.items if not item.deleted]
        return super().format_value(value)


class SequenceBoundField(BoundField):
    def build_widget_attrs(self, attrs, widget=None):
        attrs = super().build_widget_attrs(attrs, widget)
        widget = widget or self.field.widget
        if not isinstance(widget, SequenceWidget):
            return attrs

        item_errors: dict[int, list[str]] = defaultdict(list)
        has_global_error = False
        for error in self.errors.as_data():
            params = error.params or {}
            if error.code == "item_invalid" and "index" in params:
                item_errors[params["index"]].extend(error.messages)
            else:
                has_global_error = True

        attrs["_sequence_form_use_required"] = self.form.use_required_attribute
        attrs["_sequence_initial_count"] = len(self.field._initial_values(self.initial))
        attrs["_sequence_item_errors"] = dict(item_errors)
        attrs["_sequence_global_error"] = has_global_error
        return attrs


def _sequence_bound_field_class(bound_field_class: type[BoundField] | None):
    bound_field_class = bound_field_class or SequenceBoundField
    if issubclass(bound_field_class, SequenceBoundField):
        return bound_field_class
    return type(
        f"Sequence{bound_field_class.__name__}",
        (SequenceBoundField, bound_field_class),
        {},
    )


class SequenceField(Field):
    """A collection field whose rows are cleaned by one Django child field."""

    default_error_messages = {
        "invalid": _("Enter a list of values."),
        "management": _("Management form data is missing or has been tampered with."),
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
        "too_many_forms": _("Submit at most %(limit_value)d rows."),
        "unhashable": _("Set items must be hashable."),
    }
    hidden_widget = _SequenceHiddenWidget

    def __init__(
        self,
        child_field: Field,
        /,
        *,
        min_length: int = 0,
        max_length: int = 1_000,
        widget: SequenceWidget | type[SequenceWidget] | None = None,
        **kwargs,
    ):
        if not isinstance(child_field, Field):
            raise ImproperlyConfigured(
                "child_field argument for SequenceField must be a forms.Field instance"
            )
        if (
            isinstance(min_length, bool)
            or isinstance(max_length, bool)
            or not isinstance(min_length, int)
            or not isinstance(max_length, int)
            or min_length < 0
            or max_length < min_length
        ):
            raise ValueError("min_length and max_length must be non-negative integers")

        self.child_field = copy.deepcopy(child_field)
        self.min_length = min_length
        self.max_length = max_length
        if kwargs.get("localize", False):
            self.child_field.localize = True
            self.child_field.widget.is_localized = True

        if widget is None:
            sequence_widget = SequenceWidget(
                self.child_field,
                min_length=min_length,
                max_length=max_length,
            )
        elif isinstance(widget, type):
            if not issubclass(widget, SequenceWidget):
                raise TypeError("widget must be a SequenceWidget instance or subclass")
            sequence_widget = widget(
                self.child_field,
                min_length=min_length,
                max_length=max_length,
            )
        elif isinstance(widget, SequenceWidget):
            sequence_widget = copy.deepcopy(widget)
            sequence_widget.configure(
                self.child_field,
                min_length=min_length,
                max_length=max_length,
            )
        else:
            raise TypeError("widget must be a SequenceWidget instance or subclass")

        kwargs["widget"] = sequence_widget
        kwargs["bound_field_class"] = _sequence_bound_field_class(
            kwargs.get("bound_field_class")
        )
        super().__init__(**kwargs)

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.child_field = copy.deepcopy(self.child_field, memo)
        result.widget.child_field = result.child_field
        return result

    @staticmethod
    def _empty(value: object) -> bool:
        return value is None or value == "" or value in ([], (), set(), frozenset())

    def _submission(self, value: object) -> _SequenceSubmission:
        if isinstance(value, _SequenceSubmission):
            return value
        if self._empty(value):
            return _SequenceSubmission([], 0)
        if isinstance(value, (str, bytes, bytearray, dict)) or not isinstance(
            value, (list, tuple, set, frozenset)
        ):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return _SequenceSubmission(
            [_SequenceItem(index, item) for index, item in enumerate(value)], len(value)
        )

    def _initial_values(self, initial: object) -> list[object]:
        try:
            submission = self._submission(initial)
        except ValidationError:
            return []
        return [item.value for item in submission.items if not item.deleted]

    def to_python(self, value: object) -> list[object]:
        submission = self._submission(value)
        if submission.management_error:
            raise submission.management_error
        return [item.value for item in submission.items if not item.deleted]

    def _management_limit(self, initial: object) -> int:
        # Deleted rows retain their index. Allow one bounded generation of extra
        # rows as well as the active collection, while max_length still limits
        # the final compressed value.
        return max(
            self.max_length * 2,
            len(self._initial_values(initial)) + self.max_length,
        )

    def _check_submission(self, submission: _SequenceSubmission, initial: object):
        if submission.management_error:
            if submission.management_error.code == "management":
                raise ValidationError(self.error_messages["management"], code="management")
            raise submission.management_error
        if submission.total_forms > self._management_limit(initial):
            raise ValidationError(
                self.error_messages["too_many_forms"],
                code="too_many_forms",
                params={"limit_value": self._management_limit(initial)},
            )

    def _item_error(self, index: int, error: ValidationError) -> list[ValidationError]:
        errors = []
        for leaf in error.error_list:
            for message in leaf.messages:
                errors.append(
                    ValidationError(
                        _("Item %(index)d: %(message)s"),
                        code="item_invalid",
                        params={
                            "index": index,
                            "message": message,
                            "child_code": leaf.code,
                        },
                    )
                )
        return errors

    def _clean_item(self, item: _SequenceItem, initial: object, form, field_name: str):
        initial_values = self._initial_values(initial)
        item_initial = initial_values[item.index] if item.index < len(initial_values) else None
        bound_field = _SequenceItemBoundField(
            form,
            self.child_field,
            f"{field_name}-{item.index}",
            item_initial,
            item.value,
        )
        return self.child_field._clean_bound_field(bound_field)

    def clean(self, value, *, initial=None, form=None, field_name=""):
        submitted_by_widget = isinstance(value, _SequenceSubmission)
        submission = self._submission(value)
        if submitted_by_widget:
            self._check_submission(submission, initial)

        cleaned_data = []
        errors = []
        for item in submission.items:
            if item.deleted:
                continue
            try:
                cleaned_data.append(self._clean_item(item, initial, form, field_name))
            except ValidationError as error:
                errors.extend(self._item_error(item.index, error))
        if errors:
            raise ValidationError(errors)

        result = self.compress(cleaned_data)
        self.validate(result)
        if result:
            self.run_validators(result)
        return result

    def _clean_bound_field(self, bound_field):
        value = bound_field.initial if self.disabled else bound_field.data
        return self.clean(
            value,
            initial=bound_field.initial,
            form=bound_field.form,
            field_name=bound_field.html_name,
        )

    def validate(self, value):
        length = len(value)
        if not length:
            if self.required:
                raise ValidationError(self.error_messages["required"], code="required")
            return
        if length < self.min_length:
            raise ValidationError(
                self.error_messages["min_length"],
                code="min_length",
                params={"limit_value": self.min_length, "show_value": length},
            )
        if length > self.max_length:
            raise ValidationError(
                self.error_messages["max_length"],
                code="max_length",
                params={"limit_value": self.max_length, "show_value": length},
            )

    def compress(self, data_list: list[object]) -> list[object]:
        return data_list

    def bound_data(self, data, initial):
        if self.disabled:
            return initial
        submission = self._submission(data)
        initial_values = self._initial_values(initial)
        items = []
        for item in submission.items:
            item_initial = (
                initial_values[item.index] if item.index < len(initial_values) else None
            )
            value = item.value if item.deleted else self.child_field.bound_data(item.value, item_initial)
            items.append(_SequenceItem(item.index, value, item.deleted))
        return _SequenceSubmission(items, submission.total_forms, submission.management_error)

    def prepare_value(self, value):
        submission = self._submission(value)
        return _SequenceSubmission(
            [
                _SequenceItem(
                    item.index,
                    item.value
                    if item.deleted
                    else self.child_field.prepare_value(item.value),
                    item.deleted,
                )
                for item in submission.items
            ],
            submission.total_forms,
            submission.management_error,
        )

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            submitted_by_widget = isinstance(data, _SequenceSubmission)
            submission = self._submission(data)
            if submission.management_error:
                return True
            if submitted_by_widget:
                self._check_submission(submission, initial)
        except ValidationError:
            return True

        initial_values = self._initial_values(initial)
        data_by_index = {item.index: item for item in submission.items}
        for index, item_initial in enumerate(initial_values):
            item = data_by_index.get(index)
            if item is None or item.deleted:
                return True
            try:
                item_initial = self.child_field.to_python(item_initial)
            except ValidationError:
                return True
            if self.child_field.has_changed(item_initial, item.value):
                return True
        for item in submission.items:
            if item.index >= len(initial_values) and not item.deleted:
                if self.child_field.has_changed(None, item.value):
                    return True
        return False


class ListField(SequenceField):
    pass


class TupleField(SequenceField):
    def compress(self, data_list: list[object]) -> tuple[object, ...]:
        return tuple(data_list)


FrozenSequenceField = TupleField


class SetField(SequenceField):
    def compress(self, data_list: list[object]) -> set[object]:
        try:
            return set(data_list)
        except TypeError as error:
            raise ValidationError(
                self.error_messages["unhashable"], code="unhashable"
            ) from error

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            submitted_by_widget = isinstance(data, _SequenceSubmission)
            submission = self._submission(data)
            if submission.management_error:
                return True
            if submitted_by_widget:
                self._check_submission(submission, initial)
        except ValidationError:
            return True

        def unique(values: Iterable[object]) -> list[object]:
            result = []
            for value in values:
                if not any(
                    not self.child_field.has_changed(
                        self.child_field.to_python(existing), value
                    )
                    for existing in result
                ):
                    result.append(value)
            return result

        try:
            initial_values = unique(self._initial_values(initial))
            data_values = unique(
                item.value for item in submission.items if not item.deleted
            )
            unmatched = list(data_values)
            for item_initial in initial_values:
                for index, item_data in enumerate(unmatched):
                    if not self.child_field.has_changed(item_initial, item_data):
                        unmatched.pop(index)
                        break
                else:
                    return True
        except (TypeError, ValidationError):
            return True
        return bool(unmatched)


SequenceField = ListField


class SequenceWidget(Widget):
    template_name = "django/forms/widgets/sequence.html"
    use_fieldset = True

    def __init__(self, child_field: Field, *, min_length: int, max_length: int, attrs=None):
        self.configure(child_field, min_length=min_length, max_length=max_length)
        super().__init__(attrs)

    def configure(self, child_field: Field, *, min_length: int, max_length: int):
        self.child_field = child_field
        self.min_length = min_length
        self.max_length = max_length

    @property
    def _widget_total_limit(self):
        # The field later applies the tighter initial-count-aware limit. This
        # bound prevents a hostile TOTAL_FORMS value from allocating unbounded work.
        return self.max_length * 2

    def use_required_attribute(self, initial):
        # A group cannot express collection requiredness with one HTML attribute.
        return False

    def value_from_datadict(self, data, files, name):
        management_name = f"{name}-TOTAL_FORMS"
        raw_total = data.get(management_name)
        if raw_total is None:
            return _SequenceSubmission(
                [],
                0,
                ValidationError(
                    _("Management form data is missing or has been tampered with."),
                    code="management",
                ),
            )
        try:
            total_forms = int(raw_total)
        except (TypeError, ValueError):
            total_forms = -1
        if total_forms < 0 or total_forms > self._widget_total_limit:
            return _SequenceSubmission(
                [],
                0,
                ValidationError(
                    _("Management form data is missing or has been tampered with."),
                    code="management",
                ),
            )

        items = []
        for index in range(total_forms):
            row_name = f"{name}-{index}"
            deleted = data.get(f"{row_name}-DELETE") == "1"
            value = None if deleted else self.child_field.widget.value_from_datadict(
                data, files, row_name
            )
            items.append(_SequenceItem(index, value, deleted))
        return _SequenceSubmission(items, total_forms)

    def value_omitted_from_data(self, data, files, name):
        return f"{name}-TOTAL_FORMS" not in data

    def _submission_for_context(self, value) -> _SequenceSubmission:
        if isinstance(value, _SequenceSubmission):
            return value
        if value is None or value == "":
            return _SequenceSubmission([], 0)
        if isinstance(value, (list, tuple, set, frozenset)):
            return _SequenceSubmission(
                [_SequenceItem(index, item) for index, item in enumerate(value)],
                len(value),
            )
        return _SequenceSubmission([_SequenceItem(0, value)], 1)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if self.is_localized:
            self.child_field.widget.is_localized = True

        final_attrs = context["widget"]["attrs"]
        form_use_required = final_attrs.pop("_sequence_form_use_required", True)
        initial_count = final_attrs.pop("_sequence_initial_count", 0)
        item_errors = final_attrs.pop("_sequence_item_errors", {})
        global_error = final_attrs.pop("_sequence_global_error", False)
        final_attrs.pop("aria-invalid", None)
        final_attrs.pop("required", None)

        submission = self._submission_for_context(value)
        if not submission.items:
            count = min(max(self.min_length, int(self.is_required)), self.max_length)
            submission = _SequenceSubmission(
                [_SequenceItem(index, None) for index in range(count)], count
            )

        id_ = final_attrs.get("id")

        def make_row(item: _SequenceItem):
            row_name = f"{name}-{item.index}"
            widget_attrs = final_attrs.copy()
            if id_:
                widget_attrs["id"] = f"{id_}_{item.index}"
            if (
                form_use_required
                and self.child_field.required
                and self.child_field.widget.use_required_attribute(item.value)
            ):
                widget_attrs["required"] = True
            subwidget = self.child_field.widget.get_context(
                row_name, item.value, widget_attrs
            )["widget"]
            errors = item_errors.get(item.index, [])
            if errors or global_error:
                subwidget["attrs"]["aria-invalid"] = "true"
            if errors:
                error_id = f"{id_}_{item.index}_error" if id_ else None
                if error_id:
                    describedby = subwidget["attrs"].get("aria-describedby", "")
                    subwidget["attrs"]["aria-describedby"] = " ".join(
                        value for value in (describedby, error_id) if value
                    )
            return {
                "index": item.index,
                "delete_name": f"{row_name}-DELETE",
                "deleted": item.deleted,
                "errors": errors,
                "error_id": f"{id_}_{item.index}_error" if id_ else "",
                "subwidget": subwidget,
            }

        rows = [make_row(item) for item in submission.items if not item.deleted]
        deleted_rows = [make_row(item) for item in submission.items if item.deleted]
        empty_row = make_row(_SequenceItem("__prefix__", None))
        context["widget"].update(
            {
                "rows": rows,
                "deleted_rows": deleted_rows,
                "empty_row": empty_row,
                "total_forms": submission.total_forms,
                "management_name": f"{name}-TOTAL_FORMS",
                "maximum_forms": self.max_length,
                "initial_count": initial_count,
                "disabled": bool(final_attrs.get("disabled")),
            }
        )
        return context

    def id_for_label(self, id_):
        return ""

    @property
    def is_hidden(self):
        return self.child_field.widget.is_hidden

    @property
    def needs_multipart_form(self):
        return self.child_field.widget.needs_multipart_form

    @property
    def media(self):
        return Media(js=["nestingdolls/sequence.js"]) + self.child_field.widget.media
