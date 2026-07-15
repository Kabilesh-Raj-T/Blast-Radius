"""Unit and integration tests for advanced call resolution (MRO, super, ambiguity, class/staticmethod)."""

from blastradius.graph.graph import build_graph
from blastradius.parsing import parse_file
from blastradius.resolution.resolver import resolve_call_with_certainty


def test_self_and_cls_mro_inheritance():
    """Verify self.method() and cls.method() resolve to parent classes in MRO."""
    symbols = {
        "mod.Parent": {"kind": "class", "bases": []},
        "mod.Parent.helper": {"kind": "method", "function_name": "helper"},
        "mod.Child": {"kind": "class", "bases": ["Parent"]},
        "mod.Child.run": {"kind": "method", "function_name": "run"},
    }

    # Resolve self.helper inside mod.Child.run
    matches, certainty = resolve_call_with_certainty(
        "self.helper", "mod", "Child", "mod.py", {}, symbols, caller_id="mod.Child.run"
    )
    assert matches == ["mod.Parent.helper"]
    assert certainty == 0.95

    # Resolve cls.helper inside mod.Child.run
    matches_cls, certainty_cls = resolve_call_with_certainty(
        "cls.helper", "mod", "Child", "mod.py", {}, symbols, caller_id="mod.Child.run"
    )
    assert matches_cls == ["mod.Parent.helper"]
    assert certainty_cls == 0.95


def test_super_resolution():
    """Verify super().method() resolves to the parent class definition."""
    symbols = {
        "mod.BaseClass": {"kind": "class", "bases": []},
        "mod.BaseClass.setup": {"kind": "method", "function_name": "setup"},
        "mod.SubClass": {"kind": "class", "bases": ["BaseClass"]},
        "mod.SubClass.setup": {"kind": "method", "function_name": "setup"},
    }

    # In SubClass.setup calling super().setup() -> extracts as "super.setup"
    matches, certainty = resolve_call_with_certainty(
        "super.setup", "mod", "SubClass", "mod.py", {}, symbols, caller_id="mod.SubClass.setup"
    )
    assert matches == ["mod.BaseClass.setup"]
    assert certainty == 0.95


def test_multiple_inheritance_ambiguity():
    """Verify multiple inheritance returns multiple candidates if they overlap."""
    symbols = {
        "mod.Left": {"kind": "class", "bases": []},
        "mod.Left.action": {"kind": "method", "function_name": "action"},
        "mod.Right": {"kind": "class", "bases": []},
        "mod.Right.action": {"kind": "method", "function_name": "action"},
        "mod.Joint": {"kind": "class", "bases": ["Left", "Right"]},
        "mod.Joint.run": {"kind": "method", "function_name": "run"},
    }

    matches, certainty = resolve_call_with_certainty(
        "self.action", "mod", "Joint", "mod.py", {}, symbols, caller_id="mod.Joint.run"
    )
    # Both bases Left and Right define 'action'. Should return both candidates!
    assert set(matches) == {"mod.Left.action", "mod.Right.action"}
    assert certainty == 0.95


def test_parser_super_extraction_and_integration(tmp_path):
    """Parse real python code containing super() calls and verify graph wiring."""
    code = """
class Base:
    def initialize(self):
        pass

class Child(Base):
    def initialize(self):
        super().initialize()
"""
    file_path = tmp_path / "super_mod.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = parse_file(str(file_path), str(tmp_path))

    # Assert parser extracted super call correctly
    child_init = next(s for s in symbols if s.unique_id == "super_mod.Child.initialize")
    assert "super.initialize" in (child_init.calls or [])

    index = {
        "symbols": {s.unique_id: s.to_dict() for s in symbols},
        "imports": {str(file_path.relative_to(tmp_path)).replace("\\", "/"): imports},
    }

    G = build_graph(index)

    # Verify graph edge connects Child.initialize directly to Base.initialize
    assert G.has_edge("super_mod.Child.initialize", "super_mod.Base.initialize")
