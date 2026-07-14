from blastradius.parser import parse_file


def test_parse_file_valid(tmp_path):
    # Create a valid temp python file
    code = """
def parse_date(date_str: str):
    return strptime(date_str)

async def async_call():
    await helper.do_something()
"""
    file_path = tmp_path / "valid.py"
    file_path.write_text(code, encoding="utf-8")

    result = parse_file(str(file_path))
    assert "parse_date" in result
    assert result["parse_date"] == ["strptime"]
    assert "async_call" in result
    assert result["async_call"] == ["do_something"]


def test_parse_file_syntax_error(tmp_path):
    # Create an invalid python file
    code = """
def parse_date(date_str: str)
    return strptime(date_str)
"""
    file_path = tmp_path / "invalid.py"
    file_path.write_text(code, encoding="utf-8")

    result = parse_file(str(file_path))
    assert result == {}
