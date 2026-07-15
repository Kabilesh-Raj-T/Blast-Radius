"""Framework plugins for BlastRadius."""

from __future__ import annotations

from blastradius.plugins.base import FrameworkPlugin
from blastradius.plugins.django import DjangoPlugin
from blastradius.plugins.flask import FlaskPlugin
from blastradius.plugins.requests import RequestsPlugin

PLUGINS: dict[str, type[FrameworkPlugin]] = {
    "django": DjangoPlugin,
    "flask": FlaskPlugin,
    "requests": RequestsPlugin,
}


def load_plugin(name: str | None) -> FrameworkPlugin | None:
    """Dynamically load framework heuristic plugin by name."""
    if not name:
        return None
    plugin_cls = PLUGINS.get(name.lower())
    if not plugin_cls:
        raise ValueError(f"Unknown framework plugin: {name}")
    return plugin_cls()
