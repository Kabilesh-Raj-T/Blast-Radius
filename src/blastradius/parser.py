"""Parser module for dependency files."""

import ast
from pathlib import Path

import rich


def parse_file(filepath: str) -> dict[str, list[str]]:
    """Parse a Python file and extract function definitions and their calls.

    If the file cannot be parsed due to SyntaxError or UnicodeDecodeError,
    logs a skip warning using rich and returns an empty dictionary.
    """
    try:
        source = Path(filepath).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError) as e:
        rich.print(f"[yellow]SKIP[/] {filepath}: {e}")
        return {}

    result = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        calls = []
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)

        result[node.name] = calls

    return result
