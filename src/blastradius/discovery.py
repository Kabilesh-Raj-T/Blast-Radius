import fnmatch
from pathlib import Path
from typing import Any

import tomllib


class DiscoveryConfig:
    """Configurable test discovery options loaded from .blastradius.toml."""

    def __init__(self, root_dir: str | None = None) -> None:
        self.framework = "pytest"
        self.directories = ["tests"]
        self.patterns = ["test_*.py"]
        self.class_patterns = ["Test*"]
        self.function_patterns = ["test_*"]

        if root_dir is None:
            return

        # Auto-discover actual test directories from RepositoryContext
        try:
            from blastradius.context import get_repository_context

            ctx = get_repository_context(root_dir)
            if ctx.test_roots:
                # Extract directory names from discovered test roots
                discovered = [tr.name for tr in ctx.test_roots]
                # Merge with defaults (preserving common names for edge cases)
                merged = list(dict.fromkeys(discovered + ["test", "t", "spec"] + self.directories))
                self.directories = merged
                # Also include typical test file patterns
                self.patterns = list(dict.fromkeys(self.patterns + ["*_test.py"]))
        except Exception:
            pass  # Keep defaults if context is unavailable

        toml_path = Path(root_dir) / ".blastradius.toml"
        if toml_path.exists():
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                disc = data.get("test_discovery", {})
                self.framework = disc.get("framework", self.framework)
                self.directories = disc.get("directories", self.directories)
                self.patterns = disc.get("patterns", self.patterns)
                self.class_patterns = disc.get("class_patterns", self.class_patterns)
                self.function_patterns = disc.get("function_patterns", self.function_patterns)
            except Exception:
                pass  # Fallback to default options if parsing fails


class DiscoveryEngine:
    """Test discovery classification engine using DiscoveryConfig rules."""

    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config

    def is_test_file(self, filepath: str) -> bool:
        if not filepath:
            return False
        path = Path(filepath)
        filename = path.name

        # 1. Match directories
        in_test_dir = False
        if not self.config.directories:
            in_test_dir = True
        elif len(path.parts) == 1:
            in_test_dir = True
        else:
            for td in self.config.directories:
                # Check if td is a component of the file's path (e.g. td/test_app.py or folder/td/test.py)
                if td in path.parts or any(parent.name == td for parent in path.parents):
                    in_test_dir = True
                    break
        if not in_test_dir:
            return False

        # 2. Match filename patterns
        for pat in self.config.patterns:
            if fnmatch.fnmatch(filename, pat):
                return True
        return False

    def is_test_node(self, node: Any, node_data: dict[str, Any]) -> bool:
        node_str = str(node)
        if "dyn:" in node_str or "dynamic:" in node_str:
            return False

        if not node_data:
            # Fallback name-based logic when no graph node metadata exists
            if ":" in node_str:
                filepath, funcname = node_str.rsplit(":", 1)
                is_test_file = self.is_test_file(filepath)
                is_test_func = any(
                    fnmatch.fnmatch(funcname, pat) for pat in self.config.function_patterns
                )
                return is_test_file or is_test_func
            parts = node_str.split(".")
            return any(
                fnmatch.fnmatch(p, pat) for p in parts for pat in self.config.function_patterns
            )

        kind = node_data.get("kind")
        if kind not in ("function", "method"):
            return False

        filepath = node_data.get("filepath", "")
        if not self.is_test_file(filepath):
            return False

        func_name = node_data.get("function_name", "")
        class_name = node_data.get("class_name", "")

        if self.config.framework == "pytest":
            is_func_match = any(
                fnmatch.fnmatch(func_name, pat) for pat in self.config.function_patterns
            )
            is_class_match = class_name and any(
                fnmatch.fnmatch(class_name, pat) for pat in self.config.class_patterns
            )
            return is_func_match or is_class_match

        elif self.config.framework == "unittest":
            is_func_match = any(
                fnmatch.fnmatch(func_name, pat) for pat in self.config.function_patterns
            )
            # In unittest, test methods must live inside classes
            if class_name:
                return is_func_match
            return False

        else:
            return any(fnmatch.fnmatch(func_name, pat) for pat in self.config.function_patterns)
