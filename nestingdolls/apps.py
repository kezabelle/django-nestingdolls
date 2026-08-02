from __future__ import annotations

from django.apps import AppConfig


class NestingDollsConfig(AppConfig):
    name = "nestingdolls"

    def ready(self) -> None:
        from nestingdolls.patches import install_form_rendering_patch

        install_form_rendering_patch()
