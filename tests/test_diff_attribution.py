from blastradius.diff import get_symbols_for_changed_lines
from blastradius.languages import registry


def test_python_diff_attribution_containment(tmp_path):
    code = """def first_func():
    # line 2
    pass

# line 5: gap comment
# line 6

def second_func():
    # line 9
    pass



# line 15: trailing comment
"""
    file_path = tmp_path / "app.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = registry.parse_file(str(file_path), str(tmp_path))
    sym_dict = {s.unique_id: s.to_dict() for s in symbols}

    # Assert start and end lines are parsed correctly
    # first_func: lines 1-3
    assert sym_dict["app.first_func"]["line_no"] == 1
    assert sym_dict["app.first_func"]["end_line_no"] == 3

    # second_func: lines 8-10
    assert sym_dict["app.second_func"]["line_no"] == 8
    assert sym_dict["app.second_func"]["end_line_no"] == 10

    # Test line 2 (inside first_func) -> should attribute to first_func
    res = get_symbols_for_changed_lines({"app.py": [2]}, sym_dict)
    assert res == ["app.first_func"]

    # Test line 5 (in the gap) -> should not attribute to first_func
    res = get_symbols_for_changed_lines({"app.py": [5]}, sym_dict)
    assert res == []

    # Test line 6 (blank gap) -> should not attribute
    res = get_symbols_for_changed_lines({"app.py": [6]}, sym_dict)
    assert res == []

    # Test line 9 (inside second_func) -> second_func
    res = get_symbols_for_changed_lines({"app.py": [9]}, sym_dict)
    assert res == ["app.second_func"]

    # Test line 15 (trailing space/comment) -> no attribution
    res = get_symbols_for_changed_lines({"app.py": [15]}, sym_dict)
    assert res == []


def test_js_diff_attribution_containment(tmp_path):
    code = """function firstFunc() {
    // line 2
    return;
}

// line 6: gap comment

function secondFunc() {
    // line 9
    return;
}
"""
    file_path = tmp_path / "app.js"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = registry.parse_file(str(file_path), str(tmp_path))
    sym_dict = {s.unique_id: s.to_dict() for s in symbols}

    # firstFunc: lines 1-4
    assert sym_dict["app.firstFunc"]["line_no"] == 1
    assert sym_dict["app.firstFunc"]["end_line_no"] == 4

    # secondFunc: lines 8-11
    assert sym_dict["app.secondFunc"]["line_no"] == 8
    assert sym_dict["app.secondFunc"]["end_line_no"] == 11

    # Test line 2 (inside firstFunc) -> firstFunc
    res = get_symbols_for_changed_lines({"app.js": [2]}, sym_dict)
    assert res == ["app.firstFunc"]

    # Test line 6 (gap) -> none
    res = get_symbols_for_changed_lines({"app.js": [6]}, sym_dict)
    assert res == []

    # Test line 9 (inside secondFunc) -> secondFunc
    res = get_symbols_for_changed_lines({"app.js": [9]}, sym_dict)
    assert res == ["app.secondFunc"]


def test_diff_attribution_fallback_without_metadata():
    """Verify legacy fallback: nearest preceding heuristic works if end_line_no is missing."""
    sym_dict = {
        "app.first_func": {
            "unique_id": "app.first_func",
            "kind": "function",
            "filepath": "app.py",
            "line_no": 1,
            # no end_line_no
        }
    }

    # Legacy: line 5 should attribute to first_func (even though it's technically outside if we knew span)
    res = get_symbols_for_changed_lines({"app.py": [5]}, sym_dict)
    assert res == ["app.first_func"]
