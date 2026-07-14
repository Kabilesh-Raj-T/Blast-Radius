"""Indexer module for building dependency indexes."""

import json
from pathlib import Path

from blastradius.parser import parse_file


def load_index(path: str) -> dict[str, list[str]]:
    """Load the index dictionary from a JSON file.

    Returns an empty dict if the file does not exist.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_index(index: dict[str, list[str]], path: str) -> None:
    """Save the index dictionary to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _add_to_gitignore(repo_path: Path) -> None:
    """Ensure .blastradius/ is added to the .gitignore file."""
    gitignore_path = repo_path / ".gitignore"
    if gitignore_path.exists():
        try:
            content = gitignore_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            if not any(
                line.strip() == ".blastradius/" or line.strip() == ".blastradius" for line in lines
            ):
                if content and not content.endswith("\n"):
                    content += "\n"
                content += ".blastradius/\n"
                gitignore_path.write_text(content, encoding="utf-8")
        except Exception:
            pass


def index_repo(
    repo_path: str,
    exclude: list[str] | None = None,
    index_dir: str | None = None,
) -> dict[str, list[str]]:
    """Walk the repository and build the master index of all Python function calls.

    Uses mtime-based incremental caching to skip unchanged files.
    """
    if exclude is None:
        exclude = ["__pycache__", "venv", ".venv"]

    repo_dir = Path(repo_path).resolve()

    if index_dir is None:
        blastradius_dir = repo_dir / ".blastradius"
    else:
        blastradius_dir = Path(index_dir).resolve()

    index_path = blastradius_dir / "index.json"
    cache_path = blastradius_dir / "mtime_cache.json"

    # Load existing index and cache
    prev_index = load_index(str(index_path))
    prev_cache = {}
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                prev_cache = json.load(f)
        except Exception:
            prev_cache = {}

    new_index = {}
    current_cache = {}

    # Walk files
    for filepath in repo_dir.rglob("*.py"):
        # Check exclusion list against path components
        parts = filepath.relative_to(repo_dir).parts
        if any(part in exclude for part in parts):
            continue

        rel_path = filepath.relative_to(repo_dir)
        rel_path_str = str(rel_path).replace("\\", "/")

        try:
            current_mtime = filepath.stat().st_mtime
        except OSError:
            continue

        current_cache[rel_path_str] = current_mtime

        # Check cache hit
        reused = False
        if rel_path_str in prev_cache and prev_cache[rel_path_str] == current_mtime:
            # Find and reuse previous index entries for this file
            file_prefix = f"{rel_path_str}:"
            for k, v in prev_index.items():
                if k.startswith(file_prefix):
                    new_index[k] = v
            reused = True

        if not reused:
            file_results = parse_file(str(filepath))
            for fn_name, calls in file_results.items():
                new_index[f"{rel_path_str}:{fn_name}"] = calls

    # Save outputs
    save_index(new_index, str(index_path))
    blastradius_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(current_cache, f, indent=2)

    _add_to_gitignore(repo_dir)

    return new_index
