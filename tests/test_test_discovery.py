"""Unit and integration tests for configurable test discovery, framework options, directories, and .blastradius.toml parsing."""

from pathlib import Path

from blastradius.discovery import DiscoveryConfig, DiscoveryEngine


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_discovery_default_config():
    """Verify default config has standard pytest discovery values."""
    config = DiscoveryConfig(root_dir=None)
    assert config.framework == "pytest"
    assert config.directories == ["tests"]
    assert config.patterns == ["test_*.py"]


def test_discovery_config_loading_toml(tmp_path):
    """Verify loading custom configuration options from .blastradius.toml."""
    toml_content = """
[test_discovery]
framework = "unittest"
directories = ["specs", "integration_tests"]
patterns = ["*_spec.py", "*_test.py"]
class_patterns = ["*TestCase", "Test*"]
function_patterns = ["test_*", "it_*"]
"""
    _create_file(tmp_path, ".blastradius.toml", toml_content)

    config = DiscoveryConfig(str(tmp_path))
    assert config.framework == "unittest"
    assert config.directories == ["specs", "integration_tests"]
    assert config.patterns == ["*_spec.py", "*_test.py"]
    assert config.class_patterns == ["*TestCase", "Test*"]
    assert config.function_patterns == ["test_*", "it_*"]


def test_discovery_pytest_rules():
    """Verify test node classification rules in pytest mode."""
    config = DiscoveryConfig()
    config.framework = "pytest"
    config.patterns = ["test_*.py"]
    config.directories = ["tests"]
    config.class_patterns = ["Test*"]
    config.function_patterns = ["test_*"]

    engine = DiscoveryEngine(config)

    # 1. Match pytest function
    node_data_func = {
        "kind": "function",
        "filepath": "tests/test_app.py",
        "function_name": "test_calculate",
        "class_name": None,
    }
    assert engine.is_test_node("tests/test_app.py:test_calculate", node_data_func) is True

    # 2. Match pytest class method
    node_data_method = {
        "kind": "method",
        "filepath": "tests/test_app.py",
        "function_name": "verify_output",
        "class_name": "TestCalculator",
    }
    assert (
        engine.is_test_node("tests/test_app.py:TestCalculator.verify_output", node_data_method)
        is True
    )

    # 3. Not a test file
    node_data_src = {
        "kind": "function",
        "filepath": "src/app.py",
        "function_name": "test_calculate",
        "class_name": None,
    }
    assert engine.is_test_node("src/app.py:test_calculate", node_data_src) is False


def test_discovery_unittest_rules():
    """Verify test node classification rules in unittest mode (test methods must belong to a class)."""
    config = DiscoveryConfig()
    config.framework = "unittest"
    config.patterns = ["test_*.py"]
    config.directories = ["tests"]
    config.class_patterns = ["*TestCase"]
    config.function_patterns = ["test_*"]

    engine = DiscoveryEngine(config)

    # 1. Test method in class -> Test
    node_data_method = {
        "kind": "method",
        "filepath": "tests/test_app.py",
        "function_name": "test_output",
        "class_name": "MyTestCase",
    }
    assert engine.is_test_node("tests/test_app.py:MyTestCase.test_output", node_data_method) is True

    # 2. Bare function starting with test_ -> Not a test in unittest
    node_data_func = {
        "kind": "function",
        "filepath": "tests/test_app.py",
        "function_name": "test_output",
        "class_name": None,
    }
    assert engine.is_test_node("tests/test_app.py:test_output", node_data_func) is False
