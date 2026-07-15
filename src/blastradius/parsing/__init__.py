"""Language parsers package.

Instantiates all built-in language parsers, registers them in a shared
:class:`~blastradius.parsing.base.ParserRegistry` singleton, and
re-exports a drop-in ``parse_file`` function.

Adding a new language
---------------------
1. Create ``blastradius/parsing/my_lang_parser.py`` with a class that
   has ``EXTENSIONS: ClassVar[frozenset[str]]`` and a ``parse()`` method.
2. Import and register it here::

       from blastradius.parsing.my_lang_parser import MyLangParser
       registry.register(MyLangParser())

No other files need to change.
"""

from __future__ import annotations

from blastradius.parsing.base import ParserRegistry
from blastradius.parsing.go_parser import GoParser
from blastradius.parsing.java_parser import JavaParser
from blastradius.parsing.javascript_parser import JavaScriptParser
from blastradius.parsing.python_parser import PythonParser
from blastradius.parsing.rust_parser import RustParser
from blastradius.parsing.typescript_parser import TypeScriptParser

# ---------------------------------------------------------------------------
# Singleton registry — shared across the whole pipeline
# ---------------------------------------------------------------------------

registry: ParserRegistry = ParserRegistry()
registry.register(PythonParser())
registry.register(TypeScriptParser())
registry.register(JavaScriptParser())
registry.register(GoParser())
registry.register(JavaParser())
registry.register(RustParser())


# ---------------------------------------------------------------------------
# Drop-in replacement for the old blastradius.parser.parse_file
# ---------------------------------------------------------------------------


def parse_file(
    filepath: str,
    repo_path: str = ".",
) -> tuple[list, dict]:
    """Parse *filepath* using the registered parser for its extension.

    This is a backward-compatible drop-in replacement for the original
    ``blastradius.parser.parse_file``.  All callers (indexer, incremental,
    tests) that import from ``blastradius.parser`` continue to work because
    ``parser.py`` is updated to re-export this function.

    Returns ``([], {})`` for unsupported file extensions.
    """
    return registry.parse_file(filepath, repo_path)
