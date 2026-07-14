import time
from pathlib import Path
from unittest.mock import patch

from blastradius.indexer import index_repo, load_index, save_index


def test_save_and_load_index(tmp_path):
    index_data = {"file.py:func": ["call1", "call2"]}
    file_path = tmp_path / "index.json"
    save_index(index_data, str(file_path))

    loaded = load_index(str(file_path))
    assert loaded == index_data


def test_load_index_non_existent():
    assert load_index("non_existent_file.json") == {}


def test_index_repo_basic(tmp_path):
    # Setup files in a mock repo
    repo = tmp_path / "my_repo"
    repo.mkdir()

    # Create a gitignore
    gitignore = repo / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    utils = repo / "utils.py"
    utils.write_text("def parse_date():\n    strptime()\n", encoding="utf-8")

    billing = repo / "billing.py"
    billing.write_text("def invoice():\n    parse_date()\n", encoding="utf-8")

    # Run indexer
    index = index_repo(str(repo))

    assert "utils.py:parse_date" in index
    assert index["utils.py:parse_date"] == ["strptime"]
    assert "billing.py:invoice" in index
    assert index["billing.py:invoice"] == ["parse_date"]

    # Verify .blastradius/ is added to .gitignore
    git_content = gitignore.read_text(encoding="utf-8")
    assert ".blastradius/" in git_content


def test_index_repo_exclude(tmp_path):
    repo = tmp_path / "my_repo"
    repo.mkdir()

    # File to keep
    keep = repo / "keep.py"
    keep.write_text("def keep_func(): pass\n", encoding="utf-8")

    # File to exclude inside .venv/
    venv_dir = repo / ".venv"
    venv_dir.mkdir()
    skip = venv_dir / "skip.py"
    skip.write_text("def skip_func(): pass\n", encoding="utf-8")

    index = index_repo(str(repo), exclude=[".venv", "__pycache__"])

    assert "keep.py:keep_func" in index
    assert "skip.py:skip_func" not in index
    assert not any(k.startswith(".venv") for k in index.keys())


def test_index_repo_incremental_cache(tmp_path):
    repo = tmp_path / "my_repo"
    repo.mkdir()

    file_a = repo / "a.py"
    file_a.write_text("def func_a(): call_x()\n", encoding="utf-8")

    file_b = repo / "b.py"
    file_b.write_text("def func_b(): call_y()\n", encoding="utf-8")

    # First run
    index1 = index_repo(str(repo))
    assert index1["a.py:func_a"] == ["call_x"]
    assert index1["b.py:func_b"] == ["call_y"]

    # Second run without changes: verify parse_file is not called
    with patch("blastradius.indexer.parse_file") as mock_parse:
        index2 = index_repo(str(repo))
        assert index2 == index1
        mock_parse.assert_not_called()

    # Modify file_a (update mtime and content)
    # Use time.sleep or modify mtime explicitly to ensure it is different
    stat = file_a.stat()
    file_a.write_text("def func_a(): call_z()\n", encoding="utf-8")
    os_mtime = stat.st_mtime + 5.0
    Path(file_a).stat()  # touch
    time.sleep(0.01)
    # Explicitly set mtime to be sure it changed
    import os

    os.utime(str(file_a), (os_mtime, os_mtime))

    # Third run: verify only a.py is parsed
    with patch("blastradius.indexer.parse_file", return_value={"func_a": ["call_z"]}) as mock_parse:
        index3 = index_repo(str(repo))
        assert index3["a.py:func_a"] == ["call_z"]
        assert index3["b.py:func_b"] == ["call_y"]  # kept from cache
        mock_parse.assert_called_once_with(str(file_a))

    # Delete b.py: verify its entries are removed from the index
    file_b.unlink()
    index4 = index_repo(str(repo))
    assert "a.py:func_a" in index4
    assert "b.py:func_b" not in index4
