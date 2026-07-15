"""Unit and integration tests for dynamic call site detection, representation, and path score propagation."""

from pathlib import Path

from blastradius.analysis.blast import compute_blast_radius
from blastradius.graph.graph import build_graph, build_reverse_graph
from blastradius.indexing.indexer import index_repo
from blastradius.parsing import parse_file


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_getattr_setattr_partial_detection(tmp_path):
    """Verify built-in dynamic dispatches are parsed and mapped to dynamic call nodes."""
    code = """
def process():
    getattr(obj, 'name')()
    setattr(obj, 'val', 42)
    partial(my_func, 10)()
"""
    file_path = tmp_path / "dyn_test.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = parse_file(str(file_path), str(tmp_path))
    sym_dict = {s.unique_id: s.to_dict() for s in symbols}

    # Assert parser extracted them
    calls = sym_dict["dyn_test.process"]["calls"]
    assert any(c.startswith("dynamic:getattr:") for c in calls)
    assert any(c.startswith("dynamic:setattr:") for c in calls)
    assert any(c.startswith("dynamic:partial:") for c in calls)


def test_exec_eval_detection(tmp_path):
    """Verify eval and exec are detected as dynamic call sites."""
    code = """
def run_code():
    eval("1 + 1")
    exec("x = 5")
"""
    file_path = tmp_path / "dyn_test2.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = parse_file(str(file_path), str(tmp_path))
    sym_dict = {s.unique_id: s.to_dict() for s in symbols}

    calls = sym_dict["dyn_test2.run_code"]["calls"]
    assert any(c.startswith("dynamic:eval:") for c in calls)
    assert any(c.startswith("dynamic:exec:") for c in calls)


def test_runtime_dispatch_variables_and_parameters(tmp_path):
    """Verify calling parameters or local variables creates runtime dispatch dynamic calls."""
    code = """
def execute(callback):
    callback()

    local_var = get_helper()
    local_var()
"""
    file_path = tmp_path / "dispatch_test.py"
    file_path.write_text(code, encoding="utf-8")

    symbols, imports = parse_file(str(file_path), str(tmp_path))
    sym_dict = {s.unique_id: s.to_dict() for s in symbols}

    calls = sym_dict["dispatch_test.execute"]["calls"]
    # Should have two runtime dispatch calls
    dispatch_calls = [c for c in calls if c.startswith("dynamic:runtime_dispatch:")]
    assert len(dispatch_calls) == 2


def test_dynamic_path_certainty_propagation(tmp_path):
    """Verify dynamic nodes result in reduced path score and LOW confidence in BFS."""
    # We define a helper in main.py, and the test in test_app.py
    code_main = """
def my_helper():
    pass

def dispatcher(callback):
    callback()  # dynamic runtime dispatch call site
"""
    _create_file(tmp_path, "main.py", code_main)

    code_test = """
from main import dispatcher, my_helper
def test_flow():
    dispatcher(my_helper)
"""
    _create_file(tmp_path, "test_app.py", code_test)

    # Index the repository
    index = index_repo(str(tmp_path))
    G = build_graph(index)
    rev = build_reverse_graph(G)

    # Run BFS starting from main.my_helper to find affected tests
    results = compute_blast_radius(rev, "main.my_helper")

    # We expect test_app.test_flow to be affected
    assert len(results) == 1
    hit = results[0]
    assert hit.test_function == "test_app.test_flow"
    assert hit.confidence == "LOW"
    assert "dynamic dispatch" in hit.explanation
    assert "dynamic dispatch" in hit.reason
    assert "getattr, eval, partial, exec, or runtime dispatch" in hit.resolution_explanation


def test_malformed_dynamic_call_fallback():
    """Verify that a malformed dynamic call target is handled gracefully and falls back to a low-confidence edge."""
    index = {
        "symbols": {
            "module.func": {
                "unique_id": "module.func",
                "module": "module",
                "filepath": "module.py",
                "kind": "function",
                "line_no": 10,
                "calls": ["dynamic:getattr:malformed"],  # Only 3 parts instead of 4
            },
            "module.target": {
                "unique_id": "module.target",
                "module": "module",
                "filepath": "module.py",
                "kind": "function",
                "line_no": 20,
                "calls": [],
            },
        },
        "imports": {},
    }
    G = build_graph(index)
    assert G.has_node("module.func:dyn:fallback")
    assert G.has_edge("module.func", "module.func:dyn:fallback")
    assert G.has_edge("module.func:dyn:fallback", "module.target")
    edge_data = G["module.func"]["module.func:dyn:fallback"][0]
    assert edge_data.get("certainty") == 0.10
