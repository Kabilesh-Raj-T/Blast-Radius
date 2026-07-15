"""Incremental graph update engine.

Replaces full graph rebuilds with surgical node/edge patching.
Only files that have changed (by mtime) are re-parsed; the rest of
the graph is left completely untouched.

Designed for repositories with 100 k+ functions where a full
``build_graph`` call on every run is prohibitively slow.

Typical usage
-------------
Cold start (first run)::

    from blastradius.indexer import index_repo
    from blastradius.graph import build_graph, persist

    index = index_repo(repo_path)
    G = build_graph(index)
    persist(G, graph_path)

Hot path (subsequent runs)::

    from blastradius.graph import load
    from blastradius.indexer import load_index
    from blastradius.incremental import update_graph

    G = load(graph_path)
    index = load_index(index_path)
    G, index, delta = update_graph(G, index, repo_path)
    persist(G, graph_path)
    print(delta)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from blastradius.core.context import get_repository_context
from blastradius.core.symbol import SymbolID
from blastradius.parsing import registry

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class GraphDelta:
    """Describes what changed during one incremental update cycle."""

    added_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)

    added_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)

    # Each entry is (src, dst, relation)
    added_edges: list[tuple[str, str, str]] = field(default_factory=list)
    removed_edges: list[tuple[str, str, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when no files changed and no graph mutations occurred."""
        return not (self.added_files or self.modified_files or self.deleted_files)


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def compute_file_fingerprints(
    repo_dir: Path,
    exclude: list[str] | None = None,
) -> dict[str, float]:
    """Walk *repo_dir* and return ``{relative_path: mtime}`` for every .py file.

    Parameters
    ----------
    repo_dir:
        Absolute path to the repository root.
    exclude:
        Directory-name fragments to skip (e.g. ``["__pycache__", ".venv"]``).
    """
    if exclude is None:
        exclude = ["__pycache__", "venv", ".venv"]

    fingerprints: dict[str, float] = {}
    supported_exts = registry.extensions
    for filepath in repo_dir.rglob("*"):
        if filepath.is_dir():
            continue
        if filepath.suffix.lower() not in supported_exts:
            continue
        parts = filepath.relative_to(repo_dir).parts
        if any(part in exclude for part in parts):
            continue
        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            continue
        rel = str(filepath.relative_to(repo_dir)).replace("\\", "/")
        fingerprints[rel] = mtime

    return fingerprints


def diff_fingerprints(
    old: dict[str, float],
    new: dict[str, float],
) -> tuple[set[str], set[str], set[str]]:
    """Compute the file-level diff between two mtime fingerprint snapshots.

    Returns
    -------
    added:
        Files present in *new* but not in *old*.
    modified:
        Files present in both whose mtime changed.
    deleted:
        Files present in *old* but absent from *new*.
    """
    old_keys = set(old)
    new_keys = set(new)

    added = new_keys - old_keys
    deleted = old_keys - new_keys
    modified = {k for k in old_keys & new_keys if old[k] != new[k]}

    return added, modified, deleted


# ---------------------------------------------------------------------------
# Graph mutation helpers
# ---------------------------------------------------------------------------


def _collect_nodes_for_file(
    G: nx.MultiDiGraph,
    rel_filepath: str,
) -> list[SymbolID]:
    """Return all graph nodes whose ``filepath`` attribute equals *rel_filepath*.

    Includes both symbol nodes and dynamic-call nodes.
    """
    return [n for n, data in G.nodes(data=True) if data.get("filepath") == rel_filepath]


def _snapshot_incident_edges(
    G: nx.MultiDiGraph,
    nodes: list[SymbolID],
) -> list[tuple[str, str, str]]:
    """Return ``(src, dst, relation)`` tuples for all edges incident to *nodes*."""
    edges: list[tuple[str, str, str]] = []
    node_set = set(nodes)
    for n in nodes:
        for u, v, data in G.in_edges(n, data=True):
            if u not in node_set:
                edges.append((str(u), str(v), data.get("relation", "")))
        for u, v, data in G.out_edges(n, data=True):
            if v not in node_set:
                edges.append((str(u), str(v), data.get("relation", "")))
    return edges


