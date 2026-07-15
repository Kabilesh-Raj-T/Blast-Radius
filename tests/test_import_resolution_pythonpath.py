import os

from blastradius.context import RepositoryContext


def test_pythonpath_layout_detection(tmp_path):
    """Verify PYTHONPATH directories are detected as import roots."""
    external_dir = tmp_path / "external_source"
    external_dir.mkdir()

    # Create a package in the external source folder
    pkg_dir = external_dir / "extpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "helper.py").write_text("def run(): pass", encoding="utf-8")

    # Set PYTHONPATH
    old_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(external_dir.resolve())

    try:
        ctx = RepositoryContext(str(tmp_path))

        # Verify PYTHONPATH directory was registered as an import root
        assert external_dir.resolve() in ctx.import_roots

        # Verify path translation
        fqn = ctx.filepath_to_module(str(pkg_dir / "helper.py"))
        assert fqn == "extpkg.helper"
    finally:
        # Restore old PYTHONPATH
        if old_pythonpath is not None:
            os.environ["PYTHONPATH"] = old_pythonpath
        else:
            os.environ.pop("PYTHONPATH", None)
