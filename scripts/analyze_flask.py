"""Script to analyze the Flask repository call graph."""

import rich
from blastradius.graph import build_graph, build_reverse_graph
from blastradius.indexer import index_repo


def main():
    repo_path = r"C:\Users\Kabilesh\AppData\Local\Temp\flask"
    rich.print(f"Indexing Flask repository at [green]{repo_path}[/]...")

    # Index Flask, excluding tests and docs
    index = index_repo(
        repo_path,
        exclude=["tests", "docs", "venv", ".venv", "__pycache__", "examples"],
    )

    rich.print("Building forward call graph...")
    G = build_graph(index)

    rich.print("Building reverse call graph...")
    rev = build_reverse_graph(G)
    assert rev.number_of_nodes() == G.number_of_nodes()

    # Node and edge counts
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()

    rich.print("\n[bold cyan]Flask Graph Stats:[/]")
    rich.print(f"  Total Nodes (Functions): {total_nodes}")
    rich.print(f"  Total Edges (Calls): {total_edges}")

    # Top 5 nodes by in-degree (most-called internal functions)
    # in-degree represents how many other internal functions call this one
    in_degrees = sorted(G.in_degree(), key=lambda x: x[1], reverse=True)

    rich.print("\n[bold cyan]Top 5 Functions by In-Degree (Most Called):[/]")
    for node, deg in in_degrees[:5]:
        rich.print(f"  [yellow]{node}[/]: {deg} callers")

    # Top 5 nodes by out-degree (calls the most other functions)
    out_degrees = sorted(G.out_degree(), key=lambda x: x[1], reverse=True)

    rich.print("\n[bold cyan]Top 5 Functions by Out-Degree (Calls the Most):[/]")
    for node, deg in out_degrees[:5]:
        rich.print(f"  [yellow]{node}[/]: {deg} callees")


if __name__ == "__main__":
    main()
