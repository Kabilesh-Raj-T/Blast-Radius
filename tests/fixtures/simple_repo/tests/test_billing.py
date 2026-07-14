from billing.invoice import generate_invoice


def test_generate_invoice() -> None:
    """Test generating invoice."""
    result = generate_invoice("2026-07-14")
    assert result == "Invoice generated for July 14, 2026"
