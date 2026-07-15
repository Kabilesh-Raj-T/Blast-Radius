"""Blast radius calculation and analysis module."""

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from blastradius.analysis.discovery import DiscoveryConfig, DiscoveryEngine
from blastradius.core.symbol import SymbolID


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

    def __lt__(self, other: "_PathState") -> bool:
        return False


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

    if depth == 1:
        path_summary = f"Direct invocation from the test node (factors: {reason_str})."
    else:
        path_summary = f"Transitive path of depth {depth} (factors: {reason_str})."

    return score, label, path_summary, reason_str, explanation_str


# ---------------------------------------------------------------------------
# Blast radius BFS
# ---------------------------------------------------------------------------


def _get_node_properties(node: str, reverse_graph: nx.DiGraph) -> tuple[bool, bool, int]:
    node_data = reverse_graph.nodes[node] if node in reverse_graph.nodes else {}
    has_dynamic = node_data.get("kind") == "dynamic_call"
    has_decorated = bool(node_data.get("decorators"))
    calls_in = sum(
        1
        for _, _, d in reverse_graph.in_edges(node, data=True)
        if d.get("relation") == "CALLS" or d.get("relation") is None
    )
    return has_dynamic, has_decorated, calls_in


def compute_blast_radius(
    reverse_graph: nx.DiGraph,
    target: str | SymbolID,
    max_depth: int = 10,
    root_dir: str | None = None,
) -> list[AffectedTest]:
    import time

    from blastradius.core.diagnostics import tracker

    start_time = time.perf_counter()

    from blastradius.core.symbol import SymbolID

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

    import heapq

    visited: set[str] = set()
    best_score: dict[str, float] = {}

    # Initialize path state for target
    t_dynamic, t_decorated, t_fan_out = _get_node_properties(target, reverse_graph)
    initial_state = _PathState(
        has_dynamic=t_dynamic,
        min_certainty=1.0,
        max_fan_out=t_fan_out,
        has_decorated_hop=t_decorated,
        min_edge_certainty=1.0,
        has_inheritance=False,
        has_ambiguity=False,
        import_certainties=[],
        symbol_certainties=[],
    )

    best_score[target] = 1.0

    # Heap entries: (neg_score, depth, node, chain, state)
    heap: list[tuple[float, int, str, tuple[str, ...], _PathState]] = []
    heapq.heappush(heap, (-1.0, 0, target, (target,), initial_state))

    affected_map: dict[str, AffectedTest] = {}

    while heap:
        neg_score, depth, node, chain_tuple, state = heapq.heappop(heap)
        chain = list(chain_tuple)
        score = -neg_score

        if node in visited:
            continue
        visited.add(node)

        if depth > max_depth:
            continue

        node_data = reverse_graph.nodes[node] if node in reverse_graph.nodes else {}

        # ── Test hit ─────────────────────────────────────────────────
        if engine.is_test_node(node, node_data) and node != target:
            if node not in affected_map:
                if ":" in node:
                    filepath, _ = node.rsplit(":", 1)
                else:
                    nd = reverse_graph.nodes[node]
                    filepath = nd.get("filepath", "") if nd else ""

                # Compute the final values for this test hit
                score, label, explanation, reason, res_explanation = _compute_weighted_confidence(
                    depth=depth,
                    state=state,
                    node=node,
                    reverse_graph=reverse_graph,
                )

                affected_map[node] = AffectedTest(
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

                s_dynamic, s_decorated, s_fan_out = _get_node_properties(successor, reverse_graph)

                new_state = _PathState(
                    has_dynamic=state.has_dynamic or s_dynamic,
                    min_certainty=min(state.min_certainty, edge_certainty),
                    max_fan_out=max(state.max_fan_out, s_fan_out),
                    has_decorated_hop=state.has_decorated_hop or s_decorated,
                    min_edge_certainty=min(state.min_edge_certainty, edge_certainty),
                    has_inheritance=state.has_inheritance or edge_is_inheritance,
                    has_ambiguity=state.has_ambiguity or (edge_certainty == 0.60),
                    import_certainties=new_import_certs,
                    symbol_certainties=new_symbol_certs,
                )

                # Compute the potential score of the path ending at successor
                suc_score, _, _, _, _ = _compute_weighted_confidence(
                    depth=depth + 1,
                    state=new_state,
                    node=successor,
                    reverse_graph=reverse_graph,
                )

                if suc_score >= best_score.get(successor, 0.0):
                    best_score[successor] = suc_score
                    heapq.heappush(
                        heap,
                        (-suc_score, depth + 1, successor, chain_tuple + (successor,), new_state),
                    )

    tracker.query_time = time.perf_counter() - start_time
    tracker.log_structured("blast_radius_queried")
    return sorted(affected_map.values(), key=lambda x: (-x.score, x.test_function))
