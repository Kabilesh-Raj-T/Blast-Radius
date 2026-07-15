from blastradius.core.symbol import Symbol
from blastradius.parsing import parse_file


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
    assert sym.kind == "function"
    assert sym.method_kind is None
    assert sym.bases is None


def test_class_attributes(tmp_path):
    code = """
class Invoice(BaseModel, abc.ABC):
    pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    sym = result[0]
    assert sym.kind == "class"
    assert sym.function_name is None
    assert sym.class_name is None  # top-level class has no outer class name
    assert sym.unique_id == "temp_source.Invoice"
    assert sym.bases == ["BaseModel", "abc.ABC"]
    assert sym.visibility == "public"
    assert sym.method_kind is None


def test_nested_classes(tmp_path):
    code = """
class Outer:
    class Inner:
        pass
"""
    result = _write_and_parse(tmp_path, code)
    # Expect 2 class symbols: Outer and Outer.Inner
    assert len(result) == 2
    outer = next(s for s in result if s.unique_id == "temp_source.Outer")
    inner = next(s for s in result if s.unique_id == "temp_source.Outer.Inner")

    assert outer.kind == "class"
    assert outer.class_name is None

    assert inner.kind == "class"
    assert inner.class_name == "Outer"


def test_method_classifications(tmp_path):
    code = """
class Order:
    def instance_m(self): pass

    @staticmethod
    def static_m(): pass

    @classmethod
    def class_m(cls): pass

    @property
    def price(self): pass

    @price.setter
    def price(self, val): pass

    @abstractmethod
    def run(self): pass
"""
    result = _write_and_parse(tmp_path, code)
    # Order (class) + 6 methods = 7 symbols
    assert len(result) == 7

    methods = {s.function_name: s for s in result if s.kind == "method"}

    assert methods["instance_m"].method_kind == "instance"
    assert methods["static_m"].method_kind == "static"
    assert methods["class_m"].method_kind == "class"
    assert methods["price"].method_kind == "property"
    assert methods["run"].method_kind == "abstract"


def test_async_function(tmp_path):
    code = """
async def fetch_data():
    pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    assert result[0].async_sync == "async"


def test_decorators_extraction(tmp_path):
    code = """
@staticmethod
@abc.abstractmethod
def worker():
    pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    assert result[0].decorators == ["staticmethod", "abc.abstractmethod"]


def test_visibility(tmp_path):
    code = """
def public_func(): pass
def _private_func(): pass
def __init__(self): pass
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 3

    sorted_res = sorted(result, key=lambda s: s.line_no)
    assert sorted_res[0].function_name == "public_func"
    assert sorted_res[0].visibility == "public"

    assert sorted_res[1].function_name == "_private_func"
    assert sorted_res[1].visibility == "private"

    assert sorted_res[2].function_name == "__init__"
    assert sorted_res[2].visibility == "public"


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
    assert outer_sym.nested_info == {"scope_info": {"local_defs": ["inner"]}}

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
    billing_dir = tmp_path / "billing"
    billing_dir.mkdir()
    file_path = billing_dir / "invoice.py"
    file_path.write_text(code, encoding="utf-8")

    _, imports = parse_file(str(file_path), str(tmp_path))

    assert imports["osp"] == "os.path"
    assert imports["sys"] == "sys"
    assert imports["pd"] == "utils.parser.parse_date"
    assert imports["parse_datetime"] == "utils.parser.parse_datetime"
    assert imports["local_helper"] == "billing.sibling.local_helper"
    assert imports["parent_helper"] == "parent.parent_helper"


def test_function_calls_extraction(tmp_path):
    code = """
def main():
    parse_date("2026-07-14")
    self.validate()
    obj.method()
"""
    result = _write_and_parse(tmp_path, code)
    assert len(result) == 1
    assert set(result[0].calls or []) == {"parse_date", "self.validate", "obj.method"}


def test_extract_local_types_and_decorator_calls(tmp_path):
    code = """
class Worker:
    @decorator(arg)
    def do_work(self, item: Item):
        invoice: Invoice = get_invoice()
        client = Client()
        client.notify()
"""
    result = _write_and_parse(tmp_path, code)
    # Class + method = 2 symbols
    assert len(result) == 2

    method = next(s for s in result if s.kind == "method")
    assert method.local_types == {
        "self": "Worker",
        "cls": "Worker",
        "item": "Item",
        "invoice": "Invoice",
        "client": "Client",
    }

    # Decorator call `@decorator(arg)` should be captured in calls
    assert "decorator" in (method.calls or [])
