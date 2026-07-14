"""Dependency and import resolver module."""

from typing import Any

_cache: dict[int, dict[str, list[str]]] = {}


def resolve(name: str, index: Any) -> list[str]:
    """Given a bare function name, resolve it to fully-qualified identifiers.

    Supports both old flat index and new structured index.
    """
    # Fallback to extract symbols dict if it is a structured index
    symbols = index.get("symbols", index) if isinstance(index, dict) else index

    index_id = id(symbols)
    if index_id not in _cache:
        # Pre-build lookup dictionary to optimize O(N) scans to O(1) lookups
        lookup: dict[str, list[str]] = {}
        for key in symbols:
            if ":" in key:
                fn_name = key.rsplit(":", 1)[1]
                bare_name = fn_name.rsplit(".", 1)[-1]
                lookup.setdefault(bare_name, []).append(key)
        _cache[index_id] = lookup

    return _cache[index_id].get(name, [])


def resolve_call(
    call_name: str,
    caller_module: str,
    caller_class: str | None,
    filepath: str,
    imports: dict[str, dict[str, str]],
    symbols: dict[str, dict[str, Any]],
) -> list[str]:
    """Map a function call to the correct symbol in the symbol table.

    Avoids name-based matching whenever import information is available.
    Produces fully qualified function identifiers.
    """
    import_map = imports.get(filepath, {})

    parts = call_name.split(".")
    prefix = parts[0]

    # 1. Resolve using Import Map
    if prefix in import_map:
        imported_target = import_map[prefix]
        if len(parts) > 1:
            fqn = f"{imported_target}." + ".".join(parts[1:])
        else:
            fqn = imported_target

        if fqn in symbols:
            return [fqn]
        return [fqn]

    # 2. Resolve as Local Class Method (self.method / cls.method)
    if (prefix == "self" or prefix == "cls") and len(parts) > 1:
        method_name = parts[1]
        if caller_class:
            module_prefix = f"{caller_module}." if caller_module else ""
            fqn = f"{module_prefix}{caller_class}.{method_name}"
            if fqn in symbols:
                return [fqn]

    # 2b. Resolve as Local Class Method (Class.method where Class is locally defined)
    if len(parts) > 1:
        class_prefix = parts[0]
        method_name = parts[1]
        module_prefix = f"{caller_module}." if caller_module else ""
        class_fqn = f"{module_prefix}{class_prefix}"
        if class_fqn in symbols and symbols[class_fqn].get("kind") == "class":
            fqn = f"{class_fqn}.{method_name}"
            if fqn in symbols:
                return [fqn]

    # 3. Resolve as Local Module Symbol (bare function call)
    if len(parts) == 1:
        module_prefix = f"{caller_module}." if caller_module else ""
        fqn = f"{module_prefix}{call_name}"
        if fqn in symbols:
            return [fqn]
        if caller_class:
            fqn_class = f"{module_prefix}{caller_class}.{call_name}"
            if fqn_class in symbols:
                return [fqn_class]

    # 4. Fallback to Name-based matching
    bare_name = parts[-1]
    matches = []
    for sym_id, sym_dict in symbols.items():
        if sym_dict.get("function_name") == bare_name:
            matches.append(sym_id)
        elif sym_dict.get("kind") == "class" and sym_id.split(".")[-1] == bare_name:
            matches.append(sym_id)

    return matches
