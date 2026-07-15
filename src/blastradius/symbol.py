"""Language-agnostic symbol model for codebase representation."""

from dataclasses import asdict, dataclass
from typing import Any


class SymbolID(str):
    """Immutable identifier for a code symbol."""

    def __repr__(self) -> str:
        return f"SymbolID({super().__repr__()})"


@dataclass
class Symbol:
    """Represents a definition symbol (class, function, method) in the codebase."""

    unique_id: SymbolID | str
    module: str
    filepath: str
    class_name: str | None
    function_name: str | None
    decorators: list[str]
    line_no: int
    col_offset: int
    visibility: str  # "public" or "private"
    async_sync: str | None
    nested_info: dict[str, Any] | None  # e.g., {"parent_function": str, "parent_id": str}
    kind: str  # "class", "function", "method"
    method_kind: str | None  # "static", "class", "instance", "property", "abstract"
    bases: list[str] | None
    calls: list[str] | None
    local_types: dict[str, str] | None

    # Phase 2 Global Symbol Database fields
    package: str | None = None
    overload_info: dict[str, Any] | None = None
    generic_info: dict[str, Any] | None = None
    aliases: list[str] | None = None
    imported_names: list[str] | None = None
    exported_names: list[str] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.unique_id, str) and not isinstance(self.unique_id, SymbolID):
            self.unique_id = SymbolID(self.unique_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the symbol to a dictionary."""
        data = asdict(self)
        data["unique_id"] = str(self.unique_id)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Symbol":
        """Deserialize a symbol from a dictionary."""
        return cls(
            unique_id=data["unique_id"],
            module=data["module"],
            filepath=data["filepath"],
            class_name=data["class_name"],
            function_name=data["function_name"],
            decorators=data["decorators"],
            line_no=data["line_no"],
            col_offset=data["col_offset"],
            visibility=data["visibility"],
            async_sync=data["async_sync"],
            nested_info=data["nested_info"],
            kind=data["kind"],
            method_kind=data["method_kind"],
            bases=data["bases"],
            calls=data.get("calls"),
            local_types=data.get("local_types"),
            package=data.get("package"),
            overload_info=data.get("overload_info"),
            generic_info=data.get("generic_info"),
            aliases=data.get("aliases"),
            imported_names=data.get("imported_names"),
            exported_names=data.get("exported_names"),
        )
