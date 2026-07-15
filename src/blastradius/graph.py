"""Graph representation and traversal module."""

import json
from pathlib import Path
from typing import Any

import networkx as nx

from blastradius.resolver import (
    resolve_call,
    resolve_call_with_certainty,
    resolve_imports_transitively,
)


def build_graph(index: dict[str, Any]) -> nx.MultiDiGraph:
    # Preprocess and transitively resolve imports
    resolve_imports_transitively(index)
    """Build a hierarchical dependency MultiDiGraph from the index.

    Nodes represent packages, modules, classes, and functions/methods.
    Edges represent typed relationships (OWNS, IMPORTS, CALLS, INHERITS,
    IMPLEMENTS).
    """
    G = nx.MultiDiGraph()
    from blastradius.symbol import SymbolID

    symbols = index.get("symbols", {})
    imports = index.get("imports", {})

    # 1. Create Repository root node
    G.add_node(SymbolID("repo"), kind="repository", name="repo")

    # 2. Add all symbol nodes and their containment (OWNS) hierarchy
    for sym_id, sym_dict in symbols.items():
        sym_sid = SymbolID(sym_id)
        # Add the node with its metadata
        G.add_node(sym_sid, **sym_dict)

        module = sym_dict.get("module", "")
        filepath = sym_dict.get("filepath", "")

        # Reconstruct package/module nodes
        if module:
            parts = module.split(".")
            for i in range(len(parts)):
                pkg_name = ".".join(parts[: i + 1])
                pkg_sid = SymbolID(f"pkg:{pkg_name}")

                # Check if this is the module (last part) or a parent package
                if i == len(parts) - 1:
                    mod_sid = SymbolID(f"module:{pkg_name}")
                    if mod_sid not in G:
                        G.add_node(mod_sid, kind="module", name=parts[i], filepath=filepath)
                    # Link to parent package
                    if i > 0:
                        parent_pkg = SymbolID(f"pkg:{'.'.join(parts[:i])}")
                        G.add_edge(parent_pkg, mod_sid, relation="OWNS")
                    else:
                        G.add_edge(SymbolID("repo"), mod_sid, relation="OWNS")

                    # Connect Module -> Symbol if it is top-level (no class name, not nested)
                    if sym_dict.get("class_name") is None and sym_dict.get("nested_info") is None:
                        G.add_edge(mod_sid, sym_sid, relation="OWNS")
                else:
                    if pkg_sid not in G:
                        G.add_node(pkg_sid, kind="package", name=parts[i])
                    # Link package to parent package
                    if i > 0:
                        parent_pkg = SymbolID(f"pkg:{'.'.join(parts[:i])}")
                        G.add_edge(parent_pkg, pkg_sid, relation="OWNS")
                    else:
                        G.add_edge(SymbolID("repo"), pkg_sid, relation="OWNS")

        # Connection Class -> Method / Function -> Nested Function
        kind = sym_dict.get("kind")
        class_name = sym_dict.get("class_name")
        nested_info = sym_dict.get("nested_info")

        if kind == "method" and class_name:
            module_prefix = f"{module}." if module else ""
            class_sid = SymbolID(f"{module_prefix}{class_name}")
            G.add_edge(class_sid, sym_sid, relation="OWNS")
        elif nested_info:
            parent_id = nested_info.get("parent_id")
            if parent_id:
                G.add_edge(SymbolID(parent_id), sym_sid, relation="OWNS")

    # 3. Add IMPORTS, INHERITS, IMPLEMENTS, and CALLS edges
    add_edges_for_symbols(G, symbols, imports)

    return G


