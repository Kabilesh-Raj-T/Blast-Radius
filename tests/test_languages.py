"""Tests for the multi-language parser abstraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

from blastradius.languages import registry
from blastradius.languages.base import LanguageParser, ParserRegistry
from blastradius.languages.go_parser import GoParser
from blastradius.languages.java_parser import JavaParser
from blastradius.languages.javascript_parser import JavaScriptParser
from blastradius.languages.python_parser import PythonParser
from blastradius.languages.rust_parser import RustParser
from blastradius.languages.typescript_parser import TypeScriptParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, code: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


def _names(symbols) -> list[str]:
    return [s.function_name or s.unique_id.split(".")[-1] for s in symbols]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestParserRegistry:
    def test_global_registry_has_python(self):
        assert registry.get("foo.py") is not None

    def test_global_registry_has_typescript(self):
        assert registry.get("foo.ts") is not None

    def test_global_registry_has_javascript(self):
        assert registry.get("foo.js") is not None

    def test_global_registry_has_go(self):
        assert registry.get("foo.go") is not None

    def test_global_registry_has_java(self):
        assert registry.get("Foo.java") is not None

    def test_global_registry_has_rust(self):
        assert registry.get("main.rs") is not None

    def test_registry_returns_none_for_unknown_ext(self):
        assert registry.get("data.csv") is None

    def test_parse_file_unknown_returns_empty(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        syms, imp = registry.parse_file(str(f), str(tmp_path))
        assert syms == []
        assert imp == {}

    def test_registry_extensions_frozenset(self):
        exts = registry.extensions
        assert ".py" in exts
        assert ".ts" in exts
        assert ".go" in exts

    def test_custom_registry_register_unregister(self):
        r = ParserRegistry()
        r.register(PythonParser())
        assert r.get("a.py") is not None
        r.unregister(".py")
        assert r.get("a.py") is None

    def test_registry_delegates_parse(self, tmp_path):
        f = _write(tmp_path / "mod.py", "def hello(): pass\n")
        syms, _ = registry.parse_file(str(f), str(tmp_path))
        assert any(s.function_name == "hello" for s in syms)

    def test_language_parser_protocol(self):
        assert isinstance(PythonParser(), LanguageParser)
        assert isinstance(TypeScriptParser(), LanguageParser)
        assert isinstance(GoParser(), LanguageParser)
        assert isinstance(JavaParser(), LanguageParser)
        assert isinstance(RustParser(), LanguageParser)
        assert isinstance(JavaScriptParser(), LanguageParser)


# ---------------------------------------------------------------------------
# Python parser (via shim)
# ---------------------------------------------------------------------------


class TestPythonParserShim:
    def test_backward_compat_import(self):
        """from blastradius.parser import parse_file must still work."""
        from blastradius.parser import parse_file  # noqa: F401

        assert callable(parse_file)

    def test_parse_function(self, tmp_path):
        f = _write(tmp_path / "m.py", "def greet(): pass\n")
        syms, _ = PythonParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "greet" for s in syms)

    def test_parse_class_with_method(self, tmp_path):
        code = """\
            class Foo:
                def bar(self): pass
        """
        f = _write(tmp_path / "m.py", code)
        syms, _ = PythonParser().parse(str(f), str(tmp_path))
        kinds = {s.kind for s in syms}
        assert "class" in kinds
        assert "method" in kinds


# ---------------------------------------------------------------------------
# TypeScript parser
# ---------------------------------------------------------------------------


class TestTypeScriptParser:
    def test_top_level_function(self, tmp_path):
        f = _write(tmp_path / "a.ts", "function doWork(): void {}\n")
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "doWork" for s in syms)

    def test_async_function(self, tmp_path):
        f = _write(tmp_path / "a.ts", "async function fetchData() {}\n")
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "fetchData")
        assert s.async_sync == "async"

    def test_arrow_function(self, tmp_path):
        f = _write(tmp_path / "a.ts", "const myFn = () => {}\n")
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "myFn" for s in syms)

    def test_exported_arrow_function(self, tmp_path):
        f = _write(tmp_path / "a.ts", "export const handler = async (req: Request) => {}\n")
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "handler" for s in syms)

    def test_class_declaration(self, tmp_path):
        f = _write(tmp_path / "a.ts", "class MyService {}\n")
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "MyService" in s.unique_id for s in syms)

    def test_class_extends_and_implements(self, tmp_path):
        code = "class Dog extends Animal implements IAnimal {}\n"
        f = _write(tmp_path / "a.ts", code)
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        cls = next(s for s in syms if s.kind == "class")
        assert "Animal" in (cls.bases or [])
        assert "IAnimal" in (cls.bases or [])

    def test_class_method(self, tmp_path):
        code = """\
