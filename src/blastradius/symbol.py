"""Language-agnostic symbol model for codebase representation."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Symbol:
    """Represents a definition symbol (class, function, method) in the codebase."""

    unique_id: str
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

    def to_dict(self) -> dict[str, Any]:
        """Serialize the symbol to a dictionary."""
        return asdict(self)

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
        )
