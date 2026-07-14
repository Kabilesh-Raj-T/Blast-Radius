"""Script to index the requests repository and find the most-called functions."""

from collections import Counter

import rich
from blastradius.indexer import index_repo


def main():
    repo_path = r"C:\Users\Kabilesh\AppData\Local\Temp\requests"
    rich.print(f"Indexing requests repository at [green]{repo_path}[/]...")

    # We will exclude tests and docs/venv to only index src
    index = index_repo(
        repo_path,
        exclude=["tests", "docs", "venv", ".venv", "__pycache__", "build", "dist"],
    )

    rich.print(f"Indexing completed. Total function definitions indexed: {len(index)}")

    # Count the most frequently called functions (the ones appearing in the values lists)
    call_counter = Counter()
    for calls in index.values():
        for call in calls:
            call_counter[call] += 1

    rich.print("\n[bold cyan]Top 10 most-called functions/attributes in requests:[/]")
    for func, count in call_counter.most_common(10):
        rich.print(f"  [yellow]{func}[/]: {count} times")


if __name__ == "__main__":
    main()
