from __future__ import annotations

__all__ = [
    "InvalidInitialValueError",
]


class InvalidInitialValueError(ValueError):
    """Raised when composite-field initial data has the wrong shape."""
