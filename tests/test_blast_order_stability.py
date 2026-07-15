import networkx as nx
from blastradius.analysis.blast import compute_blast_radius


def test_blast_radius_path_stability_and_order_independence():
    """Verify that compute_blast_radius is stable and selects the highest-confidence path

    regardless of edge insertion order.

    Path A (low confidence): target -> dyn_node -> test_func
    Path B (high confidence): target -> helper -> test_func
    """

    # We will test two insertion orders:
    # Order 1: Path A (low confidence) then Path B (high confidence)
    # Order 2: Path B (high confidence) then Path A (low confidence)

    def build_graph_order_1():
        rev = nx.DiGraph()
        # Path A (low confidence due to dynamic_call node)
        rev.add_node("dyn_node", kind="dynamic_call")
        rev.add_edge("target", "dyn_node", relation="CALLS", certainty=1.0)
        rev.add_edge("dyn_node", "test_func", relation="CALLS", certainty=1.0)

        # Path B (high confidence)
        rev.add_node("helper", kind="function")
        rev.add_edge("target", "helper", relation="CALLS", certainty=1.0)
        rev.add_edge("helper", "test_func", relation="CALLS", certainty=1.0)
        return rev

    def build_graph_order_2():
        rev = nx.DiGraph()
        # Path B (high confidence)
        rev.add_node("helper", kind="function")
        rev.add_edge("target", "helper", relation="CALLS", certainty=1.0)
        rev.add_edge("helper", "test_func", relation="CALLS", certainty=1.0)

        # Path A (low confidence due to dynamic_call node)
        rev.add_node("dyn_node", kind="dynamic_call")
        rev.add_edge("target", "dyn_node", relation="CALLS", certainty=1.0)
        rev.add_edge("dyn_node", "test_func", relation="CALLS", certainty=1.0)
        return rev

    # Compute blast radius for both graphs
    results_1 = compute_blast_radius(build_graph_order_1(), "target")
    results_2 = compute_blast_radius(build_graph_order_2(), "target")

    # Assert they both have exactly 1 affected test
    assert len(results_1) == 1
    assert len(results_2) == 1

    r1 = results_1[0]
    r2 = results_2[0]

    # Assert that they returned the same test_function and confidence details
    assert r1.test_function == "test_func"
    assert r2.test_function == "test_func"

    # Assert that the high-confidence path was selected (the one through "helper")
    assert r1.chain == ["target", "helper", "test_func"]
    assert r2.chain == ["target", "helper", "test_func"]

    # Assert they have the exact same score and confidence label
    assert r1.score == r2.score
    assert r1.confidence == r2.confidence
    assert r1.confidence == "HIGH"  # depth 2, no dynamic calls → score 0.90 → HIGH
