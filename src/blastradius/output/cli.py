from pathlib import Path

import typer

from blastradius.analysis.blast import compute_blast_radius
from blastradius.graph.graph import build_graph, build_reverse_graph
from blastradius.indexing.indexer import index_repo
from blastradius.output.formatters import format_json, format_markdown, format_terminal

app = typer.Typer(help="Blast Radius CLI")


@app.command()
def analyze(
    target: str = typer.Argument(..., help="Fully qualified name of the changed symbol"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    format: str = typer.Option(
        "terminal", "--format", "-f", help="Output format (terminal, json, markdown)"
    ),
    framework: str = typer.Option(
        None, "--framework", help="Framework plugin to load (django, flask, requests)"
    ),
    diagnostics: bool = typer.Option(False, "--diagnostics", "-d", help="Expose diagnostics"),
):
    """Analyze the blast radius of a symbol change and identify affected tests."""
    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        typer.echo(f"Error: Repository path {repo_path} does not exist.", err=True)
        raise typer.Exit(code=1)

    from blastradius.plugins import load_plugin

    plugin = load_plugin(framework)
    exclude = ["venv", ".venv", "__pycache__"]
    if plugin:
        exclude = plugin.pre_index(exclude)

    index = index_repo(str(repo_path), exclude=exclude)
    if plugin:
        plugin.post_index(index)

    G = build_graph(index)
    if plugin:
        plugin.post_graph(G)

    rev = build_reverse_graph(G)

    results = compute_blast_radius(rev, target, root_dir=str(repo_path))

    if format == "json":
        print(format_json(results))
    elif format == "markdown":
        print(format_markdown(results, target))
    else:
        format_terminal(results, target)

    if diagnostics:
        from rich.console import Console
        from rich.table import Table

        from blastradius.core.diagnostics import tracker

        console = Console()
        table = Table(title="BlastRadius Diagnostics", border_style="bold blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")

        metrics = tracker.to_dict()
        for k, v in metrics.items():
            if k == "memory_usage_bytes":
                v_str = f"{v / (1024 * 1024):.2f} MB"
            elif k in ("index_time_sec", "query_time_sec"):
                v_str = f"{v:.4f} s"
            else:
                v_str = str(v)
            table.add_row(k.replace("_", " ").title(), v_str)
        console.print(table)
