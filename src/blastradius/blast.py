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

    A node is a test if the filename starts with 'test_' or the function name
    starts with 'test_'.
    """
    if ":" in node:
        filepath, funcname = node.rsplit(":", 1)
    else:
        filepath, funcname = "", node

    is_test_file = Path(filepath).name.startswith("test_") if filepath else False
    is_test_func = funcname.startswith("test_")

    return is_test_file or is_test_func


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
    when they reach a test function.
    """
    if target not in reverse_graph:
        return []

    affected: list[AffectedTest] = []
    visited: set[str] = set()

    # Queue entries: (node, chain, depth)
    queue: deque[tuple[str, list[str], int]] = deque()
    queue.append((target, [target], 0))

    while queue:
        node, chain, depth = queue.popleft()

        if node in visited:
            continue
        visited.add(node)

        if depth > max_depth:
            continue

        if _is_test(node) and node != target:
            # Found an affected test
            if ":" in node:
                filepath, _ = node.rsplit(":", 1)
            else:
                filepath = ""

            affected.append(
                AffectedTest(
                    test_function=node,
                    test_file=filepath,
                    chain=chain,
                    depth=depth,
                    confidence=_confidence(depth),
                )
            )
            # Do not traverse past test functions
            continue

        # Enqueue successors (which are callers in the original call graph)
        for successor in reverse_graph.successors(node):
            if successor not in visited:
                queue.append((successor, chain + [successor], depth + 1))

    return affected
