"""Backward-compatibility shim for the parser module.

The parser implementation has moved to :mod:`blastradius.languages`.
This module re-exports everything that external code previously imported
from ``blastradius.parser`` so that existing tests and callers require
zero changes.
"""

# Re-export the primary entry-point
from blastradius.languages import parse_file  # noqa: F401

# Re-export internal helpers that tests import directly
from blastradius.languages.python_parser import (  # noqa: F401
    CallExtractor,
    FileParser,
    ImportCollector,
    extract_local_types,
    filepath_to_module,
    get_call_name,
    get_decorator_name,
    get_relative_base,
)

__all__ = [
    "parse_file",
    "filepath_to_module",
    "get_decorator_name",
    "get_relative_base",
    "ImportCollector",
    "get_call_name",
    "CallExtractor",
    "extract_local_types",
    "FileParser",
]