def add_edges_for_symbols(
    G: nx.MultiDiGraph,
    symbols: dict[str, Any],
    imports: dict[str, dict[str, str]],
) -> None:
    """Wire INHERITS, IMPLEMENTS, CALLS, and IMPORTS edges for all symbols.

    Extracted as a standalone helper so that the incremental update engine
    can call it without duplicating the resolution logic from
    :func:`build_graph`.

    Parameters
    ----------
    G:
        The graph to mutate (nodes must already exist).
    symbols:
        The complete symbol table (used for resolution).
    imports:
        The complete import map keyed by relative file path.
    """
    from blastradius.symbol import SymbolID

    # --- Pre-built indexes to eliminate O(n²) inner loops ---

    # Map: class_name (unqualified) -> True if any method in that class is abstract.
    # Used to determine INHERITS vs IMPLEMENTS without scanning all symbols.
    abstract_classes: set[str] = set()
    # Map: module -> list of sym_id for functions/methods in that module.
    # Used by dynamic call fanout instead of scanning all symbols.
    module_functions: dict[str, list[str]] = {}
    # Map: filepath -> module name.  Used in section C IMPORTS edges.
    filepath_to_module: dict[str, str] = {}

    for sym_id_pre, sym_dict_pre in symbols.items():
        kind_pre = sym_dict_pre.get("kind")
        module_pre = sym_dict_pre.get("module", "")
        fp_pre = sym_dict_pre.get("filepath", "")
        cname_pre = sym_dict_pre.get("class_name")
        if kind_pre == "method" and sym_dict_pre.get("method_kind") == "abstract" and cname_pre:
            abstract_classes.add(cname_pre)
        if kind_pre in ("function", "method") and module_pre:
            module_functions.setdefault(module_pre, []).append(sym_id_pre)
        if fp_pre and module_pre and fp_pre not in filepath_to_module:
            filepath_to_module[fp_pre] = module_pre

    for sym_id, sym_dict in symbols.items():
        kind = sym_dict.get("kind")
        module = sym_dict.get("module", "")
        filepath = sym_dict.get("filepath", "")
        class_name = sym_dict.get("class_name")

        sym_sid = SymbolID(sym_id)

        # A. INHERITS & IMPLEMENTS (for Classes)
        if kind == "class" and sym_dict.get("bases"):
            for base in sym_dict.get("bases", []):
                resolved = resolve_call(
                    base, module, class_name, filepath, imports, symbols, caller_id=sym_id
                )
                for base_id in resolved:
                    if base_id in symbols:
                        # Use pre-built abstract_classes index — O(1) instead of O(n)
                        base_class_name = symbols[base_id].get("function_name") or symbols[
                            base_id
                        ].get("class_name", "")
                        is_abstract = base_class_name in abstract_classes
                        relation = "IMPLEMENTS" if is_abstract else "INHERITS"
                        G.add_edge(sym_sid, SymbolID(base_id), relation=relation)

        # B. CALLS (for Functions & Methods)
        if kind in ("function", "method") and sym_dict.get("calls"):
            added_callees: set[str] = set()
            local_types = sym_dict.get("local_types")
            for call_target in sym_dict.get("calls", []):
                if call_target.startswith("dynamic:"):
                    try:
                        parts = call_target.split(":")
                        if len(parts) == 4:
                            _, dyn_type, line, col = parts
                            dyn_node_id = SymbolID(f"{sym_id}:dyn:{dyn_type}:{line}:{col}")
                            G.add_node(
                                dyn_node_id,
                                kind="dynamic_call",
                                type=dyn_type,
                                line_no=int(line),
                                col_offset=int(col),
                                filepath=filepath,
                            )
                            # Caller -> DynamicCall
                            G.add_edge(sym_sid, dyn_node_id, relation="CALLS", certainty=0.30)
                            # DynamicCall -> potential function/method targets in this module.
                            targets = sorted(module_functions.get(module, []))
                            for other_id in targets:
                                G.add_edge(
                                    dyn_node_id,
                                    SymbolID(other_id),
                                    relation="CALLS",
                                    certainty=0.30,
                                )
                        else:
                            raise ValueError("Invalid dynamic tag structure")
                    except (ValueError, KeyError, IndexError):
                        # Fallback: create a generic low-confidence broad-impact edge/node
                        fallback_node = SymbolID(f"{sym_id}:dyn:fallback")
                        if fallback_node not in G:
                            G.add_node(
                                fallback_node,
                                kind="dynamic_call",
                                type="fallback",
                                line_no=sym_dict.get("line_no", 1),
                                col_offset=0,
                                filepath=filepath,
                            )
                        G.add_edge(sym_sid, fallback_node, relation="CALLS", certainty=0.10)
                        targets = sorted(module_functions.get(module, []))
                        for other_id in targets:
                            G.add_edge(
                                fallback_node, SymbolID(other_id), relation="CALLS", certainty=0.10
                            )
                else:
                    resolved, certainty = resolve_call_with_certainty(
                        call_target,
                        module,
                        class_name,
                        filepath,
                        imports,
                        symbols,
                        local_types,
                        caller_id=sym_id,
                    )
                    for callee_id in resolved:
                        if callee_id in symbols and callee_id not in added_callees:
                            is_inherited = False
                            callee_class = symbols[callee_id].get("class_name")
                            if class_name and callee_class and class_name != callee_class:
                                is_inherited = True
                            G.add_edge(
                                sym_sid,
                                SymbolID(callee_id),
                                relation="CALLS",
                                certainty=certainty,
                                inheritance=is_inherited,
                            )
                            added_callees.add(callee_id)

    # C. IMPORTS edges (Module -> Imported Module / Symbol)
    # Use pre-built filepath_to_module index — O(1) per file instead of O(n)
    for file_p, import_map in imports.items():
        mod_name = filepath_to_module.get(file_p)
        if mod_name:
            mod_id = SymbolID(f"module:{mod_name}")
            if mod_id in G:
                for _alias, imported_target in import_map.items():
                    if _alias.startswith("__") or not isinstance(imported_target, str):
                        continue
                    resolved_mod_id = SymbolID(f"module:{imported_target}")
                    if resolved_mod_id in G:
                        G.add_edge(mod_id, resolved_mod_id, relation="IMPORTS")
                    elif imported_target in symbols:
                        G.add_edge(mod_id, SymbolID(imported_target), relation="IMPORTS")

    # Track diagnostics
    from blastradius.diagnostics import tracker

    tracker.resolved_imports = sum(
        1 for _, _, d in G.edges(data=True) if d.get("relation") == "IMPORTS"
    )
    tracker.ambiguous_symbols = sum(
        1 for _, _, d in G.edges(data=True) if d.get("certainty") == 0.60
    )
    tracker.dynamic_calls = sum(1 for _, d in G.nodes(data=True) if d.get("kind") == "dynamic_call")


