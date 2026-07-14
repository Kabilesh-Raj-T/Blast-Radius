from blastradius.parser import parse_file


def _write_and_parse(tmp_path, code: str) -> dict[str, list[str]]:
    """Helper to write code to a temp file and parse it."""
    file_path = tmp_path / "temp_source.py"
    file_path.write_text(code, encoding="utf-8")
    return parse_file(str(file_path))


def test_single_function_no_calls(tmp_path):
    code = """
def my_func():
    x = 1 + 2
    return x
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {"my_func": []}


def test_direct_call(tmp_path):
    code = """
def main():
    parse_date("2026-07-14")
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {"main": ["parse_date"]}


def test_method_call_self(tmp_path):
    code = """
def test_func():
    self.validate()
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {"test_func": ["validate"]}


def test_method_call_obj(tmp_path):
    code = """
def run():
    obj.method()
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {"run": ["method"]}


def test_two_functions_calling_each_other(tmp_path):
    code = """
def func_a():
    func_b()

def func_b():
    func_a()
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {
        "func_a": ["func_b"],
        "func_b": ["func_a"],
    }


def test_nested_function_definitions(tmp_path):
    code = """
def outer():
    def inner():
        helper_a()
    inner()
    helper_b()
"""
    result = _write_and_parse(tmp_path, code)
    # calls inside inner() must belong to inner, not outer
    assert "outer" in result
    assert "inner" in result
    assert result["outer"] == ["inner", "helper_b"]
    assert result["inner"] == ["helper_a"]


def test_async_function(tmp_path):
    code = """
async def fetch_data():
    await resolve_url()
    return await api.get()
"""
    result = _write_and_parse(tmp_path, code)
    assert result == {"fetch_data": ["resolve_url", "get"]}


def test_complex_arguments(tmp_path):
    code = """
def process():
    format_output(get_data(param=1), "json")
"""
    result = _write_and_parse(tmp_path, code)
    # The arguments to format_output contains get_data call.
    # Order of walking: ast.walk/generic_visit should visit all.
    # format_output is visited, get_data is visited.
    assert "process" in result
    # It should extract both calls
    assert set(result["process"]) == {"format_output", "get_data"}


def test_decorators_do_not_interfere(tmp_path):
    code = """
@register
@lru_cache(maxsize=128)
def worker():
    compute()
"""
    result = _write_and_parse(tmp_path, code)
    # Note: the decorator call lru_cache(maxsize=128) is outside the function body.
    # So compute() is inside, and should be collected.
    assert result == {"worker": ["compute"]}


def test_nested_ifs_and_loops(tmp_path):
    code = """
def check_all(items):
    for item in items:
        if item.is_valid():
            log_success(item)
        else:
            log_failure()
"""
    result = _write_and_parse(tmp_path, code)
    assert "check_all" in result
    assert set(result["check_all"]) == {"is_valid", "log_success", "log_failure"}


def test_parse_file_syntax_error(tmp_path):
    code = "def invalid_syntax("
    result = _write_and_parse(tmp_path, code)
    assert result == {}