def _prune_orphan_hierarchy_nodes(G: nx.MultiDiGraph) -> list[str]:
    """Remove ``pkg:`` and ``module:`` nodes that no longer own any children.

    These shared hierarchy nodes must only be removed when their last OWNS
    child is gone.  Returns the list of pruned node IDs.

    The pruning is iterative because removing a ``module:`` node may leave its
    parent ``pkg:`` node childless.
    """
    pruned: list[str] = []
    changed = True
    while changed:
        changed = False
        hierarchy_nodes = [
            n
            for n in list(G.nodes)
            if (isinstance(n, SymbolID) or isinstance(n, str))
            and (str(n).startswith("pkg:") or str(n).startswith("module:"))
        ]
        for n in hierarchy_nodes:
            # A hierarchy node has children iff it has any OWNS out-edges
            has_children = any(
                data.get("relation") == "OWNS" for _, _, data in G.out_edges(n, data=True)
            )
            if not has_children:
                G.remove_node(n)
                pruned.append(str(n))
                changed = True
    return pruned


def _add_hierarchy_edges(
    G: nx.MultiDiGraph,
    symbols: list[Any],  # list[Symbol]
) -> None:
    """Insert ``pkg:`` / ``module:`` nodes and ``OWNS`` containment edges.

    Mirrors the hierarchy-construction logic in :func:`blastradius.graph.build_graph`.
    """
    for sym in symbols:
        sym_dict = sym.to_dict()
        sym_sid = SymbolID(sym.unique_id)
        module = sym_dict.get("module", "")
        filepath = sym_dict.get("filepath", "")

        if not module:
            continue

        parts = module.split(".")
        for i in range(len(parts)):
            pkg_name = ".".join(parts[: i + 1])
            pkg_sid = SymbolID(f"pkg:{pkg_name}")

            if i == len(parts) - 1:
                # Leaf = the module itself
                mod_sid = SymbolID(f"module:{pkg_name}")
                if mod_sid not in G:
                    G.add_node(mod_sid, kind="module", name=parts[i], filepath=filepath)
                if i > 0:
                    parent_pkg = SymbolID(f"pkg:{'.'.join(parts[:i])}")
                    if not G.has_edge(parent_pkg, mod_sid):
                        G.add_edge(parent_pkg, mod_sid, relation="OWNS")
                else:
                    if not G.has_edge(SymbolID("repo"), mod_sid):
                        G.add_edge(SymbolID("repo"), mod_sid, relation="OWNS")

                # Module → symbol (only top-level symbols)
                if sym_dict.get("class_name") is None and sym_dict.get("nested_info") is None:
                    if not G.has_edge(mod_sid, sym_sid):
                        G.add_edge(mod_sid, sym_sid, relation="OWNS")
            else:
                if pkg_sid not in G:
                    G.add_node(pkg_sid, kind="package", name=parts[i])
                if i > 0:
                    parent_pkg = SymbolID(f"pkg:{'.'.join(parts[:i])}")
                    if not G.has_edge(parent_pkg, pkg_sid):
                        G.add_edge(parent_pkg, pkg_sid, relation="OWNS")
                else:
                    if not G.has_edge(SymbolID("repo"), pkg_sid):
                        G.add_edge(SymbolID("repo"), pkg_sid, relation="OWNS")

        # Class → Method / Parent → Nested function
        kind = sym_dict.get("kind")
        class_name = sym_dict.get("class_name")
        nested_info = sym_dict.get("nested_info")
        module_prefix = f"{module}." if module else ""

        if kind == "method" and class_name:
            class_sid = SymbolID(f"{module_prefix}{class_name}")
            if not G.has_edge(class_sid, sym_sid):
                G.add_edge(class_sid, sym_sid, relation="OWNS")
        elif nested_info:
            parent_id = nested_info.get("parent_id")
            if parent_id and not G.has_edge(SymbolID(parent_id), sym_sid):
                G.add_edge(SymbolID(parent_id), sym_sid, relation="OWNS")