class Svc {
  handle() {}
}
"""
        f = _write(tmp_path / "a.ts", code)
        syms, _ = TypeScriptParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "method" and s.function_name == "handle" for s in syms)

    def test_named_imports(self, tmp_path):
        code = "import { readFile, writeFile } from 'fs';\n"
        f = _write(tmp_path / "a.ts", code)
        _, imp = TypeScriptParser().parse(str(f), str(tmp_path))
        assert "readFile" in imp
        assert "writeFile" in imp

    def test_default_import(self, tmp_path):
        code = "import axios from 'axios';\n"
        f = _write(tmp_path / "a.ts", code)
        _, imp = TypeScriptParser().parse(str(f), str(tmp_path))
        assert "axios" in imp

    def test_extensions(self):
        assert ".ts" in TypeScriptParser.EXTENSIONS
        assert ".tsx" in TypeScriptParser.EXTENSIONS


# ---------------------------------------------------------------------------
# JavaScript parser
# ---------------------------------------------------------------------------


class TestJavaScriptParser:
    def test_function_declaration(self, tmp_path):
        f = _write(tmp_path / "a.js", "function init() {}\n")
        syms, _ = JavaScriptParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "init" for s in syms)

    def test_class_with_base(self, tmp_path):
        f = _write(tmp_path / "a.js", "class Cat extends Animal {}\n")
        syms, _ = JavaScriptParser().parse(str(f), str(tmp_path))
        cls = next(s for s in syms if s.kind == "class")
        assert (cls.bases or []) == ["Animal"]

    def test_arrow_function(self, tmp_path):
        f = _write(tmp_path / "a.js", "const fn = () => {}\n")
        syms, _ = JavaScriptParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "fn" for s in syms)

    def test_require_import(self, tmp_path):
        f = _write(tmp_path / "a.js", "const fs = require('fs');\n")
        _, imp = JavaScriptParser().parse(str(f), str(tmp_path))
        assert "fs" in imp

    def test_jsx_extension(self):
        assert ".jsx" in JavaScriptParser.EXTENSIONS

    def test_mjs_extension(self):
        assert ".mjs" in JavaScriptParser.EXTENSIONS


# ---------------------------------------------------------------------------
# Go parser
# ---------------------------------------------------------------------------


class TestGoParser:
    def test_standalone_function(self, tmp_path):
        code = """\
package main

func Add(a, b int) int { return a + b }
"""
        f = _write(tmp_path / "math.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "Add" for s in syms)

    def test_method_with_pointer_receiver(self, tmp_path):
        code = """\
package server

type Server struct{}
func (s *Server) Handle(w http.ResponseWriter) {}
"""
        f = _write(tmp_path / "server.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        m = next((s for s in syms if s.function_name == "Handle"), None)
        assert m is not None
        assert m.class_name == "Server"
        assert m.kind == "method"

    def test_struct_declaration(self, tmp_path):
        code = "package repo\ntype User struct { Name string }\n"
        f = _write(tmp_path / "user.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "User" in s.unique_id for s in syms)

    def test_interface_declaration(self, tmp_path):
        code = "package repo\ntype Handler interface { Handle() error }\n"
        f = _write(tmp_path / "h.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "Handler" in s.unique_id for s in syms)

    def test_package_name_as_module(self, tmp_path):
        code = "package billing\nfunc Invoice() {}\n"
        f = _write(tmp_path / "billing.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        assert all(s.module == "billing" for s in syms)

    def test_imports_single(self, tmp_path):
        code = 'package main\nimport "fmt"\nfunc f() {}\n'
        f = _write(tmp_path / "a.go", code)
        _, imp = GoParser().parse(str(f), str(tmp_path))
        assert "fmt" in imp

    def test_imports_grouped(self, tmp_path):
        code = 'package main\nimport (\n"fmt"\n"strings"\n)\nfunc f() {}\n'
        f = _write(tmp_path / "a.go", code)
        _, imp = GoParser().parse(str(f), str(tmp_path))
        assert "fmt" in imp
        assert "strings" in imp

    def test_unexported_private(self, tmp_path):
        code = "package main\nfunc privateHelper() {}\n"
        f = _write(tmp_path / "a.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "privateHelper")
        assert s.visibility == "private"

    def test_exported_public(self, tmp_path):
        code = "package main\nfunc PublicFn() {}\n"
        f = _write(tmp_path / "a.go", code)
        syms, _ = GoParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "PublicFn")
        assert s.visibility == "public"


# ---------------------------------------------------------------------------
# Java parser
# ---------------------------------------------------------------------------


class TestJavaParser:
    def test_class_declaration(self, tmp_path):
        code = """\
