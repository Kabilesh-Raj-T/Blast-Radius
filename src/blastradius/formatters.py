"""Formatting and output visualization module for terminal, JSON, Markdown, and MCP tool views."""

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


def format_chain(chain: list[str]) -> str:
    """Format call chain FQNs into a readable visual sequence."""
    parts = []
    for node in chain:
        if ":" in node:
            _, name = node.rsplit(":", 1)
        else:
            name = node.split(".")[-1]
        if not name.startswith("module:") and name != "repo":
            parts.append(f"{name}()")
    return " \n↓\n ".join(parts)


def format_terminal(results: list[Any], target: str) -> None:
    """Print affected tests with detailed panels using Rich styling."""
    console = Console()
    if not results:
        console.print(Panel(Text(f"No affected tests found for: {target}", style="bold green")))
        return

    console.print(
        Text(
            f"Blast Radius Analysis: {len(results)} affected tests found for change in {target}\n",
            style="bold blue",
        )
    )
    for hit in results:
        chain_str = format_chain(hit.chain)
        # Indent chain lines for formatting
        indented_chain = "\n  ".join(chain_str.splitlines())

        content = Text()
        content.append("Affected Test: ", style="bold white")
        content.append(f"{hit.test_file}::{hit.test_function.split('.')[-1]}\n", style="bold red")
        content.append("Reason: ", style="bold white")
        content.append(f"{hit.reason}\n", style="bold magenta")
        content.append("Call Chain:\n  ", style="bold white")
        content.append(f"{indented_chain}\n\n", style="cyan")
        content.append("Confidence: ", style="bold white")

        style = (
            "bold green"
            if hit.confidence == "HIGH"
            else "bold yellow"
            if hit.confidence == "MEDIUM"
            else "bold red"
        )
        content.append(f"{hit.confidence} (score: {hit.score:.4f})\n", style=style)
        content.append("Explanation: ", style="bold white")
        content.append(f"{hit.resolution_explanation}")

        panel = Panel(content, title=f"Impacted Test: {hit.test_function}", border_style="dim")
        console.print(panel)


def format_json(results: list[Any]) -> str:
    """Format results as a structured JSON string."""
    data = []
    for hit in results:
        chain_nodes = []
        for node in hit.chain:
            if ":" in node:
                _, name = node.rsplit(":", 1)
            else:
                name = node.split(".")[-1]
            if not name.startswith("module:") and name != "repo":
                chain_nodes.append(f"{name}()")

        data.append(
            {
                "test_function": hit.test_function,
                "test_file": hit.test_file,
                "reason": hit.reason,
                "confidence": hit.confidence,
                "score": hit.score,
                "call_chain": chain_nodes,
                "explanation": hit.resolution_explanation,
            }
        )
    return json.dumps(data, indent=2)


def format_markdown(results: list[Any], target: str) -> str:
    """Format results as a clean Markdown report."""
    lines = [f"# Blast Radius Analysis for `{target}`", ""]
    if not results:
        lines.append("> [!NOTE]")
        lines.append("> No affected tests found.")
        return "\n".join(lines)

    lines.append(f"Found **{len(results)}** affected tests:")
    lines.append("")

    for hit in results:
        chain_str = format_chain(hit.chain)
        # Markdown blockquotes for call chain
        indented_chain = "\n> &darr;  \n> ".join(f"`{c}`" for c in chain_str.split("\n \n↓\n "))

        lines.append(f"### Affected Test: `{hit.test_file}::{hit.test_function.split('.')[-1]}`")
        lines.append(f"- **Reason**: {hit.reason}")
        lines.append(f"- **Confidence**: `{hit.confidence}` (score: `{hit.score:.4f}`)")
        lines.append("- **Call Chain**:")
        lines.append(f"> {indented_chain}")
        lines.append(f"- **Explanation**: {hit.resolution_explanation}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def format_mcp(results: list[Any], target: str) -> dict[str, Any]:
    """Format results as a Model Context Protocol tool content dictionary."""
    text_content = format_markdown(results, target)
    return {"content": [{"type": "text", "text": text_content}]}
