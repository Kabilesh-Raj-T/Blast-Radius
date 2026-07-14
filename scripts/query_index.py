"""Script to query index and resolver for debug purposes."""

import json
from pathlib import Path

import rich
from blastradius.resolver import resolve


def main():
    repo_path = Path(r"C:\Users\Kabilesh\AppData\Local\Temp\django")
    index_path = repo_path / ".blastradius" / "index.json"

    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    # Let's see if django/db/models/fields/__init__.py:to_python is in the index
    to_python_keys = [
        k
        for k in index
        if ("fields/__init__.py:to_python" in k) or ("fields/__init__.py" in k and "to_python" in k)
    ]

    rich.print("[bold cyan]Found to_python keys in index:[/]")
    for k in to_python_keys:
        rich.print(f"  {k} -> {index[k]}")

    # Let's resolve "parse_date"
    rich.print("\n[bold cyan]Resolving 'parse_date':[/]")
    res = resolve("parse_date", index)
    rich.print(res)

    # Let's find who calls parse_date in the index
    rich.print("\n[bold cyan]Who calls parse_date in index?[/]")
    callers = []
    for k, v in index.items():
        if "parse_date" in v:
            callers.append(k)
            rich.print(f"  {k} calls parse_date")


if __name__ == "__main__":
    main()
