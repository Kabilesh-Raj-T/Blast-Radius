import networkx as nx
import pytest
from blastradius.blast import _is_test, compute_blast_radius


def test_is_test_classifier():
    # 8+ test cases as requested
    # 1. test_parse_date -> True
    assert _is_test("test_parse_date") is True
    # 2. parse_date -> False
    assert _is_test("parse_date") is False
    # 3. conftest.py:fixture_fn -> False
    assert _is_test("conftest.py:fixture_fn") is False
    # 4. helpers/test_utils.py:helper -> True
    assert _is_test("helpers/test_utils.py:helper") is True
    # 5. test_utils.py:test_helper -> True
    assert _is_test("test_utils.py:test_helper") is True
    # 6. utils.py:test_my_func -> True
    assert _is_test("utils.py:test_my_func") is True
    # 7. test_main.py:main -> True
    assert _is_test("test_main.py:main") is True
    # 8. main.py:test_suite -> True
    assert _is_test("main.py:test_suite") is True
    # 9. empty string -> False
    assert _is_test("") is False


def test_compute_blast_radius_simple():
    # Chain: target -> helper -> test_func
    # Forward: test_func -> helper -> target
    # Reverse graph: target -> helper -> test_func
    rev = nx.DiGraph()
    rev.add_edge("target", "helper")
    rev.add_edge("helper", "test_func")

    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].test_function == "test_func"
    assert results[0].confidence == "MEDIUM"  # depth 2
    assert results[0].depth == 2
    assert results[0].chain == ["target", "helper", "test_func"]


def test_compute_blast_radius_cycle():
    # Cycle: target -> A -> B -> target
    # test_func is called by B
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "b")
    rev.add_edge("b", "target")
    rev.add_edge("b", "test_func")

    # Should terminate without infinite loop
    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].test_function == "test_func"
    assert results[0].depth == 3
    assert results[0].confidence == "LOW"


def test_compute_blast_radius_max_depth():
    # Chain: target -> a -> b -> test_func (depth 3)
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "b")
    rev.add_edge("b", "test_func")

    # Limit max_depth to 2
    results = compute_blast_radius(rev, "target", max_depth=2)
    assert len(results) == 0


def test_compute_blast_radius_stop_at_tests():
    # Chain: target -> test_helper -> test_func
    # If test_helper is classified as a test, BFS must stop at test_helper
    # and NOT traverse further to test_func.
    rev = nx.DiGraph()
    rev.add_edge("target", "test_helper")
    rev.add_edge("test_helper", "test_func")

    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    # Only test_helper is recorded
    assert results[0].test_function == "test_helper"


@pytest.mark.integration
def test_blast_radius_simple_repo_integration():
    from blastradius.graph import build_graph, build_reverse_graph

    # Mock index for simple_repo fixture
    index = {
        "symbols": {
            "utils.parser.parse_date": {
                "unique_id": "utils.parser.parse_date",
                "module": "utils.parser",
                "filepath": "utils/parser.py",
                "class_name": None,
                "function_name": "parse_date",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["strptime"],
            },
            "billing.invoice.generate_invoice": {
                "unique_id": "billing.invoice.generate_invoice",
                "module": "billing.invoice",
                "filepath": "billing/invoice.py",
                "class_name": None,
                "function_name": "generate_invoice",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["parse_date"],
            },
            "tests.test_billing.test_generate_invoice": {
                "unique_id": "tests.test_billing.test_generate_invoice",
                "module": "tests.test_billing",
                "filepath": "tests/test_billing.py",
                "class_name": None,
                "function_name": "test_generate_invoice",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["generate_invoice"],
            },
        },
        "imports": {
            "billing/invoice.py": {"parse_date": "utils.parser.parse_date"},
            "tests/test_billing.py": {"generate_invoice": "billing.invoice.generate_invoice"},
        },
    }
    G = build_graph(index)
    rev = build_reverse_graph(G)

    # Compute blast radius of utils.parser.parse_date
    results = compute_blast_radius(rev, "utils.parser.parse_date")

    # We expect tests.test_billing.test_generate_invoice to be affected
    test_funcs = [r.test_function for r in results]
    assert "tests.test_billing.test_generate_invoice" in test_funcs

    # Find the specific affected test entry
    tgt_test = next(
        r for r in results if r.test_function == "tests.test_billing.test_generate_invoice"
    )
    assert tgt_test.test_file == "tests/test_billing.py"
    # Chain should be: parse_date -> generate_invoice -> test_generate_invoice
    assert tgt_test.chain == [
        "utils.parser.parse_date",
        "billing.invoice.generate_invoice",
        "tests.test_billing.test_generate_invoice",
    ]
    assert tgt_test.depth == 2
    assert tgt_test.confidence == "MEDIUM"


