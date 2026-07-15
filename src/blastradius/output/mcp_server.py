"""Model Context Protocol (MCP) server stdio transport layer for the BlastRadius Engine."""

import json
import sys
from typing import Any

from blastradius import engine


def serialize_token_efficient(data: Any) -> str:
    """Serialize JSON stripping all formatting whitespaces for LLM token efficiency."""
    return json.dumps(data, separators=(",", ":"))


def main():
    """MCP stdio JSON-RPC transport loop."""
    for line in sys.stdin:
        if not line.strip():
            continue
        req_id = None
        try:
            try:
                req = json.loads(line)
            except Exception as e:
                res = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
                continue

            req_id = req.get("id")
            method = req.get("method")

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "blastradius", "version": "0.1.0"},
                    },
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "index_repository",
                                "description": "Index the repository and build symbol/import databases.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "repo": {
                                            "type": "string",
                                            "description": "Path to repository root",
                                        }
                                    },
                                    "required": ["repo"],
                                },
                            },
                            {
                                "name": "blast_radius",
                                "description": "Compute impacted test files/functions for a modified symbol.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "repo": {
                                            "type": "string",
                                            "description": "Path to repository root",
                                        },
                                        "target": {
                                            "type": "string",
                                            "description": "Fully qualified name of changed function/method",
                                        },
                                        "function": {
                                            "type": "string",
                                            "description": "Fully qualified name of changed function/method (alternative to target)",
                                        },
                                    },
                                },
                            },
                            {
                                "name": "suggest_files_to_update",
                                "description": "Suggest files that should be reviewed or updated when changing a function/method.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "repo": {
                                            "type": "string",
                                            "description": "Path to repository root",
                                        },
                                        "target": {
                                            "type": "string",
                                            "description": "Fully qualified name of changed function/method",
                                        },
                                        "function": {
                                            "type": "string",
                                            "description": "Fully qualified name of changed function/method (alternative to target)",
                                        },
                                    },
                                },
                            },
                            {
                                "name": "analyze_diff",
                                "description": "Identify containing symbols for modified lines in a git diff and find affected tests.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "repo": {
                                            "type": "string",
                                            "description": "Path to repository root",
                                        },
                                        "diff": {
                                            "type": "string",
                                            "description": "Standard git diff content text",
                                        },
                                    },
                                    "required": ["repo", "diff"],
                                },
                            },
                            {
                                "name": "explain_test",
                                "description": "Detail call dependency chains and edges of a target test.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "repo": {
                                            "type": "string",
                                            "description": "Path to repository root",
                                        },
                                        "test": {
                                            "type": "string",
                                            "description": "Fully qualified test function name",
                                        },
                                    },
                                    "required": ["repo", "test"],
                                },
                            },
                            {
                                "name": "health",
                                "description": "Check the health and platform status of the BlastRadius server.",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                        ]
                    },
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                result_data = {}
                error_data = None

                try:
                    if tool_name == "index_repository":
                        result_data = engine.index_repository(arguments.get("repo"))
                    elif tool_name == "blast_radius":
                        import os

                        repo_arg = (
                            arguments.get("repo") or os.environ.get("BLASTRADIUS_MCP_REPO") or "."
                        )
                        target_arg = arguments.get("target") or arguments.get("function")
                        if not target_arg:
                            raise ValueError(
                                "Either 'target' or 'function' argument must be provided."
                            )
                        result_data = engine.blast_radius(repo_arg, target_arg)
                    elif tool_name == "suggest_files_to_update":
                        import os

                        repo_arg = (
                            arguments.get("repo") or os.environ.get("BLASTRADIUS_MCP_REPO") or "."
                        )
                        target_arg = arguments.get("target") or arguments.get("function")
                        if not target_arg:
                            raise ValueError(
                                "Either 'target' or 'function' argument must be provided."
                            )
                        result_data = engine.suggest_files_to_update(repo_arg, target_arg)
                    elif tool_name == "analyze_diff":
                        result_data = engine.analyze_diff(
                            arguments.get("repo"), arguments.get("diff")
                        )
                    elif tool_name == "explain_test":
                        result_data = engine.explain_test(
                            arguments.get("repo"), arguments.get("test")
                        )
                    elif tool_name == "health":
                        result_data = engine.health()
                    else:
                        error_data = {"code": -32601, "message": f"Tool {tool_name} not found."}
                except Exception as e:
                    error_data = {"code": -32603, "message": str(e)}

                if error_data:
                    res = {"jsonrpc": "2.0", "id": req_id, "error": error_data}
                else:
                    compact_txt = serialize_token_efficient(result_data)
                    from blastradius.core.diagnostics import tracker

                    res = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": compact_txt}],
                            "diagnostics": tracker.to_dict(),
                        },
                    }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method {method} not found."},
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

        except Exception as outer_e:
            try:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Internal server error: {str(outer_e)}"},
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
            except Exception:
                pass


if __name__ == "__main__":
    from typing import Any

    main()
