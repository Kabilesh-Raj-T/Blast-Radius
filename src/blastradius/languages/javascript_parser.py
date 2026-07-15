"""JavaScript and JSX language parser (regex-based).

Shares the same brace-depth scanning strategy as the TypeScript parser
but without type annotations.  Handles ``.js`` and ``.jsx`` files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from blastradius.languages.base import LanguageParser
from blastradius.symbol import Symbol

# ---------------------------------------------------------------------------
# Regex patterns (subset of TS patterns — no type syntax)
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\(",
    re.MULTILINE,
)

_CLASS_RE = re.compile(
    r"^[ \t]*(?:export\s+)?class\s+(\w+)" r"(?:\s+extends\s+([\w.]+))?" r"(?:\s*\{|$)",
    re.MULTILINE,
)

_ARROW_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\(|[\w]+\s*=>)",
    re.MULTILINE,
)

_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:static|async|get|set)\s+)*(\w+)\s*\(",
    re.MULTILINE,
)

_IMPORT_NAMED_RE = re.compile(
    r"^\s*import\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_IMPORT_DEFAULT_RE = re.compile(
    r"^\s*import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_IMPORT_STAR_RE = re.compile(
    r"^\s*import\s+\*\s+as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*require\(['\"]([^'\"]+)['\"]\)",
    re.MULTILINE,
)

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
        "async",
        "await",
        "static",
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
    """Resolve a JS import source string to a canonical module name."""
    if source.startswith("."):
        base = Path(current_file).parent / source
        from blastradius.context import get_repository_context

        ctx = get_repository_context(repo_path)
        return ctx.filepath_to_module(str(base))
    return source.replace("/", ".")


class JavaScriptParser(LanguageParser):
    """JavaScript / JSX parser using regex and brace-depth scanning."""

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".js", ".jsx", ".mjs", ".cjs"})

    def parse(self, filepath: str, repo_path: str) -> tuple[list[Symbol], dict[str, str]]:
        source = self.read_file(filepath)
        if source is None:
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
            import_map[alias] = _resolve_import_path(src, filepath, repo_path)

        for m in _IMPORT_STAR_RE.finditer(source):
            alias, src = m.group(1), m.group(2)
            import_map[alias] = _resolve_import_path(src, filepath, repo_path)

        for m in _REQUIRE_RE.finditer(source):
            alias, src = m.group(1), m.group(2)
            if alias:
                import_map[alias] = _resolve_import_path(src, filepath, repo_path)

        # ── Line-by-line scan ─────────────────────────────────────────
        lines = source.splitlines()
        depth = 0
        class_stack: list[tuple[str, int]] = []  # (class_name, entry_depth)

        for lineno_0, line in enumerate(lines):
            lineno = lineno_0 + 1
            open_count = line.count("{")
            close_count = line.count("}")

            cm = _CLASS_RE.match(line)
            if cm:
                class_name = cm.group(1)
                base = cm.group(2)
                outer = class_stack[-1][0] if class_stack else None
                uid = f"{module}.{outer}.{class_name}" if outer else f"{module}.{class_name}"
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
                        visibility="public",
                        async_sync=None,
                        nested_info=None,
                        kind="class",
                        method_kind=None,
                        bases=[base] if base else None,
                        calls=None,
                        local_types=None,
                    )
                )
                class_stack.append((class_name, depth + open_count - close_count))

            elif not class_stack and depth == 0:
                fm = _FUNC_RE.match(line)
                if fm:
                    fn = fm.group(1)
                    is_async = "async" in line[: line.find(fn)]
                    symbols.append(
                        Symbol(
                            unique_id=f"{module}.{fn}",
                            module=module,
                            filepath=rel_filepath,
                            class_name=None,
                            function_name=fn,
                            decorators=[],
                            line_no=lineno,
                            col_offset=0,
                            visibility="private" if fn.startswith("_") else "public",
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
                        fn = am.group(1)
                        symbols.append(
                            Symbol(
                                unique_id=f"{module}.{fn}",
                                module=module,
                                filepath=rel_filepath,
                                class_name=None,
                                function_name=fn,
                                decorators=[],
                                line_no=lineno,
                                col_offset=0,
                                visibility="private" if fn.startswith("_") else "public",
                                async_sync="async" if "async" in line else "sync",
                                nested_info=None,
                                kind="function",
                                method_kind=None,
                                bases=None,
                                calls=None,
                                local_types=None,
                            )
                        )

            elif class_stack:
                current_class, class_depth = class_stack[-1]
                if depth == class_depth:
                    mm = _METHOD_RE.match(line)
                    if mm:
                        mn = mm.group(1)
                        if mn not in _RESERVED:
                            is_static = "static" in line[: line.index(mn)]
                            symbols.append(
                                Symbol(
                                    unique_id=f"{module}.{current_class}.{mn}",
                                    module=module,
                                    filepath=rel_filepath,
                                    class_name=current_class,
                                    function_name=mn,
                                    decorators=[],
                                    line_no=lineno,
                                    col_offset=0,
                                    visibility="private" if mn.startswith("_") else "public",
                                    async_sync="async" if "async" in line else "sync",
                                    nested_info=None,
                                    kind="method",
                                    method_kind="static" if is_static else "instance",
                                    bases=None,
                                    calls=None,
                                    local_types=None,
                                )
                            )

            depth += open_count - close_count
            if class_stack and depth < class_stack[-1][1]:
                class_stack.pop()

        return symbols, import_map
