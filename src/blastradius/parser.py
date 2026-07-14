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


class FileParser(ast.NodeVisitor):
    """AST visitor to walk the file and extract qualified function names and calls."""

    def __init__(self) -> None:
        self.result: dict[str, list[str]] = {}
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self.class_stack:
            full_name = ".".join(self.class_stack) + "." + node.name
        else:
            full_name = node.name

        extractor = CallExtractor()
        for child in node.body:
            extractor.visit(child)
        self.result[full_name] = extractor.calls
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self.class_stack:
            full_name = ".".join(self.class_stack) + "." + node.name
        else:
            full_name = node.name

        extractor = CallExtractor()
        for child in node.body:
            extractor.visit(child)
        self.result[full_name] = extractor.calls
        self.generic_visit(node)


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

    parser = FileParser()
    parser.visit(tree)
    return parser.result
