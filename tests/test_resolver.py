from blastradius.resolution.resolver import resolve, resolve_call


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


def test_resolve_call_absolute_import():
    imports = {"file.py": {"parse_date": "utils.parser.parse_date"}}
    symbols = {"utils.parser.parse_date": {"function_name": "parse_date"}}
    res = resolve_call("parse_date", "caller", None, "file.py", imports, symbols)
    assert res == ["utils.parser.parse_date"]


def test_resolve_call_absolute_import_alias():
    imports = {"file.py": {"pd": "utils.parser.parse_date"}}
    symbols = {"utils.parser.parse_date": {"function_name": "parse_date"}}
    res = resolve_call("pd", "caller", None, "file.py", imports, symbols)
    assert res == ["utils.parser.parse_date"]


def test_resolve_call_module_alias():
    imports = {"file.py": {"up": "utils.parser"}}
    symbols = {"utils.parser.parse_date": {"function_name": "parse_date"}}
    res = resolve_call("up.parse_date", "caller", None, "file.py", imports, symbols)
    assert res == ["utils.parser.parse_date"]


def test_resolve_call_module_no_alias():
    imports = {"file.py": {"utils": "utils"}}
    symbols = {"utils.parser.parse_date": {"function_name": "parse_date"}}
    res = resolve_call("utils.parser.parse_date", "caller", None, "file.py", imports, symbols)
    assert res == ["utils.parser.parse_date"]


def test_resolve_call_local_class_method():
    imports = {"file.py": {}}
    symbols = {"module.MyClass.validate": {"function_name": "validate"}}
    res = resolve_call("self.validate", "module", "MyClass", "file.py", imports, symbols)
    assert res == ["module.MyClass.validate"]


def test_resolve_call_local_module_function():
    imports = {"file.py": {}}
    symbols = {"module.local_helper": {"function_name": "local_helper"}}
    res = resolve_call("local_helper", "module", None, "file.py", imports, symbols)
    assert res == ["module.local_helper"]


def test_resolve_call_fallback_name_matching():
    imports = {"file.py": {}}
    symbols = {
        "other.validate": {"function_name": "validate"},
        "another.validate": {"function_name": "validate"},
    }
    res = resolve_call("obj.validate", "module", None, "file.py", imports, symbols)
    assert set(res) == {"other.validate", "another.validate"}


def test_resolve_call_external_unregistered():
    imports = {"file.py": {"json": "json"}}
    symbols = {}
    res = resolve_call("json.loads", "module", None, "file.py", imports, symbols)
    assert res == ["json.loads"]


def test_resolve_call_cls_method():
    imports = {"file.py": {}}
    symbols = {"module.MyClass.setup": {"function_name": "setup"}}
    res = resolve_call("cls.setup", "module", "MyClass", "file.py", imports, symbols)
    assert res == ["module.MyClass.setup"]


def test_resolve_call_class_method_prefix():
    imports = {"file.py": {}}
    symbols = {
        "module.MyClass": {"kind": "class"},
        "module.MyClass.save": {"function_name": "save"},
    }
    res = resolve_call("MyClass.save", "module", None, "file.py", imports, symbols)
    assert res == ["module.MyClass.save"]


def test_resolve_call_local_types():
    imports = {"file.py": {"Invoice": "billing.invoice.Invoice"}}
    symbols = {
        "billing.invoice.Invoice": {"kind": "class"},
        "billing.invoice.Invoice.save": {"function_name": "save"},
    }
    local_types = {"inv": "Invoice"}
    res = resolve_call("inv.save", "module", None, "file.py", imports, symbols, local_types)
    assert res == ["billing.invoice.Invoice.save"]


def test_resolve_call_circular_dependency():
    """Verify that circular dependencies in call resolution abort gracefully instead of causing stack overflow."""
    imports = {"file.py": {}}
    symbols = {
        "module.A": {"kind": "class", "bases": ["B"]},
        "module.B": {"kind": "class", "bases": ["A"]},
    }
    local_types = {"self": "A"}
    # This should not hang/infinite-recurse and should return gracefully
    res = resolve_call("self.foo", "module", "A", "file.py", imports, symbols, local_types)
    assert isinstance(res, list)
