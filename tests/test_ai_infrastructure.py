"""Unit and integration tests for Engine API, token-efficient JSON outputs, git diff mapping, and stdio MCP server."""

import json
import sys
from io import StringIO
from pathlib import Path

import pytest
from blastradius import engine
from blastradius.mcp_server import main as mcp_main


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def sample_repo(tmp_path):
    repo_path = tmp_path / "repo"
    _create_file(
        repo_path,
        "calc.py",
        """
class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
""",
    )
    _create_file(
        repo_path,
        "test_calc.py",
        """
from calc import Calculator

def test_add():
    c = Calculator()
    c.add(2, 3)

def test_subtract():
    c = Calculator()
    c.subtract(5, 2)
""",
    )
    return repo_path


def test_engine_index_repository(sample_repo):
    """Verify index_repository returns token-efficient summary data."""
    res = engine.index_repository(str(sample_repo))
    assert res["status"] == "success"
    assert res["symbols_count"] > 0
    assert res["imports_count"] > 0


def test_engine_blast_radius(sample_repo):
    """Verify blast_radius returns compact, token-efficient keys."""
    res = engine.blast_radius(str(sample_repo), "calc.Calculator.add")
    assert len(res) == 1
    hit = res[0]

    # Assert compact token-efficient keys are present
    assert "func" in hit
    assert "file" in hit
    assert "reason" in hit
    assert "conf" in hit
    assert "score" in hit
    assert "chain" in hit
    assert "exp" in hit

    assert hit["func"] == "test_calc.test_add"
    assert hit["chain"] == ["add()", "test_add()"]


def test_engine_analyze_diff(sample_repo):
    """Verify analyze_diff parses diffs and maps affected tests."""
    diff_content = """
diff --git a/calc.py b/calc.py
index e69de29..1234567 100644
--- a/calc.py
+++ b/calc.py
@@ -3,3 +3,3 @@ class Calculator:
     def add(self, a, b):
-        return a + b
+        return a + b + 0
"""
    res = engine.analyze_diff(str(sample_repo), diff_content)
    assert "changed_symbols" in res
    assert "calc.Calculator.add" in res["changed_symbols"]

    assert "affected_tests" in res
    assert len(res["affected_tests"]) == 1
    assert res["affected_tests"][0]["func"] == "test_calc.test_add"


def test_engine_explain_test(sample_repo):
    """Verify explain_test lists test FQN, file, and direct dependencies."""
    res = engine.explain_test(str(sample_repo), "test_calc.test_add")
    assert "test" in res
    assert "file" in res
    assert "depends_on" in res
    assert res["test"] == "test_calc.test_add"

    deps = res["depends_on"]
    assert len(deps) == 2
    assert any(d["target"] == "calc.Calculator" for d in deps)
    assert any(d["target"] == "calc.Calculator.add" for d in deps)


def test_engine_health():
    """Verify health returns server information."""
    res = engine.health()
    assert res["status"] == "healthy"
    assert "python_version" in res
    assert "networkx_version" in res


def test_mcp_stdio_transport(sample_repo):
    """Verify stdio MCP JSON-RPC protocol initialize and list tools handler."""
    # Simulate MCP stdin input
    mcp_input = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'

    # Capture stdout
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    sys.stdin = StringIO(mcp_input)
    sys.stdout = StringIO()

    try:
        mcp_main()
        output = sys.stdout.getvalue()
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    res = json.loads(output)
    assert res["jsonrpc"] == "2.0"
    assert res["id"] == 1

    tools = res["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "index_repository" in tool_names
    assert "blast_radius" in tool_names
    assert "analyze_diff" in tool_names
    assert "explain_test" in tool_names
    assert "health" in tool_names
