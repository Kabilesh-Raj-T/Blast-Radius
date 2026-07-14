"""Script to analyze Django's parse_date blast radius."""

import time
from collections import Counter

import rich
from blastradius.blast import compute_blast_radius
from blastradius.graph import build_graph, build_reverse_graph
from blastradius.indexer import index_repo


def main():
    repo_path = r"C:\Users\Kabilesh\AppData\Local\Temp\django"
    target = "django/utils/dateparse.py:parse_date"

    rich.print(f"Indexing Django at [green]{repo_path}[/]...")

    # We include tests but exclude standard build/docs/env dirs
    index = index_repo(
        repo_path,
        exclude=["venv", ".venv", "__pycache__", "docs", "build", "dist"],
    )

    rich.print(f"Total function definitions indexed: {len(index)}")

    rich.print("Building forward call graph...")
    G = build_graph(index)

    rich.print("Building reverse call graph...")
    rev = build_reverse_graph(G)

    rich.print(f"Computing blast radius for [yellow]{target}[/]...")
    start = time.perf_counter()
    results = compute_blast_radius(rev, target)
    duration = time.perf_counter() - start

    rich.print(f"Blast radius computed in [green]{duration:.3f}s[/].")
    rich.print(f"Total tests at risk: {len(results)}")

    # Confidence distribution
    conf_counter = Counter(r.confidence for r in results)
    rich.print("\n[bold cyan]Confidence Distribution:[/]")
    for conf, count in conf_counter.items():
        rich.print(f"  {conf}: {count}")

    # Top 5 call chains
    rich.print("\n[bold cyan]Top 5 Call Chains:[/]")
    sorted_results = sorted(results, key=lambda x: (x.depth, x.test_function))
    for r in sorted_results[:5]:
        rich.print(f"  [yellow]{r.test_function}[/] (confidence: {r.confidence}, depth: {r.depth})")
        rich.print(f"    Chain: {' -> '.join(r.chain)}")


if __name__ == "__main__":
    main()
