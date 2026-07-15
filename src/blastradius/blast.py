"""Blast radius calculation and analysis module."""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from blastradius.discovery import DiscoveryConfig, DiscoveryEngine
from blastradius.symbol import SymbolID


@dataclass
class AffectedTest:
    test_function: str
    test_file: str
    chain: list[str]
    depth: int
    confidence: str  # "HIGH" / "MEDIUM" / "LOW"
    score: float = 0.0  # weighted score in [0.0, 1.0]
    explanation: str = ""  # human-readable breakdown
    reason: str = ""
    resolution_explanation: str = ""


def _is_test(node: str) -> bool:
    """Classify if a node represents a test file or a test function.

    A node is a test if the filename starts with 'test_', the function name
    starts with 'test_', or any dot-separated component starts with 'test_'.
    """
    if "dyn:" in node or "dynamic:" in node:
        return False

    if ":" in node:
        filepath, funcname = node.rsplit(":", 1)
        is_test_file = Path(filepath).name.startswith("test_") if filepath else False
        is_test_func = funcname.startswith("test_")
        return is_test_file or is_test_func

    parts = node.split(".")
    return any(p.startswith("test_") for p in parts)


# ---------------------------------------------------------------------------
# Weighted confidence scoring
# ---------------------------------------------------------------------------


@dataclass
class _PathState:
    """Accumulated factors along one BFS traversal path."""

    has_dynamic: bool = False
    """True if any node in the path is a dynamic_call node."""

    min_certainty: float = 1.0
    """Minimum CALLS-edge certainty seen along this path (deprecated)."""

    max_fan_out: int = 1
    """Maximum number of CALLS targets any node in the path had."""

    has_decorated_hop: bool = False
    """True if any function node in the path carries decorators."""

    min_edge_certainty: float = 1.0
    """Minimum edge resolution certainty seen along this path."""

    has_inheritance: bool = False
    """True if any edge in the path resolved via class hierarchy / MRO."""

    has_ambiguity: bool = False
    """True if any edge in the path resolved via fallback name matching."""

    import_certainties: list[float] = field(default_factory=list)
    """Import mapping certainties collected along the path."""

    symbol_certainties: list[float] = field(default_factory=list)
    """Symbol resolution certainties (lexical, local, types) collected along the path."""


