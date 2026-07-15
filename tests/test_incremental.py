"""Tests for the incremental graph update engine (blastradius.incremental)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import networkx as nx
from blastradius.incremental import (
    GraphDelta,
    _prune_orphan_hierarchy_nodes,
    compute_file_fingerprints,
    diff_fingerprints,
    invalidate_file,
    patch_file,
    update_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_with_file(filepath: str) -> tuple[nx.MultiDiGraph, dict]:
    """Build a minimal graph + index that contains two symbols from *filepath*."""
    G = nx.MultiDiGraph()
    G.add_node("repo", kind="repository", name="repo")
    G.add_node("module:mymod", kind="module", name="mymod", filepath=filepath)
    G.add_node(
        "mymod.foo",
        kind="function",
        function_name="foo",
        filepath=filepath,
        module="mymod",
        class_name=None,
        nested_info=None,
        calls=[],
        local_types=None,
        decorators=[],
        line_no=1,
        col_offset=0,
        visibility="public",
        async_sync="sync",
        method_kind=None,
        bases=None,
        unique_id="mymod.foo",
    )
    G.add_node(
        "mymod.bar",
        kind="function",
        function_name="bar",
        filepath=filepath,
        module="mymod",
        class_name=None,
        nested_info=None,
        calls=["foo"],
        local_types=None,
        decorators=[],
        line_no=5,
        col_offset=0,
        visibility="public",
        async_sync="sync",
        method_kind=None,
        bases=None,
        unique_id="mymod.bar",
    )
    G.add_edge("repo", "module:mymod", relation="OWNS")
    G.add_edge("module:mymod", "mymod.foo", relation="OWNS")
    G.add_edge("module:mymod", "mymod.bar", relation="OWNS")
    G.add_edge("mymod.bar", "mymod.foo", relation="CALLS")

    index: dict = {
        "symbols": {
            "mymod.foo": {
                "unique_id": "mymod.foo",
                "module": "mymod",
                "filepath": filepath,
                "class_name": None,
                "function_name": "foo",
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
                "local_types": None,
            },
            "mymod.bar": {
                "unique_id": "mymod.bar",
                "module": "mymod",
                "filepath": filepath,
                "class_name": None,
                "function_name": "bar",
                "decorators": [],
                "line_no": 5,
                "col_offset": 0,
                "visibility": "public",
                "async_sync": "sync",
                "nested_info": None,
                "kind": "function",
                "method_kind": None,
                "bases": None,
                "calls": ["foo"],
                "local_types": None,
            },
        },
        "imports": {filepath: {}},
    }
    return G, index


def _write_py(path: Path, code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")


# ---------------------------------------------------------------------------
# GraphDelta
# ---------------------------------------------------------------------------


class TestGraphDelta:
    def test_is_empty_when_no_changes(self):
        delta = GraphDelta()
        assert delta.is_empty()

    def test_not_empty_with_added_files(self):
        delta = GraphDelta(added_files=["a.py"])
        assert not delta.is_empty()

    def test_not_empty_with_modified_files(self):
        delta = GraphDelta(modified_files=["b.py"])
        assert not delta.is_empty()

    def test_not_empty_with_deleted_files(self):
        delta = GraphDelta(deleted_files=["c.py"])
        assert not delta.is_empty()

    def test_node_and_edge_lists_do_not_affect_is_empty(self):
        # is_empty only cares about file-level changes
        delta = GraphDelta(added_nodes=["n"], removed_edges=[("a", "b", "CALLS")])
        assert delta.is_empty()


# ---------------------------------------------------------------------------
# compute_file_fingerprints
# ---------------------------------------------------------------------------


class TestComputeFileFingerprints:
    def test_finds_py_files(self, tmp_path):
        _write_py(tmp_path / "a.py", "def foo(): pass")
        _write_py(tmp_path / "pkg" / "b.py", "def bar(): pass")
        fps = compute_file_fingerprints(tmp_path)
        assert "a.py" in fps
        assert "pkg/b.py" in fps

    def test_excludes_venv(self, tmp_path):
        _write_py(tmp_path / "a.py", "def foo(): pass")
        _write_py(tmp_path / ".venv" / "lib" / "site.py", "x = 1")
        fps = compute_file_fingerprints(tmp_path)
        assert "a.py" in fps
        assert not any(".venv" in k for k in fps)

    def test_excludes_pycache(self, tmp_path):
        _write_py(tmp_path / "a.py", "pass")
        _write_py(tmp_path / "__pycache__" / "a.cpython-312.pyc", "cached")
        fps = compute_file_fingerprints(tmp_path)
        # .pyc is not .py so it won't appear; __pycache__ .py files are excluded too
        assert "__pycache__" not in str(list(fps.keys()))

    def test_values_are_floats(self, tmp_path):
        _write_py(tmp_path / "x.py", "pass")
        fps = compute_file_fingerprints(tmp_path)
        for v in fps.values():
            assert isinstance(v, float)

    def test_custom_exclude(self, tmp_path):
        _write_py(tmp_path / "a.py", "pass")
        _write_py(tmp_path / "build" / "generated.py", "pass")
        fps = compute_file_fingerprints(tmp_path, exclude=["build"])
        assert "a.py" in fps
        assert "build/generated.py" not in fps


# ---------------------------------------------------------------------------
# diff_fingerprints
# ---------------------------------------------------------------------------


class TestDiffFingerprints:
    def test_added(self):
        old = {"a.py": 1.0}
        new = {"a.py": 1.0, "b.py": 2.0}
        added, modified, deleted = diff_fingerprints(old, new)
        assert added == {"b.py"}
        assert modified == set()
        assert deleted == set()

    def test_deleted(self):
        old = {"a.py": 1.0, "b.py": 2.0}
        new = {"a.py": 1.0}
        added, modified, deleted = diff_fingerprints(old, new)
        assert added == set()
        assert modified == set()
        assert deleted == {"b.py"}

    def test_modified(self):
        old = {"a.py": 1.0}
        new = {"a.py": 2.0}
        added, modified, deleted = diff_fingerprints(old, new)
        assert added == set()
        assert modified == {"a.py"}
        assert deleted == set()

    def test_no_change(self):
        old = {"a.py": 1.0, "b.py": 2.0}
        new = {"a.py": 1.0, "b.py": 2.0}
        added, modified, deleted = diff_fingerprints(old, new)
        assert added == set()
        assert modified == set()
        assert deleted == set()

    def test_empty_old(self):
        new = {"a.py": 1.0}
        added, modified, deleted = diff_fingerprints({}, new)
        assert added == {"a.py"}
        assert modified == set()
        assert deleted == set()

    def test_empty_new(self):
        old = {"a.py": 1.0}
        added, modified, deleted = diff_fingerprints(old, {})
        assert added == set()
        assert modified == set()
        assert deleted == {"a.py"}


# ---------------------------------------------------------------------------
# _prune_orphan_hierarchy_nodes
# ---------------------------------------------------------------------------


class TestPruneOrphanHierarchyNodes:
    def test_prunes_empty_module(self):
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository")
        G.add_node("module:mymod", kind="module")
        G.add_edge("repo", "module:mymod", relation="OWNS")
        # No OWNS children of module:mymod
        pruned = _prune_orphan_hierarchy_nodes(G)
        assert "module:mymod" in pruned
        assert "module:mymod" not in G

    def test_keeps_module_with_children(self):
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository")
        G.add_node("module:mymod", kind="module")
        G.add_node("mymod.foo", kind="function")
        G.add_edge("repo", "module:mymod", relation="OWNS")
        G.add_edge("module:mymod", "mymod.foo", relation="OWNS")
        pruned = _prune_orphan_hierarchy_nodes(G)
        assert "module:mymod" not in pruned
        assert "module:mymod" in G

    def test_cascade_prunes_parent_package(self):
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository")
        G.add_node("pkg:mypkg", kind="package")
        G.add_node("module:mypkg.mymod", kind="module")
        G.add_edge("repo", "pkg:mypkg", relation="OWNS")
        G.add_edge("pkg:mypkg", "module:mypkg.mymod", relation="OWNS")
        # module has no children → gets pruned → pkg then becomes childless → also pruned
        pruned = _prune_orphan_hierarchy_nodes(G)
        assert "module:mypkg.mymod" in pruned
        assert "pkg:mypkg" in pruned

    def test_non_hierarchy_nodes_untouched(self):
        G = nx.MultiDiGraph()
        G.add_node("mymod.foo", kind="function")
        pruned = _prune_orphan_hierarchy_nodes(G)
        assert pruned == []
        assert "mymod.foo" in G


# ---------------------------------------------------------------------------
# invalidate_file
# ---------------------------------------------------------------------------


class TestInvalidateFile:
    def test_removes_symbols_owned_by_file(self):
        filepath = "mymod.py"
        G, index = _make_graph_with_file(filepath)
        removed_nodes, _ = invalidate_file(G, index, filepath)
        assert "mymod.foo" not in G
        assert "mymod.bar" not in G
        assert "mymod.foo" in removed_nodes or "mymod.bar" in removed_nodes

    def test_removes_symbols_from_index(self):
        filepath = "mymod.py"
        G, index = _make_graph_with_file(filepath)
        invalidate_file(G, index, filepath)
        assert "mymod.foo" not in index["symbols"]
        assert "mymod.bar" not in index["symbols"]

    def test_removes_import_map_for_file(self):
        filepath = "mymod.py"
        G, index = _make_graph_with_file(filepath)
        invalidate_file(G, index, filepath)
        assert filepath not in index["imports"]

    def test_removes_calls_edges(self):
        filepath = "mymod.py"
        G, index = _make_graph_with_file(filepath)
        # bar -> foo CALLS edge exists before invalidation
        assert G.has_edge("mymod.bar", "mymod.foo")
        invalidate_file(G, index, filepath)
        assert not G.has_edge("mymod.bar", "mymod.foo")

    def test_keeps_nodes_from_other_file(self):
        filepath_a = "mod_a.py"
        filepath_b = "mod_b.py"
        G, index = _make_graph_with_file(filepath_a)
        # Add a second file's symbol
        G.add_node(
            "modb.baz",
            kind="function",
            filepath=filepath_b,
            module="modb",
            function_name="baz",
            class_name=None,
            nested_info=None,
            calls=[],
            local_types=None,
            decorators=[],
            line_no=1,
            col_offset=0,
            visibility="public",
            async_sync="sync",
            method_kind=None,
            bases=None,
            unique_id="modb.baz",
        )
        index["symbols"]["modb.baz"] = {
            "filepath": filepath_b,
            "module": "modb",
            "unique_id": "modb.baz",
            "kind": "function",
            "function_name": "baz",
            "class_name": None,
            "nested_info": None,
            "calls": [],
            "local_types": None,
            "decorators": [],
            "line_no": 1,
            "col_offset": 0,
            "visibility": "public",
            "async_sync": "sync",
            "method_kind": None,
            "bases": None,
        }
        invalidate_file(G, index, filepath_a)
        assert "modb.baz" in G
        assert "modb.baz" in index["symbols"]

    def test_prunes_orphan_module_node(self):
        filepath = "mymod.py"
        G, index = _make_graph_with_file(filepath)
        assert "module:mymod" in G
        invalidate_file(G, index, filepath)
        # module:mymod had only OWNS children that were removed, so it should be pruned
        assert "module:mymod" not in G


# ---------------------------------------------------------------------------
# patch_file
# ---------------------------------------------------------------------------


class TestPatchFile:
    def test_adds_nodes_for_new_file(self, tmp_path):
        code = "def alpha(): pass\ndef beta(): pass\n"
        py = tmp_path / "newmod.py"
        _write_py(py, code)
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        added_nodes, _ = patch_file(G, index, py, tmp_path)
        sym_ids = [k for k in index["symbols"]]
        assert any("alpha" in s for s in sym_ids)
        assert any("beta" in s for s in sym_ids)
        assert len(added_nodes) >= 2

    def test_updates_index_symbols(self, tmp_path):
        code = "def gamma(): pass\n"
        py = tmp_path / "gmod.py"
        _write_py(py, code)
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        patch_file(G, index, py, tmp_path)
        assert any("gamma" in s for s in index["symbols"])

    def test_adds_hierarchy_edges(self, tmp_path):
        code = "def hello(): pass\n"
        py = tmp_path / "hmod.py"
        _write_py(py, code)
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        patch_file(G, index, py, tmp_path)
        mod_node = "module:hmod"
        assert mod_node in G
        assert G.has_edge("repo", mod_node)

    def test_rewires_calls_edges(self, tmp_path):
        code = "def callee(): pass\ndef caller():\n    callee()\n"
        py = tmp_path / "cmod.py"
        _write_py(py, code)
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        patch_file(G, index, py, tmp_path)
        # Expect a CALLS edge from caller -> callee
        caller_id = "cmod.caller"
        callee_id = "cmod.callee"
        assert caller_id in G
        assert callee_id in G
        has_call = any(
            d.get("relation") == "CALLS" for _, _, d in G.out_edges(caller_id, data=True)
        )
        assert has_call, "Expected CALLS edge from caller to callee"


# ---------------------------------------------------------------------------
# update_graph — orchestrator
# ---------------------------------------------------------------------------


class TestUpdateGraph:
    def test_no_change_returns_empty_delta(self, tmp_path):
        _write_py(tmp_path / "a.py", "def foo(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        # First call builds fingerprints
        G, index, delta1 = update_graph(G, index, str(tmp_path))
        # Second call with identical mtimes → no changes
        G, index, delta2 = update_graph(G, index, str(tmp_path))
        assert delta2.is_empty()

    def test_added_file_detected(self, tmp_path):
        _write_py(tmp_path / "a.py", "def foo(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        # First run — seeds fingerprint cache
        G, index, _ = update_graph(G, index, str(tmp_path))

        # Add a new file
        _write_py(tmp_path / "b.py", "def bar(): pass")
        G, index, delta = update_graph(G, index, str(tmp_path))

        assert "b.py" in delta.added_files
        assert any("bar" in n for n in delta.added_nodes)

    def test_modified_file_reparsed(self, tmp_path):
        py = tmp_path / "mod.py"
        _write_py(py, "def original(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        G, index, _ = update_graph(G, index, str(tmp_path))

        # Force mtime to change by sleeping slightly and rewriting
        time.sleep(0.05)
        _write_py(py, "def renamed(): pass")
        G, index, delta = update_graph(G, index, str(tmp_path))

        assert "mod.py" in delta.modified_files
        # Old symbol should be gone, new one added
        assert not any("original" in n for n in index["symbols"])
        assert any("renamed" in n for n in index["symbols"])

    def test_deleted_file_removes_nodes(self, tmp_path):
        py = tmp_path / "todelete.py"
        _write_py(py, "def dying(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        G, index, _ = update_graph(G, index, str(tmp_path))
        assert any("dying" in n for n in index["symbols"])

        py.unlink()
        G, index, delta = update_graph(G, index, str(tmp_path))

        assert "todelete.py" in delta.deleted_files
        assert not any("dying" in n for n in index["symbols"])
        assert not any("dying" in n for n in G.nodes)

    def test_unchanged_file_nodes_untouched(self, tmp_path):
        _write_py(tmp_path / "stable.py", "def stable_fn(): pass")
        _write_py(tmp_path / "changing.py", "def v1(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        G, index, _ = update_graph(G, index, str(tmp_path))

        # Record which nodes belong to stable.py before the change
        stable_nodes_before = {n for n, d in G.nodes(data=True) if d.get("filepath") == "stable.py"}

        time.sleep(0.05)
        _write_py(tmp_path / "changing.py", "def v2(): pass")
        G, index, delta = update_graph(G, index, str(tmp_path))

        stable_nodes_after = {n for n, d in G.nodes(data=True) if d.get("filepath") == "stable.py"}
        assert stable_nodes_before == stable_nodes_after
        assert "changing.py" in delta.modified_files
        assert "stable.py" not in delta.modified_files

    def test_fingerprint_cache_written(self, tmp_path):
        _write_py(tmp_path / "x.py", "def x(): pass")
        cache_path = tmp_path / ".blastradius" / "mtime_cache.json"
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        update_graph(G, index, str(tmp_path), fingerprint_cache_path=str(cache_path))
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert "x.py" in data

    def test_orphan_hierarchy_pruned_after_delete(self, tmp_path):
        py = tmp_path / "solo.py"
        _write_py(py, "def only_fn(): pass")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        G, index, _ = update_graph(G, index, str(tmp_path))
        assert "module:solo" in G

        py.unlink()
        G, index, delta = update_graph(G, index, str(tmp_path))
        # The module node should have been pruned since it has no children
        assert "module:solo" not in G

    def test_graph_stays_consistent_across_updates(self, tmp_path):
        """The graph must have no dangling edges after multiple cycles."""
        py = tmp_path / "cycle_test.py"
        _write_py(py, "def a(): pass\ndef b(): return a()")
        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}
        G, index, _ = update_graph(G, index, str(tmp_path))

        for v in G.nodes:
            for _, w, data in G.out_edges(v, data=True):
                assert w in G, f"Dangling edge {v} -> {w} (after first update)"

        time.sleep(0.05)
        _write_py(py, "def a(): pass\ndef b(): pass\ndef c(): return b()")
        G, index, _ = update_graph(G, index, str(tmp_path))

        for v in G.nodes:
            for _, w, data in G.out_edges(v, data=True):
                assert w in G, f"Dangling edge {v} -> {w} (after second update)"

    def test_atomic_write_cache_failure(self, tmp_path):
        """Simulate a failure during cache write and verify the old cache remains uncorrupted."""
        import json
        from unittest.mock import patch

        from blastradius.incremental import update_graph

        cache_file = tmp_path / ".blastradius" / "mtime_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Write initial uncorrupted cache content
        initial_content = {"file_a.py": 12345.67}
        cache_file.write_text(json.dumps(initial_content), encoding="utf-8")

        # Modify a file to trigger an update_graph write
        py = tmp_path / "app.py"
        _write_py(py, "def x(): pass")

        G = nx.MultiDiGraph()
        G.add_node("repo", kind="repository", name="repo")
        index: dict = {"symbols": {}, "imports": {}}

        # Mock os.replace to raise OSError (simulating a crash/failure during atomic replacement)
        with patch("os.replace", side_effect=OSError("Disk full/Write failure")):
            try:
                update_graph(G, index, str(tmp_path), fingerprint_cache_path=str(cache_file))
            except OSError:
                pass

        # Assert that the cache file exists and still contains the initial uncorrupted content
        assert cache_file.exists()
        current_content = json.loads(cache_file.read_text(encoding="utf-8"))
        assert current_content == initial_content
