"""Unit tests for optimized incremental indexing caching, hot indexing speed, and format validation."""

import json
from pathlib import Path

from blastradius.indexer import index_repo


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_incremental_indexing_flow(tmp_path):
    """Verify that incremental indexing re-uses unchanged symbols and updates changed ones."""
    # 1. Setup mock repo
    repo_path = tmp_path / "repo"
    _create_file(repo_path, "main.py", "def run():\n    pass\n")
    _create_file(repo_path, "utils.py", "def helper():\n    pass\n")

    # 2. Cold indexing
    index1 = index_repo(str(repo_path))
    assert "main.run" in index1["symbols"]
    assert "utils.helper" in index1["symbols"]

    # 3. Hot indexing - no changes
    index2 = index_repo(str(repo_path))
    assert index2["symbols"] == index1["symbols"]

    # 4. Modify main.py
    _create_file(repo_path, "main.py", "def run():\n    pass\n\ndef extra():\n    pass\n")
    index3 = index_repo(str(repo_path))

    assert "main.run" in index3["symbols"]
    assert "main.extra" in index3["symbols"]
    # utils.py should be reused
    assert "utils.helper" in index3["symbols"]


def test_invalid_index_format_forces_rebuild(tmp_path):
    """Verify that a legacy/invalid index format forces a rebuild instead of reusing cached empty structures."""
    repo_path = tmp_path / "repo"
    _create_file(repo_path, "main.py", "def run():\n    pass\n")

    # Write a legacy index (not containing "symbols" or "imports" keys)
    blastradius_dir = repo_path / ".blastradius"
    blastradius_dir.mkdir(parents=True, exist_ok=True)
    legacy_index = {"main.py:run": []}
    with open(blastradius_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(legacy_index, f)

    # Write a cache that matches the mtime
    mtime = (repo_path / "main.py").stat().st_mtime
    with open(blastradius_dir / "mtime_cache.json", "w", encoding="utf-8") as f:
        json.dump({"main.py": mtime}, f)

    # Indexing should discard the legacy format and build the correct symbols
    index = index_repo(str(repo_path))
    assert "symbols" in index
    assert "main.run" in index["symbols"]
