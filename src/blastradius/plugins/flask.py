"""Flask framework plugin implementation."""

from __future__ import annotations

import networkx as nx

from blastradius.plugins.base import FrameworkPlugin


class FlaskPlugin(FrameworkPlugin):
    """Flask framework heuristic plugin."""

    name: str = "flask"

    def pre_index(self, exclude: list[str]) -> list[str]:
        """Automatically add tests, docs, and examples to excludes."""
        flask_excludes = ["tests", "docs", "examples"]
        return list(sorted(set(exclude) | set(flask_excludes)))

    def post_graph(self, G: nx.MultiDiGraph) -> None:
        """Report Flask graph statistics."""
        import rich

        rich.print(
            f"[dim][Flask Plugin][/] Post-graph run. Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}"
        )
