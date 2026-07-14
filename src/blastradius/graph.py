"""Graph representation and traversal module."""

import json
from pathlib import Path

import networkx as nx

from blastradius.resolver import resolve


def build_graph(index: dict[str, list[str]]) -> nx.DiGraph:
    """Build a forward call graph (caller -> callee) from the index.

    Nodes represent fully-qualified functions/methods, and directed edges
    represent calls. Ambiguous targets are resolved to all possible matches.
    """
    G = nx.DiGraph()
    # Add all keys as nodes to ensure isolated functions are represented
    for caller_id in index:
        G.add_node(caller_id)

    # Add edges
    for caller_id, callees in index.items():
        for callee_name in callees:
            resolved_callees = resolve(callee_name, index)
            for callee_id in resolved_callees:
                G.add_edge(caller_id, callee_id)

    return G


def build_reverse_graph(G: nx.DiGraph) -> nx.DiGraph:
    """Flip all edges in the graph to represent a callee -> caller mapping.

    This allows forward traversal starting from the modified function.
    """
    return G.reverse(copy=True)


def persist_graph(G: nx.DiGraph, path: str) -> None:
    """Serialize the graph to disk in JSON format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_graph(path: str) -> nx.DiGraph:
    """Deserialize the graph from a JSON file."""
    p = Path(path)
    if not p.exists():
        return nx.DiGraph()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return nx.node_link_graph(data)
    except Exception:
        return nx.DiGraph()
