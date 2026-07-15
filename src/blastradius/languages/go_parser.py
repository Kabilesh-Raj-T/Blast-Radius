"""Go language parser (regex-based).

Extracts top-level functions, receiver methods, struct and interface
type declarations, and import statements from ``.go`` files.

Module naming
-------------
The ``module`` field is set to the Go package name (from ``package xyz``).
The ``unique_id`` is ``{package}.{FunctionName}`` for standalone functions
and ``{package}.{ReceiverType}.{MethodName}`` for methods.

Import map
----------
Maps the local package alias (or the last segment of the import path) to
the full import path.  E.g. ``import "encoding/json"`` →
``{"json": "encoding/json"}``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from blastradius.languages.base import LanguageParser
from blastradius.symbol import Symbol

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r"^\s*package\s+(\w+)", re.MULTILINE)

# Single import: `import "pkg"` or `import alias "pkg"`
_IMPORT_SINGLE_RE = re.compile(r'^\s*import\s+(?:(\w+)\s+)?"([^"]+)"', re.MULTILINE)

# Grouped imports: `import ( ... )`
_IMPORT_GROUP_RE = re.compile(r"import\s*\(([^)]+)\)", re.DOTALL)
_IMPORT_LINE_RE = re.compile(r'^\s*(?:(\w+)\s+)?"([^"]+)"', re.MULTILINE)

# Top-level function: `func FunctionName(`
_FUNC_RE = re.compile(r"^func\s+(\w+)\s*[\[(]", re.MULTILINE)

# Method with receiver: `func (r *ReceiverType) MethodName(`
# or `func (r ReceiverType) MethodName(`
_METHOD_RE = re.compile(
    r"^func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)\s*[\[(]",
    re.MULTILINE,
)

# Type declarations: `type Name struct {` or `type Name interface {`
_TYPE_RE = re.compile(
    r"^type\s+(\w+)\s+(struct|interface)\s*\{",
    re.MULTILINE,
)


def extract_struct_bases(source: str, start_pos: int) -> list[str]:
    """Find the struct body and extract embedded structs as bases.

    start_pos should be the position of the opening '{'.
    """
    open_brace = start_pos
    if open_brace == -1 or open_brace >= len(source) or source[open_brace] != "{":
        return []

    depth = 0
    close_brace = -1
    for idx in range(open_brace, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                close_brace = idx
                break

    if close_brace == -1:
        return []

    body = source[open_brace + 1 : close_brace]
    bases = []

    for line in body.splitlines():
        line = line.split("//")[0].split("/*")[0].strip()
        if not line:
            continue
        parts = line.split("`")[0].strip().split()
        if len(parts) == 1:
            part = parts[0]
            part = part.lstrip("*")
            if re.match(r"^(?:\w+\.)?\w+$", part):
                if part not in ("interface", "struct", "map", "chan", "func"):
                    bases.append(part)
    return bases


class GoParser(LanguageParser):
    """Go language parser using regex."""

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".go"})

    def parse(self, filepath: str, repo_path: str) -> tuple[list[Symbol], dict[str, str]]:
        source = self.read_file(filepath)
        if source is None:
            return [], {}

        try:
            rel = Path(filepath).resolve().relative_to(Path(repo_path).resolve())
            rel_filepath = str(rel).replace("\\", "/")
        except ValueError:
            rel_filepath = filepath

        # ── Package name ─────────────────────────────────────────────
        pkg_match = _PACKAGE_RE.search(source)
        module = pkg_match.group(1) if pkg_match else Path(filepath).stem

        symbols: list[Symbol] = []
        import_map: dict[str, str] = {}

        # ── Imports ───────────────────────────────────────────────────
        # Grouped imports first (they consume the source range)
        for group_m in _IMPORT_GROUP_RE.finditer(source):
            group_body = group_m.group(1)
            for line_m in _IMPORT_LINE_RE.finditer(group_body):
                alias = line_m.group(1)
                path = line_m.group(2)
                local = alias if alias else path.split("/")[-1]
                import_map[local] = path

        # Single-line imports
        for m in _IMPORT_SINGLE_RE.finditer(source):
            alias = m.group(1)
            path = m.group(2)
            local = alias if alias else path.split("/")[-1]
            import_map[local] = path

        # ── Types (struct / interface) ────────────────────────────────
        # Build a set of known struct names for visibility checks
        struct_names: set[str] = set()
        for m in _TYPE_RE.finditer(source):
            type_name = m.group(1)
            kind_str = m.group(2)
            struct_names.add(type_name)
            # In Go, unexported names start with a lowercase letter
            visibility = "public" if type_name[0].isupper() else "private"
            lineno = source[: m.start()].count("\n") + 1

            symbols.append(
                Symbol(
                    unique_id=f"{module}.{type_name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=None,
                    function_name=None,
                    decorators=[],
                    line_no=lineno,
                    col_offset=0,
                    visibility=visibility,
                    async_sync=None,
                    nested_info=None,
                    kind="class",  # map struct/interface to class
                    method_kind=None,
                    bases=extract_struct_bases(source, m.end() - 1)
                    if kind_str == "struct"
                    else None,
                    calls=None,
                    local_types=None,
                )
            )

        # ── Methods (must come before functions to avoid double-counting) ──
        method_starts: set[int] = set()
        for m in _METHOD_RE.finditer(source):
            receiver_type = m.group(1)
            method_name = m.group(2)
            visibility = "public" if method_name[0].isupper() else "private"
            lineno = source[: m.start()].count("\n") + 1
            method_starts.add(m.start())

            symbols.append(
                Symbol(
                    unique_id=f"{module}.{receiver_type}.{method_name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=receiver_type,
                    function_name=method_name,
                    decorators=[],
                    line_no=lineno,
                    col_offset=0,
                    visibility=visibility,
                    async_sync="sync",
                    nested_info=None,
                    kind="method",
                    method_kind="instance",
                    bases=None,
                    calls=None,
                    local_types=None,
                )
            )

        # ── Top-level functions ───────────────────────────────────────
        for m in _FUNC_RE.finditer(source):
            # Skip if this position was already captured as a method
            if m.start() in method_starts:
                continue
            # The method regex also starts with "^func" — double-check
            # that this isn't a method by looking for receiver syntax
            context = source[m.start() : m.start() + 60]
            if re.match(r"^func\s*\(", context):
                continue
            fn_name = m.group(1)
            visibility = "public" if fn_name[0].isupper() else "private"
            lineno = source[: m.start()].count("\n") + 1

            symbols.append(
                Symbol(
                    unique_id=f"{module}.{fn_name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=None,
                    function_name=fn_name,
                    decorators=[],
                    line_no=lineno,
                    col_offset=0,
                    visibility=visibility,
                    async_sync="sync",
                    nested_info=None,
                    kind="function",
                    method_kind=None,
                    bases=None,
                    calls=None,
                    local_types=None,
                )
            )

        # Post-parse call extraction pass
        lines = source.splitlines()
        call_regex = re.compile(r"\b([\w.]+)\s*\(")
        sorted_symbols = sorted(symbols, key=lambda s: s.line_no)
        for idx, sym in enumerate(sorted_symbols):
            if sym.kind in ("function", "method"):
                start_idx = sym.line_no - 1
                end_idx = (
                    sorted_symbols[idx + 1].line_no - 1
                    if idx + 1 < len(sorted_symbols)
                    else len(lines)
                )

                body_lines = lines[start_idx:end_idx]
                body_text = "\n".join(body_lines)

                calls = call_regex.findall(body_text)
                filtered_calls = []
                for call in calls:
                    parts = call.split(".")
                    if parts[-1] not in (
                        "func",
                        "package",
                        "import",
                        "type",
                        "struct",
                        "interface",
                        "map",
                        "chan",
                        "go",
                        "select",
                        "defer",
                        "return",
                        "if",
                        "for",
                        "switch",
                        "case",
                        "default",
                    ):
                        filtered_calls.append(call)
                sym.calls = filtered_calls

        return symbols, import_map
