"""Unit and integration tests for scope-aware symbol resolution."""

from blastradius.graph.graph import build_graph
from blastradius.parsing import parse_file
from blastradius.resolution.resolver import resolve_call_with_certainty


def test_lexical_scope_sibling_resolve():
    """Verify sibling nested functions resolve within lexical scope, not fallback."""
    symbols = {
        "mod.outer": {
            "kind": "function",
            "nested_info": {"scope_info": {"local_defs": ["helper", "caller"]}},
        },
        "mod.outer.helper": {
            "kind": "function",
            "function_name": "helper",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "mod.outer.caller": {
            "kind": "function",
            "function_name": "caller",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        # A global fallback that should NOT be matched
        "other_mod.helper": {"kind": "function", "function_name": "helper"},
    }

    matches, certainty = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports={},
        symbols=symbols,
        caller_id="mod.outer.caller",
    )

    assert matches == ["mod.outer.helper"]
    assert certainty == 0.95  # Found in enclosing scope walk


def test_closure_nested_walk_resolve():
    """Verify inner nested closures resolve variables up multiple scopes."""
    symbols = {
        "mod.outer": {"kind": "function", "nested_info": {"scope_info": {"local_defs": ["mid"]}}},
        "mod.outer.mid": {
            "kind": "function",
            "nested_info": {
                "parent_function": "outer",
                "parent_id": "mod.outer",
                "scope_info": {"local_defs": ["inner"]},
            },
        },
        "mod.outer.mid.inner": {
            "kind": "function",
            "nested_info": {"parent_function": "mid", "parent_id": "mod.outer.mid"},
        },
        "mod.outer.helper": {
            "kind": "function",
            "function_name": "helper",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
    }

    # Let's add "helper" to outer local_defs
    symbols["mod.outer"]["nested_info"]["scope_info"]["local_defs"].append("helper")

    matches, certainty = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports={},
        symbols=symbols,
        caller_id="mod.outer.mid.inner",
    )

    assert matches == ["mod.outer.helper"]
    assert certainty == 0.95


def test_shadow_precedence_over_imports():
    """Verify local definitions shadow same-name imports (precedence rule)."""
    imports = {"mod.py": {"helper": "external_library.helper"}}
    symbols = {
        "mod.outer": {
            "kind": "function",
            "nested_info": {"scope_info": {"local_defs": ["helper", "caller"]}},
        },
        "mod.outer.helper": {
            "kind": "function",
            "function_name": "helper",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "mod.outer.caller": {
            "kind": "function",
            "function_name": "caller",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "external_library.helper": {"kind": "function", "function_name": "helper"},
    }

    # With caller_id set, caller should resolve helper locally, shadowing import
    matches, certainty = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports=imports,
        symbols=symbols,
        caller_id="mod.outer.caller",
    )
    assert matches == ["mod.outer.helper"]
    assert certainty == 0.95

    # Without caller_id, or if caller is outside the scope, falls back to import map
    matches_fallback, certainty_fallback = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports=imports,
        symbols=symbols,
        caller_id=None,
    )
    assert matches_fallback == ["external_library.helper"]
    assert certainty_fallback == 1.00


def test_global_scope_resolution():
    """Verify `global x` explicitly resolves to the module namespace."""
    symbols = {
        "mod.helper": {"kind": "function", "function_name": "helper"},
        "mod.outer": {
            "kind": "function",
            "nested_info": {"scope_info": {"local_defs": ["helper", "caller"]}},
        },
        "mod.outer.helper": {
            "kind": "function",
            "function_name": "helper",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "mod.outer.caller": {
            "kind": "function",
            "function_name": "caller",
            "nested_info": {
                "parent_function": "outer",
                "parent_id": "mod.outer",
                "scope_info": {"globals": ["helper"]},
            },
        },
    }

    matches, certainty = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports={},
        symbols=symbols,
        caller_id="mod.outer.caller",
    )

    # Should bypass nested helper and resolve to global/module helper
    assert matches == ["mod.helper"]
    assert certainty == 0.95


def test_nonlocal_scope_resolution():
    """Verify `nonlocal x` bypasses current local definition and starts from enclosing."""
    symbols = {
        "mod.outer": {
            "kind": "function",
            "nested_info": {"scope_info": {"local_defs": ["helper", "mid"]}},
        },
        "mod.outer.helper": {
            "kind": "function",
            "function_name": "helper",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "mod.outer.mid": {
            "kind": "function",
            "nested_info": {
                "parent_function": "outer",
                "parent_id": "mod.outer",
                "scope_info": {"local_defs": ["inner"]},
            },
        },
        "mod.outer.mid.inner": {
            "kind": "function",
            "nested_info": {
                "parent_function": "mid",
                "parent_id": "mod.outer.mid",
                "scope_info": {"nonlocals": ["helper"]},
            },
        },
    }

    matches, certainty = resolve_call_with_certainty(
        call_name="helper",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports={},
        symbols=symbols,
        caller_id="mod.outer.mid.inner",
    )

    # Should resolve to mod.outer.helper
    assert matches == ["mod.outer.helper"]
    assert certainty == 0.95


def test_own_local_def_precedence():
    """Verify function calling another function defined inside itself has the highest precedence."""
    symbols = {
        "mod.outer": {"kind": "function", "nested_info": {"scope_info": {"local_defs": ["inner"]}}},
        "mod.outer.inner": {
            "kind": "function",
            "function_name": "inner",
            "nested_info": {"parent_function": "outer", "parent_id": "mod.outer"},
        },
        "mod.inner": {"kind": "function", "function_name": "inner"},
    }

    matches, certainty = resolve_call_with_certainty(
        call_name="inner",
        caller_module="mod",
        caller_class=None,
        filepath="mod.py",
        imports={},
        symbols=symbols,
        caller_id="mod.outer",
    )

    assert matches == ["mod.outer.inner"]
    assert certainty == 0.98  # own local definition


def test_integration_scope_parser_and_graph(tmp_path):
    """Parse real python code with complex nesting, build graph, and assert correct wiring."""
    code = """
def global_helper():
    pass

def outer():
    def inner_helper():
        pass

    def caller():
        inner_helper()
        global_helper()
"""
    file_path = tmp_path / "scope_mod.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = parse_file(str(file_path), str(tmp_path))

    index = {
        "symbols": {s.unique_id: s.to_dict() for s in symbols},
        "imports": {str(file_path.relative_to(tmp_path)).replace("\\", "/"): imports},
    }

    G = build_graph(index)

    # Assert correct edges are created
    assert G.has_edge("scope_mod.outer.caller", "scope_mod.outer.inner_helper")
    assert G.has_edge("scope_mod.outer.caller", "scope_mod.global_helper")

    # Check certainty is correct
    edge_inner = G["scope_mod.outer.caller"]["scope_mod.outer.inner_helper"][0]
    assert edge_inner["certainty"] == 0.95  # Lexical scope walk

    edge_global = G["scope_mod.outer.caller"]["scope_mod.global_helper"][0]
    assert edge_global["certainty"] == 0.90  # Local module symbol
