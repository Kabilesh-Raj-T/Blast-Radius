"""TypeScript and TSX language parser (regex-based, no external dependencies).

Extracts classes, functions, arrow-function constants, and methods from
``.ts`` / ``.tsx`` files using multi-pass line scanning with brace-depth
tracking.  Import statements are fully resolved to their source paths.

Accuracy notes
--------------
* Top-level and class-level declarations are reliably detected.
* Arrow functions assigned to ``const``/``let``/``var`` are captured.
* Multi-line function signatures spread across many lines may not be
  fully captured — the declaration is associated with the first line.
* Dynamic / computed property names are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from blastradius.symbol import Symbol

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# `function foo(` or `async function foo(` or `export function foo(`
_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*[<(]",
    re.MULTILINE,
)

# `class Foo` / `export class Foo extends Bar implements IBar, IBaz`
_CLASS_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"
    r"(?:\s+extends\s+([\w.]+))?"
    r"(?:\s+implements\s+([\w\s,]+?))?(?:\s*\{|$)",
    re.MULTILINE,
)

# `const foo = (...) =>` or `const foo = async (...) =>`
_ARROW_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*"
    r"(?::\s*[\w<>\[\]|,\s]+?)?\s*=\s*(?:async\s+)?(?:\(|[\w]+\s*=>)",
    re.MULTILINE,
)

# Method inside a class body (handles public/private/protected/static/async/abstract/override)
_METHOD_RE = re.compile(
    r"^[ \t]+"
    r"(?:(?:public|private|protected|static|abstract|async|override|readonly)\s+)*"
    r"(?:get\s+|set\s+)?"
    r"(\w+)\s*[<(]",
    re.MULTILINE,
)

# `import { A, B } from 'path'` or `import X from 'path'` or `import * as X from 'path'`
_IMPORT_NAMED_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_IMPORT_DEFAULT_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?(\w+)\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_IMPORT_STAR_RE = re.compile(
    r"^\s*import\s+\*\s+as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?:\{[^}]+\}|(\w+))\s*=\s*require\(['\"]([^'\"]+)['\"]\)",
    re.MULTILINE,
)

# Keywords that are NOT method names even if they match _METHOD_RE
_RESERVED = frozenset(
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
        "typeof",
        "instanceof",
        "void",
        "delete",
        "in",
        "of",
        "import",
        "export",
        "from",
        "const",
        "let",
        "var",
        "class",
        "extends",
        "implements",
        "interface",
        "enum",
        "type",
        "declare",
        "namespace",
        "module",
        "abstract",
        "async",
        "await",
        "static",
        "public",
        "private",
        "protected",
        "override",
        "readonly",
        "get",
        "set",
        "constructor",
    }
)


def _module_from_path(filepath: str, repo_path: str) -> str:
    """Return fully-qualified module path."""
    from blastradius.context import get_repository_context

    ctx = get_repository_context(repo_path)
    return ctx.filepath_to_module(filepath)


def _resolve_import_path(source: str, current_file: str, repo_path: str) -> str:
    """Resolve a TS import source string to a canonical module name."""
    if source.startswith("."):
        base = Path(current_file).parent / source
        from blastradius.context import get_repository_context

        ctx = get_repository_context(repo_path)
        return ctx.filepath_to_module(str(base))
    # Replace slashes with dots for package references
    return source.replace("/", ".")


class TypeScriptParser:
    """TypeScript / TSX parser using regex and brace-depth scanning."""

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".ts", ".tsx"})

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

        # ── Imports ──────────────────────────────────────────────────────
        for m in _IMPORT_NAMED_RE.finditer(source):
            names_str, src = m.group(1), m.group(2)
            resolved = _resolve_import_path(src, filepath, repo_path)
            for name in names_str.split(","):
                name = name.strip().split(" as ")[-1].strip()
                if name:
                    import_map[name] = f"{resolved}.{name}"

        for m in _IMPORT_DEFAULT_RE.finditer(source):
            alias, src = m.group(1), m.group(2)
            resolved = _resolve_import_path(src, filepath, repo_path)
            import_map[alias] = resolved

        for m in _IMPORT_STAR_RE.finditer(source):
            alias, src = m.group(1), m.group(2)
            resolved = _resolve_import_path(src, filepath, repo_path)
            import_map[alias] = resolved

        for m in _REQUIRE_RE.finditer(source):
            alias, src = m.group(1), m.group(2)
            if alias:
                resolved = _resolve_import_path(src, filepath, repo_path)
                import_map[alias] = resolved

        # ── Line-by-line scan with brace-depth tracking ───────────────
        lines = source.splitlines()
        depth = 0  # brace depth
        class_stack: list[tuple[str, list[str], int]] = []
        # (class_name, bases, class_start_depth)

        i = 0
        while i < len(lines):
            line = lines[i]
            lineno = i + 1

            # Track brace depth changes
            open_count = line.count("{")
            close_count = line.count("}")

            # ── Class declarations ────────────────────────────────────
            cm = _CLASS_RE.match(line)
            if cm:
                class_name = cm.group(1)
                base = cm.group(2)
                implements_raw = cm.group(3)

                bases: list[str] = []
                if base:
                    bases.append(base)
                if implements_raw:
                    bases.extend(p.strip() for p in implements_raw.split(",") if p.strip())

                outer_class = class_stack[-1][0] if class_stack else None
                unique_id = (
                    f"{module}.{outer_class}.{class_name}"
                    if outer_class
                    else f"{module}.{class_name}"
                )

                symbols.append(
                    Symbol(
                        unique_id=unique_id,
                        module=module,
                        filepath=rel_filepath,
                        class_name=outer_class,
                        function_name=None,
                        decorators=[],
                        line_no=lineno,
                        col_offset=0,
                        visibility="public",
                        async_sync=None,
                        nested_info=None,
                        kind="class",
                        method_kind=None,
                        bases=bases if bases else None,
                        calls=None,
                        local_types=None,
                    )
                )
                # Will enter class body on the opening brace
                class_stack.append((class_name, bases, depth + open_count - close_count))

            # ── Top-level function declarations ───────────────────────
            elif not class_stack and depth == 0:
                fm = _FUNC_RE.match(line)
                if fm:
                    fn_name = fm.group(1)
                    is_async = "async" in line[: line.find(fn_name)]
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
                            visibility="private" if fn_name.startswith("_") else "public",
                            async_sync="async" if is_async else "sync",
                            nested_info=None,
                            kind="function",
                            method_kind=None,
                            bases=None,
                            calls=None,
                            local_types=None,
                        )
                    )
                else:
                    am = _ARROW_RE.match(line)
                    if am:
                        fn_name = am.group(1)
                        is_async = "async" in line
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
                                visibility="private" if fn_name.startswith("_") else "public",
                                async_sync="async" if is_async else "sync",
                                nested_info=None,
                                kind="function",
                                method_kind=None,
                                bases=None,
                                calls=None,
                                local_types=None,
                            )
                        )

            # ── Methods inside a class ────────────────────────────────
            elif class_stack:
                current_class, _, class_depth = class_stack[-1]
                # Only match methods at exactly one brace level inside the class
                if depth == class_depth:
                    mm = _METHOD_RE.match(line)
                    if mm:
                        method_name = mm.group(1)
                        if method_name not in _RESERVED:
                            is_static = "static" in line[: line.index(method_name)]
                            is_private = (
                                "private" in line[: line.index(method_name)]
                                or method_name.startswith("_")
                                or method_name.startswith("#")
                            )
                            is_async = "async" in line[: line.index(method_name)]
                            mk = "static" if is_static else "instance"

                            symbols.append(
                                Symbol(
                                    unique_id=f"{module}.{current_class}.{method_name}",
                                    module=module,
                                    filepath=rel_filepath,
                                    class_name=current_class,
                                    function_name=method_name,
                                    decorators=[],
                                    line_no=lineno,
                                    col_offset=0,
                                    visibility="private" if is_private else "public",
                                    async_sync="async" if is_async else "sync",
                                    nested_info=None,
                                    kind="method",
                                    method_kind=mk,
                                    bases=None,
                                    calls=None,
                                    local_types=None,
                                )
                            )

            # Update depth
            depth += open_count - close_count

            # Pop class off stack when we exit its body
            if class_stack and depth < class_stack[-1][2]:
                class_stack.pop()

            i += 1

        # Post-parse call extraction pass
        call_regex = re.compile(r"\b([\w$.]+(?:\.[\w$]+)*)\s*\(")
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
                    if parts[-1] not in _RESERVED and parts[-1] not in (
                        "super",
                        "this",
                        "constructor",
                    ):
                        filtered_calls.append(call)
                sym.calls = filtered_calls

        return symbols, import_map
