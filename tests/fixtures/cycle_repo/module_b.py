def func_b() -> None:
    """Func B which calls Func A."""
    from module_a import func_a

    func_a()
