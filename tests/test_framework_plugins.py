"""Unit and integration tests for framework plugin/adapter system."""

from __future__ import annotations

from pathlib import Path

import pytest
from blastradius import engine
from blastradius.cli import app
from blastradius.plugins import load_plugin
from blastradius.plugins.django import DjangoPlugin
from blastradius.plugins.flask import FlaskPlugin
from blastradius.plugins.requests import RequestsPlugin
from typer.testing import CliRunner


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def mock_repo(tmp_path):
    repo_path = tmp_path / "mock_repo"
    _create_file(
        repo_path,
        "app.py",
        """
def calc(a, b):
    return a + b

def test_calc():
    assert calc(2, 3) == 5
""",
    )
    # create directories to check excludes
    _create_file(repo_path, "docs/index.rst", "content")
    _create_file(repo_path, "tests/test_dummy.py", "content")
    return repo_path


def test_plugin_loading():
    """Verify plugins are loaded by name or throw ValueError."""
    django = load_plugin("django")
    assert isinstance(django, DjangoPlugin)
    assert django.name == "django"

    flask = load_plugin("flask")
    assert isinstance(flask, FlaskPlugin)
    assert flask.name == "flask"

    requests = load_plugin("requests")
    assert isinstance(requests, RequestsPlugin)
    assert requests.name == "requests"

    assert load_plugin(None) is None

    with pytest.raises(ValueError, match="Unknown framework plugin"):
        load_plugin("invalid_framework")


def test_django_plugin_behavior():
    """Verify Django plugin adds its paths to the exclude list."""
    plugin = DjangoPlugin()
    excludes = ["venv"]
    res = plugin.pre_index(excludes)
    assert "docs" in res
    assert "build" in res
    assert "dist" in res


def test_flask_plugin_behavior():
    """Verify Flask plugin adds its paths to the exclude list."""
    plugin = FlaskPlugin()
    excludes = ["venv"]
    res = plugin.pre_index(excludes)
    assert "tests" in res
    assert "docs" in res
    assert "examples" in res


def test_requests_plugin_behavior():
    """Verify Requests plugin adds its paths to the exclude list."""
    plugin = RequestsPlugin()
    excludes = ["venv"]
    res = plugin.pre_index(excludes)
    assert "tests" in res
    assert "docs" in res
    assert "build" in res
    assert "dist" in res


def test_engine_integration_with_plugins(mock_repo):
    """Verify that engine operations accept the framework parameter and utilize the plugins."""
    # Test index_repository with plugin
    res = engine.index_repository(str(mock_repo), framework="django")
    assert res["status"] == "success"

    # Test blast_radius with plugin
    res_br = engine.blast_radius(str(mock_repo), "app.calc", framework="flask")
    assert isinstance(res_br, list)


def test_cli_integration_with_plugins(mock_repo):
    """Verify that the CLI analyze command supports the --framework option."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "app.calc",
            "-r",
            str(mock_repo),
            "--framework",
            "django",
        ],
    )
    assert result.exit_code == 0
