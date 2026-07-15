"""Requests library plugin implementation."""

from __future__ import annotations

from blastradius.plugins.base import FrameworkPlugin


class RequestsPlugin(FrameworkPlugin):
    """Requests library heuristic plugin."""

    name: str = "requests"

    def pre_index(self, exclude: list[str]) -> list[str]:
        """Automatically add tests, docs, build, and dist to excludes."""
        requests_excludes = ["tests", "docs", "build", "dist"]
        return list(sorted(set(exclude) | set(requests_excludes)))
