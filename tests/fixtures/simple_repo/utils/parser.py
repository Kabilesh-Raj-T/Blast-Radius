from datetime import datetime


def parse_date(date_str: str) -> datetime:
    """Parse date using strptime."""
    return datetime.strptime(date_str, "%Y-%m-%d")
