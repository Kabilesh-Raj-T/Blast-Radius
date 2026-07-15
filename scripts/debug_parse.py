#!/usr/bin/env python3
"""Debug parse script to run parse_file on the simple_repo fixture files."""

from pathlib import Path

import rich
from blastradius.parsing import parse_file


def main():
    simple_repo = Path("tests/fixtures/simple_repo")
    if not simple_repo.exists():
        rich.print(f"[red]Error:[/] {simple_repo} directory does not exist.")
        return

    # Find all python files recursively in the simple_repo fixture
    py_files = sorted(list(simple_repo.rglob("*.py")))

    rich.print("[bold cyan]Parsing files in simple_repo fixture...[/]")
    for filepath in py_files:
        # Ignore empty __init__.py files for cleaner output, or show them if they have functions
        rel_path = filepath.relative_to(simple_repo)
        result = parse_file(str(filepath))

        # Format the relative path for display (using forward slashes)
        display_path = str(rel_path).replace("\\", "/")

        rich.print(f"\n[green]{display_path}[/]:")
        rich.print(result)


if __name__ == "__main__":
    main()
