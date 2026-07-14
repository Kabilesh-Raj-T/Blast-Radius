"""Dependency resolver module."""


_cache: dict[int, dict[str, list[str]]] = {}


def resolve(name: str, index: dict[str, list[str]]) -> list[str]:
    """Given a bare function name, resolve it to fully-qualified identifiers.

    Uses a pre-built lookup cache for efficient O(1) matching.
    """
    index_id = id(index)
    if index_id not in _cache:
        # Pre-build lookup dictionary to optimize O(N) scans to O(1) lookups
        lookup: dict[str, list[str]] = {}
        for key in index:
            if ":" in key:
                fn_name = key.rsplit(":", 1)[1]
                bare_name = fn_name.rsplit(".", 1)[-1]
                lookup.setdefault(bare_name, []).append(key)
        _cache[index_id] = lookup

    return _cache[index_id].get(name, [])
