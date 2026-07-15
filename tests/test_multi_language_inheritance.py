"""Unit and integration tests verifying multi-language inheritance, C3 MRO lookup, and call extraction for TypeScript, Java, and Go."""

from pathlib import Path

from blastradius.graph.graph import build_graph
from blastradius.parsing.go_parser import GoParser
from blastradius.parsing.java_parser import JavaParser
from blastradius.parsing.typescript_parser import TypeScriptParser


def _write_file(tmp_path: Path, rel_path: str, content: str) -> Path:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_typescript_this_mro_call_resolution(tmp_path):
    """Verify that this.method() call inside a TypeScript subclass resolves to base method in the graph."""
    code = """
class BaseClass {
    public baseMethod() {}
}

class SubClass extends BaseClass {
    public run() {
        this.baseMethod();
    }
}
"""
    f = _write_file(tmp_path, "sub.ts", code)
    symbols, imports = TypeScriptParser().parse(str(f), str(tmp_path))

    # Check calls extraction
    run_sym = next(s for s in symbols if s.function_name == "run")
    assert "this.baseMethod" in run_sym.calls

    # Check bases populated
    sub_sym = next(s for s in symbols if s.unique_id == "sub.SubClass")
    assert sub_sym.bases == ["BaseClass"]

    # Graph resolution check
    index = {"symbols": {s.unique_id: s.to_dict() for s in symbols}, "imports": {"sub.ts": imports}}
    G = build_graph(index)

    # Verify edge exists from run to baseMethod
    run_uid = "sub.SubClass.run"
    base_uid = "sub.BaseClass.baseMethod"
    assert G.has_edge(run_uid, base_uid)
    edge_data = G[run_uid][base_uid][0]
    assert edge_data["relation"] == "CALLS"
    assert edge_data["inheritance"] is True


def test_java_super_mro_call_resolution(tmp_path):
    """Verify that super.method() inside a Java subclass resolves to parent class method in the graph."""
    code = """
package com.example;

class Parent {
    void process() {}
}

class Child extends Parent {
    void run() {
        super.process();
    }
}
"""
    f = _write_file(tmp_path, "Child.java", code)
    symbols, imports = JavaParser().parse(str(f), str(tmp_path))

    # Check calls extraction
    run_sym = next(s for s in symbols if s.function_name == "run")
    assert "super.process" in run_sym.calls

    # Check bases populated
    child_sym = next(s for s in symbols if s.unique_id == "com.example.Child")
    assert child_sym.bases == ["Parent"]

    # Graph resolution check
    index = {
        "symbols": {s.unique_id: s.to_dict() for s in symbols},
        "imports": {"Child.java": imports},
    }
    G = build_graph(index)

    run_uid = "com.example.Child.run"
    parent_uid = "com.example.Parent.process"
    assert G.has_edge(run_uid, parent_uid)


def test_go_struct_embedding_resolution(tmp_path):
    """Verify Go struct embedding parses embedded structs into bases."""
    code = """
package main

type Inner struct {
    Val int
}

type Outer struct {
    *Inner
    Name string
}
"""
    f = _write_file(tmp_path, "main.go", code)
    symbols, imports = GoParser().parse(str(f), str(tmp_path))

    outer_sym = next(s for s in symbols if s.unique_id == "main.Outer")
    assert outer_sym.bases == ["Inner"]
