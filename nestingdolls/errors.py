from __future__ import annotations

__all__ = [
    "InvalidInitialValueError",
]


class InvalidInitialValueError(ValueError):
    """Raised when a sequence initial value is not collection-shaped."""
