"""Parser module for dependency files."""

import ast
from pathlib import Path

import rich

from blastradius.symbol import Symbol


def filepath_to_module(filepath: str, repo_path: str) -> str:
    """Convert a filepath to a Python module name relative to repo_path."""
    abs_filepath = Path(filepath).resolve()
    abs_repo = Path(repo_path).resolve()
    try:
        rel_path = abs_filepath.relative_to(abs_repo)
    except ValueError:
        rel_path = Path(filepath)

    if rel_path.name == "__init__.py":
        parts = rel_path.parent.parts
    else:
        parts = rel_path.with_suffix("").parts

    module_name = ".".join(p for p in parts if p)
    return module_name if module_name else "root"


def get_decorator_name(decorator_node: ast.AST) -> str:
    """Extract a human-readable name of a decorator node."""
    if isinstance(decorator_node, ast.Name):
        return decorator_node.id
    elif isinstance(decorator_node, ast.Attribute):
        parts = []
        curr: ast.AST = decorator_node
        while isinstance(curr, ast.Attribute):
            parts.append(curr.attr)
            curr = curr.value
        if isinstance(curr, ast.Name):
            parts.append(curr.id)
        return ".".join(reversed(parts))
    elif isinstance(decorator_node, ast.Call):
        return get_decorator_name(decorator_node.func)
    return ""


class FileParser(ast.NodeVisitor):
    """AST visitor to walk the file and extract detailed symbols."""

    def __init__(self, filepath: str, repo_path: str) -> None:
        self.filepath = filepath
        self.repo_path = repo_path
        self.module = filepath_to_module(filepath, repo_path)

        # Compute relative filepath for portable symbol IDs and cache lookups
        abs_filepath = Path(filepath).resolve()
        abs_repo = Path(repo_path).resolve()
        try:
            rel_path = abs_filepath.relative_to(abs_repo)
            self.rel_filepath = str(rel_path).replace("\\", "/")
        except ValueError:
            self.rel_filepath = filepath

        self.symbols: list[Symbol] = []

        self.class_stack: list[str] = []
        self.function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.function_ids: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _process_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        self.function_stack.append(node)

        # 1. Class name
        class_name = ".".join(self.class_stack) if self.class_stack else None

        # 2. Unique ID & Nested info
        module_prefix = self.module + "." if self.module else ""
        if len(self.function_stack) >= 2:
            # Nested function definition
            parent_id = self.function_ids[-1]
            unique_id = f"{parent_id}.{node.name}"
            nested_info = {
                "parent_function": self.function_stack[-2].name,
                "parent_id": parent_id,
            }
        else:
            nested_info = None
            if class_name:
                unique_id = f"{module_prefix}{class_name}.{node.name}"
            else:
                unique_id = f"{module_prefix}{node.name}"

        self.function_ids.append(unique_id)

        # 3. Decorators
        decorators = []
        for dec in node.decorator_list:
            dec_name = get_decorator_name(dec)
            if dec_name:
                decorators.append(dec_name)

        # 4. Visibility
        # Starts with single underscore, but not magic dunders
        if node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            visibility = "private"
        else:
            visibility = "public"

        # 5. Async/sync
        async_sync = "async" if is_async else "sync"

        # Create symbol
        symbol = Symbol(
            unique_id=unique_id,
            module=self.module,
            filepath=self.rel_filepath,
            class_name=class_name,
            function_name=node.name,
            decorators=decorators,
            line_no=node.lineno,
            col_offset=node.col_offset,
            visibility=visibility,
            async_sync=async_sync,
            nested_info=nested_info,
        )
        self.symbols.append(symbol)

        self.generic_visit(node)

        self.function_stack.pop()
        self.function_ids.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node, is_async=True)


def parse_file(filepath: str, repo_path: str = ".") -> list[Symbol]:
    """Parse a Python file and extract all defined symbols.

    If the file cannot be parsed due to SyntaxError or UnicodeDecodeError,
    logs a skip warning using rich and returns an empty list.
    """
    try:
        source = Path(filepath).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError) as e:
        rich.print(f"[yellow]SKIP[/] {filepath}: {e}")
        return []

    parser = FileParser(filepath, repo_path)
    parser.visit(tree)
    return parser.symbols