def _compute_weighted_confidence(
    depth: int,
    state: _PathState,
    node: str,
    reverse_graph: nx.MultiDiGraph,
) -> tuple[float, str, str, str, str]:
    """Compute a multi-factor weighted confidence score.

    Returns
    -------
    score:
        Float in [0.0, 1.0].
    label:
        "HIGH", "MEDIUM", or "LOW".
    explanation:
        Comma-separated legacy explanation.
    reason:
        Brief summary of confidence factors.
    resolution_explanation:
        Detailed breakdown of MRO, imports, dynamic dispatches, etc.
    """
    score = 1.0
    reasons = []
    explanations = []

    # 1. Graph Depth
    if depth == 1:
        reasons.append("direct invocation")
        explanations.append("The target is directly invoked by the test.")
    else:
        depth_factor = 0.90 ** (depth - 1)
        score *= depth_factor
        reasons.append(f"{depth}-hop depth")
        explanations.append(
            f"Traversed a transitive path of {depth} hops (depth penalty: ×{depth_factor:.2f})."
        )

    # 2. Dynamic Dispatch
    if state.has_dynamic:
        score *= 0.40
        reasons.append("dynamic dispatch")
        explanations.append(
            "Traversed one or more dynamic call sites (getattr, eval, partial, exec, or runtime dispatch)."
        )

    # 3. Inheritance / Mixins
    if state.has_inheritance:
        score *= 0.95
        reasons.append("class inheritance")
        explanations.append("Resolved method call via class hierarchy MRO traversal.")

    # 4. Import Certainty
    if state.import_certainties:
        avg_import = sum(state.import_certainties) / len(state.import_certainties)
        if avg_import < 1.0:
            score *= avg_import
            reasons.append("import uncertainty")
            explanations.append(
                f"Traversed import statements with lower certainty (average: {avg_import:.2f})."
            )

    # 5. Symbol Certainty
    if state.symbol_certainties:
        avg_symbol = sum(state.symbol_certainties) / len(state.symbol_certainties)
        score *= avg_symbol
        if avg_symbol < 0.90:
            reasons.append("weak symbol resolution")
            explanations.append(
                f"Traversed symbols resolved via local annotations or inferences (average: {avg_symbol:.2f})."
            )

    # 6. Ambiguity
    if state.has_ambiguity:
        score *= 0.60
        reasons.append("ambiguous resolution")
        explanations.append(
            "Encountered name-based resolution fallback due to multiple matching symbols in the codebase."
        )

    # 7. Edge Certainty
    if state.min_edge_certainty < 1.0:
        score *= state.min_edge_certainty
        cert_pct = int(state.min_edge_certainty * 100)
        reasons.append(f"edge certainty {cert_pct}%")
        explanations.append(
            f"Traversed at least one edge with low resolution certainty ({cert_pct}%)."
        )

    # 8. Decorator wrapping
    if state.has_decorated_hop:
        score *= 0.90
        reasons.append("decorated hop")
        explanations.append("Traversed decorated function wrappers in the call path.")

    # 9. Fan-out
    if state.max_fan_out >= 10:
        score *= 0.65
        reasons.append(f"very high fan-out ({state.max_fan_out})")
        explanations.append(
            f"Encountered very high branch ambiguity with {state.max_fan_out} call targets."
        )
    elif state.max_fan_out >= 6:
        score *= 0.80
        reasons.append(f"high fan-out ({state.max_fan_out})")
        explanations.append(
            f"Encountered high branch ambiguity with {state.max_fan_out} call targets."
        )
    elif state.max_fan_out >= 3:
        score *= 0.90
        reasons.append(f"moderate fan-out ({state.max_fan_out})")
        explanations.append(
            f"Encountered moderate branch ambiguity with {state.max_fan_out} call targets."
        )

    # Clamp score
    score = max(0.0, min(1.0, round(score, 4)))

    # Map to label
    if score >= 0.85:
        label = "HIGH"
    elif score >= 0.55:
        label = "MEDIUM"
    else:
        label = "LOW"

    reason_str = ", ".join(reasons) if reasons else "direct call"
    explanation_str = " ".join(explanations)
    return score, label, reason_str, reason_str, explanation_str


# ---------------------------------------------------------------------------
# Blast radius BFS
# ---------------------------------------------------------------------------


