"""Unit and integration tests for multi-factor confidence scoring (imports, MRO inheritance, fallback ambiguities, dynamic paths, depths)."""

from pathlib import Path

from blastradius.blast import _compute_weighted_confidence, _PathState, compute_blast_radius
from blastradius.graph import build_graph, build_reverse_graph
from blastradius.indexer import index_repo


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_confidence_scoring_factors():
    """Verify that path state factors affect score, reason, and resolution explanation as expected."""
    # 1. Base case: 1-hop direct call, perfect certainty
    state = _PathState()
    score, label, reason, legacy_exp, detail = _compute_weighted_confidence(1, state, "node", None)
    assert score == 1.0
    assert label == "HIGH"
    assert "direct invocation" in reason
    assert "directly invoked" in detail

    # 2. Transitive depth penalty
    state = _PathState()
    score, label, reason, legacy_exp, detail = _compute_weighted_confidence(3, state, "node", None)
    assert score == 0.81  # 0.90 ** (3 - 1)
    assert label == "MEDIUM"
    assert "3-hop depth" in reason
    assert "depth penalty" in detail

    # 3. Dynamic dispatch
    state = _PathState(has_dynamic=True)
    score, label, reason, legacy_exp, detail = _compute_weighted_confidence(1, state, "node", None)
    assert score == 0.40
    assert label == "LOW"
    assert "dynamic dispatch" in reason

    # 4. Class inheritance
    state = _PathState(has_inheritance=True)
    score, label, reason, legacy_exp, detail = _compute_weighted_confidence(1, state, "node", None)
    assert score == 0.95
    assert label == "HIGH"
    assert "class inheritance" in reason

    # 5. Ambiguity
    state = _PathState(has_ambiguity=True)
    score, label, reason, legacy_exp, detail = _compute_weighted_confidence(1, state, "node", None)
    assert score == 0.60
    assert label == "MEDIUM"
    assert "ambiguous resolution" in reason


def test_integration_confidence_attributes(tmp_path):
    """Test full integration tracing through import, inheritance, and test hit. Verify AffectedTest fields."""
    code_main = """
class Base:
    def common(self):
        pass

class Sub(Base):
    def run(self):
        self.common()
"""
    _create_file(tmp_path, "app.py", code_main)

    code_test = """
from app import Sub
def test_method():
    s = Sub()
    s.run()
"""
    _create_file(tmp_path, "test_app.py", code_test)

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    # Assert inheritance attribute is set on base class edge
    assert G.has_edge("app.Sub.run", "app.Base.common")
    edge_data = G["app.Sub.run"]["app.Base.common"][0]
    assert edge_data.get("inheritance") is True

    rev = build_reverse_graph(G)
    results = compute_blast_radius(rev, "app.Base.common")

    assert len(results) == 1
    hit = results[0]

    assert hit.test_function == "test_app.test_method"
    # Should contain confidence, reason, and resolution_explanation
    assert hit.confidence in ("HIGH", "MEDIUM", "LOW")
    assert hit.reason != ""
    assert hit.resolution_explanation != ""
    assert "class inheritance" in hit.reason
    assert "MRO traversal" in hit.resolution_explanation
