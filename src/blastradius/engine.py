"""Engine API housing the core business logic for indexing, diff analysis, blast radius calculation, and test explaining."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import networkx as nx

from blastradius.analysis.blast import compute_blast_radius
from blastradius.analysis.diff import get_symbols_for_changed_lines, parse_git_diff
from blastradius.graph.graph import build_graph, build_reverse_graph
from blastradius.indexing.indexer import index_repo
from blastradius.plugins import load_plugin


def index_repository(repo_path: str, framework: str | None = None) -> dict[str, Any]:
    """Index the repository and return summary metadata instead of full index to save tokens."""
    repo_p = Path(repo_path).resolve()
    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)
    index = index_repo(str(repo_p), exclude=exclude)
    if plugin:
        plugin.post_index(index)
    return {
        "status": "success",
        "symbols_count": len(index.get("symbols", {})),
        "imports_count": len(index.get("imports", {})),
    }


def blast_radius(repo_path: str, target: str, framework: str | None = None) -> list[dict[str, Any]]:
    """Compute the blast radius of a symbol and return token-efficient results."""
    repo_p = Path(repo_path).resolve()
    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)
    index = index_repo(str(repo_p), exclude=exclude)
    if plugin:
        plugin.post_index(index)
    G = build_graph(index)
    if plugin:
        plugin.post_graph(G)
    rev = build_reverse_graph(G)
    raw_results = compute_blast_radius(rev, target, root_dir=str(repo_p))

    # Convert to token-efficient JSON format
    compact_results = []
    for hit in raw_results:
        compact_results.append(
            {
                "func": hit.test_function,
                "file": hit.test_file,
                "reason": hit.reason,
                "conf": hit.confidence,
                "score": hit.score,
                "chain": [
                    f"{c.split('.')[-1] if ':' not in c else c.rsplit(':', 1)[1]}()"
                    for c in hit.chain
                    if not c.startswith("module:") and c != "repo"
                ],
                "exp": hit.resolution_explanation,
            }
        )
    return compact_results


def analyze_diff(repo_path: str, diff_content: str, framework: str | None = None) -> dict[str, Any]:
    """Parse git diff, map to containing symbols, and compute collective blast radius."""
    repo_p = Path(repo_path).resolve()
    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)
    index = index_repo(str(repo_p), exclude=exclude)
    if plugin:
        plugin.post_index(index)
    symbols = index.get("symbols", {})

    changed_lines = parse_git_diff(diff_content)
    changed_symbols = get_symbols_for_changed_lines(changed_lines, symbols)

    if not changed_symbols:
        return {"changed_symbols": [], "affected_tests": []}

    G = build_graph(index)
    if plugin:
        plugin.post_graph(G)
    rev = build_reverse_graph(G)

    # Collect affected tests from all changed symbols
    aggregated_results: dict[str, dict[str, Any]] = {}
    for sym in changed_symbols:
        res = compute_blast_radius(rev, sym, root_dir=str(repo_p))
        for hit in res:
            test_fun = hit.test_function
            if (
                test_fun not in aggregated_results
                or hit.score > aggregated_results[test_fun]["score"]
            ):
                # Map to token-efficient format
                aggregated_results[test_fun] = {
                    "func": hit.test_function,
                    "file": hit.test_file,
                    "reason": hit.reason,
                    "conf": hit.confidence,
                    "score": hit.score,
                    "chain": [
                        f"{c.split('.')[-1] if ':' not in c else c.rsplit(':', 1)[1]}()"
                        for c in hit.chain
                        if not c.startswith("module:") and c != "repo"
                    ],
                    "exp": hit.resolution_explanation,
                }

    return {"changed_symbols": changed_symbols, "affected_tests": list(aggregated_results.values())}


def explain_test(repo_path: str, test_name: str, framework: str | None = None) -> dict[str, Any]:
    """Explain dependency details of a test, returning its incoming calls/dependencies."""
    repo_p = Path(repo_path).resolve()
    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)
    index = index_repo(str(repo_p), exclude=exclude)
    if plugin:
        plugin.post_index(index)
    G = build_graph(index)
    if plugin:
        plugin.post_graph(G)

    if test_name not in G:
        return {"error": f"Test {test_name} not found in dependency graph."}

    # Find what this test calls (outgoing edges in forward graph)
    dependencies = []
    if G.has_node(test_name):
        for _, neighbor, data in G.out_edges(test_name, data=True):
            if data.get("relation") == "CALLS":
                dependencies.append(
                    {
                        "target": neighbor,
                        "cert": data.get("certainty", 1.0),
                        "inherited": data.get("inheritance", False),
                    }
                )

    return {
        "test": test_name,
        "file": G.nodes[test_name].get("filepath", ""),
        "depends_on": dependencies,
    }


def suggest_files_to_update(
    repo_path: str, target: str, framework: str | None = None
) -> dict[str, Any]:
    """Suggest files that should be reviewed or updated when changing a function/method."""
    repo_p = Path(repo_path).resolve()
    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)
    index = index_repo(str(repo_p), exclude=exclude)
    if plugin:
        plugin.post_index(index)
    G = build_graph(index)
    if plugin:
        plugin.post_graph(G)
    rev = build_reverse_graph(G)

    from collections import deque

    from blastradius.analysis.discovery import DiscoveryConfig, DiscoveryEngine

    discovery_config = DiscoveryConfig(str(repo_p))
    discovery_engine = DiscoveryEngine(discovery_config)

    # Walk the reverse graph starting at target using a BFS
    # Queue entries: (node, chain, depth)
    queue: deque[tuple[str, list[str], int]] = deque([(target, [target], 0)])
    visited = {target}

    # Map file_path -> (relationship, reason, priority_value)
    # Priority: 1=direct_caller, 2=transitive_caller, 3=transitive_test
    file_suggestions: dict[str, tuple[str, str, int]] = {}

    target_name = target.rsplit(":", 1)[1] if ":" in target else target.split(".")[-1]

    while queue:
        node, chain, depth = queue.popleft()

        if node != target:
            # Determine filepath and node data
            node_data = rev.nodes.get(node, {})
            filepath = node_data.get("filepath", "")
            if not filepath and ":" in node:
                filepath, _ = node.rsplit(":", 1)

            if filepath:
                # Make filepath relative to repo root
                try:
                    rel_path = str(Path(filepath).relative_to(repo_p)).replace("\\", "/")
                except ValueError:
                    rel_path = str(Path(filepath)).replace("\\", "/")

                # Classify node
                is_test = discovery_engine.is_test_node(node, node_data)

                if is_test:
                    relationship = "transitive_test"
                    priority = 3
                    if depth == 1:
                        reason = f"tests {target_name} directly"
                    else:
                        called_name = (
                            chain[-2].rsplit(":", 1)[1]
                            if ":" in chain[-2]
                            else chain[-2].split(".")[-1]
                        )
                        reason = f"tests {called_name} which calls {target_name}"
                else:
                    if depth == 1:
                        relationship = "direct_caller"
                        priority = 1
                        reason = f"calls {target_name} directly"
                    else:
                        relationship = "transitive_caller"
                        priority = 2
                        via_name = (
                            chain[1].rsplit(":", 1)[1]
                            if ":" in chain[1]
                            else chain[1].split(".")[-1]
                        )
                        reason = f"calls {target_name} via {via_name}"

                # Update if new or higher priority relationship found
                if rel_path not in file_suggestions or priority < file_suggestions[rel_path][2]:
                    file_suggestions[rel_path] = (relationship, reason, priority)

        # Traverse successors if we are not at a test node
        node_data = rev.nodes.get(node, {})
        if node == target or not discovery_engine.is_test_node(node, node_data):
            for successor in rev.successors(node):
                if successor not in visited:
                    visited.add(successor)
                    is_call = False
                    if rev.is_multigraph():
                        edges_attrs = list(rev[node][successor].values())
                        if all(d.get("relation") is None for d in edges_attrs):
                            is_call = True
                        else:
                            is_call = any(d.get("relation") == "CALLS" for d in edges_attrs)
                    else:
                        rel = rev[node][successor].get("relation")
                        is_call = (rel == "CALLS") or (rel is None)

                    if is_call:
                        queue.append((successor, chain + [successor], depth + 1))

    # Convert to expected list format sorted by priority, then path
    files_to_review = []
    for path, (rel, reason, priority) in sorted(
        file_suggestions.items(), key=lambda item: (item[1][2], item[0])
    ):
        files_to_review.append({"path": path, "reason": reason, "relationship": rel})

    return {"function": target, "files_to_review": files_to_review}


def health() -> dict[str, Any]:
    """Return diagnostic metadata about the static analysis server."""
    return {
        "status": "healthy",
        "python_version": sys.version,
        "networkx_version": nx.__version__,
        "platform": sys.platform,
        "pid": os.getpid(),
    }
