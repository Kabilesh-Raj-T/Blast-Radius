"""Graph representation and traversal module."""

import json
from pathlib import Path
from typing import Any

import networkx as nx


def build_graph(index: dict[str, Any]) -> nx.MultiDiGraph:
    """Build a hierarchical dependency MultiDiGraph from the index.

    Nodes represent packages, modules, classes, and functions/methods.
    Edges represent typed relationships (OWNS, IMPORTS, CALLS, INHERITS,
    IMPLEMENTS).
    """
    G = nx.MultiDiGraph()

    symbols = index.get("symbols", {})
    imports = index.get("imports", {})

    # 1. Create Repository root node
    G.add_node("repo", kind="repository", name="repo")

    # 2. Add all symbol nodes and their containment (OWNS) hierarchy
    for sym_id, sym_dict in symbols.items():
        # Add the node with its metadata
        G.add_node(sym_id, **sym_dict)

        module = sym_dict.get("module", "")
        filepath = sym_dict.get("filepath", "")

        # Reconstruct package/module nodes
        if module:
            parts = module.split(".")
            for i in range(len(parts)):
                pkg_name = ".".join(parts[: i + 1])
                pkg_id = f"pkg:{pkg_name}"

                # Check if this is the module (last part) or a parent package
                if i == len(parts) - 1:
                    mod_id = f"module:{pkg_name}"
                    if mod_id not in G:
                        G.add_node(mod_id, kind="module", name=parts[i], filepath=filepath)
                    # Link to parent package
                    if i > 0:
                        parent_pkg = f"pkg:{'.'.join(parts[:i])}"
                        G.add_edge(parent_pkg, mod_id, relation="OWNS")
                    else:
                        G.add_edge("repo", mod_id, relation="OWNS")

                    # Connect Module -> Symbol if it is top-level (no class name, not nested)
                    if sym_dict.get("class_name") is None and sym_dict.get("nested_info") is None:
                        G.add_edge(mod_id, sym_id, relation="OWNS")
                else:
                    if pkg_id not in G:
                        G.add_node(pkg_id, kind="package", name=parts[i])
                    # Link package to parent package
                    if i > 0:
                        parent_pkg = f"pkg:{'.'.join(parts[:i])}"
                        G.add_edge(parent_pkg, pkg_id, relation="OWNS")
                    else:
                        G.add_edge("repo", pkg_id, relation="OWNS")

        # Connection Class -> Method / Function -> Nested Function
        kind = sym_dict.get("kind")
        class_name = sym_dict.get("class_name")
        nested_info = sym_dict.get("nested_info")

        if kind == "method" and class_name:
            module_prefix = f"{module}." if module else ""
            class_id = f"{module_prefix}{class_name}"
            G.add_edge(class_id, sym_id, relation="OWNS")
        elif nested_info:
            parent_id = nested_info.get("parent_id")
            if parent_id:
                G.add_edge(parent_id, sym_id, relation="OWNS")

    # 3. Add IMPORTS, INHERITS, IMPLEMENTS, and CALLS edges
    from blastradius.resolver import resolve_call

    for sym_id, sym_dict in symbols.items():
        kind = sym_dict.get("kind")
        module = sym_dict.get("module", "")
        filepath = sym_dict.get("filepath", "")
        class_name = sym_dict.get("class_name")

        # A. INHERITS & IMPLEMENTS (for Classes)
        if kind == "class" and sym_dict.get("bases"):
            for base in sym_dict.get("bases", []):
                resolved = resolve_call(base, module, class_name, filepath, imports, symbols)
                for base_id in resolved:
                    if base_id in symbols:
                        # Check if base is abstract (has any abstract methods)
                        is_abstract = False
                        for m_id, m_dict in symbols.items():
                            if (
                                m_dict.get("class_name") == symbols[base_id].get("function_name")
                                and m_dict.get("method_kind") == "abstract"
                            ):
                                is_abstract = True
                                break

                        relation = "IMPLEMENTS" if is_abstract else "INHERITS"
                        G.add_edge(sym_id, base_id, relation=relation)

        # B. CALLS (for Functions & Methods)
        if kind in ("function", "method") and sym_dict.get("calls"):
            added_callees = set()
            for call_target in sym_dict.get("calls", []):
                resolved = resolve_call(call_target, module, class_name, filepath, imports, symbols)
                for callee_id in resolved:
                    if callee_id in symbols and callee_id not in added_callees:
                        G.add_edge(sym_id, callee_id, relation="CALLS")
                        added_callees.add(callee_id)

    # C. IMPORTS edges (Module -> Imported Module / Symbol)
    for file_p, import_map in imports.items():
        mod_name = None
        for sym_id, sym_dict in symbols.items():
            if sym_dict.get("filepath") == file_p:
                mod_name = sym_dict.get("module")
                break
        if mod_name:
            mod_id = f"module:{mod_name}"
            if mod_id in G:
                for alias, imported_target in import_map.items():
                    resolved_mod_id = f"module:{imported_target}"
                    if resolved_mod_id in G:
                        G.add_edge(mod_id, resolved_mod_id, relation="IMPORTS")
                    elif imported_target in symbols:
                        G.add_edge(mod_id, imported_target, relation="IMPORTS")

    return G


def build_reverse_graph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Flip all edges in the graph to represent a callee -> caller mapping.

    This preserves edge attributes like 'relation' and 'key'.
    """
    return G.reverse(copy=True)


def persist(G: nx.MultiDiGraph, path: str) -> None:
    """Serialize the graph to disk in JSON format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load(path: str) -> nx.MultiDiGraph:
    """Deserialize the graph from a JSON file."""
    p = Path(path)
    if not p.exists():
        return nx.MultiDiGraph()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return nx.node_link_graph(data)
    except Exception:
        return nx.MultiDiGraph()
