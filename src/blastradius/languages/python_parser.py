"""Python language parser — wraps the existing AST-based implementation.

This module re-uses all the logic from the original ``parser.py`` and
exposes it through the :class:`LanguageParser` Protocol so it can be
registered in :class:`~blastradius.languages.base.ParserRegistry`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, ClassVar

import rich

from blastradius.symbol import Symbol

# ---------------------------------------------------------------------------
# Helpers (unchanged from original parser.py)
# ---------------------------------------------------------------------------


def filepath_to_module(filepath: str, repo_path: str) -> str:
    """Convert a filepath to a Python module name relative to repo_path using RepositoryContext."""
    from blastradius.context import get_repository_context

    ctx = get_repository_context(repo_path)
    return ctx.filepath_to_module(filepath)


def get_decorator_name(decorator_node: ast.AST) -> str:
    """Extract a human-readable name of a decorator node."""
    if isinstance(decorator_node, ast.Name):
        return decorator_node.id
    elif isinstance(decorator_node, ast.Attribute):
        parts: list[str] = []
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


def get_relative_base(module_name: str, filepath: str, level: int) -> str:
    """Resolve the package base for a relative import level."""
    parts = module_name.split(".") if module_name else []
    is_init = Path(filepath).name == "__init__.py"

    drop = (level - 1) if is_init else level
    drop = max(0, drop)

    if drop >= len(parts):
        base_parts: list[str] = []
    else:
        base_parts = list(parts[: len(parts) - drop])

    return ".".join(base_parts)


class ImportCollector(ast.NodeVisitor):
    """AST visitor to collect imported names and map them to fully qualified paths."""

    def __init__(self, current_module: str, filepath: str, repo_path: str) -> None:
        self.current_module = current_module
        self.filepath = filepath
        self.repo_path = repo_path
        self.import_map: dict[str, Any] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            asname = alias.asname
            if asname:
                self.import_map[asname] = name
            else:
                prefix = name.split(".")[0]
                self.import_map[prefix] = prefix
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = node.module
        level = node.level or 0

        if level > 0:
            rel_base = get_relative_base(self.current_module, self.filepath, level)
            if module_name:
                base_package = f"{rel_base}.{module_name}" if rel_base else module_name
            else:
                base_package = rel_base
        else:
            base_package = module_name or ""

        for alias in node.names:
            name = alias.name
            asname = alias.asname
            local_name = asname if asname else name

            if name == "*":
                self.import_map.setdefault("__wildcards__", []).append(base_package)
                continue

            fqn = f"{base_package}.{name}" if base_package else name
            self.import_map[local_name] = fqn

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                exported = self._literal_string_sequence(node.value)
                if exported is not None:
                    self.import_map["__all__"] = exported
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == "__all__":
            if node.value is not None:
                exported = self._literal_string_sequence(node.value)
                if exported is not None:
                    self.import_map["__all__"] = exported
        self.generic_visit(node)

    @staticmethod
    def _literal_string_sequence(node: ast.AST) -> list[str] | None:
        if not isinstance(node, (ast.List, ast.Tuple)):
            return None
        exported: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return None
            exported.append(element.value)
        return exported


def get_call_name(node: ast.AST) -> str:
    """Recursively resolve name/attribute nodes to a dot-separated string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        val = get_call_name(node.value)
        return f"{val}.{node.attr}" if val else node.attr
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "super":
        return "super"
    return ""


