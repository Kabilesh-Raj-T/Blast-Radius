def func_a() -> None:
    """Func A which calls Func B."""
    from module_b import func_b

    func_b()
