"""Git diff parser and symbol coverage mapper."""

import re
from typing import Any


def parse_git_diff(diff_content: str) -> dict[str, list[int]]:
    """Parse standard git diff format and extract changed line numbers per file.

    Returns:
        A dict mapping relative file paths to lists of modified line numbers.
    """
    changed_lines: dict[str, list[int]] = {}
    current_file = None

    # Matches: +++ b/billing/invoice.py or +++ b/app.py
    file_pattern = re.compile(r"^\+\+\+\s+b/(.*)$")
    # Matches hunk headers: @@ -10,6 +10,8 @@
    hunk_pattern = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")

    for line in diff_content.splitlines():
        file_match = file_pattern.match(line)
        if file_match:
            current_file = file_match.group(1).strip()
            changed_lines[current_file] = []
            continue

        if current_file:
            hunk_match = hunk_pattern.match(line)
            if hunk_match:
                start_line = int(hunk_match.group(1))
                count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                for line_num in range(start_line, start_line + count):
                    changed_lines[current_file].append(line_num)

    return changed_lines


def get_symbols_for_changed_lines(
    changed_lines: dict[str, list[int]], symbols: dict[str, dict[str, Any]]
) -> list[str]:
    """Map modified line numbers to containing function/method symbols.

    Matches each modified line to the closest preceding symbol in that file.
    """
    affected_symbols = []

    # Group symbols by filepath
    symbols_by_file: dict[str, list[dict[str, Any]]] = {}
    for sym_id, sym_dict in symbols.items():
        if sym_dict.get("kind") in ("function", "method"):
            fpath = sym_dict.get("filepath")
            if fpath:
                if fpath not in symbols_by_file:
                    symbols_by_file[fpath] = []
                symbols_by_file[fpath].append(sym_dict)

    # Map changed lines to symbols
    for rel_path, lines in changed_lines.items():
        rel_path_str = rel_path.replace("\\", "/")
        file_symbols = symbols_by_file.get(rel_path_str, [])
        if not file_symbols or not lines:
            continue

        # Sort symbols by starting line number
        file_symbols.sort(key=lambda s: s.get("line_no", 0))

        for line in lines:
            best_sym = None
            for sym in file_symbols:
                start = sym.get("line_no", 0)
                end = sym.get("end_line_no")
                if end is not None:
                    if start <= line <= end:
                        best_sym = sym
                        break
                else:
                    if start <= line:
                        best_sym = sym
                    else:
                        break
            if best_sym and best_sym["unique_id"] not in affected_symbols:
                affected_symbols.append(best_sym["unique_id"])

    return affected_symbols
