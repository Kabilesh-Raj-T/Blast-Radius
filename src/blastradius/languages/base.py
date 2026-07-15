"""Language parser Protocol and ParserRegistry.

Every language-specific parser must satisfy the :class:`LanguageParser`
Protocol — a structural interface (no inheritance required).

Usage::

    from blastradius.languages.base import ParserRegistry
    from blastradius.languages.python_parser import PythonParser

    registry = ParserRegistry()
    registry.register(PythonParser())

    symbols, import_map = registry.parse_file("utils/parser.py", "/repo")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from blastradius.symbol import Symbol


@runtime_checkable
class LanguageParser(Protocol):
    """Structural interface that every language parser must satisfy.

    Implementors **must** declare :attr:`EXTENSIONS` as a class variable and
    implement :meth:`parse`.  No base-class inheritance is required.
    """

    #: Set of lowercase file extensions this parser handles, e.g. ``{".py"}``.
    EXTENSIONS: ClassVar[frozenset[str]]

    def parse(
        self,
        filepath: str,
        repo_path: str,
    ) -> tuple[list["Symbol"], dict[str, str]]:
        """Parse *filepath* and return ``(symbols, import_map)``.

        Parameters
        ----------
        filepath:
            Absolute path to the source file.
        repo_path:
            Absolute path to the repository root (used for computing
            relative paths and module names).

        Returns
        -------
        symbols:
            All classes, functions, and methods defined in the file.
        import_map:
            ``{local_alias: fully_qualified_name}`` for every import in
            the file.
        """
        ...


def find_end_line(source: str, start_index: int) -> int | None:
    # Find the first '{' after start_index
    open_brace_idx = source.find("{", start_index)
    if open_brace_idx == -1:
        return None

    depth = 0
    in_string = None
    escaped = False
    in_line_comment = False
    in_block_comment = False

    idx = open_brace_idx
    n = len(source)
    while idx < n:
        char = source[idx]

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            idx += 1
            continue

        if in_block_comment:
            if char == "*" and idx + 1 < n and source[idx + 1] == "/":
                in_block_comment = False
                idx += 2
            else:
                idx += 1
            continue

        if escaped:
            escaped = False
            idx += 1
            continue

        if char == "\\":
            escaped = True
            idx += 1
            continue

        if in_string:
            if char == in_string:
                in_string = None
            idx += 1
            continue

        # Check for comments start
        if char == "/" and idx + 1 < n:
            if source[idx + 1] == "/":
                in_line_comment = True
                idx += 2
                continue
            elif source[idx + 1] == "*":
                in_block_comment = True
                idx += 2
                continue

        if char in ('"', "'", "`"):
            in_string = char
            idx += 1
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[:idx].count("\n") + 1
        idx += 1

    return None


class ParserRegistry:
    """Maps file extensions to :class:`LanguageParser` instances.

    A single registry is instantiated in :mod:`blastradius.languages` and
    shared across the whole pipeline.

    Example::

        from blastradius.languages import registry

        symbols, imports = registry.parse_file("main.go", "/my/repo")
    """

    def __init__(self) -> None:
        # ext (lowercase, with dot) → parser instance
        self._parsers: dict[str, LanguageParser] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, parser: LanguageParser) -> None:
        """Register *parser* for all of its declared extensions."""
        for ext in parser.EXTENSIONS:
            self._parsers[ext.lower()] = parser

    def unregister(self, extension: str) -> None:
        """Remove the parser registered for *extension* (if any)."""
        self._parsers.pop(extension.lower(), None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, filepath: str) -> LanguageParser | None:
        """Return the parser for *filepath*'s extension, or ``None``."""
        ext = Path(filepath).suffix.lower()
        return self._parsers.get(ext)

    @property
    def extensions(self) -> frozenset[str]:
        """All file extensions currently registered (e.g. ``{'.py', '.ts'}``)."""
        return frozenset(self._parsers)

    # ------------------------------------------------------------------
    # Parsing entry-point
    # ------------------------------------------------------------------

    def parse_file(
        self,
        filepath: str,
        repo_path: str,
    ) -> tuple[list["Symbol"], dict[str, str]]:
        """Dispatch to the correct parser for *filepath*.

        Returns ``([], {})`` if no parser is registered for the file's
        extension so callers never need to guard against ``None``.
        """
        parser = self.get(filepath)
        if parser is None:
            return [], {}
        symbols, import_map = parser.parse(filepath, repo_path)

        # Post-process symbols to compute end_line_no for brace-based languages
        ext = Path(filepath).suffix.lower()
        if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".java", ".rs"):
            try:
                source = Path(filepath).read_text(encoding="utf-8")
                # Pre-calculate line offsets for O(1) character index lookup
                lines = source.splitlines(keepends=True)
                line_offsets = [0]
                total = 0
                for line in lines:
                    total += len(line)
                    line_offsets.append(total)

                for sym in symbols:
                    if getattr(sym, "end_line_no", None) is None:
                        start_line = sym.line_no
                        if start_line <= len(line_offsets):
                            start_idx = line_offsets[start_line - 1]
                            end_line = find_end_line(source, start_idx)
                            if end_line is not None:
                                sym.end_line_no = end_line
            except Exception:
                pass

        return symbols, import_map
