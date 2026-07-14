from blastradius.resolver import resolve


def test_resolve_single_match():
    index = {
        "utils/parser.py:parse_date": ["strptime"],
        "billing/invoice.py:generate_invoice": ["parse_date"],
    }
    # Resolve single match
    res = resolve("parse_date", index)
    assert res == ["utils/parser.py:parse_date"]


def test_resolve_multiple_matches():
    index = {
        "module_a.py:validate": [],
        "module_b.py:validate": [],
    }
    # Resolve multiple matches
    res = resolve("validate", index)
    assert set(res) == {"module_a.py:validate", "module_b.py:validate"}


def test_resolve_no_matches():
    index = {
        "utils/parser.py:parse_date": ["strptime"],
    }
    # Resolve no matches (e.g. built-in/external)
    res = resolve("strptime", index)
    assert res == []