def _rewire_edges(
    G: nx.MultiDiGraph,
    index: dict[str, Any],
    new_symbols: list[Any],  # list[Symbol]
    import_map: dict[str, str],
    rel_filepath: str,
) -> list[tuple[str, str, str]]:
    """Re-resolve CALLS / INHERITS / IMPLEMENTS / IMPORTS edges.

    Covers three groups:
    1. Outgoing edges from newly added symbols (their calls and bases).
    2. IMPORTS edges from the file's module node.
    3. Incoming CALLS edges from callers that previously pointed at symbols
       in this file (their nodes still exist; we patch their out-edges).

    Returns a list of ``(src, dst, relation)`` tuples for all edges added.
    """
    from blastradius.resolution.resolver import resolve_call  # local import to avoid circular

    symbols = index["symbols"]
    imports = index["imports"]
    added: list[tuple[str, str, str]] = []

    def _add(src: SymbolID, dst: SymbolID, relation: str) -> None:
        G.add_edge(src, dst, relation=relation)
        added.append((str(src), str(dst), relation))

    # ── 1. Edges FROM newly inserted symbols ──────────────────────────────

    for sym in new_symbols:
        sym_dict = sym.to_dict()
        sym_sid = SymbolID(sym.unique_id)
        module = sym_dict.get("module", "")
        class_name = sym_dict.get("class_name")
        filepath = sym_dict.get("filepath", "")
        kind = sym_dict.get("kind")
        local_types = sym_dict.get("local_types")

        # INHERITS / IMPLEMENTS
        if kind == "class" and sym_dict.get("bases"):
            for base in sym_dict.get("bases", []):
                resolved = resolve_call(
                    base, module, class_name, filepath, imports, symbols, local_types
                )
                for base_id in resolved:
                    if base_id in symbols:
                        # Determine relation type
                        is_abstract = any(
                            m.get("class_name") == symbols[base_id].get("function_name")
                            and m.get("method_kind") == "abstract"
                            for m in symbols.values()
                        )
                        relation = "IMPLEMENTS" if is_abstract else "INHERITS"
                        _add(sym_sid, SymbolID(base_id), relation)

        # CALLS / dynamic calls
        if kind in ("function", "method") and sym_dict.get("calls"):
            added_callees: set[str] = set()
            for call_target in sym_dict.get("calls", []):
                if call_target.startswith("dynamic:"):
                    parts = call_target.split(":")
                    if len(parts) == 4:
                        _, dyn_type, line, col = parts
                        dyn_sid = SymbolID(f"{sym.unique_id}:dyn:{dyn_type}:{line}:{col}")
                        if dyn_sid not in G:
                            G.add_node(
                                dyn_sid,
                                kind="dynamic_call",
                                type=dyn_type,
                                line_no=int(line),
                                col_offset=int(col),
                                filepath=filepath,
                            )
                        _add(sym_sid, dyn_sid, "CALLS")
                        for other_id, other_dict in symbols.items():
                            if (
                                other_dict.get("kind") in ("function", "method")
                                and other_dict.get("module") == module
                            ):
                                _add(dyn_sid, SymbolID(other_id), "CALLS")
                else:
                    resolved = resolve_call(
                        call_target,
                        module,
                        class_name,
                        filepath,
                        imports,
                        symbols,
                        local_types,
                    )
                    for callee_id in resolved:
                        if callee_id in symbols and callee_id not in added_callees:
                            _add(sym_sid, SymbolID(callee_id), "CALLS")
                            added_callees.add(callee_id)

    # ── 2. IMPORTS edges from the file's module node ──────────────────────

    new_sym_ids = {s.unique_id for s in new_symbols}
    mod_name = None
    for sym in new_symbols:
        mod_name = sym.to_dict().get("module")
        if mod_name:
            break

    if mod_name:
        mod_sid = SymbolID(f"module:{mod_name}")
        if mod_sid in G:
            for alias, imported_target in import_map.items():
                if alias.startswith("__") or not isinstance(imported_target, str):
                    continue
                resolved_mod_sid = SymbolID(f"module:{imported_target}")
                if resolved_mod_sid in G:
                    _add(mod_sid, resolved_mod_sid, "IMPORTS")
                elif imported_target in symbols:
                    _add(mod_sid, SymbolID(imported_target), "IMPORTS")

    # ── 3. Re-wire incoming CALLS from external callers ───────────────────
    # Callers that imported from this file may have lost their CALLS edges
    # when we removed the old symbol nodes.  Re-resolve them now.

    new_sym_by_name: dict[str, str] = {}
    for sym in new_symbols:
        sym_dict = sym.to_dict()
        fn = sym_dict.get("function_name")
        if fn:
            new_sym_by_name[fn] = sym.unique_id
        # Also index by class name
        cls = sym_dict.get("class_name")
        if cls and sym_dict.get("kind") == "class":
            new_sym_by_name[cls] = sym.unique_id

    for caller_id, caller_dict in symbols.items():
        if caller_id in new_sym_ids:
            continue  # already handled above
        caller_filepath = caller_dict.get("filepath", "")
        caller_module = caller_dict.get("module", "")
        caller_class = caller_dict.get("class_name")
        caller_local_types = caller_dict.get("local_types")
        caller_kind = caller_dict.get("kind")

        if caller_kind not in ("function", "method"):
            continue

        caller_imports = imports.get(caller_filepath, {})
        # Check if this caller imports anything from our changed file
        imports_from_file = (
            any(v.startswith(mod_name + ".") or v == mod_name for v in caller_imports.values())
            if mod_name
            else False
        )

        if not imports_from_file:
            continue

        # Re-resolve each of this caller's call targets
        caller_sid = SymbolID(caller_id)
        existing_callees = {
            str(v)
            for _, v, data in G.out_edges(caller_sid, data=True)
            if data.get("relation") == "CALLS"
        }
        for call_target in caller_dict.get("calls") or []:
            if call_target.startswith("dynamic:"):
                continue
            resolved = resolve_call(
                call_target,
                caller_module,
                caller_class,
                caller_filepath,
                imports,
                symbols,
                caller_local_types,
            )
            for callee_id in resolved:
                if callee_id in symbols and callee_id not in existing_callees:
                    _add(caller_sid, SymbolID(callee_id), "CALLS")
                    existing_callees.add(callee_id)

    return added


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def invalidate_file(
    G: nx.MultiDiGraph,
    index: dict[str, Any],
    rel_filepath: str,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Remove all nodes and edges owned by *rel_filepath* from the graph.

    Parameters
    ----------
    G:
        The in-memory dependency graph (mutated in-place).
    index:
        The symbol + import index (mutated in-place).
    rel_filepath:
        Repository-relative path of the file being invalidated
        (forward-slash separated, e.g. ``"utils/parser.py"``).

    Returns
    -------
    removed_nodes:
        IDs of nodes that were removed.
    removed_edges:
        ``(src, dst, relation)`` tuples for edges that were removed.
    """
    nodes_to_remove = _collect_nodes_for_file(G, rel_filepath)
    removed_edges = _snapshot_incident_edges(G, nodes_to_remove)

    # NetworkX removes incident edges automatically when a node is deleted
    G.remove_nodes_from(nodes_to_remove)

    # Update the index
    for n in nodes_to_remove:
        index["symbols"].pop(n, None)
    index["imports"].pop(rel_filepath, None)
    index.setdefault("modules", {}).pop(rel_filepath, None)

    from blastradius.resolution.resolver import invalidate_caches

    invalidate_caches()

    # Clean up hierarchy nodes that became childless
    orphans = _prune_orphan_hierarchy_nodes(G)

    return nodes_to_remove + orphans, removed_edges


def patch_file(
    G: nx.MultiDiGraph,
    index: dict[str, Any],
    abs_filepath: Path,
    repo_dir: Path,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Parse *abs_filepath* and insert its symbols + edges into the graph.

    Assumes the file has already been invalidated (via :func:`invalidate_file`)
    so there are no stale nodes to collide with.

    Parameters
    ----------
    G:
        The in-memory dependency graph (mutated in-place).
    index:
        The symbol + import index (mutated in-place).
    abs_filepath:
        Absolute path of the file to (re-)parse.
    repo_dir:
        Absolute path to the repository root.

    Returns
    -------
    added_nodes:
        IDs of nodes that were added.
    added_edges:
        ``(src, dst, relation)`` tuples for edges that were added.
    """
    rel_filepath = str(abs_filepath.relative_to(repo_dir)).replace("\\", "/")

    # Ensure the repo root exists in the graph
    if SymbolID("repo") not in G:
        G.add_node(SymbolID("repo"), kind="repository", name="repo")

    # Parse the file
    symbols, import_map = registry.parse_file(str(abs_filepath), str(repo_dir))

    # Insert symbol nodes and update the index
    added_nodes: list[str] = []
    for sym in symbols:
        sym_dict = sym.to_dict()
        G.add_node(sym.unique_id, **sym_dict)
        index["symbols"][str(sym.unique_id)] = sym_dict
        added_nodes.append(str(sym.unique_id))

    # Update import and module maps
    index["imports"][rel_filepath] = import_map
    ctx = get_repository_context(str(repo_dir))
    index.setdefault("modules", {})[rel_filepath] = ctx.module_metadata(str(abs_filepath))

    from blastradius.resolution.resolver import invalidate_caches

    invalidate_caches()

    # Rebuild hierarchy edges (OWNS)
    _add_hierarchy_edges(G, symbols)

    # Re-resolve semantic edges (CALLS, INHERITS, IMPORTS, ...)
    added_edges = _rewire_edges(G, index, symbols, import_map, rel_filepath)

    return added_nodes, added_edges


def update_graph(
    G: nx.MultiDiGraph,
    index: dict[str, Any],
    repo_path: str,
    exclude: list[str] | None = None,
    fingerprint_cache_path: str | None = None,
) -> tuple[nx.MultiDiGraph, dict[str, Any], GraphDelta]:
    """Detect changed files and incrementally update *G* and *index*.

    This is the main entry-point for the hot-path update cycle.

    Parameters
    ----------
    G:
        The in-memory dependency graph loaded from disk.  Mutated in-place.
    index:
        The symbol + import index loaded from disk.  Mutated in-place.
    repo_path:
        Path to the repository root.
    exclude:
        Directory-name fragments to skip during file discovery.
    fingerprint_cache_path:
        Path to the mtime cache JSON file.  Defaults to
        ``<repo>/.blastradius/mtime_cache.json``.

    Returns
    -------
    G:
        The updated graph (same object, mutated).
    index:
        The updated index (same object, mutated).
    delta:
        A :class:`GraphDelta` describing every change made.
    """
    if exclude is None:
        exclude = ["__pycache__", "venv", ".venv"]

    repo_dir = Path(repo_path).resolve()

    if fingerprint_cache_path is None:
        fingerprint_cache_path = str(repo_dir / ".blastradius" / "mtime_cache.json")

    # ── Load previous fingerprints ─────────────────────────────────────────
    cache_path = Path(fingerprint_cache_path)
    old_fingerprints: dict[str, float] = {}
    if cache_path.exists():
        try:
            old_fingerprints = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            old_fingerprints = {}

    # ── Compute current fingerprints ───────────────────────────────────────
    new_fingerprints = compute_file_fingerprints(repo_dir, exclude)

    # ── Diff ───────────────────────────────────────────────────────────────
    added_files, modified_files, deleted_files = diff_fingerprints(
        old_fingerprints, new_fingerprints
    )

    delta = GraphDelta(
        added_files=sorted(added_files),
        modified_files=sorted(modified_files),
        deleted_files=sorted(deleted_files),
    )

    if delta.is_empty():
        return G, index, delta

    # ── Process deletions ──────────────────────────────────────────────────
    for rel_path in sorted(deleted_files):
        removed_nodes, removed_edges = invalidate_file(G, index, rel_path)
        delta.removed_nodes.extend(removed_nodes)
        delta.removed_edges.extend(removed_edges)

    # ── Process modifications (invalidate then re-patch) ───────────────────
    for rel_path in sorted(modified_files):
        removed_nodes, removed_edges = invalidate_file(G, index, rel_path)
        delta.removed_nodes.extend(removed_nodes)
        delta.removed_edges.extend(removed_edges)

        abs_path = repo_dir / rel_path
        if abs_path.exists():
            added_nodes, added_edges = patch_file(G, index, abs_path, repo_dir)
            delta.added_nodes.extend(added_nodes)
            delta.added_edges.extend(added_edges)

    # ── Process additions ──────────────────────────────────────────────────
    for rel_path in sorted(added_files):
        abs_path = repo_dir / rel_path
        if abs_path.exists():
            added_nodes, added_edges = patch_file(G, index, abs_path, repo_dir)
            delta.added_nodes.extend(added_nodes)
            delta.added_edges.extend(added_edges)

    # ── Persist updated fingerprint cache ─────────────────────────────────
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(cache_path.name + f".{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(new_fingerprints, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except Exception:
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    return G, index, delta
