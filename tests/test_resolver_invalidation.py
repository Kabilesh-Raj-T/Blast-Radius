import os
import time

from blastradius.resolver import invalidate_caches, resolve, resolve_call


def test_resolve_cache_invalidation():
    symbols = {
        "mymod.py:foo": {
            "unique_id": "mymod.py:foo",
            "kind": "function",
            "function_name": "foo",
        }
    }

    # First resolve call
    res = resolve("foo", symbols)
    assert res == ["mymod.py:foo"]

    # Mutate in place (add another symbol with the same bare name from a different file)
    symbols["othermod.py:foo"] = {
        "unique_id": "othermod.py:foo",
        "kind": "function",
        "function_name": "foo",
    }

    # Without invalidation, should return the cached result (only mymod.py:foo)
    res_stale = resolve("foo", symbols)
    assert res_stale == ["mymod.py:foo"]

    # With invalidation, should return both
    invalidate_caches()
    res_fresh = resolve("foo", symbols)
    assert sorted(res_fresh) == sorted(["mymod.py:foo", "othermod.py:foo"])


def test_resolve_call_cache_invalidation():
    symbols = {
        "mymod.foo": {
            "unique_id": "mymod.foo",
            "kind": "function",
            "function_name": "foo",
            "module": "mymod",
            "filepath": "mymod.py",
        }
    }
    imports = {"caller.py": {"foo": "mymod.foo"}}

    # Resolve call
    res = resolve_call("foo", "caller", None, "caller.py", imports, symbols)
    assert res == ["mymod.foo"]

    # Mutate imports in place to point to bar instead
    symbols["mymod.bar"] = {
        "unique_id": "mymod.bar",
        "kind": "function",
        "function_name": "bar",
        "module": "mymod",
        "filepath": "mymod.py",
    }
    imports["caller.py"]["foo"] = "mymod.bar"

    # Without invalidation, should return cached target
    res_stale = resolve_call("foo", "caller", None, "caller.py", imports, symbols)
    assert res_stale == ["mymod.foo"]

    # With invalidation, should return new target
    invalidate_caches()
    res_fresh = resolve_call("foo", "caller", None, "caller.py", imports, symbols)
    assert res_fresh == ["mymod.bar"]


def test_incremental_update_path_invalidation(tmp_path):
    # Setup a dummy repo directory
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Create two python files
    file_a = repo_dir / "a.py"
    file_a.write_text("def foo():\n    pass\n", encoding="utf-8")

    file_b = repo_dir / "b.py"
    file_b.write_text("from a import foo\ndef bar():\n    foo()\n", encoding="utf-8")

    # Initial indexing
    from blastradius.graph import build_graph
    from blastradius.indexer import index_repo, update_index

    # Exclude typical folders and specify test index_dir
    index_dir = str(repo_dir / ".blastradius")
    index = index_repo(str(repo_dir), index_dir=index_dir)
    G = build_graph(index)

    # Check that calls are resolved
    # File b calls a.foo
    assert G.has_edge("b.bar", "a.foo")

    # Now modify file_a to define bar_helper, and modify file_b to call bar_helper instead
    file_a.write_text("def foo():\n    pass\ndef bar_helper():\n    pass\n", encoding="utf-8")
    file_b.write_text("from a import bar_helper\ndef bar():\n    bar_helper()\n", encoding="utf-8")

    # Artificially modify mtimes of file_a and file_b so indexer/incremental picks them up
    new_mtime = time.time() + 5
    os.utime(str(file_a), (new_mtime, new_mtime))
    os.utime(str(file_b), (new_mtime, new_mtime))

    # Run update_index (which runs update_graph, which mutates index and graph)
    G_updated, index_updated, delta = update_index(str(repo_dir), G, index_dir=index_dir)

    # Verify that the new dependencies are correctly resolved and the old ones are removed
    assert not G_updated.has_edge("b.bar", "a.foo")
    assert G_updated.has_edge("b.bar", "a.bar_helper")
