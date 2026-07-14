from blastradius.parser import parse_file
from blastradius.symbol import Symbol


def _write_and_parse(tmp_path, code: str) -> list[Symbol]:
    """Helper to write code to a temp file and parse it."""
    file_path = tmp_path / "temp_source.py"
    file_path.write_text(code, encoding="utf-8")
    symbols, _ = parse_file(str(file_path), str(tmp_path))
    return symbols


def test_single_function_attributes(tmp_path):
    code = """
def my_func():
    return 1
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    sym = result[0]
    assert sym.function_name == "my_func"
    assert sym.unique_id == "temp_source.my_func"
    assert sym.module == "temp_source"
    assert sym.class_name is None
    assert sym.decorators == []
    assert sym.visibility == "public"
    assert sym.async_sync == "sync"
    assert sym.nested_info is None
    assert sym.line_no == 2
    assert sym.col_offset == 0


def test_async_function(tmp_path):
    code = """
async def fetch_data():
    pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    assert result[0].async_sync == "async"


def test_class_method(tmp_path):
    code = """
class Invoice:
    def generate(self):
        pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    sym = result[0]
    assert sym.function_name == "generate"
    assert sym.class_name == "Invoice"
    assert sym.unique_id == "temp_source.Invoice.generate"


def test_nested_classes(tmp_path):
    code = """
class Outer:
    class Inner:
        def method(self):
            pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    sym = result[0]
    assert sym.function_name == "method"
    assert sym.class_name == "Outer.Inner"
    assert sym.unique_id == "temp_source.Outer.Inner.method"


def test_decorators_extraction(tmp_path):
    code = """
@staticmethod
@abc.abstractmethod
@lru_cache(maxsize=128)
def worker():
    pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    assert result[0].decorators == ["staticmethod", "abc.abstractmethod", "lru_cache"]


def test_visibility(tmp_path):
    code = """
def public_func(): pass
def _private_func(): pass
def __init__(self): pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 3

    # Sort by line number to assert in order
    sorted_res = sorted(result, key=lambda s: s.line_no)
    assert sorted_res[0].function_name == "public_func"
    assert sorted_res[0].visibility == "public"

    assert sorted_res[1].function_name == "_private_func"
    assert sorted_res[1].visibility == "private"

    assert sorted_res[2].function_name == "__init__"
    assert sorted_res[2].visibility == "public"  # dunders are public


def test_nested_functions(tmp_path):
    code = """
def outer():
    def inner():
        pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 2

    outer_sym = next(s for s in result if s.function_name == "outer")
    inner_sym = next(s for s in result if s.function_name == "inner")

    assert outer_sym.unique_id == "temp_source.outer"
    assert outer_sym.nested_info is None

    assert inner_sym.unique_id == "temp_source.outer.inner"
    assert inner_sym.nested_info == {"parent_function": "outer", "parent_id": "temp_source.outer"}


def test_parse_file_syntax_error(tmp_path):
    code = "def invalid_syntax("
    result = _write_and_parse(tmp_path, code)
    assert result == []


def test_non_utf8_bytes(tmp_path):
    file_path = tmp_path / "binary.py"
    file_path.write_bytes(b"\xff\xfe")
    symbols, imports = parse_file(str(file_path))
    assert symbols == []
    assert imports == {}


def test_empty_file(tmp_path):
    result = _write_and_parse(tmp_path, "")
    assert result == []


def test_only_imports_no_functions(tmp_path):
    code = """
import os
import sys
"""
    result = _write_and_parse(tmp_path, code)
    assert result == []


def test_lambda_assignment_not_tracked(tmp_path):
    code = """
fn = lambda x: print(x)
"""
    result = _write_and_parse(tmp_path, code)
    assert result == []


def test_imports_map_extraction(tmp_path):
    code = """
import os.path as osp
import sys
from utils.parser import parse_date as pd
from utils.parser import parse_datetime
from .sibling import local_helper
from ..parent import parent_helper
"""
    # Write this code to billing/invoice.py relative to tmp_path
    # package billing
    billing_dir = tmp_path / "billing"
    billing_dir.mkdir()
    file_path = billing_dir / "invoice.py"
    file_path.write_text(code, encoding="utf-8")

    # Module name should be billing.invoice
    _, imports = parse_file(str(file_path), str(tmp_path))

    # Assertions
    assert imports["osp"] == "os.path"
    assert imports["sys"] == "sys"
    assert imports["pd"] == "utils.parser.parse_date"
    assert imports["parse_datetime"] == "utils.parser.parse_datetime"
    # Sibling relative import
    assert imports["local_helper"] == "billing.sibling.local_helper"
    # Parent relative import
    assert imports["parent_helper"] == "parent.parent_helper"
