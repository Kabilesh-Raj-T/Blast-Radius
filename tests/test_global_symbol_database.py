from blastradius.core.symbol import Symbol, SymbolID


def test_symbol_id_properties():
    """Verify that SymbolID subclasses str and is immutable."""
    sid = SymbolID("mypkg.module.func")

    # Verify string subclassing
    assert isinstance(sid, str)
    assert sid == "mypkg.module.func"
    assert sid.startswith("mypkg")
    assert sid.split(".") == ["mypkg", "module", "func"]
    assert repr(sid) == "SymbolID('mypkg.module.func')"


def test_symbol_phase2_fields():
    """Verify that Symbol contains all Phase 2 fields and supports default values."""
    sym = Symbol(
        unique_id="mypkg.module.Class",
        module="mypkg.module",
        filepath="mypkg/module.py",
        class_name=None,
        function_name="Class",
        decorators=[],
        line_no=10,
        col_offset=4,
        visibility="public",
        async_sync=None,
        nested_info=None,
        kind="class",
        method_kind=None,
        bases=[],
        calls=[],
        local_types={},
        package="mypkg",
        overload_info={"is_overload": False},
        generic_info={"type_params": ["T"]},
        aliases=["ClassAlias"],
        imported_names=["other_func"],
        exported_names=["Class"],
    )

    # Verify normalization to SymbolID
    assert isinstance(sym.unique_id, SymbolID)
    assert sym.unique_id == "mypkg.module.Class"

    # Verify custom fields
    assert sym.package == "mypkg"
    assert sym.overload_info == {"is_overload": False}
    assert sym.generic_info == {"type_params": ["T"]}
    assert sym.aliases == ["ClassAlias"]
    assert sym.imported_names == ["other_func"]
    assert sym.exported_names == ["Class"]

    # Verify serialization
    data = sym.to_dict()
    assert data["unique_id"] == "mypkg.module.Class"
    assert data["package"] == "mypkg"
    assert data["overload_info"] == {"is_overload": False}

    # Verify deserialization
    sym2 = Symbol.from_dict(data)
    assert isinstance(sym2.unique_id, SymbolID)
    assert sym2.package == "mypkg"
    assert sym2.overload_info == {"is_overload": False}
