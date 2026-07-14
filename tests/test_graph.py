import networkx as nx
from blastradius.graph import build_graph, build_reverse_graph, load, persist


def test_build_graph():
    index = {
        "utils/parser.py:parse_date": ["strptime"],  # strptime won't resolve -> no edge
        "billing/invoice.py:generate_invoice": ["parse_date"],  # resolves -> edge billing -> utils
        "isolated.py:dummy": [],  # no calls -> isolated node
    }
    G = build_graph(index)

    # All caller keys must be nodes
    assert "utils/parser.py:parse_date" in G.nodes
    assert "billing/invoice.py:generate_invoice" in G.nodes
    assert "isolated.py:dummy" in G.nodes

    # Check edges
    # billing/invoice.py:generate_invoice calls parse_date,
    # which resolves to utils/parser.py:parse_date

    assert G.has_edge("billing/invoice.py:generate_invoice", "utils/parser.py:parse_date")
    assert G.number_of_edges() == 1


def test_build_reverse_graph():
    index = {
        "billing/invoice.py:generate_invoice": ["parse_date"],
        "utils/parser.py:parse_date": [],
    }
    G = build_graph(index)
    assert G.has_edge("billing/invoice.py:generate_invoice", "utils/parser.py:parse_date")

    rev = build_reverse_graph(G)
    assert rev.has_edge("utils/parser.py:parse_date", "billing/invoice.py:generate_invoice")
    assert not rev.has_edge("billing/invoice.py:generate_invoice", "utils/parser.py:parse_date")


def test_persist_and_load_graph(tmp_path):
    index = {
        "billing/invoice.py:generate_invoice": ["parse_date"],
        "utils/parser.py:parse_date": [],
    }
    G = build_graph(index)

    path = tmp_path / "graph.json"
    persist(G, str(path))

    loaded = load(str(path))
    assert loaded.nodes == G.nodes
    assert list(loaded.edges) == list(G.edges)


def test_load_graph_non_existent():
    loaded = load("non_existent_graph.json")
    assert isinstance(loaded, nx.DiGraph)
    assert len(loaded.nodes) == 0
