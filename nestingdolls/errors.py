from __future__ import annotations

from typing import TYPE_CHECKING, Self

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise as StrPromise
else:
    from django.utils.functional import Promise as StrPromise

__all__ = [
    "InvalidInitialValueError",
    "ItemValidationError",
    "MappingInputValidationError",
    "MissingManagementFormValidationError",
    "SequenceInputValidationError",
    "TooManyComparisonsError",
    "TooManyFormsValidationError",
]


class InvalidInitialValueError(ValueError):
    """Composite-field initial data has the wrong shape."""


class ItemValidationError(ValidationError):
    """A child item failed validation inside a composite field."""

    item: int | str
    item_path: tuple[int | str, ...]
    child_code: str | None
    child_message: str

    def __init__(
        self,
        message: str,
        *,
        item: int | str,
        child_code: str | None,
        child_path: tuple[int | str, ...] = (),
    ) -> None:
        # ``message`` is a rendered child message. It is never a lazy string.
        # ``ValidationError.messages`` always translates the message first.
        self.item = item
        self.item_path = (item, *child_path)
        self.child_code = child_code
        self.child_message = message
        super().__init__(
            # Django applies ``message % params`` when params is set.
            # A child message with a literal percent sign must escape it.
            message.replace("%", "%%"),
            code="item_invalid",
            params={"item": item, "message": message, "child_code": child_code},
        )

    @classmethod
    def for_messages_of(cls, item: int | str, error: ValidationError, /) -> list[Self]:
        """Return one item error for each message in a child error.

        Each message keeps its own code, its own parameters, and its own
        translation. Each message also records the item it came from.
        Django flattens a composite error to its leaf messages. This method
        makes one item error for each leaf message.

        A leaf can be an ``ItemValidationError`` from a deeper nested field.
        This method keeps that leaf's own item path under the current item.
        A widget many levels down can then still find its own error.
        """
        return [
            cls(
                message,
                item=item,
                child_code=(leaf.params or {}).get("child_code", leaf.code),
                child_path=leaf.item_path if isinstance(leaf, cls) else (),
            )
            for leaf in error.error_list
            for message in leaf.messages
        ]


class MappingInputValidationError(ValidationError):
    """The outer submitted mapping value has the wrong shape."""

    def __init__(self, message: str | StrPromise) -> None:
        super().__init__(message, code="invalid")


class SequenceInputValidationError(ValidationError):
    """The outer submitted sequence value has the wrong shape."""

    def __init__(self, message: str | StrPromise) -> None:
        super().__init__(message, code="invalid")


class MissingManagementFormValidationError(ValidationError):
    """Submitted sequence management data is missing or malformed."""

    def __init__(self, message: str | StrPromise, *, field_names: str) -> None:
        super().__init__(
            message,
            code="missing_management_form",
            params={"field_names": field_names},
        )


class TooManyComparisonsError(RuntimeError):
    """A set field's change detection gave up after too many comparisons.

    ``SetField.has_changed()`` compares each submitted row against the
    initial members. Each comparison calls the child field's own
    ``has_changed()`` method, and that method can be slow. The number of
    rows comes from the submitted data, not from the server. This error
    stops the comparison at a fixed limit. Past that limit, the field
    reports a change and does not finish the comparison.
    """


class TooManyFormsValidationError(ValidationError):
    """Submitted sequence data exceeds the authoritative row limit."""

    def __init__(self, message: str | StrPromise, *, num: int) -> None:
        super().__init__(message, code="too_many_forms", params={"num": num})
