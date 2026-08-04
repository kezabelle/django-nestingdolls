from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise as StrPromise
else:
    from django.utils.functional import Promise as StrPromise

__all__ = [
    "InvalidInitialValueError",
    "InvalidMappingInputError",
    "ItemValidationError",
    "MissingManagementFormValidationError",
    "SequenceInputValidationError",
    "TooManyFormsValidationError",
]


class InvalidInitialValueError(ValueError):
    """Raised when composite-field initial data has the wrong shape."""


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


class TooManyFormsValidationError(ValidationError):
    """Submitted sequence data exceeds the authoritative row limit."""

    def __init__(self, message: str | StrPromise, *, num: int) -> None:
        super().__init__(message, code="too_many_forms", params={"num": num})


class ItemValidationError(ValidationError):
    """A child item failed validation inside a composite field."""

    item: int | str
    child_error: ValidationError
    child_code: str | None

    def __init__(
        self, item: int | str, message: str, child_error: ValidationError
    ) -> None:
        self.item = item
        self.child_error = child_error
        self.child_code = child_error.code
        super().__init__(
            message,
            code="item_invalid",
            params={
                "item": item,
                "message": message,
                "child_code": child_error.code,
            },
        )


class InvalidMappingInputError(ValidationError):
    """The outer submitted mapping value has the wrong shape."""

    def __init__(self, message: str | StrPromise) -> None:
        super().__init__(message, code="invalid")