package com.example;
public class Service {}
"""
        f = _write(tmp_path / "Service.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "Service" in s.unique_id for s in syms)

    def test_class_extends_implements(self, tmp_path):
        code = """\
package com.example;
public class Dog extends Animal implements IAnimal {}
"""
        f = _write(tmp_path / "Dog.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        cls = next(s for s in syms if s.kind == "class")
        assert "Animal" in (cls.bases or [])
        assert "IAnimal" in (cls.bases or [])

    def test_method_extraction(self, tmp_path):
        code = """\
package com.example;
public class Svc {
    public void handle(String req) {}
}
"""
        f = _write(tmp_path / "Svc.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "method" and s.function_name == "handle" for s in syms)

    def test_static_method(self, tmp_path):
        code = """\
package com.example;
public class Utils {
    public static String format(String s) { return s; }
}
"""
        f = _write(tmp_path / "Utils.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        m = next((s for s in syms if s.function_name == "format"), None)
        assert m is not None
        assert m.method_kind == "static"

    def test_package_as_module(self, tmp_path):
        code = "package com.example.billing;\npublic class Invoice {}\n"
        f = _write(tmp_path / "Invoice.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        assert all(s.module == "com.example.billing" for s in syms)

    def test_import_extraction(self, tmp_path):
        code = """\
package com.example;
import com.example.util.Parser;
public class Foo {}
"""
        f = _write(tmp_path / "Foo.java", code)
        _, imp = JavaParser().parse(str(f), str(tmp_path))
        assert "Parser" in imp
        assert imp["Parser"] == "com.example.util.Parser"

    def test_private_method(self, tmp_path):
        code = """\
package x;
public class A {
    private void helper() {}
}
"""
        f = _write(tmp_path / "A.java", code)
        syms, _ = JavaParser().parse(str(f), str(tmp_path))
        m = next((s for s in syms if s.function_name == "helper"), None)
        assert m is not None
        assert m.visibility == "private"


# ---------------------------------------------------------------------------
# Rust parser
# ---------------------------------------------------------------------------


class TestRustParser:
    def test_top_level_function(self, tmp_path):
        code = "pub fn process() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        assert any(s.function_name == "process" for s in syms)

    def test_private_function(self, tmp_path):
        code = "fn helper() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "helper")
        assert s.visibility == "private"

    def test_public_function_visibility(self, tmp_path):
        code = "pub fn public_fn() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "public_fn")
        assert s.visibility == "public"

    def test_struct_declaration(self, tmp_path):
        code = "pub struct Server { port: u16 }\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "Server" in s.unique_id for s in syms)

    def test_trait_declaration(self, tmp_path):
        code = "pub trait Handler { fn handle(&self); }\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        assert any(s.kind == "class" and "Handler" in s.unique_id for s in syms)

    def test_impl_method(self, tmp_path):
        code = """\
pub struct Server {}
impl Server {
    pub fn listen(&self) {}
}
"""
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        m = next((s for s in syms if s.function_name == "listen"), None)
        assert m is not None
        assert m.class_name == "Server"
        assert m.kind == "method"

    def test_use_simple(self, tmp_path):
        code = "use std::collections::HashMap;\nfn f() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        _, imp = RustParser().parse(str(f), str(tmp_path))
        assert "HashMap" in imp

    def test_use_grouped(self, tmp_path):
        code = "use std::io::{Read, Write};\nfn f() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        _, imp = RustParser().parse(str(f), str(tmp_path))
        assert "Read" in imp
        assert "Write" in imp

    def test_async_function(self, tmp_path):
        code = "pub async fn fetch() {}\n"
        f = _write(tmp_path / "lib.rs", code)
        syms, _ = RustParser().parse(str(f), str(tmp_path))
        s = next(s for s in syms if s.function_name == "fetch")
        assert s.async_sync == "async"
