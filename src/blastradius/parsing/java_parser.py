"""Java language parser (regex-based).

Extracts class / interface / enum declarations, methods, and import
statements from ``.java`` files.

Module naming
-------------
``module`` is set to the Java package name (from ``package com.example;``).
``unique_id`` follows ``{package}.{ClassName}.{methodName}`` for methods and
``{package}.{ClassName}`` for type declarations.

Visibility
----------
Java access modifiers are mapped directly:
- ``public`` / (no modifier) → ``"public"``
- ``private`` / ``protected`` → ``"private"``
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from blastradius.core.symbol import Symbol
from blastradius.parsing.base import LanguageParser

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)

# Class / interface / enum: handles annotations like @Test on previous line
_CLASS_RE = re.compile(
    r"^[ \t]*(?:(?:public|protected|private|abstract|final|static)\s+)*"
    r"(?:class|interface|enum|record)\s+(\w+)"
    r"(?:\s+extends\s+([\w.,\s<>]+?))?"
    r"(?:\s+implements\s+([\w.,\s<>]+?))?(?:\s*\{|\s*$)",
    re.MULTILINE,
)

# Method declarations inside a class body
_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:@\w+(?:\([^)]*\))?\s+)*)"  # optional annotations
    r"(?:(?:public|protected|private|static|final|"
    r"abstract|synchronized|native|default|override)\s+)*"
    r"(?:<[^>]+>\s+)?"  # optional generic return
    r"(?:[\w\[\].<>,\s]+?\s+)"  # return type
    r"(\w+)\s*\(",  # method name
    re.MULTILINE,
)

_RESERVED_JAVA = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "switch",
        "return",
        "catch",
        "finally",
        "case",
        "default",
        "new",
        "throw",
        "try",
        "import",
        "package",
        "class",
        "interface",
        "enum",
        "extends",
        "implements",
        "super",
        "this",
        "void",
        "int",
        "long",
        "double",
        "float",
        "boolean",
        "byte",
        "short",
        "char",
        "String",
        "Object",
        "null",
        "true",
        "false",
        "instanceof",
        "static",
        "final",
        "abstract",
        "synchronized",
        "native",
        "volatile",
        "transient",
        "strictfp",
        "assert",
        "do",
        "break",
        "continue",
        "record",
        "sealed",
        "permits",
        "yield",
    }
)


class JavaParser(LanguageParser):
    """Java language parser using regex and brace-depth tracking."""

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".java"})

    def parse(self, filepath: str, repo_path: str) -> tuple[list[Symbol], dict[str, str]]:
        source = self.read_file(filepath)
        if source is None:
            return [], {}

        try:
            rel = Path(filepath).resolve().relative_to(Path(repo_path).resolve())
            rel_filepath = str(rel).replace("\\", "/")
        except ValueError:
            rel_filepath = filepath

        # ── Package ───────────────────────────────────────────────────
        pkg_m = _PACKAGE_RE.search(source)
        module = pkg_m.group(1) if pkg_m else ""

        symbols: list[Symbol] = []
        import_map: dict[str, str] = {}

        # ── Imports ───────────────────────────────────────────────────
        for m in _IMPORT_RE.finditer(source):
            fqn = m.group(1)
            simple = fqn.split(".")[-1]
            if simple != "*":
                import_map[simple] = fqn

        # ── Line-by-line scan ─────────────────────────────────────────
        lines = source.splitlines()
        depth = 0
        class_stack: list[tuple[str, list[str], int]] = []
        # (class_name, bases, entry_depth)

        for lineno_0, line in enumerate(lines):
            lineno = lineno_0 + 1
            open_count = line.count("{")
            close_count = line.count("}")

            cm = _CLASS_RE.match(line)
            if cm:
                class_name = cm.group(1)
                extends_raw = cm.group(2)
                implements_raw = cm.group(3)
                outer = class_stack[-1][0] if class_stack else None

                bases: list[str] = []
                if extends_raw:
                    bases.extend(
                        p.strip().split("<")[0] for p in extends_raw.split(",") if p.strip()
                    )
                if implements_raw:
                    bases.extend(
                        p.strip().split("<")[0] for p in implements_raw.split(",") if p.strip()
                    )

                uid = (
                    f"{module}.{outer}.{class_name}"
                    if outer
                    else f"{module}.{class_name}"
                    if module
                    else class_name
                )
                visibility = "private" if "private" in line or "protected" in line else "public"

                symbols.append(
                    Symbol(
                        unique_id=uid,
                        module=module,
                        filepath=rel_filepath,
                        class_name=outer,
                        function_name=None,
                        decorators=[],
                        line_no=lineno,
                        col_offset=0,
                        visibility=visibility,
                        async_sync=None,
                        nested_info=None,
                        kind="class",
                        method_kind=None,
                        bases=bases if bases else None,
                        calls=None,
                        local_types=None,
                    )
                )
                class_stack.append((class_name, bases, depth + open_count - close_count))

            elif class_stack:
                current_class, _, class_depth = class_stack[-1]
                if depth == class_depth:
                    mm = _METHOD_RE.match(line)
                    if mm:
                        method_name = mm.group(1)
                        if method_name not in _RESERVED_JAVA:
                            is_static = "static" in line[: line.index(method_name)]
                            is_abstract = "abstract" in line[: line.index(method_name)]
                            is_private = (
                                "private" in line[: line.index(method_name)]
                                or "protected" in line[: line.index(method_name)]
                            )
                            if is_abstract:
                                mk = "abstract"
                            elif is_static:
                                mk = "static"
                            else:
                                mk = "instance"

                            outer_class = class_stack[-1][0]
                            uid_prefix = f"{module}.{outer_class}" if module else outer_class
                            symbols.append(
                                Symbol(
                                    unique_id=f"{uid_prefix}.{method_name}",
                                    module=module,
                                    filepath=rel_filepath,
                                    class_name=outer_class,
                                    function_name=method_name,
                                    decorators=[],
                                    line_no=lineno,
                                    col_offset=0,
                                    visibility="private" if is_private else "public",
                                    async_sync="sync",
                                    nested_info=None,
                                    kind="method",
                                    method_kind=mk,
                                    bases=None,
                                    calls=None,
                                    local_types=None,
                                )
                            )

            depth += open_count - close_count
            if class_stack and depth < class_stack[-1][2]:
                class_stack.pop()

        # Post-parse call extraction pass
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
                    if parts[-1] not in _RESERVED_JAVA and parts[-1] not in ("super", "this"):
                        filtered_calls.append(call)
                sym.calls = filtered_calls

        return symbols, import_map
