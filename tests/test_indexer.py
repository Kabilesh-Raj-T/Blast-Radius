from pathlib import Path
from unittest.mock import patch

import pytest
from blastradius.indexer import index_repo, load_index, save_index
from blastradius.symbol import Symbol


def make_symbol(
    unique_id: str,
    module: str,
    filepath: str,
    function_name: str,
    decorators: list[str] | None = None,
    line_no: int = 1,
    col_offset: int = 0,
    visibility: str = "public",
    async_sync: str = "sync",
    class_name: str | None = None,
    nested_info: dict | None = None,
) -> Symbol:
    return Symbol(
        unique_id=unique_id,
        module=module,
        filepath=filepath,
        class_name=class_name,
        function_name=function_name,
        decorators=decorators or [],
        line_no=line_no,
        col_offset=col_offset,
        visibility=visibility,
        async_sync=async_sync,
        nested_info=nested_info,
    )


def test_save_and_load_index(tmp_path):
    sym = make_symbol("file.func", "file", "file.py", "func")
    index_data = {"symbols": {sym.unique_id: sym.to_dict()}, "imports": {"file.py": {}}}
    file_path = tmp_path / "index.json"
    save_index(index_data, str(file_path))

    loaded = load_index(str(file_path))
    assert loaded == index_data


def test_load_index_non_existent():
    assert load_index("non_existent_file.json") == {}


def test_index_repo_basic(tmp_path):
    repo = tmp_path / "my_repo"
    repo.mkdir()

    gitignore = repo / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    utils = repo / "utils.py"
    utils.write_text("def parse_date(): pass\n", encoding="utf-8")

    billing = repo / "billing.py"
    billing.write_text("def invoice(): pass\n", encoding="utf-8")

    index = index_repo(str(repo))

    assert "symbols" in index
    assert "imports" in index

    symbols = index["symbols"]
    assert "utils.parse_date" in symbols
    assert symbols["utils.parse_date"]["function_name"] == "parse_date"
    assert symbols["utils.parse_date"]["filepath"] == "utils.py"

    assert "billing.invoice" in symbols
    assert symbols["billing.invoice"]["function_name"] == "invoice"
    assert symbols["billing.invoice"]["filepath"] == "billing.py"

    git_content = gitignore.read_text(encoding="utf-8")
    assert ".blastradius/" in git_content


def test_index_repo_exclude(tmp_path):
    repo = tmp_path / "my_repo"
    repo.mkdir()

    keep = repo / "keep.py"
    keep.write_text("def keep_func(): pass\n", encoding="utf-8")

    venv_dir = repo / ".venv"
    venv_dir.mkdir()
    skip = venv_dir / "skip.py"
    skip.write_text("def skip_func(): pass\n", encoding="utf-8")

    index = index_repo(str(repo), exclude=[".venv", "__pycache__"])
    symbols = index["symbols"]

    assert "keep.keep_func" in symbols
    assert not any("skip" in k for k in symbols.keys())


def test_index_repo_incremental_cache(tmp_path):
    repo = tmp_path / "my_repo"
    repo.mkdir()

    file_a = repo / "a.py"
    file_a.write_text("def func_a(): pass\n", encoding="utf-8")

    file_b = repo / "b.py"
    file_b.write_text("def func_b(): pass\n", encoding="utf-8")

    index1 = index_repo(str(repo))
    assert "a.func_a" in index1["symbols"]
    assert "b.func_b" in index1["symbols"]

    # Second run: parse_file should not be called
    with patch("blastradius.indexer.parse_file") as mock_parse:
        index2 = index_repo(str(repo))
        assert index2 == index1
        mock_parse.assert_not_called()

    # Modify file_a
    stat = file_a.stat()
    file_a.write_text("def func_a_new(): pass\n", encoding="utf-8")
    os_mtime = stat.st_mtime + 5.0
    import os

    os.utime(str(file_a), (os_mtime, os_mtime))

    new_sym = make_symbol("a.func_a_new", "a", "a.py", "func_a_new")
    with patch("blastradius.indexer.parse_file", return_value=([new_sym], {})) as mock_parse:
        index3 = index_repo(str(repo))
        assert "a.func_a_new" in index3["symbols"]
        assert "b.func_b" in index3["symbols"]  # kept from cache
        mock_parse.assert_called_once_with(str(file_a), str(repo.resolve()))

    # Delete b.py
    file_b.unlink()
    index4 = index_repo(str(repo))
    assert "a.func_a_new" in index4["symbols"]
    assert "b.func_b" not in index4["symbols"]


@pytest.mark.integration
def test_simple_repo_integration(tmp_path):
    import shutil

    src_dir = Path("tests/fixtures/simple_repo")
    dest_dir = tmp_path / "simple_repo"
    shutil.copytree(src_dir, dest_dir)

    index = index_repo(str(dest_dir))
    symbols = index["symbols"]
    imports = index["imports"]

    assert "utils.parser.parse_date" in symbols
    assert isinstance(imports, dict)

    assert symbols["utils.parser.parse_date"]["function_name"] == "parse_date"
    assert "billing.invoice.generate_invoice" in symbols
    assert "tests.test_billing.test_generate_invoice" in symbols

    # Exclude pattern works
    index_ex = index_repo(
        str(dest_dir), exclude=["tests", "__pycache__"], index_dir=str(dest_dir / ".blastradius_ex")
    )
    assert "utils.parser.parse_date" in index_ex["symbols"]
    assert "tests.test_billing.test_generate_invoice" not in index_ex["symbols"]

    # Round trip
    index_file = dest_dir / "index_custom.json"
    save_index(index, str(index_file))
    loaded = load_index(str(index_file))
    assert loaded == index

    # Incremental cache check
    cache_file = dest_dir / ".blastradius" / "mtime_cache.json"
    assert cache_file.exists()

    with patch("blastradius.indexer.parse_file") as mock_parse:
        index_re1 = index_repo(str(dest_dir))
        assert index_re1 == index
        mock_parse.assert_not_called()

    # Modify parser.py
    parser_py = dest_dir / "utils" / "parser.py"
    stat = parser_py.stat()
    parser_py.write_text("def parse_date_modified(): pass\n", encoding="utf-8")

    new_mtime = stat.st_mtime + 5.0
    import os

    os.utime(str(parser_py), (new_mtime, new_mtime))

    mod_sym = make_symbol(
        "utils.parser.parse_date_modified",
        "utils.parser",
        "utils/parser.py",
        "parse_date_modified",
    )
    with patch("blastradius.indexer.parse_file", return_value=([mod_sym], {})) as mock_parse:
        index_re2 = index_repo(str(dest_dir))
        mock_parse.assert_called_once_with(str(parser_py), str(dest_dir.resolve()))
        assert "utils.parser.parse_date_modified" in index_re2["symbols"]
        assert "utils.parser.parse_date" not in index_re2["symbols"]
