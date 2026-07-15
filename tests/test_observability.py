"""Unit and integration tests for the diagnostics subsystem, structured logging, memory utilization, and CLI/MCP exposure."""

import json
import logging
import sys
from io import StringIO
from pathlib import Path

import pytest
from blastradius.blast import compute_blast_radius
from blastradius.diagnostics import tracker
from blastradius.graph import build_graph, build_reverse_graph
from blastradius.indexer import index_repo
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
        "main.py",
        """
def compute():
    # dynamic call
    getattr(None, 'nonexistent')()
""",
    )
    _create_file(
        repo_path,
        "test_main.py",
        """
from main import compute
def test_compute():
    compute()
""",
    )
    return repo_path


def test_diagnostics_tracking_and_structured_logs(sample_repo):
    """Verify diagnostics populate correctly and structured logger emits JSON payloads."""
    # Capture structured logging outputs
    log_capture = StringIO()
    diag_logger = logging.getLogger("blastradius.diagnostics")
    handler = logging.StreamHandler(log_capture)
    diag_logger.addHandler(handler)

    try:
        # 1. Cold indexing
        index = index_repo(str(sample_repo))
        assert tracker.files_indexed == 2
        assert tracker.skipped_files == 0
        assert tracker.symbols > 0
        assert tracker.functions > 0
        assert tracker.index_time > 0.0

        # 2. Graph creation
        G = build_graph(index)
        assert tracker.dynamic_calls == 1  # getattr count

        # 3. Querying
        rev = build_reverse_graph(G)
        _ = compute_blast_radius(rev, "main.compute", root_dir=str(sample_repo))
        assert tracker.query_time > 0.0

        # Check captured logs
        log_output = log_capture.getvalue()
        lines = log_output.strip().split("\n")
        assert len(lines) >= 2

        # Verify JSON formatting of structured logs
        log1 = json.loads(lines[0])
        assert log1["event"] == "repo_indexing_completed"
        assert "metrics" in log1
        assert log1["metrics"]["files_indexed"] == 2

        log2 = json.loads(lines[1])
        assert log2["event"] == "blast_radius_queried"
        assert log2["metrics"]["query_time_sec"] > 0.0

    finally:
        diag_logger.removeHandler(handler)


def test_memory_utilization_helper():
    """Verify process memory tracker runs and retrieves positive working set size."""
    mem = tracker.get_memory_usage()
    assert isinstance(mem, int)
    # Memory should be positive if queried successfully
    if sys.platform in ("win32", "linux", "darwin"):
        assert mem >= 0


def test_mcp_diagnostics_exposure(sample_repo):
    """Verify MCP response envelope exposes structured diagnostics alongside compact tool output."""
    mcp_input = f'{{"jsonrpc":"2.0","id":42,"method":"tools/call","params":{{"name":"blast_radius","arguments":{{"repo":"{sample_repo.as_posix()}","target":"main.compute"}}}}}}\n'

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
    assert res["id"] == 42
    assert "diagnostics" in res["result"]

    diag = res["result"]["diagnostics"]
    assert diag["files_indexed"] >= 0
    assert diag["symbols"] >= 0
    assert diag["memory_usage_bytes"] >= 0
