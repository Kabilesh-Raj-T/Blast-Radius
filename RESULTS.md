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


## Flask library

The `flask` library (cloned from `https://github.com/pallets/flask`) was indexed and its forward/reverse call graphs were analyzed.

- **Total Nodes (Function definitions)**: 310
- **Total Edges (Resolved call sites)**: 504

### Top 5 Nodes by In-Degree (Most Called Internally)

In-degree represents the number of other internal Flask functions that directly call the target function:

| Rank | Function / Method | In-Degree (Callers) | Description |
| --- | --- | --- | --- |
| 1 | `src/flask/ctx.py:get` | 25 | Context getter helper |
| 2 | `src/flask/sansio/scaffold.py:get` | 25 | Route/endpoint scaffold getter |
| 3 | `src/flask/ctx.py:setdefault` | 16 | Context dictionary initialization |
| 4 | `src/flask/app.py:ensure_sync` | 12 | Helper to run async view functions synchronously |
| 5 | `src/flask/sansio/blueprints.py:record_once` | 10 | Blueprint deferred callback registration |

### Top 5 Nodes by Out-Degree (Calls the Most Other Functions)

Out-degree represents the number of unique internal functions called by the target function:

| Rank | Function / Method | Out-Degree (Callees) | Description |
| --- | --- | --- | --- |
| 1 | `src/flask/app.py:__init__` | 20 | Main Flask app constructor setting up defaults |
| 2 | `src/flask/sansio/app.py:__init__` | 18 | Sans-IO core app constructor setup |
| 3 | `src/flask/blueprints.py:__init__` | 15 | Blueprint setup constructor |
| 4 | `src/flask/config.py:__init__` | 15 | Configuration setup constructor |
| 5 | `src/flask/debughelpers.py:__init__` | 15 | Debug helper initialization |


## Django library

The `django` library (cloned from `https://github.com/django/django`) was indexed and analyzed for the blast radius of `django/utils/dateparse.py:parse_date`.

- **Total Nodes (Function/Method definitions)**: 32,009
- **Blast radius target**: `django/utils/dateparse.py:parse_date`
- **Total tests at risk**: 8,692
- **Confidence Distribution**:
  * **HIGH**: 1
  * **MEDIUM**: 15
  * **LOW**: 8,676

### Analysis of Blast Radius Findings

1. **HIGH Confidence**: Only `tests/utils_tests/test_dateparse.py:DateParseTests.test_parse_date` calls `parse_date` directly.
2. **MEDIUM Confidence**: Calls made 2 hops away (e.g. through model/form fields). Examples:
   - `tests/gis_tests/test_geoforms.py:GeometryFieldTest.test_geom_type` via `GeometryField.to_python`.
   - `tests/auth_tests/test_forms.py:BaseUserCreationFormTest.test_invalid_username_no_normalize`.
3. **LOW Confidence**: There is a high concentration of LOW confidence nodes (8,676). This occurs because `parse_date` is called by `DateField.to_python`. Since `to_python` is a generic method name defined in dozens of forms and model classes, static resolution of `.to_python()` calls resolves to all implementations across the codebase. Consequently, the call graph transitively links almost every model/form test in Django to the modified function. This is a classic case of name-resolution ambiguity described in the limitations section.

---
*Generated dynamically using `scripts/analyze_requests.py`, `scripts/analyze_flask.py`, and `scripts/analyze_django.py`.*


