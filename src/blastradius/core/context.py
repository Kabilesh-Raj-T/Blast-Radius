from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class RepositoryContext:
    """Discovers repository root, Python source/import roots, test roots, and ignored folders."""

    def __init__(self, repo_path: str):
        self.repo_root = Path(repo_path).resolve()
        self.ignored_dirs = {
            "__pycache__",
            "venv",
            ".venv",
            ".git",
            ".blastradius",
            "node_modules",
            "build",
            "dist",
        }
        self.import_roots: list[Path] = []
        self.test_roots: list[Path] = []
        self._module_metadata_cache: dict[str, dict[str, Any]] = {}
        self._filepath_to_module_cache: dict[str, str] = {}
        self.discover_layout()

    def discover_layout(self) -> None:
        import_set = {self.repo_root}
        pythonpath = os.environ.get("PYTHONPATH")
        if pythonpath:
            for path_str in pythonpath.split(os.pathsep):
                if path_str:
                    import_set.add(Path(path_str).resolve())
        test_set = set()

        # Check pyproject.toml
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib

                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)

                tool = data.get("tool", {})

                # Poetry packages
                poetry = tool.get("poetry", {})
                for pkg in poetry.get("packages", []):
                    pkg_from = pkg.get("from")
                    if pkg_from:
                        import_set.add((self.repo_root / pkg_from).resolve())

                # Setuptools custom packages find
                setuptools = tool.get("setuptools", {})
                packages = setuptools.get("packages", {})
                if isinstance(packages, dict):
                    find_cfg = packages.get("find", {})
                    for src in find_cfg.get("where", []):
                        import_set.add((self.repo_root / src).resolve())
            except Exception:
                pass

        # Respect PYTHONPATH entries that point inside the repository. External
        # entries may be importable at runtime, but they are outside the indexed
        # codebase and should not create local module names.
        for raw_entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
            if not raw_entry:
                continue
            entry = Path(raw_entry).expanduser()
            if not entry.is_absolute():
                entry = self.repo_root / entry
            try:
                resolved = entry.resolve()
                resolved.relative_to(self.repo_root)
            except (OSError, ValueError):
                continue
            if resolved.exists() and resolved.is_dir():
                import_set.add(resolved)

        # Editable installs commonly leave .pth or .egg-link files containing a
        # source root. When those files live in the repository, use any pointed
        # root that also stays inside the repository. Look only in the repo root
        # to avoid scanning the entire project.
        for pattern in ("*.pth", "*.egg-link", "*/*.pth", "*/*.egg-link"):
            for metadata_file in self.repo_root.glob(pattern):
                try:
                    lines = metadata_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for line in lines:
                    candidate_text = line.strip()
                    if not candidate_text or candidate_text.startswith(("import ", "#")):
                        continue
                    candidate = Path(candidate_text).expanduser()
                    if not candidate.is_absolute():
                        candidate = metadata_file.parent / candidate
                    try:
                        resolved = candidate.resolve()
                        resolved.relative_to(self.repo_root)
                    except (OSError, ValueError):
                        continue
                    if resolved.exists() and resolved.is_dir():
                        import_set.add(resolved)

        # Scan for common source layouts: src, lib, packages, backend, frontend, pkg, etc.
        common_layouts = {"src", "lib", "packages", "backend", "frontend", "pkg"}
        if self.repo_root.exists():
            for path in self.repo_root.iterdir():
                if path.is_dir() and path.name in common_layouts:
                    import_set.add(path.resolve())

        # Also find test roots. Check for known test directory names at the repo root.
        # Subdirectories do not need to be enumerated — is_test_file() checks
        # path.parts so any file under tests/orm/... is automatically matched.
        common_test_dirs = {"tests", "test", "t", "spec"}
        for td in common_test_dirs:
            test_dir_path = self.repo_root / td
            if test_dir_path.exists() and test_dir_path.is_dir():
                test_set.add(test_dir_path.resolve())

        # Keep roots sorted by specificity (longest paths first)
        self.import_roots = sorted(list(import_set), key=lambda p: len(p.parts), reverse=True)
        self.test_roots = sorted(list(test_set), key=lambda p: len(p.parts), reverse=True)

    def filepath_to_module(self, filepath: str) -> str:
        if filepath in self._filepath_to_module_cache:
            return self._filepath_to_module_cache[filepath]
        abs_path = Path(filepath).resolve()
        matching_root = self.repo_root
        for root in self.import_roots:
            try:
                abs_path.relative_to(root)
                matching_root = root
                break
            except ValueError:
                continue

        rel_path = abs_path.relative_to(matching_root)
        init_names = (
            "__init__.py",
            "__init__.ts",
            "__init__.js",
            "__init__.go",
            "__init__.java",
        )
        if rel_path.name in init_names:
            parts = rel_path.parent.parts
        else:
            parts = rel_path.with_suffix("").parts

        module_name = ".".join(p for p in parts if p)
        res = module_name if module_name else "root"
        self._filepath_to_module_cache[filepath] = res
        return res

    def package_for_module(self, module_name: str, filepath: str) -> str:
        """Return the containing Python package for a module path."""
        if not module_name or module_name == "root":
            return ""
        if Path(filepath).name == "__init__.py":
            return module_name
        parts = module_name.split(".")
        return ".".join(parts[:-1])

    def module_metadata(self, filepath: str) -> dict[str, str | bool]:
        """Describe a source file's canonical import identity."""
        if filepath in self._module_metadata_cache:
            return self._module_metadata_cache[filepath]
        abs_path = Path(filepath).resolve()
        module_name = self.filepath_to_module(str(abs_path))
        matching_root = self.repo_root
        for root in self.import_roots:
            try:
                abs_path.relative_to(root)
                matching_root = root
                break
            except ValueError:
                continue

        res: dict[str, str | bool] = {
            "module": module_name,
            "package": self.package_for_module(module_name, str(abs_path)),
            "filepath": str(abs_path.relative_to(self.repo_root)).replace("\\", "/"),
            "import_root": str(matching_root),
            "is_package": abs_path.name == "__init__.py",
            "is_namespace": abs_path.name != "__init__.py"
            and not (abs_path.parent / "__init__.py").exists(),
        }
        self._module_metadata_cache[filepath] = res
        return res


_context_cache: dict[str, RepositoryContext] = {}


def get_repository_context(repo_path: str) -> RepositoryContext:
    abs_path = str(Path(repo_path).resolve())
    if abs_path not in _context_cache:
        _context_cache[abs_path] = RepositoryContext(abs_path)
    return _context_cache[abs_path]