def compute_blast_radius(
    reverse_graph: nx.DiGraph,
    target: str | SymbolID,
    max_depth: int = 10,
    root_dir: str | None = None,
) -> list[AffectedTest]:
    import time

    from blastradius.diagnostics import tracker

    start_time = time.perf_counter()

    from blastradius.symbol import SymbolID

    if isinstance(target, str):
        target = SymbolID(target)

    if target not in reverse_graph:
        tracker.query_time = time.perf_counter() - start_time
        tracker.log_structured("blast_radius_queried")
        return []

    if root_dir is None:
        target_data = reverse_graph.nodes.get(target, {})
        target_path = target_data.get("filepath", "")
        if target_path:
            root_dir = str(Path(target_path).parent)
        else:
            root_dir = "."

    config = DiscoveryConfig(root_dir)
    engine = DiscoveryEngine(config)

    affected: list[AffectedTest] = []
    visited: set[str] = set()

    # Queue entries: (node, chain, depth, path_state)
    queue: deque[tuple[str, list[str], int, _PathState]] = deque()
    queue.append((target, [target], 0, _PathState()))

    while queue:
        node, chain, depth, state = queue.popleft()

        if node in visited:
            continue
        visited.add(node)

        if depth > max_depth:
            continue

        # ── Update path state with current node's properties ──────────
        node_data = reverse_graph.nodes[node] if node in reverse_graph.nodes else {}

        new_has_dynamic = state.has_dynamic
        if node_data.get("kind") == "dynamic_call":
            new_has_dynamic = True

        new_has_decorated = state.has_decorated_hop
        if node_data.get("decorators"):
            new_has_decorated = True

        # Fan-out: how many distinct CALLS targets does this node have?
        calls_in = sum(
            1
            for _, _, d in reverse_graph.in_edges(node, data=True)
            if d.get("relation") == "CALLS" or d.get("relation") is None
        )
        new_max_fan_out = max(state.max_fan_out, calls_in)

        current_state = _PathState(
            has_dynamic=new_has_dynamic,
            min_certainty=state.min_certainty,
            max_fan_out=new_max_fan_out,
            has_decorated_hop=new_has_decorated,
            min_edge_certainty=state.min_edge_certainty,
            has_inheritance=state.has_inheritance,
            has_ambiguity=state.has_ambiguity,
            import_certainties=state.import_certainties.copy(),
            symbol_certainties=state.symbol_certainties.copy(),
        )

        # ── Test hit ─────────────────────────────────────────────────
        if engine.is_test_node(node, node_data) and node != target:
            if ":" in node:
                filepath, _ = node.rsplit(":", 1)
            else:
                nd = reverse_graph.nodes[node]
                filepath = nd.get("filepath", "") if nd else ""

            score, label, explanation, reason, res_explanation = _compute_weighted_confidence(
                depth=depth,
                state=current_state,
                node=node,
                reverse_graph=reverse_graph,
            )

            affected.append(
                AffectedTest(
                    test_function=node,
                    test_file=filepath,
                    chain=chain,
                    depth=depth,
                    confidence=label,
                    score=score,
                    explanation=explanation,
                    reason=reason,
                    resolution_explanation=res_explanation,
                )
            )
            # Do not traverse past test functions
            continue

        # ── Enqueue successors (callers in the original graph) ────────
        for successor in reverse_graph.successors(node):
            if successor in visited:
                continue

            is_call = False
            edge_certainty = 1.0
            edge_is_inheritance = False

            if reverse_graph.is_multigraph():
                edges_attrs = list(reverse_graph[node][successor].values())
                if all(d.get("relation") is None for d in edges_attrs):
                    is_call = True
                    edge_certainty = min(
                        (d.get("certainty", 1.0) for d in edges_attrs), default=1.0
                    )
                    edge_is_inheritance = any(d.get("inheritance") for d in edges_attrs)
                else:
                    for d in edges_attrs:
                        if d.get("relation") == "CALLS":
                            is_call = True
                            edge_certainty = min(edge_certainty, d.get("certainty", 1.0))
                            if d.get("inheritance"):
                                edge_is_inheritance = True
            else:
                rel = reverse_graph[node][successor].get("relation")
                is_call = (rel == "CALLS") or (rel is None)
                edge_certainty = reverse_graph[node][successor].get("certainty", 1.0)
                edge_is_inheritance = reverse_graph[node][successor].get("inheritance", False)

            if is_call:
                new_import_certs = state.import_certainties.copy()
                new_symbol_certs = state.symbol_certainties.copy()
                if edge_certainty == 1.0:
                    new_import_certs.append(1.0)
                elif edge_certainty in (0.98, 0.95, 0.90, 0.85):
                    new_symbol_certs.append(edge_certainty)

                new_state = _PathState(
                    has_dynamic=new_has_dynamic,
                    min_certainty=min(state.min_certainty, edge_certainty),
                    max_fan_out=new_max_fan_out,
                    has_decorated_hop=new_has_decorated,
                    min_edge_certainty=min(state.min_edge_certainty, edge_certainty),
                    has_inheritance=state.has_inheritance or edge_is_inheritance,
                    has_ambiguity=state.has_ambiguity or (edge_certainty == 0.60),
                    import_certainties=new_import_certs,
                    symbol_certainties=new_symbol_certs,
                )
                queue.append((successor, chain + [successor], depth + 1, new_state))

    tracker.query_time = time.perf_counter() - start_time
    tracker.log_structured("blast_radius_queried")
    return affected
