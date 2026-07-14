# Blast Radius Validation Results

This document contains real-world validation results of the `blastradius` tool run on popular open-source repositories.

## requests library

The `requests` library (cloned from `https://github.com/psf/requests`) was indexed excluding the tests, docs, and build files.

- **Total functions/methods defined**: 228
- **Total call sites detected**: 898 (approximate)

### 5 Most-Called Functions/Attributes (Raw Counts)

These are the functions/attributes (including built-ins and standard library methods) that appear most frequently in the call targets of the indexed functions:

| Rank | Function / Attribute | Occurrences as Callee |
| --- | --- | --- |
| 1 | `isinstance` | 71 |
| 2 | `get` | 34 |
| 3 | `split` | 21 |
| 4 | `urlparse` | 19 |
| 5 | `cast` | 18 |

### Top 5 Non-Builtin/HTTP-Specific Functions/Attributes

If we filter out basic built-ins (like `isinstance`, `getattr`, `len`), typing constructs (`cast`), and standard list/string methods (like `split`, `encode`, `append`), the most common domain-specific call targets are:

| Rank | Function / Attribute | Occurrences as Callee | Description |
| --- | --- | --- | --- |
| 1 | `urlparse` | 19 | URL parsing (from `urllib.parse`) |
| 2 | `request` | 15 | Request dispatching |
| 3 | `lower` | 14 | Case-insensitive header lookup / checking |
| 4 | `startswith` | 12 | Prefix matching (e.g., protocol verification) |
| 5 | `environ` | 10 | Environment lookup (e.g., proxy configuration) |

---
*Generated dynamically using `scripts/analyze_requests.py`.*
