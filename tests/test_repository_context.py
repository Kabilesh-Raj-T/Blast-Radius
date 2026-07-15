from pathlib import Path

from blastradius.core.context import RepositoryContext


def _create_file(tmp_path: Path, rel_path: str, content: str) -> Path:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_src_layout_detection(tmp_path):
    """Verify that a repository with a src/ folder is correctly resolved as a src layout import root."""
    _create_file(tmp_path, "src/mypkg/__init__.py", "")
    _create_file(tmp_path, "src/mypkg/utils.py", "def helper(): pass")

    ctx = RepositoryContext(str(tmp_path))

    # Verify that src/ is resolved as an import root
    src_dir = (tmp_path / "src").resolve()
    assert src_dir in ctx.import_roots

    # Verify that FQN is resolved without 'src.' prefix
    mod_name = ctx.filepath_to_module(str(tmp_path / "src/mypkg/utils.py"))
    assert mod_name == "mypkg.utils"


def test_poetry_pyproject_layout_detection(tmp_path):
    """Verify custom Poetry package from paths in pyproject.toml are detected as import roots."""
    pyproject_content = """
[tool.poetry]
name = "custom-app"
version = "0.1.0"
packages = [
    { include = "app", from = "backend" }
]
"""
    _create_file(tmp_path, "pyproject.toml", pyproject_content)
    _create_file(tmp_path, "backend/app/__init__.py", "")
    _create_file(tmp_path, "backend/app/main.py", "def run(): pass")

    ctx = RepositoryContext(str(tmp_path))

    backend_dir = (tmp_path / "backend").resolve()
    assert backend_dir in ctx.import_roots

    mod_name = ctx.filepath_to_module(str(tmp_path / "backend/app/main.py"))
    assert mod_name == "app.main"


def test_setuptools_pyproject_layout_detection(tmp_path):
    """Verify custom Setuptools packages find paths in pyproject.toml are detected as import roots."""
    pyproject_content = """
[tool.setuptools.packages.find]
where = ["lib"]
"""
    _create_file(tmp_path, "pyproject.toml", pyproject_content)
    _create_file(tmp_path, "lib/mypkg/__init__.py", "")
    _create_file(tmp_path, "lib/mypkg/core.py", "def execute(): pass")

    ctx = RepositoryContext(str(tmp_path))

    lib_dir = (tmp_path / "lib").resolve()
    assert lib_dir in ctx.import_roots

    mod_name = ctx.filepath_to_module(str(tmp_path / "lib/mypkg/core.py"))
    assert mod_name == "mypkg.core"


def test_multiple_source_roots(tmp_path):
    """Verify that multiple standard layouts (e.g. src/ and backend/) are resolved correctly."""
    _create_file(tmp_path, "src/mypkg/__init__.py", "")
    _create_file(tmp_path, "backend/server/__init__.py", "")

    ctx = RepositoryContext(str(tmp_path))

    src_dir = (tmp_path / "src").resolve()
    backend_dir = (tmp_path / "backend").resolve()

    assert src_dir in ctx.import_roots
    assert backend_dir in ctx.import_roots

    assert ctx.filepath_to_module(str(tmp_path / "src/mypkg/core.py")) == "mypkg.core"
    assert ctx.filepath_to_module(str(tmp_path / "backend/server/main.py")) == "server.main"
