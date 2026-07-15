# blastradius

> "If I change this function, how many tests will break?"

`blastradius` is a static analysis CLI tool, pre-commit hook, and MCP server that answers that question before you touch a single file. It parses a codebase, builds a reverse function call graph, and computes which test files transitively depend on any given function — showing you the exact call chain from your change to each affected test.

Built for both humans (pre-commit hook, GitHub Actions) and AI coding agents (MCP server that Claude Code, Cursor, and other agents can call as a tool before making changes).

---

## Table of contents

1. [Why this exists](#why-this-exists)
2. [How it works](#how-it-works)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [CLI reference](#cli-reference)
6. [Pre-commit hook setup](#pre-commit-hook-setup)
7. [GitHub Actions integration](#github-actions-integration)
8. [MCP server — AI agent integration](#mcp-server--ai-agent-integration)
9. [Output formats](#output-formats)
10. [Configuration](#configuration)
11. [Architecture](#architecture)
12. [Core algorithm](#core-algorithm)
13. [Known limitations](#known-limitations)
14. [Project structure](#project-structure)
15. [Development setup](#development-setup)
16. [Running tests](#running-tests)
17. [Benchmarks](#benchmarks)
18. [Design decisions](#design-decisions)
19. [Roadmap](#roadmap)
20. [Contributing](#contributing)

---

## Why this exists

AI coding agents (Claude Code, Cursor, Copilot, Devin) modify files at machine speed. The problem: they edit a function without knowing which tests in other files depend on it — because cross-file dependency analysis requires a call graph, and building one is expensive. The agent changes `utils/parser.py:parse_date()`, has no idea that `billing/invoice.py` calls it, and that `test_billing.py` has 23 tests that exercise that path. CI fails. The agent is confused.

A 2025 CodeRabbit study of 470 open-source pull requests found that AI-authored code produces 1.7x more issues per PR than human-authored code, with logic errors 75% more common. The root cause is consistently identified as insufficient cross-file context — the agent cannot see what it cannot traverse.

`blastradius` solves this at the right layer: it pre-computes the call graph once, caches it, and makes the blast radius queryable in under 500ms — fast enough to call on every file edit.

### For humans

- Know before you refactor. Run `blastradius analyze` before touching a utility function.
- Pre-commit hook warns you when a change has high blast radius.
- GitHub Actions posts a blast radius report on every PR.

### For AI agents

- MCP server exposes `blast_radius(function)` and `suggest_files_to_update(function)` as tools.
- Agents call these before editing, get back the affected files, include them in their context window.
- Result: the agent edits all the right files. CI passes.

---

## How it works

At a high level, three steps:

```
1. INDEX      Parse every code file in the repo using language-specific AST tools.
              Extract all function definitions and the functions they call.
              Build a directed call graph: caller → callee.
              Persist to .blastradius/index.json.

2. REVERSE    Flip all edges: callee → caller.
              Now you can walk upward from any function to find everything
              that calls it, transitively.

3. BFS        Starting from your target symbol, do BFS on the reverse graph.
              At each node, check: is this a test function?
              (file starts with test_ or function starts with test_)
              If yes: record it, stop traversing that branch.
              If no: add its callers to the queue.
              Result: every test that transitively exercises your target function.
```

The call chain is preserved at each BFS step, so the output shows exactly why each test is at risk — not just that it is.

---

## Installation

### From PyPI

```bash
pip install blastradius
```

### From source

```bash
git clone https://github.com/Kabilesh-Raj-T/Blast-Radius.git
cd Blast-Radius
pip install -e ".[dev]"
```

### Requirements

- Python 3.10+
- No external services. Runs entirely locally.

### Dependencies

| Package     | Purpose                              |
|-------------|--------------------------------------|
| `networkx`  | Graph construction and BFS traversal |
| `typer`     | CLI framework                        |
| `rich`      | Terminal output formatting           |
| `mcp`       | MCP server (optional, for AI agents) |

---

## Quick start

```bash
# Step 1: index your repo (builds the call graph)
blastradius index ./myproject/

# Step 2: analyze a specific function
blastradius analyze myproject/utils/parser.py:parse_date

# Step 3: analyze everything changed in your current git diff
blastradius diff
```

Sample output:

```
Blast radius: myproject/utils/parser.py:parse_date
────────────────────────────────────────────────────

47 tests across 12 files are at risk.

HIGH confidence (direct callers that are tests):
  test_parser.py:test_parse_date_valid          chain: parse_date → test_parse_date_valid
  test_parser.py:test_parse_date_invalid        chain: parse_date → test_parse_date_invalid

MEDIUM confidence (one hop away):
  test_billing.py:test_generate_invoice         chain: parse_date → generate_invoice → test_generate_invoice
  test_billing.py:test_invoice_date_format      chain: parse_date → generate_invoice → test_invoice_date_format
  test_reports.py:test_monthly_summary          chain: parse_date → build_report → test_monthly_summary
  ... 18 more

LOW confidence (2+ hops away):
  test_api.py:test_create_order                 chain: parse_date → generate_invoice → create_order → test_create_order
  ... 22 more

Suggested action: review 12 test files before merging.
Run with --output markdown to get a PR-ready comment.
```

---

## CLI reference

### `blastradius index <repo_path>`

Parses the repo and builds the call graph. Must be run before `analyze` or `diff`.

```bash
blastradius index ./myproject/
blastradius index ./myproject/ --exclude "migrations,vendor,__pycache__"
blastradius index ./myproject/ --output-dir .blastradius/
```

**Flags:**

| Flag              | Default              | Description                                              |
|-------------------|----------------------|----------------------------------------------------------|
| `--exclude`       | `__pycache__,venv`   | Comma-separated list of directory patterns to skip       |
| `--output-dir`    | `.blastradius/`      | Where to store the index file                            |
| `--force`         | false                | Re-index all files, ignoring mtime cache                 |
| `--verbose`       | false                | Print each file as it is parsed                          |

**What it does:**

1. Walks all files under `repo_path`, skipping excluded patterns.
2. Parses files matching supported extensions (e.g. `.py`, `.ts`, `.java`, `.go`, `.rs`) using language-specific AST scanners.
3. For each symbol definition, extracts called functions/methods and local type annotations.
4. Resolves call targets to their definition files using import maps and MRO.
5. Builds a `networkx.MultiDiGraph` and persists it as `.blastradius/index.json`.
6. Stores file modification timestamps alongside the index for incremental re-indexing.

**Incremental indexing:**

On subsequent runs, `blastradius index` compares each file's current `mtime` against the stored timestamp. Only files that have changed are re-parsed. On a 10,000-file repo after changing one file, re-index time drops from ~30s to under 1s.

---

### `blastradius analyze <function>`

Computes the blast radius of a single function.

```bash
blastradius analyze myproject/utils/parser.py:parse_date
blastradius analyze myproject/utils/parser.py:parse_date --output json
blastradius analyze myproject/utils/parser.py:parse_date --output markdown
blastradius analyze myproject/utils/parser.py:parse_date --max-depth 5
blastradius analyze myproject/utils/parser.py:parse_date --threshold 20
```

**Flags:**

| Flag           | Default    | Description                                                          |
|----------------|------------|----------------------------------------------------------------------|
| `--output`     | `terminal` | Output format: `terminal`, `json`, `markdown`                        |
| `--max-depth`  | `10`       | Maximum BFS depth. Limits traversal for very deep call trees.        |
| `--threshold`  | `0`        | If blast radius exceeds this, exit with code 1. Useful in CI.        |
| `--index-dir`  | `.blastradius/` | Location of the index built by `blastradius index`              |
| `--no-chains`  | false      | Omit call chains from output (faster, smaller output)               |

**Function identifier format:**

```
<filepath>:<function_name>

Examples:
  myproject/utils/parser.py:parse_date
  src/billing/invoice.py:generate_invoice
  api/endpoints.py:create_order
```

The filepath is relative to the repo root (same directory where you ran `blastradius index`).

---

### `blastradius diff`

Analyzes all functions changed in the current git working tree. Equivalent to running `blastradius analyze` on every function that appears in `git diff`.

```bash
blastradius diff
blastradius diff --base main          # diff against main branch
blastradius diff --staged             # only staged changes
blastradius diff --output markdown    # PR-ready output
blastradius diff --threshold 50       # exit 1 if >50 tests at risk
```

**How it determines changed functions:**

1. Runs `git diff --unified=0` (or `git diff --staged` with `--staged`).
2. Parses the diff to find which line numbers changed in each source file.
3. Attributes line changes to symbols using precise end-span containment metadata.
4. Runs `blastradius analyze` on each changed symbol.
5. Merges results, deduplicating tests that appear in multiple blast radii.

**Flags:**

| Flag          | Default        | Description                                             |
|---------------|----------------|---------------------------------------------------------|
| `--base`      | `HEAD`         | Git ref to diff against                                 |
| `--staged`    | false          | Only analyze staged changes                             |
| `--output`    | `terminal`     | Output format: `terminal`, `json`, `markdown`           |
| `--threshold` | `0`            | Exit code 1 if total tests at risk exceeds this number  |

---

### `blastradius serve`

Starts the MCP server for AI agent integration. See [MCP server section](#mcp-server--ai-agent-integration).

```bash
blastradius serve
blastradius serve --port 3000
blastradius serve --repo ./myproject/
```

---

## Pre-commit hook setup

### Installation

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Kabilesh-Raj-T/Blast-Radius
    rev: v0.1.0
    hooks:
      - id: blastradius
        args: [--threshold, "30"]
```

Install the hook:

```bash
pre-commit install
```

### What happens on commit

1. `blastradius diff --staged` runs against your staged changes.
2. If blast radius is below threshold: commit proceeds normally.
3. If blast radius exceeds threshold:
   - In warn mode (default): prints the report, commit proceeds.
   - In strict mode (`--strict`): prints the report, blocks the commit with exit code 1.

### Skipping the hook for a specific commit

```bash
git commit --no-verify -m "your message"
# or
SKIP=blastradius git commit -m "your message"
```

### Configuration in `.pre-commit-config.yaml`

```yaml
- id: blastradius
  args:
    - --threshold=30       # warn if >30 tests at risk
    - --strict             # block commit instead of warn
    - --output=terminal    # output format
```

---

## GitHub Actions integration

### Basic setup

Create `.github/workflows/blast-radius.yml`:

```yaml
name: Blast radius check

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  blast-radius:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install blastradius
        run: pip install blastradius

      - name: Build index
        run: blastradius index .

      - name: Compute blast radius
        id: blast
        run: |
          blastradius diff --base origin/main --output markdown > blast_report.md
          echo "report<<EOF" >> $GITHUB_OUTPUT
          cat blast_report.md >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Post PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const report = `${{ steps.blast.outputs.report }}`;
            const { data: comments } = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            const existing = comments.find(c =>
              c.user.login === 'github-actions[bot]' &&
              c.body.startsWith('## Blast radius report')
            );
            if (existing) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                comment_id: existing.id,
                body: report,
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: report,
              });
            }
```

---

## MCP server — AI agent integration

This is the core use case for AI coding agents. The MCP server exposes two tools that agents (Claude Code, Cursor, Windsurf, or any MCP-compatible client) can call before modifying files.

### Starting the server

```bash
blastradius serve --repo ./myproject/
```

The server starts on `stdio` by default (which is how MCP servers communicate with agents). It automatically builds the index on startup if `.blastradius/index.json` doesn't exist.

### Connecting to Claude Code

Add to your Claude Code MCP config (`~/.claude/mcp_config.json` or per-project `.claude/mcp_config.json`):

```json
{
  "mcpServers": {
    "blastradius": {
      "command": "blastradius",
      "args": ["serve", "--repo", "."],
      "env": {}
    }
  }
}
```

### Connecting to Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "blastradius": {
      "command": "blastradius",
      "args": ["serve", "--repo", "."]
    }
  }
}
```

### Available MCP tools

> [!TIP]
> The MCP server outputs use a **token-efficient representation** (with compact keys) to minimize LLM context window costs and round-trip sizes.

#### `blast_radius`

Returns the full blast radius of a function. Accepts either `target` or `function` parameter.

**Input:**
```json
{
  "repo": ".",
  "target": "utils/parser.py:parse_date"
}
```
*Note: You can also use `"function": "utils/parser.py:parse_date"`.*

**Output (Token-Efficient Format):**
```json
[
  {
    "func": "test_billing.test_generate_invoice",
    "file": "test_billing.py",
    "reason": "direct invocation",
    "conf": "HIGH",
    "score": 1.0,
    "chain": ["parse_date()", "test_generate_invoice()"],
    "exp": "Direct invocation from the test node (factors: direct invocation)."
  }
]
```

#### `suggest_files_to_update`

Returns the list of files an AI agent should read and potentially update when changing a function. This is the tool to call before editing — it tells the agent exactly which files belong in its context window. Accepts either `target` or `function` parameter.

**Input:**
```json
{
  "repo": ".",
  "target": "utils/parser.py:parse_date"
}
```
*Note: You can also use `"function": "utils/parser.py:parse_date"`.*

**Output:**
```json
{
  "function": "utils/parser.py:parse_date",
  "files_to_review": [
    {
      "path": "billing/invoice.py",
      "reason": "calls parse_date directly",
      "relationship": "direct_caller"
    },
    {
      "path": "test_billing.py",
      "reason": "tests generate_invoice which calls parse_date",
      "relationship": "transitive_test"
    },
    {
      "path": "reports/monthly.py",
      "reason": "calls parse_date via build_report",
      "relationship": "transitive_caller"
    }
  ]
}
```

---

## Output formats

### Terminal (default)

Rich, colored output for interactive use. Shows a summary, confidence-grouped results, and call chains. Not suitable for piping.

### JSON (`--output json`)

Machine-readable. Suitable for piping into other tools or storing as CI artifacts.

### Markdown (`--output markdown`)

GitHub-flavored Markdown. Ready to paste into a PR comment or Confluence page. Used by the GitHub Actions integration.

---

## Configuration

Create a `.blastradius.toml` in your repo root to configure defaults:

```toml
[index]
exclude = ["migrations", "vendor", "__pycache__", "venv", ".venv", "node_modules"]
output_dir = ".blastradius"

[analyze]
max_depth = 10
default_output = "terminal"

[diff]
default_base = "main"
threshold = 0       # 0 means no threshold (never exit 1)
strict = false      # if true, exit 1 when threshold exceeded

[pre_commit]
threshold = 30
strict = false

[mcp]
port = 3000
auto_index = true   # rebuild index on server start if stale
```

---

## Architecture

```
src/blastradius/
├── __init__.py
├── engine.py             # Public engine orchestrator
├── core/                 # Core domain models and context
│   ├── __init__.py
│   ├── context.py        # Repository layout and roots
│   ├── diagnostics.py    # diagnostics and logging metrics
│   └── symbol.py         # Symbol and SymbolID dataclasses
├── parsing/              # AST parsing subsystem
│   ├── __init__.py       # Parser registry singleton loader
│   ├── base.py           # LanguageParser ABC
│   ├── go_parser.py
│   ├── java_parser.py
│   ├── javascript_parser.py
│   ├── python_parser.py
│   ├── rust_parser.py
│   └── typescript_parser.py
├── indexing/             # Filesystem indexing and persistence
│   ├── __init__.py
│   ├── incremental.py    # Incremental update logic
│   └── indexer.py        # Directory scanning
├── resolution/           # Dependency/import/call resolution
│   ├── __init__.py
│   └── resolver.py       # MRO, imports, call targets resolution
├── graph/                # Dependency graph representation
│   ├── __init__.py
│   └── graph.py          # NetworkX MultiDiGraph builder
├── analysis/             # Static analysis algorithms
│   ├── __init__.py
│   ├── blast.py          # Blast radius scores propagation
│   ├── diff.py           # git diff and symbol containment
│   └── discovery.py      # pytest/unittest classification rules
└── output/               # Output presentation layer
    ├── __init__.py
    ├── cli.py            # Typer CLI definition
    ├── formatters.py     # Terminal/JSON/Markdown formatters
    └── mcp_server.py     # Model Context Protocol stdio loop
```

### Data flow

```
blastradius index ./repo/
    ↓
indexer.py          walks all source files
    ↓
parsing/registry    delegates to correct LanguageParser instance
    ↓
python_parser.py    ast.parse() → Symbol structures
    ↓
resolver.py         resolves imports & scopes to FQNs
    ↓
graph.py            builds nx.MultiDiGraph, persists to JSON
    ↓
.blastradius/index.json


blastradius analyze utils/parser.py:parse_date
    ↓
graph.py            load index, build reverse graph (callee → caller)
    ↓
blast.py            BFS from target through reverse graph, returning path states
    ↓
formatters.py       render terminal / JSON / Markdown
```

---

## Core algorithm

### Step 1: AST parsing (`python_parser.py`)

```python
import ast
from pathlib import Path


def extract_calls(filepath: str) -> dict[str, list[str]]:
    """
    Parse a Python file and return a mapping of
    function_name -> list of function names it calls.
    """
    try:
        source = Path(filepath).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        return {}

    result = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        calls = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            # Direct call: parse_date(x)
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            # Attribute call: parser.parse_date(x) or self.parse_date(x)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)

        result[node.name] = calls

    return result
```

### Step 2: Building the reverse graph (`graph.py`)

```python
import json
import networkx as nx
from pathlib import Path


def build_graph(index: dict[str, list[str]]) -> nx.DiGraph:
    """
    index: {"utils/parser.py:parse_date": ["strptime", "split"], ...}
    Returns a DiGraph where edge A → B means "A calls B".
    """
    G = nx.DiGraph()
    for caller, callees in index.items():
        for callee in callees:
            G.add_edge(caller, callee)
    return G


def build_reverse_graph(G: nx.DiGraph) -> nx.DiGraph:
    """
    Flip all edges. Edge A → B becomes B → A.
    Now: walking forward from any node finds everything that calls it.
    """
    return G.reverse(copy=True)
```

---

## Benchmarks

Measured on a MacBook Pro M2, Python 3.11. Results committed to `BENCHMARKS.md`.

### Index build time

| Repo           | Files  | Functions | Full index | Re-index (1 file changed) |
|----------------|--------|-----------|------------|---------------------------|
| `requests`     | 42     | 380       | 0.4s       | <0.05s                    |
| `flask`        | 89     | 720       | 0.9s       | <0.05s                    |
| `django`       | 1,240  | 9,800     | 11.2s      | 0.08s                     |
| synthetic 10k  | 10,000 | 80,000    | 94s        | <0.1s                     |

### Blast radius query time (after index built)

| Graph size       | Query time |
|------------------|------------|
| 380 functions    | 3ms        |
| 9,800 functions  | 12ms       |
| 80,000 functions | 48ms       |

MCP tool call round-trip (including server overhead): under 100ms for repos under 10,000 functions.

---

## Design decisions

### Why NetworkX instead of a custom graph?

NetworkX provides BFS, cycle detection, and graph serialization out of the box. The overhead is acceptable: at 80,000 nodes and 200,000 edges (a large monorepo), graph traversal takes under 50ms.

### Why stop BFS at test functions?

Continuing past test functions adds noise without adding signal. The test function itself is the terminal node — it is what pytest runs. Knowing that `test_billing.py:test_generate_invoice` is affected is all the information you need.

### Why confidence levels instead of a single score?

Confidence is a human-readable proxy for how directly a change affects a test. A test that directly calls the changed function is HIGH. A test 3 hops away is LOW — there are intermediate callers that might absorb the change.

---

## Roadmap

### v0.1 (current) — Core multi-language static analysis

- [x] Multi-language parser system (Python, TypeScript, Go, Java, Rust)
- [x] Forward and reverse call graph construction
- [x] Scope-aware and MRO-aware name resolution
- [x] BFS blast radius with confidence scoring
- [x] Pre-commit hook & GitHub Actions workflow
- [x] MCP server with `blast_radius` and `suggest_files_to_update` tools
- [x] Incremental indexing (mtime cache)

---

## Contributing

Contributions are welcome. This is an actively developed project.

---

## License

MIT. See `LICENSE`.

---

*Built by Kabilesh Raj — sourced from Google TAP internals, Meta's test selection infrastructure, and the cross-file dependency analysis gap identified in SWE-Bench Pro (2025).*
