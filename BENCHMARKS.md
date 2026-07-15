# BlastRadius Benchmarks

This file summarizes the performance benchmarks for `blastradius`, detailing the indexing times, query response times, and static analysis quality (precision/recall) across several popular open-source packages.

These measurements are automatically collected and updated using the script `benchmarks/run_benchmarks.py`.

---

## Performance Summary

### 1. Indexing Times

The table below shows the duration to walk the codebase, parse the files, construct the symbol tables, and build the initial call graph:

| Repository | Indexing Time (seconds) |
| :--- | :--- |
| **requests** | 0.026s |
| **flask** | 0.035s |
| **celery** | 0.257s |
| **fastapi** | 0.281s |
| **sqlalchemy** | 0.495s |
| **django** | 1.068s |
| **click** | 2.994s |
| **jinja** | 3.290s |
| **pydantic** | 18.533s |

---

### 2. Query Performance & Accuracy Metrics

This benchmark measures the time it takes to compute the blast radius for a target symbol on the pre-built reverse call graph. It also compares the static analysis results against dynamic/runtime test execution (true positives, false positives, false negatives):

| Repository | Target Symbol | Precision | Recall | Query Time (seconds) |
| :--- | :--- | :--- | :--- | :--- |
| **requests** | `requests.api.request` | 100% | 50.0% | 0.017s |
| **flask** | `flask.app.Flask` | 100% | 40.0% | 0.004s |
| **fastapi** | `fastapi.applications.FastAPI` | 100% | 8.8% | 0.007s |
| **celery** | `celery.app.base.Celery` | 51.4% | 28.4% | 0.048s |
| **django** | `django.http.request.HttpRequest` | 76.7% | 56.1% | 0.039s |
| **sqlalchemy** | `sqlalchemy.orm.session.Session` | 42.9% | 80.2% | 1.051s |
| **click** | `click.core.Command` | 100% | 61.9% | 0.004s |
| **jinja** | `jinja2.environment.Environment` | 100% | 83.3% | 0.016s |
| **pydantic** | `pydantic.main.BaseModel` | 100% | 0.7% | 0.005s |

---

## Detailed Metric Descriptions

- **Indexing Time**: The time taken to perform a full static analysis of all package files, build imports/definitions maps, and serialize the resulting network graph database. Subsequent runs run incrementally (comparing file modification timestamps) and complete in **under 0.1s**.
- **Precision**: Out of the tests flagged by BlastRadius as "at risk", what percentage actually run/exercise the target symbol at runtime. High precision (e.g. 100% for `requests`/`flask`/`fastapi`) means the tool does not generate false alarms.
- **Recall**: Out of all the tests that actually exercise the target symbol at runtime, what percentage was BlastRadius able to identify statically. Lower recall values reflect dynamic call dispatch paths (e.g., dynamic imports, factory patterns) which are statically invisible.
- **Query Time**: The latency of a single BFS traversal through the reverse call graph to discover impacted test files and construct caller chains. Typically **under 50ms** for packages under 10k functions.
