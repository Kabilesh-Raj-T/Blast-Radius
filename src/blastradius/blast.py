"""Blast radius calculation and analysis module."""

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import networkx as nx


@dataclass
class AffectedTest:
    test_function: str
    test_file: str
    chain: list[str]
    depth: int
    confidence: str


def _is_test(node: str) -> bool:
    """Classify if a node represents a test file or a test function.

    A node is a test if the filename starts with 'test_', the function name
    starts with 'test_', or any dot-separated component starts with 'test_'.
    """
    if "dyn:" in node or "dynamic:" in node:
        return False

    if ":" in node:
        filepath, funcname = node.rsplit(":", 1)
        is_test_file = Path(filepath).name.startswith("test_") if filepath else False
        is_test_func = funcname.startswith("test_")
        return is_test_file or is_test_func

    parts = node.split(".")
    return any(p.startswith("test_") for p in parts)


def _confidence(depth: int) -> str:
    """Map traversal depth to confidence levels."""
    if depth == 1:
        return "HIGH"
    if depth == 2:
        return "MEDIUM"
    return "LOW"


def compute_blast_radius(
    reverse_graph: nx.DiGraph,
    target: str,
    max_depth: int = 10,
) -> list[AffectedTest]:
    """Perform BFS on the reverse call graph to compute affected tests.

    Starts from target, traverses upward, and stops traversing along branches
    when they reach a test function. Marks confidence as LOW if traversal
    passes through dynamic call nodes.
    """
    if target not in reverse_graph:
        return []

    affected: list[AffectedTest] = []
    visited: set[str] = set()

    # Queue entries: (node, chain, depth, has_dynamic)
    queue: deque[tuple[str, list[str], int, bool]] = deque()
    queue.append((target, [target], 0, False))

    while queue:
        node, chain, depth, has_dynamic = queue.popleft()

        if node in visited:
            continue
        visited.add(node)

        if depth > max_depth:
            continue

        # Check if current node is a dynamic call site
        node_kind = reverse_graph.nodes[node].get("kind") if node in reverse_graph.nodes else None
        if node_kind == "dynamic_call":
            has_dynamic = True

        if _is_test(node) and node != target:
            # Found an affected test
            if ":" in node:
                filepath, _ = node.rsplit(":", 1)
            else:
                node_data = reverse_graph.nodes[node]
                filepath = node_data.get("filepath", "") if node_data else ""

            confidence = "LOW" if has_dynamic else _confidence(depth)
            affected.append(
                AffectedTest(
                    test_function=node,
                    test_file=filepath,
                    chain=chain,
                    depth=depth,
                    confidence=confidence,
                )
            )
            # Do not traverse past test functions
            continue

        # Enqueue successors (which are callers in the original call graph)
        for successor in reverse_graph.successors(node):
            # Check edge type to ensure we only traverse execution calls
            is_call = False
            if reverse_graph.is_multigraph():
                edges_attrs = reverse_graph[node][successor].values()
                if all(d.get("relation") is None for d in edges_attrs):
                    is_call = True
                else:
                    is_call = any(d.get("relation") == "CALLS" for d in edges_attrs)
            else:
                rel = reverse_graph[node][successor].get("relation")
                is_call = (rel == "CALLS") or (rel is None)

            if is_call and successor not in visited:
                queue.append((successor, chain + [successor], depth + 1, has_dynamic))

    return affected
