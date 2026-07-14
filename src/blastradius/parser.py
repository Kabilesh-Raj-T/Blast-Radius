"""Parser module for dependency files."""

import ast
from pathlib import Path

import rich


class CallExtractor(ast.NodeVisitor):
    """AST visitor to extract call targets within a function body.

    It stops recursing when it reaches nested function definitions.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.append(node.func.attr)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Do not recurse into nested function definitions
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Do not recurse into nested async function definitions
        pass


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

        extractor = CallExtractor()
        for child in node.body:
            extractor.visit(child)

        result[node.name] = extractor.calls

    return result
