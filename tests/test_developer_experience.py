"""Unit tests for developer experience formatting (terminal, JSON, Markdown, MCP outputs)."""

import json

import pytest
from blastradius.blast import AffectedTest
from blastradius.formatters import format_json, format_markdown, format_mcp, format_terminal


@pytest.fixture
def sample_results():
    return [
        AffectedTest(
            test_function="tests.test_invoice.test_generate_invoice",
            test_file="tests/test_invoice.py",
            chain=[
                "utils.parser.parse_date",
                "billing.invoice.generate_invoice",
                "tests.test_invoice.test_generate_invoice",
            ],
            depth=3,
            confidence="HIGH",
            score=0.81,
            explanation="Explicit import",
            reason="Explicit import",
            resolution_explanation="Resolved via explicit imports mapping.",
        )
    ]


def test_terminal_formatter(sample_results):
    """Verify terminal formatting runs without exceptions."""
    format_terminal(sample_results, "utils.parser.parse_date")


def test_json_formatter(sample_results):
    """Verify JSON output structure and keys."""
    json_str = format_json(sample_results)
    data = json.loads(json_str)

    assert len(data) == 1
    hit = data[0]
    assert hit["test_function"] == "tests.test_invoice.test_generate_invoice"
    assert hit["test_file"] == "tests/test_invoice.py"
    assert hit["reason"] == "Explicit import"
    assert hit["confidence"] == "HIGH"
    assert hit["score"] == 0.81
    assert hit["call_chain"] == ["parse_date()", "generate_invoice()", "test_generate_invoice()"]
    assert hit["explanation"] == "Resolved via explicit imports mapping."


def test_markdown_formatter(sample_results):
    """Verify Markdown formatting contains the required call chain representation."""
    md_str = format_markdown(sample_results, "utils.parser.parse_date")

    assert "# Blast Radius Analysis for `utils.parser.parse_date`" in md_str
    assert "test_invoice.py::test_generate_invoice" in md_str
    assert "Explicit import" in md_str
    assert "HIGH" in md_str
    # Verify arrow-based visual call chain
    assert "parse_date()" in md_str
    assert "generate_invoice()" in md_str
    assert "test_generate_invoice()" in md_str


def test_mcp_formatter(sample_results):
    """Verify MCP output payload format."""
    mcp_dict = format_mcp(sample_results, "utils.parser.parse_date")

    assert "content" in mcp_dict
    assert len(mcp_dict["content"]) == 1
    content = mcp_dict["content"][0]
    assert content["type"] == "text"
    assert "Blast Radius Analysis" in content["text"]