class LocalNameCollector(ast.NodeVisitor):
    """Collect local variable and parameter names in a function scope."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.names.add(node.target.id)
        self.generic_visit(node)

    # Do not recurse into nested function or class definitions
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass


class CallExtractor(ast.NodeVisitor):
    """AST visitor to extract call targets within a function body."""

    def __init__(self, local_names: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.local_names = local_names if local_names is not None else set()

    def visit_Call(self, node: ast.Call) -> None:
        call_name = get_call_name(node.func)
        is_dynamic = False
        dyn_type = None

        if isinstance(node.func, ast.Name):
            name_id = node.func.id
            if name_id in ("getattr", "setattr", "eval", "exec", "__import__"):
                is_dynamic = True
                dyn_type = name_id
            elif name_id == "partial":
                is_dynamic = True
                dyn_type = "partial"
            elif name_id in self.local_names:
                is_dynamic = True
                dyn_type = "runtime_dispatch"
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in ("import_module", "__getattr__", "__call__"):
                is_dynamic = True
                dyn_type = attr_name
            elif call_name == "functools.partial":
                is_dynamic = True
                dyn_type = "partial"
        elif isinstance(node.func, ast.Lambda):
            is_dynamic = True
            dyn_type = "lambda"

        if is_dynamic and dyn_type:
            self.calls.append(f"dynamic:{dyn_type}:{node.lineno}:{node.col_offset}")
        elif call_name:
            self.calls.append(call_name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass


class ScopeExtractor(ast.NodeVisitor):
    """Extract ``global``, ``nonlocal``, and local definition names from a function body.

    Recurses into compound statements (``if``/``for``/``try``/``with``/…) to
    find ``global``/``nonlocal`` declarations at any depth, but does **not**
    recurse into nested function or class bodies (those are separate scopes).
    """

    def __init__(self) -> None:
        self.globals: list[str] = []
        self.nonlocals: list[str] = []
        self.local_defs: list[str] = []

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.extend(node.names)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocals.extend(node.names)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Record the name but do NOT recurse — nested body is a separate scope
        self.local_defs.append(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.local_defs.append(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.local_defs.append(node.name)


def extract_local_types(
    node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None
) -> dict[str, str]:
    """Build a local type map from function parameters, AnnAssign, and instantiations."""
    local_types: dict[str, str] = {}

    if class_name:
        innermost = class_name.split(".")[-1]
        local_types["self"] = innermost
        local_types["cls"] = innermost

    for arg in node.args.args:
        if arg.annotation:
            anno_name = get_call_name(arg.annotation)
            if anno_name:
                local_types[arg.arg] = anno_name

    class AssignmentVisitor(ast.NodeVisitor):
        def visit_AnnAssign(self, assign_node: ast.AnnAssign) -> None:
            if isinstance(assign_node.target, ast.Name) and assign_node.annotation:
                anno_name = get_call_name(assign_node.annotation)
                if anno_name:
                    local_types[assign_node.target.id] = anno_name
            self.generic_visit(assign_node)

        def visit_Assign(self, assign_node: ast.Assign) -> None:
            if isinstance(assign_node.value, ast.Call) and isinstance(
                assign_node.value.func, ast.Name
            ):
                class_type = assign_node.value.func.id
                for target in assign_node.targets:
                    if isinstance(target, ast.Name):
                        local_types[target.id] = class_type
            self.generic_visit(assign_node)

        def visit_FunctionDef(self, nested_node: ast.FunctionDef) -> None:
            pass

        def visit_AsyncFunctionDef(self, nested_node: ast.AsyncFunctionDef) -> None:
            pass

        def visit_ClassDef(self, nested_node: ast.ClassDef) -> None:
            pass

    visitor = AssignmentVisitor()
    for child in node.body:
        visitor.visit(child)
    return local_types


class FileParser(ast.NodeVisitor):
    """AST visitor to walk the file and extract detailed symbols."""

    def __init__(self, filepath: str, repo_path: str) -> None:
        self.filepath = filepath
        self.repo_path = repo_path
        self.module = filepath_to_module(filepath, repo_path)

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
        module_prefix = self.module + "." if self.module else ""
        class_name = ".".join(self.class_stack) if self.class_stack else None

        if class_name:
            unique_id = f"{module_prefix}{class_name}.{node.name}"
        else:
            unique_id = f"{module_prefix}{node.name}"

        bases = [get_decorator_name(base) for base in node.bases if get_decorator_name(base)]

        visibility = (
            "private"
            if node.name.startswith("_")
            and not (node.name.startswith("__") and node.name.endswith("__"))
            else "public"
        )

        self.symbols.append(
            Symbol(
                unique_id=unique_id,
                module=self.module,
                filepath=self.rel_filepath,
                class_name=class_name,
                function_name=None,
                decorators=[],
                line_no=node.lineno,
                col_offset=node.col_offset,
                visibility=visibility,
                async_sync=None,
                nested_info=None,
                kind="class",
                method_kind=None,
                bases=bases,
                calls=None,
                local_types=None,
                end_line_no=getattr(node, "end_lineno", None),
            )
        )

        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _process_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        self.function_stack.append(node)

        class_name = ".".join(self.class_stack) if self.class_stack else None
        module_prefix = self.module + "." if self.module else ""

        nested_info: dict[str, Any] | None = None
        if len(self.function_stack) >= 2:
            parent_id = self.function_ids[-1]
            unique_id = f"{parent_id}.{node.name}"
            nested_info = {
                "parent_function": self.function_stack[-2].name,
                "parent_id": parent_id,
            }
        else:
            if class_name:
                unique_id = f"{module_prefix}{class_name}.{node.name}"
            else:
                unique_id = f"{module_prefix}{node.name}"

        self.function_ids.append(unique_id)

        decorators = [
            get_decorator_name(dec) for dec in node.decorator_list if get_decorator_name(dec)
        ]

        visibility = (
            "private"
            if node.name.startswith("_")
            and not (node.name.startswith("__") and node.name.endswith("__"))
            else "public"
        )

        async_sync = "async" if is_async else "sync"

        if class_name:
            kind = "method"
            if "staticmethod" in decorators:
                method_kind = "static"
            elif "classmethod" in decorators:
                method_kind = "class"
            elif any(
                d == "property" or d.endswith(".setter") or d.endswith(".getter")
                for d in decorators
            ):
                method_kind = "property"
            elif any(d == "abstractmethod" or d == "abc.abstractmethod" for d in decorators):
                method_kind = "abstract"
            else:
                method_kind = "instance"
        else:
            kind = "function"
            method_kind = None

        # Collect local variable names and parameters
        local_names = set()
        for arg in node.args.args:
            local_names.add(arg.arg)
        if node.args.vararg:
            local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_names.add(node.args.kwarg.arg)
        for arg in node.args.kwonlyargs:
            local_names.add(arg.arg)

        local_collector = LocalNameCollector()
        for child in node.body:
            local_collector.visit(child)
        local_names.update(local_collector.names)

        extractor = CallExtractor(local_names)
        for child in node.body:
            extractor.visit(child)
        for dec in node.decorator_list:
            extractor.visit(dec)

        local_types = extract_local_types(node, class_name)

        # ── Scope declarations (global / nonlocal / local defs) ───────
        scope_ext = ScopeExtractor()
        for child in node.body:
            scope_ext.visit(child)

        scope_info: dict[str, list[str]] = {}
        if scope_ext.globals:
            scope_info["globals"] = scope_ext.globals
        if scope_ext.nonlocals:
            scope_info["nonlocals"] = scope_ext.nonlocals
        if scope_ext.local_defs:
            scope_info["local_defs"] = scope_ext.local_defs

        # Merge scope_info into nested_info (only when non-empty)
        if scope_info:
            if nested_info is None:
                nested_info = {}
            nested_info["scope_info"] = scope_info

        self.symbols.append(
            Symbol(
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
                kind=kind,
                method_kind=method_kind,
                bases=None,
                calls=extractor.calls,
                local_types=local_types,
                end_line_no=getattr(node, "end_lineno", None),
            )
        )

        self.generic_visit(node)
        self.function_stack.pop()
        self.function_ids.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node, is_async=True)


# ---------------------------------------------------------------------------
# Parser class (LanguageParser implementation)
# ---------------------------------------------------------------------------


class PythonParser:
    """Python language parser using the ``ast`` module.

    This is the original parser implementation, now wrapped to satisfy
    the :class:`~blastradius.languages.base.LanguageParser` Protocol.
    """

    EXTENSIONS: ClassVar[frozenset[str]] = frozenset({".py"})

    def parse(
        self,
        filepath: str,
        repo_path: str,
    ) -> tuple[list[Symbol], dict[str, str]]:
        """Parse a Python source file using the standard ``ast`` module."""
        try:
            source = Path(filepath).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, UnicodeDecodeError) as e:
            rich.print(f"[yellow]SKIP[/] {filepath}: {e}")
            return [], {}

        file_parser = FileParser(filepath, repo_path)
        file_parser.visit(tree)

        module_name = filepath_to_module(filepath, repo_path)
        collector = ImportCollector(module_name, filepath, repo_path)
        collector.visit(tree)

        return file_parser.symbols, collector.import_map
