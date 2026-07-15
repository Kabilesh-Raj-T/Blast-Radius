"""Rust language parser (regex-based).

Extracts ``fn`` declarations, ``struct`` / ``trait`` / ``enum`` definitions,
``impl`` block methods, and ``use`` statements from ``.rs`` files.

Module naming
-------------
``module`` is the slash-separated relative file path without extension,
mirroring how Rust's module hierarchy maps to the file system.
``unique_id`` follows ``{module}.{ItemName}`` for top-level items and
``{module}.{StructName}.{methodName}`` for impl methods.

Visibility
----------
Items without a ``pub`` keyword are private.  ``pub(crate)`` and
``pub(super)`` are treated as ``"public"`` within the project.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from blastradius.symbol import Symbol

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# `use std::collections::HashMap;` or `use crate::module::{A, B};`
_USE_RE = re.compile(
    r"^\s*(?:pub\s+)?use\s+([\w:]+)(?:::\{([^}]+)\})?(?:\s+as\s+(\w+))?;",
    re.MULTILINE,
)

# Struct / enum / trait declarations
_STRUCT_RE = re.compile(
    r"^(?:pub(?:\(\w+\))?\s+)?(?:struct|enum)\s+(\w+)",
    re.MULTILINE,
)
_TRAIT_RE = re.compile(
    r"^(?:pub(?:\(\w+\))?\s+)?trait\s+(\w+)",
    re.MULTILINE,
)

# Top-level `fn` (not inside an impl block)
_FN_RE = re.compile(
    r"^(?:pub(?:\(\w+\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*[\[(<]",
    re.MULTILINE,
)

# `impl TypeName {` or `impl TraitName for TypeName {`
_IMPL_RE = re.compile(
    r"^impl(?:<[^>]+>)?\s+(?:(\w+)\s+for\s+)?(\w+)(?:<[^>]+>)?\s*\{",
    re.MULTILINE,
)

# Method inside an impl block
_METHOD_RE = re.compile(
    r"^[ \t]+(?:pub(?:\(\w+\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*[\[(<]",
    re.MULTILINE,
)


def _module_from_path(filepath: str, repo_path: str) -> str:
    """Return fully-qualified module path."""
    from blastradius.context import get_repository_context

    ctx = get_repository_context(repo_path)
    return ctx.filepath_to_module(filepath)


class RustParser:
    """Rust language parser using regex and impl-block tracking."""

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".rs"})

    def parse(self, filepath: str, repo_path: str) -> tuple[list[Symbol], dict[str, str]]:
        try:
            source = Path(filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return [], {}

        try:
            rel = Path(filepath).resolve().relative_to(Path(repo_path).resolve())
            rel_filepath = str(rel).replace("\\", "/")
        except ValueError:
            rel_filepath = filepath

        module = _module_from_path(filepath, repo_path)
        symbols: list[Symbol] = []
        import_map: dict[str, str] = {}

        # ── Use statements ────────────────────────────────────────────
        for m in _USE_RE.finditer(source):
            path = m.group(1)
            items = m.group(2)
            alias = m.group(3)

            if items:
                # `use foo::bar::{A, B as C}`
                for item in items.split(","):
                    item = item.strip()
                    if " as " in item:
                        orig, local = item.split(" as ", 1)
                        import_map[local.strip()] = f"{path}::{orig.strip()}"
                    elif item:
                        import_map[item] = f"{path}::{item}"
            elif alias:
                import_map[alias] = path
            else:
                local = path.split("::")[-1]
                if local and local != "*":
                    import_map[local] = path

        # ── Structs / Enums ───────────────────────────────────────────
        struct_names: set[str] = set()
        for m in _STRUCT_RE.finditer(source):
            name = m.group(1)
            struct_names.add(name)
            is_pub = m.group(0).lstrip().startswith("pub")
            lineno = source[: m.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    unique_id=f"{module}.{name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=None,
                    function_name=None,
                    decorators=[],
                    line_no=lineno,
                    col_offset=0,
                    visibility="public" if is_pub else "private",
                    async_sync=None,
                    nested_info=None,
                    kind="class",
                    method_kind=None,
                    bases=None,
                    calls=None,
                    local_types=None,
                )
            )

        # ── Traits ───────────────────────────────────────────────────
        for m in _TRAIT_RE.finditer(source):
            name = m.group(1)
            struct_names.add(name)
            is_pub = m.group(0).lstrip().startswith("pub")
            lineno = source[: m.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    unique_id=f"{module}.{name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=None,
                    function_name=None,
                    decorators=[],
                    line_no=lineno,
                    col_offset=0,
                    visibility="public" if is_pub else "private",
                    async_sync=None,
                    nested_info=None,
                    kind="class",
                    method_kind=None,
                    bases=None,
                    calls=None,
                    local_types=None,
                )
            )

        # ── Impl blocks + their methods ───────────────────────────────
        # Strategy: find each impl block's position in the source, then
        # scan lines inside its brace range for method definitions.
        lines = source.splitlines()
        impl_positions: list[tuple[int, str]] = []  # (char_offset, type_name)

        for m in _IMPL_RE.finditer(source):
            type_name = m.group(2)  # group 2 is always the concrete type
            impl_positions.append((m.start(), type_name))

        # Track which char ranges are impl bodies
        # Build a map: line_no → impl type_name
        line_offsets = [0]
        for ch in source:
            line_offsets.append(line_offsets[-1] + (1 if ch != "\n" else 1))

        # Recompute cumulative line start offsets
        cum: list[int] = []
        pos = 0
        for ln in lines:
            cum.append(pos)
            pos += len(ln) + 1  # +1 for newline

        def _line_of_offset(offset: int) -> int:
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if cum[mid] <= offset:
                    lo = mid
                else:
                    hi = mid - 1
            return lo  # 0-indexed

        # For each impl, find the brace range
        impl_ranges: list[tuple[int, int, str]] = []  # (start_line, end_line, type)
        for impl_offset, type_name in impl_positions:
            start_line = _line_of_offset(impl_offset)
            # Walk forward to find matching closing brace
            brace_depth = 0
            end_line = start_line
            for li in range(start_line, len(lines)):
                brace_depth += lines[li].count("{") - lines[li].count("}")
                if brace_depth <= 0 and li > start_line:
                    end_line = li
                    break
            else:
                end_line = len(lines) - 1
            impl_ranges.append((start_line, end_line, type_name))

        # Now find methods
        method_line_set: set[int] = set()
        for start_ln, end_ln, type_name in impl_ranges:
            for li in range(start_ln + 1, end_ln):
                line = lines[li]
                mm = _METHOD_RE.match(line)
                if mm and li not in method_line_set:
                    method_name = mm.group(1)
                    method_line_set.add(li)
                    is_pub = "pub" in line[: line.index(method_name)]
                    is_async = "async" in line[: line.index(method_name)]
                    symbols.append(
                        Symbol(
                            unique_id=f"{module}.{type_name}.{method_name}",
                            module=module,
                            filepath=rel_filepath,
                            class_name=type_name,
                            function_name=method_name,
                            decorators=[],
                            line_no=li + 1,
                            col_offset=0,
                            visibility="public" if is_pub else "private",
                            async_sync="async" if is_async else "sync",
                            nested_info=None,
                            kind="method",
                            method_kind="instance",
                            bases=None,
                            calls=None,
                            local_types=None,
                        )
                    )

        # ── Top-level functions (outside impl blocks) ─────────────────
        impl_line_set: set[int] = set()
        for start_ln, end_ln, _ in impl_ranges:
            for li in range(start_ln, end_ln + 1):
                impl_line_set.add(li)

        for m in _FN_RE.finditer(source):
            lineno_0 = source[: m.start()].count("\n")
            if lineno_0 in impl_line_set:
                continue  # inside an impl — already captured as method
            fn_name = m.group(1)
            is_pub = m.group(0).lstrip().startswith("pub")
            is_async = "async" in m.group(0)
            symbols.append(
                Symbol(
                    unique_id=f"{module}.{fn_name}",
                    module=module,
                    filepath=rel_filepath,
                    class_name=None,
                    function_name=fn_name,
                    decorators=[],
                    line_no=lineno_0 + 1,
                    col_offset=0,
                    visibility="public" if is_pub else "private",
                    async_sync="async" if is_async else "sync",
                    nested_info=None,
                    kind="function",
                    method_kind=None,
                    bases=None,
                    calls=None,
                    local_types=None,
                )
            )

        return symbols, import_map
