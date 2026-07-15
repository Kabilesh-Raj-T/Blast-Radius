"""Command line interface for BlastRadius."""

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import typer

from blastradius.analysis.blast import compute_blast_radius
from blastradius.analysis.diff import get_symbols_for_changed_lines, parse_git_diff
from blastradius.core.config import Config
from blastradius.graph.graph import build_graph, build_reverse_graph
from blastradius.indexing.indexer import index_repo
from blastradius.output.formatters import format_json, format_markdown, format_terminal
from blastradius.plugins import load_plugin

app = typer.Typer(help="Blast Radius CLI - Static analysis impact assessment tool.")


@app.command()
def index(
    repo_path: str = typer.Argument(".", help="Path to repository"),
    exclude: Optional[str] = typer.Option(
        None, "--exclude", help="Comma-separated list of directory patterns to skip"
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", help="Where to store the index file"
    ),
    framework: Optional[str] = typer.Option(
        None, "--framework", help="Framework plugin to load (django, flask, requests)"
    ),
    force: bool = typer.Option(False, "--force", help="Re-index all files, ignoring mtime cache"),
    verbose: bool = typer.Option(False, "--verbose", help="Print each file as it is parsed"),
):
    """Parse the repo and build the call graph index."""
    repo_p = Path(repo_path).resolve()
    config = Config(str(repo_p))

    # Parse command line overrides, falling back to config defaults
    exclude_list = (
        [e.strip() for e in exclude.split(",") if e.strip()] if exclude else config.exclude
    )
    idx_dir = output_dir if output_dir else config.output_dir

    plugin = load_plugin(framework)
    if plugin:
        exclude_list = plugin.pre_index(exclude_list)

    typer.echo(f"Indexing repository at {repo_p}...")
    index_data = index_repo(str(repo_p), exclude=exclude_list, index_dir=idx_dir)
    if plugin:
        plugin.post_index(index_data)

    typer.echo(
        f"Indexing complete. Symbols: {len(index_data.get('symbols', {}))}, Imports: {len(index_data.get('imports', {}))}"
    )


