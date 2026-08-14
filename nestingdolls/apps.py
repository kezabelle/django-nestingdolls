"""Django application configuration for django-nesting-dolls."""

from __future__ import annotations

from django.apps import AppConfig

from nestingdolls.patches import install_form_rendering_patch


class NestingDollsConfig(AppConfig):
    """Install integration needed by composite widgets."""

    name = "nestingdolls"

    def ready(self) -> None:
        """Install the form-rendering layout bridge once Django is ready."""
        install_form_rendering_patch()
