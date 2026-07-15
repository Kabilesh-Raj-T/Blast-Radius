"""Diagnostics and structured logging subsystem for monitoring performance, memory, and code statistics."""

import json
import logging
import sys
import time
from typing import Any

# Configure structured logger
logger = logging.getLogger("blastradius.diagnostics")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


class DiagnosticsTracker:
    """Tracks and logs performance metrics, index details, and resource utilization."""

    def __init__(self) -> None:
        self.files_indexed = 0
        self.skipped_files = 0
        self.symbols = 0
        self.functions = 0
        self.calls = 0
        self.resolved_imports = 0
        self.ambiguous_symbols = 0
        self.dynamic_calls = 0
        self.index_time = 0.0
        self.query_time = 0.0

    def get_memory_usage(self) -> int:
        """Get the Working Set memory usage of the process in bytes.

        Uses native Windows API via ctypes on Win32, and getrusage on Unix.
        """
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
                GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess

                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                process = GetCurrentProcess()
                if GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                    return counters.WorkingSetSize
            except Exception:
                pass
            return 0
        else:
            try:
                import resource

                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            except Exception:
                return 0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a standard python dictionary."""
        return {
            "files_indexed": self.files_indexed,
            "skipped_files": self.skipped_files,
            "symbols": self.symbols,
            "functions": self.functions,
            "calls": self.calls,
            "resolved_imports": self.resolved_imports,
            "ambiguous_symbols": self.ambiguous_symbols,
            "dynamic_calls": self.dynamic_calls,
            "index_time_sec": round(self.index_time, 4),
            "query_time_sec": round(self.query_time, 4),
            "memory_usage_bytes": self.get_memory_usage(),
        }

    def log_structured(self, event_name: str) -> None:
        """Write a structured JSON log entry containing diagnostic metrics."""
        payload = {"event": event_name, "metrics": self.to_dict(), "timestamp": time.time()}
        logger.info(json.dumps(payload))


# Global diagnostics tracker singleton
tracker = DiagnosticsTracker()