@app.command()
def analyze(
    target: str = typer.Argument(..., help="Fully qualified name of the changed symbol"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    format: Optional[str] = typer.Option(
        None,
        "--format",
        "-f",
        help="Output format: terminal, json, markdown",
    ),
    framework: Optional[str] = typer.Option(
        None, "--framework", help="Framework plugin to load (django, flask, requests)"
    ),
    max_depth: Optional[int] = typer.Option(None, "--max-depth", help="Maximum BFS depth"),
    threshold: Optional[int] = typer.Option(
        None, "--threshold", help="Exit code 1 if blast radius exceeds threshold"
    ),
    strict: Optional[bool] = typer.Option(
        None, "--strict", help="If true, exit 1 when threshold exceeded"
    ),
    index_dir: Optional[str] = typer.Option(
        None, "--index-dir", help="Location of the index folder"
    ),
    no_chains: bool = typer.Option(False, "--no-chains", help="Omit call chains from output"),
    diagnostics: bool = typer.Option(False, "--diagnostics", "-d", help="Expose diagnostics"),
):
    """Compute the blast radius of a single function or method."""
    repo_path = Path(repo).resolve()
    config = Config(str(repo_path))

    # Resolve options with config overrides
    fmt = format if format else config.default_output
    depth = max_depth if max_depth is not None else config.max_depth
    idx_dir = index_dir if index_dir else config.output_dir
    thresh = threshold if threshold is not None else config.threshold
    is_strict = strict if strict is not None else config.strict

    # Load index and resolve graph
    plugin = load_plugin(framework)
    exclude_list = config.exclude
    if plugin:
        exclude_list = plugin.pre_index(exclude_list)

    index_data = index_repo(str(repo_path), exclude=exclude_list, index_dir=idx_dir)
    if plugin:
        plugin.post_index(index_data)

    G = build_graph(index_data)
    if plugin:
        plugin.post_graph(G)

    rev = build_reverse_graph(G)

    results = compute_blast_radius(rev, target, max_depth=depth, root_dir=str(repo_path))

    # Output rendering
    if fmt == "json":
        print(format_json(results))
    elif fmt == "markdown":
        print(format_markdown(results, target))
    else:
        format_terminal(results, target)

    # Expose diagnostics if requested
    if diagnostics:
        _print_diagnostics_table()

    # Threshold checks
    total_impacted = len(results)
    if thresh > 0 and total_impacted > thresh:
        typer.echo(
            f"\nWarning: Impacted tests ({total_impacted}) exceed threshold ({thresh})!",
            err=True,
        )
        if is_strict:
            raise typer.Exit(code=1)


@app.command()
def diff(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    base: Optional[str] = typer.Option(None, "--base", help="Git ref to diff against"),
    staged: bool = typer.Option(False, "--staged", help="Only analyze staged changes"),
    format: Optional[str] = typer.Option(
        None,
        "--format",
        "-f",
        help="Output format: terminal, json, markdown",
    ),
    framework: Optional[str] = typer.Option(
        None, "--framework", help="Framework plugin to load (django, flask, requests)"
    ),
    threshold: Optional[int] = typer.Option(
        None, "--threshold", help="Exit code 1 if total tests at risk exceeds threshold"
    ),
    strict: Optional[bool] = typer.Option(
        None, "--strict", help="If true, exit 1 when threshold exceeded"
    ),
    index_dir: Optional[str] = typer.Option(
        None, "--index-dir", help="Location of the index folder"
    ),
    diagnostics: bool = typer.Option(False, "--diagnostics", "-d", help="Expose diagnostics"),
):
    """Analyze all functions changed in the current git diff."""
    repo_path = Path(repo).resolve()
    config = Config(str(repo_path))

    # Resolve options
    fmt = format if format else config.default_output
    idx_dir = index_dir if index_dir else config.output_dir
    thresh = threshold if threshold is not None else config.threshold
    is_strict = strict if strict is not None else config.strict
    git_base = base if base else config.default_base

    # Run git diff subprocess
    cmd = ["git", "diff", "--unified=0"]
    if staged:
        cmd.append("--staged")
    elif git_base:
        cmd.append(git_base)

    try:
        res = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, check=True)
        diff_content = res.stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        typer.echo(f"Error running git diff: {e}", err=True)
        raise typer.Exit(code=1)

    # Parse and index
    plugin = load_plugin(framework)
    exclude_list = config.exclude
    if plugin:
        exclude_list = plugin.pre_index(exclude_list)

    index_data = index_repo(str(repo_path), exclude=exclude_list, index_dir=idx_dir)
    if plugin:
        plugin.post_index(index_data)

    symbols = index_data.get("symbols", {})

    changed_lines = parse_git_diff(diff_content)
    changed_symbols = get_symbols_for_changed_lines(changed_lines, symbols)

    if not changed_symbols:
        typer.echo("No modified symbols found in the git diff.")
        raise typer.Exit(code=0)

    # Build Graph
    G = build_graph(index_data)
    if plugin:
        plugin.post_graph(G)

    rev = build_reverse_graph(G)

    # Collect affected tests
    aggregated_results: dict[str, Any] = {}
    for sym in changed_symbols:
        res_list = compute_blast_radius(rev, sym, root_dir=str(repo_path))
        for hit in res_list:
            test_fun = hit.test_function
            if test_fun not in aggregated_results or hit.score > aggregated_results[test_fun].score:
                aggregated_results[test_fun] = hit

    results = list(aggregated_results.values())

    # Output rendering
    target_summary = ", ".join(changed_symbols)
    if fmt == "json":
        print(format_json(results))
    elif fmt == "markdown":
        print(format_markdown(results, target_summary))
    else:
        format_terminal(results, target_summary)

    if diagnostics:
        _print_diagnostics_table()

    # Threshold checks
    total_impacted = len(results)
    if thresh > 0 and total_impacted > thresh:
        typer.echo(
            f"\nWarning: Impacted tests ({total_impacted}) exceed threshold ({thresh})!",
            err=True,
        )
        if is_strict:
            raise typer.Exit(code=1)


@app.command()
def serve(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    port: Optional[int] = typer.Option(None, "--port", help="Exposed port for the server"),
):
    """Start the Model Context Protocol (MCP) stdio server."""
    repo_path = Path(repo).resolve()
    # Add repo_path environment context so the MCP server picks up the right root
    os.environ["BLASTRADIUS_MCP_REPO"] = str(repo_path)

    from blastradius.output.mcp_server import main as mcp_main

    typer.echo(f"Starting MCP stdio server for repository: {repo_path}...", err=True)
    mcp_main()


def _print_diagnostics_table() -> None:
    """Print the rich diagnostic table helper."""
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


if __name__ == "__main__":
    app()
