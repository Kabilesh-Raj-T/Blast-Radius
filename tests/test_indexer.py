import time
from pathlib import Path
from unittest.mock import patch

import pytest
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


@pytest.mark.integration
def test_simple_repo_integration(tmp_path):
    # Copy simple_repo files into a temp directory so we can run and mutate it
    import shutil

    src_dir = Path("tests/fixtures/simple_repo")
    dest_dir = tmp_path / "simple_repo"
    shutil.copytree(src_dir, dest_dir)

    # 1. index_repo returns keys for all 3 functions across the 3 files
    index = index_repo(str(dest_dir))
    assert "utils/parser.py:parse_date" in index
    assert index["utils/parser.py:parse_date"] == ["strptime"]
    assert "billing/invoice.py:generate_invoice" in index
    assert "parse_date" in index["billing/invoice.py:generate_invoice"]
    assert "tests/test_billing.py:test_generate_invoice" in index
    assert index["tests/test_billing.py:test_generate_invoice"] == ["generate_invoice"]

    # 2. Exclude pattern works: exclude=['tests'] removes test file keys
    index_ex = index_repo(
        str(dest_dir), exclude=["tests", "__pycache__"], index_dir=str(dest_dir / ".blastradius_ex")
    )
    assert "utils/parser.py:parse_date" in index_ex
    assert "billing/invoice.py:generate_invoice" in index_ex
    assert "tests/test_billing.py:test_generate_invoice" not in index_ex

    # 3. save_index and load_index round-trip: saved JSON loads back to identical dict
    index_file = dest_dir / "index_custom.json"
    save_index(index, str(index_file))
    loaded = load_index(str(index_file))
    assert loaded == index

    # 4. Incremental cache: index once, modify one file, re-index,
    # verify only 1 file was re-parsed (check mtime_cache.json)

    cache_file = dest_dir / ".blastradius" / "mtime_cache.json"
    assert cache_file.exists()

    # Re-index without changes: check that parse_file is not called
    with patch("blastradius.indexer.parse_file") as mock_parse:
        index_re1 = index_repo(str(dest_dir))
        assert index_re1 == index
        mock_parse.assert_not_called()

    # Modify utils/parser.py
    parser_py = dest_dir / "utils" / "parser.py"
    stat = parser_py.stat()
    parser_py.write_text("def parse_date(date_str):\n    return 'new_parse'\n", encoding="utf-8")

    new_mtime = stat.st_mtime + 5.0
    import os

    os.utime(str(parser_py), (new_mtime, new_mtime))

    with patch("blastradius.indexer.parse_file", return_value={"parse_date": []}) as mock_parse:
        index_re2 = index_repo(str(dest_dir))
        mock_parse.assert_called_once_with(str(parser_py))
        assert index_re2["utils/parser.py:parse_date"] == []
