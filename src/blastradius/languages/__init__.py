"""Language parsers package.

Instantiates all built-in language parsers, registers them in a shared
:class:`~blastradius.languages.base.ParserRegistry` singleton, and
re-exports a drop-in ``parse_file`` function with the same signature as
the original ``blastradius.parser.parse_file``.

Adding a new language
---------------------
1. Create ``blastradius/languages/my_lang_parser.py`` with a class that
   has ``EXTENSIONS: ClassVar[frozenset[str]]`` and a ``parse()`` method.
2. Import and register it here::

       from blastradius.languages.my_lang_parser import MyLangParser
       registry.register(MyLangParser())

No other files need to change.
"""

from __future__ import annotations

from blastradius.languages.base import ParserRegistry
from blastradius.languages.go_parser import GoParser
from blastradius.languages.java_parser import JavaParser
from blastradius.languages.javascript_parser import JavaScriptParser
from blastradius.languages.python_parser import PythonParser
from blastradius.languages.rust_parser import RustParser
from blastradius.languages.typescript_parser import TypeScriptParser

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
