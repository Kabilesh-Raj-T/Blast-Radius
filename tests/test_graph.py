import networkx as nx
from blastradius.graph.graph import build_graph, build_reverse_graph, load, persist


def test_build_graph_hierarchy():
    # Construct a rich mock index
    index = {
        "symbols": {
            "utils.parser": {
                "unique_id": "utils.parser",
                "module": "utils",
                "filepath": "utils.py",
                "class_name": None,
                "function_name": None,
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": None,
                "nested_info": None,
                "kind": "class",
                "method_kind": None,
                "bases": [],
            },
            "utils.parser.parse_date": {
                "unique_id": "utils.parser.parse_date",
                "module": "utils",
                "filepath": "utils.py",
                "class_name": "parser",
                "function_name": "parse_date",
                "decorators": [],
                "line_no": 2,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "method",
                "method_kind": "instance",
                "bases": None,
                "calls": [],
            },
            "billing.invoice.Invoice": {
                "unique_id": "billing.invoice.Invoice",
                "module": "billing.invoice",
                "filepath": "billing/invoice.py",
                "class_name": None,
                "function_name": None,
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": None,
                "nested_info": None,
                "kind": "class",
                "method_kind": None,
                "bases": ["utils.parser"],
            },
            "billing.invoice.Invoice.generate": {
                "unique_id": "billing.invoice.Invoice.generate",
                "module": "billing.invoice",
                "filepath": "billing/invoice.py",
                "class_name": "Invoice",
                "function_name": "generate",
                "decorators": [],
                "line_no": 3,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "method",
                "method_kind": "instance",
                "bases": None,
                "calls": ["parse_date"],
            },
        },
        "imports": {
            "billing/invoice.py": {
                "parse_date": "utils.parser.parse_date",
                "utils": "utils",
            }
        },
    }

    G = build_graph(index)

    # 1. Assert nodes exist with attributes
    assert "repo" in G.nodes
    assert G.nodes["repo"]["kind"] == "repository"

    assert "pkg:billing" in G.nodes
    assert G.nodes["pkg:billing"]["kind"] == "package"

    assert "module:utils" in G.nodes
    assert G.nodes["module:utils"]["kind"] == "module"

    assert "utils.parser" in G.nodes
    assert G.nodes["utils.parser"]["kind"] == "class"

    assert "utils.parser.parse_date" in G.nodes
    assert G.nodes["utils.parser.parse_date"]["kind"] == "method"

    # 2. Assert OWNS containment hierarchy
    # repo owns module:utils
    assert G.has_edge("repo", "module:utils")
    assert G["repo"]["module:utils"][0]["relation"] == "OWNS"

    # module:utils owns class utils.parser
    assert G.has_edge("module:utils", "utils.parser")
    assert G["module:utils"]["utils.parser"][0]["relation"] == "OWNS"

    # class utils.parser owns method utils.parser.parse_date
    assert G.has_edge("utils.parser", "utils.parser.parse_date")
    assert G["utils.parser"]["utils.parser.parse_date"][0]["relation"] == "OWNS"

    # 3. Assert INHERITS relationship
    # billing.invoice.Invoice inherits utils.parser
    assert G.has_edge("billing.invoice.Invoice", "utils.parser")
    assert G["billing.invoice.Invoice"]["utils.parser"][0]["relation"] == "INHERITS"

    assert G.has_edge("billing.invoice.Invoice.generate", "utils.parser.parse_date")
    rel = G["billing.invoice.Invoice.generate"]["utils.parser.parse_date"][0]["relation"]
    assert rel == "CALLS"


def test_build_reverse_graph():
    index = {
        "symbols": {
            "a": {
                "unique_id": "a",
                "module": "m",
                "filepath": "m.py",
                "class_name": None,
                "function_name": "a",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["b"],
            },
            "b": {
                "unique_id": "b",
                "module": "m",
                "filepath": "m.py",
                "class_name": None,
                "function_name": "b",
                "decorators": [],
                "line_no": 3,
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
        "imports": {},
    }
    G = build_graph(index)
    assert G.has_edge("a", "b")

    rev = build_reverse_graph(G)
    assert rev.has_edge("b", "a")
    assert not rev.has_edge("a", "b")


def test_persist_and_load_graph(tmp_path):
    index = {
        "symbols": {
            "a": {
                "unique_id": "a",
                "module": "m",
                "filepath": "m.py",
                "class_name": None,
                "function_name": "a",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": [],
            }
        },
        "imports": {},
    }
    G = build_graph(index)

    path = tmp_path / "graph.json"
    persist(G, str(path))

    loaded = load(str(path))
    assert loaded.nodes == G.nodes
    assert list(loaded.edges) == list(G.edges)


def test_load_graph_non_existent():
    loaded = load("non_existent_graph.json")
    assert isinstance(loaded, nx.MultiDiGraph)
    assert len(loaded.nodes) == 0


def test_parallel_edges_deduplicated():
    index = {
        "symbols": {
            "a": {
                "unique_id": "a",
                "module": "m",
                "filepath": "m.py",
                "class_name": None,
                "function_name": "a",
                "decorators": [],
                "line_no": 1,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["b", "b"],  # calls b twice
            },
            "b": {
                "unique_id": "b",
                "module": "m",
                "filepath": "m.py",
                "class_name": None,
                "function_name": "b",
                "decorators": [],
                "line_no": 3,
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
        "imports": {},
    }
    G = build_graph(index)
    assert G.has_edge("a", "b")
    # Verify we only have 1 CALLS edge from a to b
    calls_edges = [
        edge
        for edge in G.edges(keys=True)
        if edge[0] == "a"
        and edge[1] == "b"
        and G[edge[0]][edge[1]][edge[2]].get("relation") == "CALLS"
    ]
    assert len(calls_edges) == 1
