"""Base plugin definition for framework adapters."""

from __future__ import annotations

from typing import Any

import networkx as nx


class FrameworkPlugin:
    """Base class/interface for framework-specific plugins/adapters."""

    name: str = "base"

    def pre_index(self, exclude: list[str]) -> list[str]:
        """Optionally modify or return the list of excluded paths for this framework."""
        return exclude

    def post_index(self, index: dict[str, Any]) -> None:
        """Heuristics applied on the index after repository indexing completes."""
        pass

    def post_graph(self, G: nx.MultiDiGraph) -> None:
        """Heuristics/analytics applied on the graph after it is constructed."""
        pass