@pytest.mark.integration
def test_blast_radius_cycle_repo_integration():
    import time

    from blastradius.graph import build_graph, build_reverse_graph

    # Mock index for cycle_repo fixture
    index = {
        "symbols": {
            "module_a.func_a": {
                "unique_id": "module_a.func_a",
                "module": "module_a",
                "filepath": "module_a.py",
                "class_name": None,
                "function_name": "func_a",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["func_b"],
            },
            "module_b.func_b": {
                "unique_id": "module_b.func_b",
                "module": "module_b",
                "filepath": "module_b.py",
                "class_name": None,
                "function_name": "func_b",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["func_a", "test_func"],
            },
            "module_b.test_func": {
                "unique_id": "module_b.test_func",
                "module": "module_b",
                "filepath": "module_b.py",
                "class_name": None,
                "function_name": "test_func",
                "decorators": [],
                "line_no": 5,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": [],
            },
        },
        "imports": {
            "module_a.py": {"func_b": "module_b.func_b"},
            "module_b.py": {"func_a": "module_a.func_a"},
        },
    }
    G = build_graph(index)
    rev = build_reverse_graph(G)

    # Time the BFS traversal to ensure cycle safety and that it does not loop infinitely
    start_time = time.perf_counter()
    results = compute_blast_radius(rev, "module_a.func_a")
    duration = time.perf_counter() - start_time

    # Assertions
    assert duration < 1.0
    assert isinstance(results, list)


def test_confidence_high():
    # Direct caller: target -> test_func (depth 1)
    rev = nx.DiGraph()
    rev.add_edge("target", "test_func")
    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].confidence == "HIGH"
    assert results[0].depth == 1
    assert len(results[0].chain) == 2


def test_confidence_medium():
    # 2-hop: target -> a -> test_func (depth 2)
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "test_func")
    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].confidence == "MEDIUM"
    assert results[0].depth == 2
    assert len(results[0].chain) == 3


def test_confidence_low():
    # 3-hop: target -> a -> b -> test_func (depth 3)
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "b")
    rev.add_edge("b", "test_func")
    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].confidence == "LOW"
    assert results[0].depth == 3
    assert len(results[0].chain) == 4


def test_no_tests_in_graph():
    # target -> a -> b (no test functions)
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "b")
    results = compute_blast_radius(rev, "target")
    assert results == []


def test_max_depth_strict():
    # Chain: target -> a -> b -> test_func (depth 3)
    # With max_depth=2, test_func (depth 3) should NOT be returned
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("a", "b")
    rev.add_edge("b", "test_func")
    results = compute_blast_radius(rev, "target", max_depth=2)
    assert len(results) == 0


def test_multiple_tests_returned():
    # target calls test_a and test_b
    rev = nx.DiGraph()
    rev.add_edge("target", "test_a")
    rev.add_edge("target", "test_b")
    results = compute_blast_radius(rev, "target")
    assert len(results) == 2
    funcs = {r.test_function for r in results}
    assert funcs == {"test_a", "test_b"}


def test_deduplicate_test_paths():
    # test_func is reachable via two paths:
    # 1. target -> a -> test_func
    # 2. target -> b -> test_func
    # Visited set should ensure test_func is only returned once
    rev = nx.DiGraph()
    rev.add_edge("target", "a")
    rev.add_edge("target", "b")
    rev.add_edge("a", "test_func")
    rev.add_edge("b", "test_func")
    results = compute_blast_radius(rev, "target")
    assert len(results) == 1
    assert results[0].test_function == "test_func"


def test_target_not_in_graph():
    # Target function is not in the graph at all
    rev = nx.DiGraph()
    rev.add_node("other_func")
    results = compute_blast_radius(rev, "target")
    assert results == []
