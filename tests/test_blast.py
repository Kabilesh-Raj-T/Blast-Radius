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
    from blastradius.indexer import index_repo

    index = index_repo("tests/fixtures/simple_repo")
    G = build_graph(index)
    rev = build_reverse_graph(G)

    # Compute blast radius of utils/parser.py:parse_date
    results = compute_blast_radius(rev, "utils/parser.py:parse_date")

    # We expect tests/test_billing.py:test_generate_invoice to be affected
    test_funcs = [r.test_function for r in results]
    assert "tests/test_billing.py:test_generate_invoice" in test_funcs

    # Find the specific affected test entry
    tgt_test = next(
        r for r in results if r.test_function == "tests/test_billing.py:test_generate_invoice"
    )
    assert tgt_test.test_file == "tests/test_billing.py"
    # Chain should be: parse_date -> generate_invoice -> test_generate_invoice
    assert tgt_test.chain == [
        "utils/parser.py:parse_date",
        "billing/invoice.py:generate_invoice",
        "tests/test_billing.py:test_generate_invoice",
    ]
    assert tgt_test.depth == 2
    assert tgt_test.confidence == "MEDIUM"
