"""Django framework plugin implementation."""

from __future__ import annotations

from typing import Any

from blastradius.plugins.base import FrameworkPlugin


class DjangoPlugin(FrameworkPlugin):
    """Django framework heuristic plugin."""

    name: str = "django"

    def pre_index(self, exclude: list[str]) -> list[str]:
        """Automatically add build and documentation paths to excludes."""
        django_excludes = ["docs", "build", "dist"]
        return list(sorted(set(exclude) | set(django_excludes)))

    def post_index(self, index: dict[str, Any]) -> None:
        """Report Django definitions summary."""
        import rich

        rich.print(
            f"[dim][Django Plugin][/] Post-index run. Total definitions: {len(index.get('symbols', index))}"
        )
