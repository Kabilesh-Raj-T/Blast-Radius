"""Configuration manager for BlastRadius, loading .blastradius.toml and environment variables."""

import os
from pathlib import Path
from typing import Any, Dict, List

# Try to use tomllib (Python 3.11+), otherwise fallback to a simple custom parser
try:
    import tomllib  # type: ignore
except ImportError:
    tomllib = None  # type: ignore


class Config:
    """Configuration class exposing typed accessors with overrides."""

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.raw_config: Dict[str, Any] = {}
        self.load_toml()

    def load_toml(self) -> None:
        """Load .blastradius.toml from the repository root."""
        toml_path = self.repo_path / ".blastradius.toml"
        if not toml_path.exists():
            return

        try:
            content = toml_path.read_text(encoding="utf-8")
            if tomllib:
                self.raw_config = tomllib.loads(content)
            else:
                self.raw_config = self._parse_toml_fallback(content)
        except Exception:
            # Fallback silently to defaults if TOML is malformed
            self.raw_config = {}

    def _parse_toml_fallback(self, content: str) -> Dict[str, Any]:
        """Simple custom TOML parser for basic nested structures."""
        config: Dict[str, Any] = {}
        current_section = ""

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue

            if "=" in line:
                key, val_str = line.split("=", 1)
                key = key.strip()
                val_str = val_str.strip()

                # Parse basic value types
                val: Any = val_str
                if val_str.startswith("[") and val_str.endswith("]"):
                    # Parse lists of strings
                    elements = [
                        e.strip().strip('"').strip("'")
                        for e in val_str[1:-1].split(",")
                        if e.strip()
                    ]
                    val = elements
                elif val_str.lower() == "true":
                    val = True
                elif val_str.lower() == "false":
                    val = False
                elif val_str.isdigit():
                    val = int(val_str)
                elif val_str.startswith('"') and val_str.endswith('"'):
                    val = val_str[1:-1]
                elif val_str.startswith("'") and val_str.endswith("'"):
                    val = val_str[1:-1]

                if current_section:
                    config.setdefault(current_section, {})[key] = val
                else:
                    config[key] = val

        return config

    def get_value(self, section: str, key: str, default: Any) -> Any:
        """Get config value with TOML loading and environment variable override."""
        # Check environment variable first (e.g. BLASTRADIUS_DIFF_THRESHOLD)
        env_var_name = f"BLASTRADIUS_{section.upper()}_{key.upper()}"
        if env_var_name in os.environ:
            env_val = os.environ[env_var_name]
            if isinstance(default, bool):
                return env_val.lower() in ("true", "1", "yes")
            if isinstance(default, int):
                try:
                    return int(env_val)
                except ValueError:
                    return default
            if isinstance(default, list):
                return [e.strip() for e in env_val.split(",") if e.strip()]
            return env_val

        # Check loaded TOML config
        section_dict = self.raw_config.get(section, {})
        if key in section_dict:
            return section_dict[key]

        return default

    # --- Property Accessors ---

    @property
    def exclude(self) -> List[str]:
        return self.get_value(
            "index",
            "exclude",
            ["migrations", "vendor", "__pycache__", "venv", ".venv", "node_modules"],
        )

    @property
    def output_dir(self) -> str:
        return self.get_value("index", "output_dir", ".blastradius")

    @property
    def max_depth(self) -> int:
        return self.get_value("analyze", "max_depth", 10)

    @property
    def default_output(self) -> str:
        return self.get_value("analyze", "default_output", "terminal")

    @property
    def default_base(self) -> str:
        return self.get_value("diff", "default_base", "HEAD")

    @property
    def threshold(self) -> int:
        return self.get_value("diff", "threshold", 0)

    @property
    def strict(self) -> bool:
        return self.get_value("diff", "strict", False)

    @property
    def pre_commit_threshold(self) -> int:
        return self.get_value("pre_commit", "threshold", 30)

    @property
    def pre_commit_strict(self) -> bool:
        return self.get_value("pre_commit", "strict", False)

    @property
    def port(self) -> int:
        return self.get_value("mcp", "port", 3000)

    @property
    def auto_index(self) -> bool:
        return self.get_value("mcp", "auto_index", True)
