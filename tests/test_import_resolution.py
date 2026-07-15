"""Unit and integration tests for robust import resolution."""

from pathlib import Path

from blastradius.graph import build_graph
from blastradius.indexer import index_repo


def _create_file(base_dir: Path, rel_path: str, content: str) -> Path:
    p = base_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_transitive_and_alias_imports(tmp_path):
    """Test standard absolute imports, aliases, and transitive chains.

    A -> B (alias) -> C (defines helper)
    """
    _create_file(tmp_path, "pkg_c.py", "def helper(): pass\n")

    _create_file(
        tmp_path,
        "pkg_b.py",
        """
from pkg_c import helper as custom_helper
""",
    )

    _create_file(
        tmp_path,
        "pkg_a.py",
        """
from pkg_b import custom_helper
def run():
    custom_helper()
""",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    # Assert pkg_a.run calls target definition pkg_c.helper directly
    assert G.has_edge("pkg_a.run", "pkg_c.helper")
    edge = G["pkg_a.run"]["pkg_c.helper"][0]
    assert edge["certainty"] == 1.00  # resolved via transitive imports


def test_package_and_relative_imports(tmp_path):
    """Test relative imports and package __init__.py exposure.

    caller -> my_pkg -> my_pkg/sub.py
    """
    # package init imports relative
    _create_file(
        tmp_path,
        "my_pkg/__init__.py",
        """
from .sub import core_func
""",
    )

    _create_file(
        tmp_path,
        "my_pkg/sub.py",
        """
def core_func(): pass
""",
    )

    _create_file(
        tmp_path,
        "caller.py",
        """
import my_pkg
def execute():
    my_pkg.core_func()
""",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    # Assert caller.execute calls my_pkg.sub.core_func directly
    assert G.has_edge("caller.execute", "my_pkg.sub.core_func")


def test_wildcard_imports(tmp_path):
    """Test from module import * including transitively exposed wildcards."""
    _create_file(
        tmp_path,
        "source.py",
        """
def public_one(): pass
def public_two(): pass
def _private_one(): pass
""",
    )

    _create_file(
        tmp_path,
        "middle.py",
        """
from source import *
""",
    )

    _create_file(
        tmp_path,
        "client.py",
        """
from middle import *
def test_all():
    public_one()
    public_two()
""",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    # Assert client.test_all calls source.public_one and source.public_two
    assert G.has_edge("client.test_all", "source.public_one")
    assert G.has_edge("client.test_all", "source.public_two")
    # Assert private was not imported by wildcard
    assert not G.has_node("client.test_all:dyn:getattr:4:0")  # or no edge to private
    assert not G.has_edge("client.test_all", "source._private_one")


def test_parent_relative_imports(tmp_path):
    """Test multi-level relative imports (..parent)."""
    _create_file(tmp_path, "parent_func.py", "def root_helper(): pass\n")

    _create_file(tmp_path, "sub_pkg/__init__.py", "")

    _create_file(
        tmp_path,
        "sub_pkg/leaf.py",
        """
from ..parent_func import root_helper
def run_leaf():
    root_helper()
""",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    assert G.has_edge("sub_pkg.leaf.run_leaf", "parent_func.root_helper")


def test_cyclic_imports_termination(tmp_path):
    """Ensure cyclic imports do not cause infinite recursion and terminate correctly."""
    _create_file(
        tmp_path,
        "cycle_a.py",
        """
from cycle_b import func_b
def func_a():
    func_b()
""",
    )

    _create_file(
        tmp_path,
        "cycle_b.py",
        """
from cycle_a import func_a
def func_b():
    func_a()
""",
    )

    index = index_repo(str(tmp_path))

    # Build graph should terminate and not raise RecursionError
    G = build_graph(index)
    assert G.has_edge("cycle_a.func_a", "cycle_b.func_b")
    assert G.has_edge("cycle_b.func_b", "cycle_a.func_a")


def test_src_layout_import_resolution_uses_canonical_modules(tmp_path):
    """Calls through a src-layout package resolve without a synthetic src prefix."""
    _create_file(tmp_path, "src/acme/__init__.py", "from .core import run_core\n")
    _create_file(tmp_path, "src/acme/core.py", "def run_core(): pass\n")
    _create_file(tmp_path, "app.py", "import acme\ndef main():\n    acme.run_core()\n")

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    assert index["modules"]["src/acme/core.py"]["module"] == "acme.core"
    assert G.has_edge("app.main", "acme.core.run_core")


def test_namespace_package_import_resolution(tmp_path):
    """PEP 420-style packages without __init__.py still get canonical module names."""
    _create_file(tmp_path, "src/ns_pkg/feature/tools.py", "def tool(): pass\n")
    _create_file(
        tmp_path,
        "consumer.py",
        "import ns_pkg.feature.tools as tools\ndef use():\n    tools.tool()\n",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    assert index["modules"]["src/ns_pkg/feature/tools.py"]["is_namespace"] is True
    assert G.has_edge("consumer.use", "ns_pkg.feature.tools.tool")


def test_star_import_respects_literal_all(tmp_path):
    """Wildcard imports use __all__ when it is statically known."""
    _create_file(
        tmp_path,
        "exports.py",
        "__all__ = ['public_one']\ndef public_one(): pass\ndef public_two(): pass\n",
    )
    _create_file(
        tmp_path,
        "client.py",
        "from exports import *\ndef run():\n    public_one()\n    public_two()\n",
    )

    index = index_repo(str(tmp_path))
    G = build_graph(index)

    assert G.has_edge("client.run", "exports.public_one")
    assert not G.has_edge("client.run", "exports.public_two")


def test_pythonpath_import_root_detection(tmp_path, monkeypatch):
    """Repository-local PYTHONPATH entries participate in module naming."""
    _create_file(tmp_path, "custom_root/pkg/mod.py", "def helper(): pass\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "custom_root"))

    from blastradius.context import RepositoryContext

    ctx = RepositoryContext(str(tmp_path))
    assert ctx.filepath_to_module(str(tmp_path / "custom_root/pkg/mod.py")) == "pkg.mod"


def test_editable_install_root_detection(tmp_path):
    """Repository-local .pth metadata can declare an import root."""
    _create_file(tmp_path, "site-packages/project.pth", "../editable_src\n")
    _create_file(tmp_path, "editable_src/editpkg/mod.py", "def helper(): pass\n")

    from blastradius.context import RepositoryContext

    ctx = RepositoryContext(str(tmp_path))
    assert ctx.filepath_to_module(str(tmp_path / "editable_src/editpkg/mod.py")) == "editpkg.mod"
