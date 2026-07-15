"""Dependency and import resolver module."""

from pathlib import Path
from typing import Any

_cache: dict[int, dict[str, list[str]]] = {}


def invalidate_caches() -> None:
    """Clear all resolver caches."""
    _cache.clear()
    _module_symbols_cache.clear()
    _module_to_file_cache.clear()
    _c3_mro_cache.clear()
    _resolve_call_cache.clear()
    _name_to_symbols_cache.clear()


def _legacy_module_from_filepath(filepath: str) -> str:
    p = Path(filepath.replace("\\", "/"))
    if p.name == "__init__.py":
        parts = p.parent.parts
    else:
        parts = p.with_suffix("").parts
    module_name = ".".join(parts)
    return module_name if module_name else "root"


def _build_module_to_file(
    symbols: dict[str, dict[str, Any]],
    imports: dict[str, dict[str, Any]],
    modules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Build a canonical module-to-file map without guessing when metadata exists."""
    mapping: dict[str, str] = {}

    if modules:
        for filepath, metadata in modules.items():
            module_name = metadata.get("module")
            if isinstance(module_name, str) and module_name:
                mapping[module_name] = filepath

    for sym_dict in symbols.values():
        if not isinstance(sym_dict, dict):
            continue
        module_name = sym_dict.get("module")
        fpath = sym_dict.get("filepath")
        if isinstance(module_name, str) and module_name and isinstance(fpath, str):
            mapping.setdefault(module_name, fpath)

    for filepath in imports:
        mapping.setdefault(_legacy_module_from_filepath(filepath), filepath)

    return mapping


_module_symbols_cache: dict[int, dict[str, list[tuple[str, dict]]]] = {}


def _get_module_symbols(symbols: dict[str, dict]) -> dict[str, list[tuple[str, dict]]]:
    """Return (and cache) a module-name -> [(sym_id, sym_dict)] index."""
    key = id(symbols)
    if key in _module_symbols_cache:
        return _module_symbols_cache[key]
    index: dict[str, list[tuple[str, dict]]] = {}
    for sym_id, sym_dict in symbols.items():
        mod = sym_dict.get("module", "")
        if mod:
            index.setdefault(mod, []).append((sym_id, sym_dict))
    _module_symbols_cache[key] = index
    return index


def _direct_public_symbols(
    target_module: str,
    symbols: dict[str, dict[str, Any]],
) -> dict[str, str]:
    exported: dict[str, str] = {}
    module_index = _get_module_symbols(symbols)
    for sym_id, sym_dict in module_index.get(target_module, []):
        if (
            sym_dict.get("kind") in ("function", "class")
            and sym_dict.get("visibility") == "public"
            and sym_dict.get("class_name") is None
        ):
            short_name = sym_dict.get("function_name") or sym_id.split(".")[-1]
            exported[short_name] = sym_id
    return exported


def _module_exports(
    target_module: str,
    target_imports: dict[str, Any],
    symbols: dict[str, dict[str, Any]],
) -> dict[str, str]:
    direct_symbols = _direct_public_symbols(target_module, symbols)
    imported_symbols = {
        local_name: fqn
        for local_name, fqn in target_imports.items()
        if isinstance(fqn, str) and not local_name.startswith("__") and local_name != "*"
    }

    explicit_all = target_imports.get("__all__")
    if isinstance(explicit_all, list) and all(isinstance(name, str) for name in explicit_all):
        exported: dict[str, str] = {}
        for name in explicit_all:
            if name in imported_symbols:
                exported[name] = imported_symbols[name]
            elif name in direct_symbols:
                exported[name] = direct_symbols[name]
        return exported

    return {**imported_symbols, **direct_symbols}


def resolve_imports_transitively(index: Any) -> None:
    """Expand wildcards and resolve transitive import chains in an index."""
    if not isinstance(index, dict):
        return
    symbols = index.get("symbols", {})
    imports = index.get("imports", {})
    modules = index.get("modules", {})

    module_to_file = _build_module_to_file(symbols, imports, modules)
    _module_to_file_cache[id(symbols)] = module_to_file

    # 1. Expand wildcard imports iteratively. Cycles converge because each pass
    # only adds a local binding that was not already present.
    changed = True
    limit = max(10, len(imports) + 1)
    while changed and limit > 0:
        changed = False
        limit -= 1
        for _filepath, file_imports in list(imports.items()):
            wildcards = file_imports.get("__wildcards__")
            if not isinstance(wildcards, list):
                continue
            for target_module in list(wildcards):
                if not isinstance(target_module, str):
                    continue
                target_file = module_to_file.get(target_module)
                if not target_file:
                    continue
                target_imports = imports.get(target_file, {})
                exports = _module_exports(target_module, target_imports, symbols)
                explicit_all = target_imports.get("__all__")
                if isinstance(explicit_all, list) and all(
                    isinstance(name, str) for name in explicit_all
                ):
                    public_names = set(_direct_public_symbols(target_module, symbols))
                    public_names.update(
                        name
                        for name, value in target_imports.items()
                        if isinstance(value, str) and not name.startswith("__") and name != "*"
                    )
                    excluded = sorted(public_names - set(explicit_all))
                    if excluded:
                        existing = file_imports.setdefault("__star_excludes__", [])
                        if isinstance(existing, list):
                            for name in excluded:
                                if name not in existing:
                                    existing.append(name)
                for local_name, fqn in exports.items():
                    if local_name not in file_imports:
                        file_imports[local_name] = fqn
                        changed = True

    for file_imports in imports.values():
        file_imports.pop("__wildcards__", None)

    def split_fqn(fqn: str) -> tuple[str, str] | None:
        parts = fqn.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in module_to_file:
                suffix = ".".join(parts[i:])
                return prefix, suffix
        return None

    def resolve_fqn_transitively(fqn: str, visited: set[str]) -> str:
        if fqn in visited:
            return fqn
        visited.add(fqn)

        split = split_fqn(fqn)
        if not split:
            return fqn

        mod_name, suffix = split
        if not suffix:
            return fqn

        target_file = module_to_file[mod_name]
        target_imports = imports.get(target_file, {})
        suffix_parts = suffix.split(".")
        first_suffix_part = suffix_parts[0]

        imported_fqn = target_imports.get(first_suffix_part)
        if isinstance(imported_fqn, str):
            new_fqn = imported_fqn
            if len(suffix_parts) > 1:
                new_fqn = f"{imported_fqn}." + ".".join(suffix_parts[1:])
            return resolve_fqn_transitively(new_fqn, visited)

        return fqn

    for _filepath, file_imports in imports.items():
        for local_name, fqn in list(file_imports.items()):
            if local_name.startswith("__") or not isinstance(fqn, str):
                continue
            file_imports[local_name] = resolve_fqn_transitively(fqn, set())


_module_to_file_cache: dict[int, dict[str, str]] = {}


def get_module_to_file(
    symbols: dict[str, dict[str, Any]],
    imports: dict[str, dict[str, Any]],
) -> dict[str, str]:
    sym_id = id(symbols)
    if sym_id not in _module_to_file_cache:
        _module_to_file_cache[sym_id] = _build_module_to_file(symbols, imports)
    return _module_to_file_cache[sym_id]


def resolve_fqn_transitively_cached(
    fqn: str,
    symbols: dict[str, dict[str, Any]],
    imports: dict[str, dict[str, Any]],
    visited: set[str],
) -> str:
    module_to_file = get_module_to_file(symbols, imports)

    def split_fqn(name: str) -> tuple[str, str] | None:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in module_to_file:
                suffix = ".".join(parts[i:])
                return prefix, suffix
        return None

    if fqn in visited:
        return fqn
    visited.add(fqn)

    split = split_fqn(fqn)
    if not split:
        return fqn

    mod_name, suffix = split
    if not suffix:
        return fqn

    target_file = module_to_file[mod_name]
    target_imports = imports.get(target_file, {})
    suffix_parts = suffix.split(".")
    first_suffix_part = suffix_parts[0]

    if first_suffix_part in target_imports:
        imported_fqn = target_imports[first_suffix_part]
        new_fqn = imported_fqn
        if len(suffix_parts) > 1:
            new_fqn = f"{imported_fqn}." + ".".join(suffix_parts[1:])
        return resolve_fqn_transitively_cached(new_fqn, symbols, imports, visited)

    return fqn


_c3_mro_cache: dict[int, dict[str, list[str]]] = {}


def get_c3_mro(
    class_fqn: str, symbols: dict[str, dict[str, Any]], imports: dict[str, dict[str, Any]]
) -> list[str]:
    sym_id = id(symbols)
    if sym_id not in _c3_mro_cache:
        _c3_mro_cache[sym_id] = {}

    if class_fqn not in _c3_mro_cache[sym_id]:
        _c3_mro_cache[sym_id][class_fqn] = compute_c3_mro(class_fqn, symbols, imports, set())
    return _c3_mro_cache[sym_id][class_fqn]


def compute_c3_mro(
    class_fqn: str,
    symbols: dict[str, dict[str, Any]],
    imports: dict[str, dict[str, Any]],
    visited: set[str],
) -> list[str]:
    if class_fqn in visited:
        return [class_fqn]
    visited.add(class_fqn)

    class_sym = symbols.get(class_fqn)
    if not class_sym:
        return [class_fqn]

    bases = class_sym.get("bases") or []
    resolved_bases = []
    base_module = class_sym.get("module", "")
    for base in bases:
        base_classes, _ = resolve_call_with_certainty(
            base, base_module, None, class_sym.get("filepath", ""), imports, symbols
        )
        if base_classes:
            resolved_bases.append(base_classes[0])
        else:
            resolved_bases.append(f"{base_module}.{base}" if base_module else base)

    base_mros = []
    for base_fqn in resolved_bases:
        base_mros.append(compute_c3_mro(base_fqn, symbols, imports, visited.copy()))

    return [class_fqn] + merge_c3(base_mros, resolved_bases)


def merge_c3(mros: list[list[str]], bases: list[str]) -> list[str]:
    lists = [list(mro) for mro in mros] + [list(bases)]
    res = []
    while True:
        lists = [seq for seq in lists if seq]
        if not lists:
            break
        candidate = None
        for seq in lists:
            head = seq[0]
            in_tail = False
            for other_list in lists:
                if head in other_list[1:]:
                    in_tail = True
                    break
            if not in_tail:
                candidate = head
                break
        if candidate is None:
            # Fallback for MRO conflict to maintain static robustness
            for seq in lists:
                if seq:
                    candidate = seq[0]
                    break
            if candidate is None:
                break
        res.append(candidate)
        for seq in lists:
            if seq and seq[0] == candidate:
                seq.pop(0)
    return res


def find_method_in_mro_all(
    class_fqn: str,
    method_name: str,
    symbols: dict[str, dict[str, Any]],
    imports: dict[str, dict[str, Any]],
    visited: set[str],
) -> list[tuple[str, float]]:
    mro = get_c3_mro(class_fqn, symbols, imports)

    # 1. Collect all classes in the MRO that define the method
    defining_classes = []
    for c_fqn in mro:
        method_fqn = f"{c_fqn}.{method_name}"
        if method_fqn in symbols:
            defining_classes.append(c_fqn)

    # 2. Filter out ancestor classes that are overridden by descendants
    filtered_classes = []
    for c1 in defining_classes:
        overridden = False
        for c2 in defining_classes:
            if c1 != c2:
                # If c2 is a descendant of c1, then c2 overrides c1's method
                c1_mro = get_c3_mro(c2, symbols, imports)
                if c1 in c1_mro:
                    overridden = True
                    break
        if not overridden:
            filtered_classes.append(c1)

    # 3. Return matches for the remaining classes
    return [(f"{c_fqn}.{method_name}", 0.95) for c_fqn in filtered_classes]


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
        for k in lookup:
            lookup[k].sort()
        _cache[index_id] = lookup

    return _cache[index_id].get(name, [])


# ---------------------------------------------------------------------------
# Scope-chain helpers (lexical scope, closures, global/nonlocal)
# ---------------------------------------------------------------------------


def _walk_enclosing_scopes(
    name: str,
    scope_id: str,
    symbols: dict[str, dict[str, Any]],
) -> tuple[list[str], float] | None:
    """Walk up the enclosing-function chain looking for *name* in ``local_defs``.

    Returns ``([fqn], certainty)`` on the first hit, or ``None``.
    """
    visited: set[str] = set()
    current: str | None = scope_id

    while current and current not in visited:
        visited.add(current)
        scope_sym = symbols.get(current)
        if scope_sym is None:
            break

        scope_nested = scope_sym.get("nested_info") or {}
        scope_scope_info = scope_nested.get("scope_info", {})

        if name in scope_scope_info.get("local_defs", []):
            fqn = f"{current}.{name}"
            if fqn in symbols:
                return [fqn], 0.95

        current = scope_nested.get("parent_id")

    return None


def _resolve_via_scope_chain(
    name: str,
    caller_id: str,
    caller_module: str,
    symbols: dict[str, dict[str, Any]],
) -> tuple[list[str], float] | None:
    """Attempt to resolve a bare *name* by walking the lexical scope chain.

    Resolution order (mirrors Python's LEGB rule for ``def`` names):

    1. ``global`` declaration → jump to module scope.
    2. ``nonlocal`` declaration → start from the enclosing scope.
    3. Caller's own ``local_defs`` (functions/classes defined in its body).
    4. Walk up each enclosing scope's ``local_defs``.

    Returns ``([fqn], certainty)`` on the first hit, or ``None`` if the
    scope chain does not resolve the name (so the caller should fall through
    to import-map / fallback resolution).
    """
    caller_sym = symbols.get(caller_id)
    if caller_sym is None:
        return None

    nested_info = caller_sym.get("nested_info") or {}
    scope_info = nested_info.get("scope_info", {})

    # 1. ``global`` — bind directly to module namespace
    if name in scope_info.get("globals", []):
        module_prefix = f"{caller_module}." if caller_module else ""
        fqn = f"{module_prefix}{name}"
        if fqn in symbols:
            return [fqn], 0.95
        # The name is global but not a known symbol (could be a variable
        # assigned at module level, or set by an import).  Fall through to
        # let the import-map / fallback handle it.
        return None

    # 2. ``nonlocal`` — start search from the enclosing scope
    if name in scope_info.get("nonlocals", []):
        parent_id = nested_info.get("parent_id")
        if parent_id:
            return _walk_enclosing_scopes(name, parent_id, symbols)
        return None

    # 3. Caller's own local definitions (nested functions / classes)
    if name in scope_info.get("local_defs", []):
        fqn = f"{caller_id}.{name}"
        if fqn in symbols:
            return [fqn], 0.98

    # 4. Walk enclosing scopes
    parent_id = nested_info.get("parent_id")
    if parent_id:
        result = _walk_enclosing_scopes(name, parent_id, symbols)
        if result:
            return result

    return None


# ---------------------------------------------------------------------------
# Primary resolution functions
# ---------------------------------------------------------------------------

_resolve_call_cache: dict[tuple, tuple[list[str], float]] = {}

# Pre-built reverse index: function_name / class_name -> [sym_id]
# Keyed by id(symbols) so it is rebuilt when the symbol table changes.
_name_to_symbols_cache: dict[int, dict[str, list[str]]] = {}


def _get_name_to_symbols(symbols: dict[str, dict]) -> dict[str, list[str]]:
    """Return (and cache) a reverse index from bare name -> list of sym_ids."""
    key = id(symbols)
    if key in _name_to_symbols_cache:
        return _name_to_symbols_cache[key]
    index: dict[str, list[str]] = {}
    for sym_id, sym_dict in symbols.items():
        fn = sym_dict.get("function_name")
        if fn:
            index.setdefault(fn, []).append(sym_id)
        if sym_dict.get("kind") == "class":
            bare = sym_id.split(".")[-1]
            index.setdefault(bare, []).append(sym_id)
    for k in index:
        index[k].sort()
    _name_to_symbols_cache[key] = index
    return index


def resolve_call_with_certainty(
    call_name: str,
    caller_module: str,
    caller_class: str | None,
    filepath: str,
    imports: dict[str, dict[str, Any]],
    symbols: dict[str, dict[str, Any]],
    local_types: dict[str, str] | None = None,
    caller_id: str | None = None,
    _visited: set[tuple[str, str | None, str]] | None = None,
) -> tuple[list[str], float]:
    if _visited is None:
        _visited = set()

    cycle_key = (caller_module, caller_class, call_name)
    if cycle_key in _visited:
        from blastradius.core.diagnostics import tracker

        tracker.log_structured("circular_call_resolution_aborted")
        return [], 0.60

    _visited.add(cycle_key)

    lt_key = frozenset(local_types.items()) if local_types else None
    cache_key = (id(symbols), filepath, caller_module, caller_class, caller_id, call_name, lt_key)
    if cache_key in _resolve_call_cache:
        _visited.remove(cycle_key)
        return _resolve_call_cache[cache_key]

    matches, certainty = _resolve_call_with_certainty_raw(
        call_name,
        caller_module,
        caller_class,
        filepath,
        imports,
        symbols,
        local_types,
        caller_id,
        _visited,
    )
    resolved_matches = []
    for m in matches:
        resolved_matches.append(resolve_fqn_transitively_cached(m, symbols, imports, set()))
    resolved_matches = sorted(list(set(resolved_matches)))
    res = (resolved_matches, certainty)
    _resolve_call_cache[cache_key] = res
    _visited.remove(cycle_key)
    return res


def _resolve_call_with_certainty_raw(
    call_name: str,
    caller_module: str,
    caller_class: str | None,
    filepath: str,
    imports: dict[str, dict[str, Any]],
    symbols: dict[str, dict[str, Any]],
    local_types: dict[str, str] | None = None,
    caller_id: str | None = None,
    _visited: set[tuple[str, str | None, str]] | None = None,
) -> tuple[list[str], float]:
    """Like :func:`resolve_call` but also returns the resolution certainty.

    Returns
    -------
    matches:
        List of fully-qualified symbol IDs that the call resolves to.
    certainty:
        A float in ``[0.0, 1.0]`` indicating how confident the resolution
        method is:

        - ``1.00`` — resolved via the import map (unambiguous)
        - ``0.98`` — resolved via lexical scope (own local definition)
        - ``0.95`` — resolved via lexical scope (enclosing scope / global /
          nonlocal) or ``self``/``cls`` method lookup
        - ``0.90`` — resolved via local module or local class method
        - ``0.85`` — resolved via local type annotation
        - ``0.60`` — resolved via name-based fallback (may be ambiguous)
    """
    import_map = imports.get(filepath, {})
    parts = call_name.split(".")
    prefix = parts[0]

    # ── 0. Scope-chain resolution for bare names ──────────────────────
    # This MUST run before the import-map check so that a local ``def``
    # correctly shadows an imported name of the same spelling.
    if len(parts) == 1 and caller_id:
        scope_result = _resolve_via_scope_chain(
            call_name,
            caller_id,
            caller_module,
            symbols,
        )
        if scope_result is not None:
            return scope_result

    # ── 1. Local variable types (annotated parameters / assignments) ──
    if local_types and prefix in local_types and len(parts) > 1:
        class_type = local_types[prefix]
        method_name = ".".join(parts[1:])
        resolved_classes, _ = resolve_call_with_certainty(
            class_type,
            caller_module,
            caller_class,
            filepath,
            imports,
            symbols,
            local_types,
            caller_id=caller_id,
            _visited=_visited,
        )
        for class_fqn in resolved_classes:
            res = find_method_in_mro_all(class_fqn, method_name, symbols, imports, set())
            if res:
                return [r[0] for r in res], 0.85
        return [], 0.85

    # ── 2. Import map (highest certainty — statically deterministic) ──
    if prefix in import_map:
        imported_target = import_map[prefix]
        fqn = f"{imported_target}." + ".".join(parts[1:]) if len(parts) > 1 else imported_target
        return [fqn], 1.0

    # ── 3a. self / cls method call ────────────────────────────────────
    if (prefix in ("this", "self", "cls")) and len(parts) > 1:
        method_name = parts[1]
        if caller_class:
            module_prefix = f"{caller_module}." if caller_module else ""
            class_fqn = f"{module_prefix}{caller_class}"
            res = find_method_in_mro_all(class_fqn, method_name, symbols, imports, set())
            if res:
                return [r[0] for r in res], max(r[1] for r in res)

    # ── 3b. super() method call ───────────────────────────────────────
    if prefix == "super" and len(parts) > 1:
        method_name = parts[1]
        if caller_class:
            module_prefix = f"{caller_module}." if caller_module else ""
            class_fqn = f"{module_prefix}{caller_class}"
            class_sym = symbols.get(class_fqn)
            if class_sym:
                bases = class_sym.get("bases") or []
                super_matches = []
                for base in bases:
                    base_classes, _ = resolve_call_with_certainty(
                        base, caller_module, None, filepath, imports, symbols, _visited=_visited
                    )
                    for base_fqn in base_classes:
                        res = find_method_in_mro_all(base_fqn, method_name, symbols, imports, set())
                        super_matches.extend(res)
                if super_matches:
                    return [r[0] for r in super_matches], max(r[1] for r in super_matches)

    # ── 3c. Local class method (ClassName.method) ─────────────────────
    if len(parts) > 1:
        class_prefix = parts[0]
        method_name = parts[1]
        module_prefix = f"{caller_module}." if caller_module else ""
        class_fqn = f"{module_prefix}{class_prefix}"
        if class_fqn in symbols and symbols[class_fqn].get("kind") == "class":
            res = find_method_in_mro_all(class_fqn, method_name, symbols, imports, set())
            if res:
                return [r[0] for r in res], 0.90

    # ── 4. Local module symbol (bare function call) ───────────────────
    if len(parts) == 1:
        module_prefix = f"{caller_module}." if caller_module else ""
        fqn = f"{module_prefix}{call_name}"
        if fqn in symbols:
            return [fqn], 0.90
        if caller_class:
            fqn_class = f"{module_prefix}{caller_class}.{call_name}"
            if fqn_class in symbols:
                return [fqn_class], 0.90

    # ── 5. Name-based fallback (lowest certainty) ─────────────────────
    bare_name = parts[-1]
    star_excludes = import_map.get("__star_excludes__", [])
    if len(parts) == 1 and isinstance(star_excludes, list) and bare_name in star_excludes:
        return [], 1.0
    # Use pre-built index — O(1) instead of O(n) full scan.
    # Cap at 8 matches: names with 9+ matches are so common (e.g. __init__,
    # get, run, update) that any edge added would likely be a false positive.
    name_index = _get_name_to_symbols(symbols)
    matches = name_index.get(bare_name, [])
    if len(matches) > 8:
        return [], 0.60
    return matches, 0.60


def resolve_call(
    call_name: str,
    caller_module: str,
    caller_class: str | None,
    filepath: str,
    imports: dict[str, dict[str, Any]],
    symbols: dict[str, dict[str, Any]],
    local_types: dict[str, str] | None = None,
    caller_id: str | None = None,
) -> list[str]:
    """Map a function call to the correct symbol in the symbol table.

    Delegates to :func:`resolve_call_with_certainty` and discards the
    certainty value.  All existing callers remain unchanged.
    """
    matches, _ = resolve_call_with_certainty(
        call_name,
        caller_module,
        caller_class,
        filepath,
        imports,
        symbols,
        local_types,
        caller_id=caller_id,
    )
    return matches