def build_reverse_graph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Flip all edges in the graph to represent a callee -> caller mapping.

    Returns a read-only reversed view of the graph (O(1), no edge copy).
    ``compute_blast_radius`` only reads the reverse graph, so a view is safe.
    """
    return G.reverse(copy=False)


def persist(G: nx.MultiDiGraph, path: str) -> None:
    """Serialize the graph to disk in JSON format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Convert nodes to string keys for JSON serialization
    string_G = nx.MultiDiGraph()
    for node, data in G.nodes(data=True):
        string_G.add_node(str(node), **data)
    for u, v, key, data in G.edges(keys=True, data=True):
        string_G.add_edge(str(u), str(v), key=key, **data)
    data = nx.node_link_data(string_G)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load(path: str) -> nx.MultiDiGraph:
    """Deserialize the graph from a JSON file."""
    p = Path(path)
    if not p.exists():
        return nx.MultiDiGraph()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        string_G = nx.node_link_graph(data)
        # Convert string node keys back to SymbolID instances
        from blastradius.symbol import SymbolID

        G = nx.MultiDiGraph()
        for node, data in string_G.nodes(data=True):
            G.add_node(SymbolID(node), **data)
        for u, v, key, data in string_G.edges(keys=True, data=True):
            G.add_edge(SymbolID(u), SymbolID(v), key=key, **data)
        return G
    except Exception:
        return nx.MultiDiGraph()
