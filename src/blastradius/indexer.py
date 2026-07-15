"""Indexer module for building dependency indexes."""

import json
from pathlib import Path
from typing import Any

from blastradius.context import get_repository_context
from blastradius.languages import registry


def load_index(path: str) -> dict[str, dict[str, Any]]:
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


def save_index(index: dict[str, dict[str, Any]], path: str) -> None:
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
) -> dict[str, dict[str, Any]]:
    """Walk the repository and build a master symbol table and import mapping.

    Uses mtime-based incremental caching to skip unchanged files.
    """
    import time

    from blastradius.diagnostics import tracker

    start_time = time.perf_counter()

    if exclude is None:
        exclude = ["__pycache__", "venv", ".venv"]

    repo_dir = Path(repo_path).resolve()
    repo_context = get_repository_context(str(repo_dir))

    if index_dir is None:
        blastradius_dir = repo_dir / ".blastradius"
    else:
        blastradius_dir = Path(index_dir).resolve()

    index_path = blastradius_dir / "index.json"
    cache_path = blastradius_dir / "mtime_cache.json"

    # 1. Quick collect current mtimes
    supported_exts = registry.extensions
    current_cache = {}
    seen_files: set[Path] = set()
    for filepath in repo_dir.rglob("*"):
        if (
            filepath in seen_files
            or filepath.is_dir()
            or filepath.suffix.lower() not in supported_exts
        ):
            continue
        seen_files.add(filepath)

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

    # 2. Check full cache hit
    prev_cache = {}
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                prev_cache = json.load(f)
        except Exception:
            pass

    if prev_cache and current_cache == prev_cache and index_path.exists():
        index = load_index(str(index_path))
        if index and "symbols" in index and "imports" in index and "modules" in index:
            tracker.skipped_files = len(current_cache)
            tracker.files_indexed = 0
            tracker.symbols = len(index.get("symbols", {}))
            tracker.functions = sum(
                1
                for s in index.get("symbols", {}).values()
                if isinstance(s, dict) and s.get("kind") in ("function", "method")
            )
            tracker.calls = sum(
                len(s.get("calls") or [])
                for s in index.get("symbols", {}).values()
                if isinstance(s, dict)
            )
            tracker.index_time = time.perf_counter() - start_time
            tracker.log_structured("repo_indexing_completed")
            return index

    # 3. Incremental indexing (mtimes changed or new/deleted files)
    prev_index = load_index(str(index_path))
    if prev_index and ("symbols" not in prev_index or "imports" not in prev_index):
        prev_symbols = {}
        prev_imports = {}
        prev_modules = {}
        prev_cache = {}  # Discard cache to force re-parsing
    else:
        prev_symbols = prev_index.get("symbols", {})
        prev_imports = prev_index.get("imports", {})
        prev_modules = prev_index.get("modules", {})

    # Pre-group previous symbols by filepath for O(1) retrieval
    symbols_by_file: dict[str, dict[str, Any]] = {}
    for symbol_id, symbol_dict in prev_symbols.items():
        if isinstance(symbol_dict, dict):
            fpath = symbol_dict.get("filepath")
            if fpath:
                if fpath not in symbols_by_file:
                    symbols_by_file[fpath] = {}
                symbols_by_file[fpath][symbol_id] = symbol_dict

    new_symbols = {}
    new_imports = {}
    new_modules = {}

    for rel_path_str, current_mtime in current_cache.items():
        filepath = repo_dir / rel_path_str
        reused = False
        if rel_path_str in prev_cache and prev_cache[rel_path_str] == current_mtime:
            if rel_path_str in symbols_by_file:
                new_symbols.update(symbols_by_file[rel_path_str])
            # Reuse imports
            if rel_path_str in prev_imports:
                new_imports[rel_path_str] = prev_imports[rel_path_str]
            if rel_path_str in prev_modules:
                new_modules[rel_path_str] = prev_modules[rel_path_str]
            else:
                new_modules[rel_path_str] = repo_context.module_metadata(str(filepath))
            reused = True

        if not reused:
            symbols, import_map = registry.parse_file(str(filepath), str(repo_dir))
            for symbol in symbols:
                new_symbols[symbol.unique_id] = symbol.to_dict()
            new_imports[rel_path_str] = import_map
            new_modules[rel_path_str] = repo_context.module_metadata(str(filepath))

    new_index = {
        "symbols": new_symbols,
        "imports": new_imports,
        "modules": new_modules,
    }

    # Save outputs
    save_index(new_index, str(index_path))
    blastradius_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(current_cache, f, indent=2)

    _add_to_gitignore(repo_dir)

    # Track metrics
    tracker.skipped_files = sum(
        1
        for rel_path_str, current_mtime in current_cache.items()
        if rel_path_str in prev_cache and prev_cache[rel_path_str] == current_mtime
    )
    tracker.files_indexed = len(current_cache) - tracker.skipped_files
    tracker.symbols = len(new_symbols)
    tracker.functions = sum(
        1
        for s in new_symbols.values()
        if isinstance(s, dict) and s.get("kind") in ("function", "method")
    )
    tracker.calls = sum(
        len(s.get("calls") or []) for s in new_symbols.values() if isinstance(s, dict)
    )
    tracker.index_time = time.perf_counter() - start_time
    tracker.log_structured("repo_indexing_completed")

    return new_index


def update_index(
    repo_path: str,
    G: Any,
    exclude: list[str] | None = None,
    index_dir: str | None = None,
) -> tuple[Any, dict, Any]:
    """Incrementally update the graph and index for a repository.

    This is the **hot-path** entry-point intended for repeated calls after
    the initial cold-start build.  Only files whose mtime has changed since
    the last run are re-parsed; the rest of the graph is untouched.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    G:
        The in-memory dependency graph previously loaded from disk.
        Mutated in-place and returned.
    exclude:
        Directory-name fragments to skip (e.g. ``[\"__pycache__\", \".venv\"]``).
        Defaults to ``[\"__pycache__\", \"venv\", \".venv\"]``.
    index_dir:
        Override the ``.blastradius/`` directory.  Defaults to
        ``<repo_path>/.blastradius/``.

    Returns
    -------
    G:
        The updated graph (same object, mutated).
    index:
        The updated symbol + import index (dict).
    delta:
        A :class:`~blastradius.incremental.GraphDelta` describing every
        node / edge that was added or removed.
    """
    from blastradius.incremental import update_graph

    repo_dir = Path(repo_path).resolve()

    if index_dir is None:
        blastradius_dir = repo_dir / ".blastradius"
    else:
        blastradius_dir = Path(index_dir).resolve()

    index_path = blastradius_dir / "index.json"
    cache_path = blastradius_dir / "mtime_cache.json"

    # Load the current index from disk
    index = load_index(str(index_path))
    if not index or ("symbols" not in index or "imports" not in index):
        index = {"symbols": {}, "imports": {}}

    G, index, delta = update_graph(
        G,
        index,
        repo_path,
        exclude=exclude,
        fingerprint_cache_path=str(cache_path),
    )

    # Persist updated index
    save_index(index, str(index_path))

    return G, index, delta
