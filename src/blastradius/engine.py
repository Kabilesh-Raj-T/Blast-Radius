"""Engine API housing the core business logic for indexing, diff analysis, blast radius calculation, and test explaining."""

import os
import sys
from pathlib import Path
from typing import Any

import networkx as nx

from blastradius.blast import compute_blast_radius
from blastradius.diff import get_symbols_for_changed_lines, parse_git_diff
from blastradius.graph import build_graph, build_reverse_graph
from blastradius.indexer import index_repo


def index_repository(repo_path: str) -> dict[str, Any]:
    """Index the repository and return summary metadata instead of full index to save tokens."""
    repo_p = Path(repo_path).resolve()
    index = index_repo(str(repo_p))
    return {
        "status": "success",
        "symbols_count": len(index.get("symbols", {})),
        "imports_count": len(index.get("imports", {})),
    }


def blast_radius(repo_path: str, target: str) -> list[dict[str, Any]]:
    """Compute the blast radius of a symbol and return token-efficient results."""
    repo_p = Path(repo_path).resolve()
    index = index_repo(str(repo_p))
    G = build_graph(index)
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


def analyze_diff(repo_path: str, diff_content: str) -> dict[str, Any]:
    """Parse git diff, map to containing symbols, and compute collective blast radius."""
    repo_p = Path(repo_path).resolve()
    index = index_repo(str(repo_p))
    symbols = index.get("symbols", {})

    changed_lines = parse_git_diff(diff_content)
    changed_symbols = get_symbols_for_changed_lines(changed_lines, symbols)

    if not changed_symbols:
        return {"changed_symbols": [], "affected_tests": []}

    G = build_graph(index)
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


def explain_test(repo_path: str, test_name: str) -> dict[str, Any]:
    """Explain dependency details of a test, returning its incoming calls/dependencies."""
    repo_p = Path(repo_path).resolve()
    index = index_repo(str(repo_p))
    G = build_graph(index)

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


def health() -> dict[str, Any]:
    """Return diagnostic metadata about the static analysis server."""
    return {
        "status": "healthy",
        "python_version": sys.version,
        "networkx_version": nx.__version__,
        "platform": sys.platform,
        "pid": os.getpid(),
    }
