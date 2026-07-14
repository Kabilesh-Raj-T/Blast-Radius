from utils.parser import parse_date


def generate_invoice(date_str: str) -> str:
    """Generate invoice, parsing the date."""
    parsed_date = parse_date(date_str)
    return f"Invoice generated for {parsed_date.strftime('%B %d, %Y')}"
