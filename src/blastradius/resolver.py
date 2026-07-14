"""Dependency resolver module."""


def resolve(name: str, index: dict[str, list[str]]) -> list[str]:
    """Given a bare function name, resolve it to fully-qualified identifiers.

    Looks for keys in the index that end with ':' followed by the name.
    """
    suffix = f":{name}"
    return [key for key in index if key.endswith(suffix)]
