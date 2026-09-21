"""Layer 5 — Execution Engine: Sandboxed code execution with resource controls.

Security measures:
- Restricted builtins (no open, exec, eval, compile, __import__)
- Timeout enforcement
- Memory-limit approximation via row-count cap
- Only pandas/numpy/math/datetime/re/json/collections in namespace
"""

from __future__ import annotations

import logging
import signal
import threading
import traceback
import time
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Execution limits
_TIMEOUT_SECONDS = 30
_MAX_OUTPUT_ROWS = 50_000
_MAX_OUTPUT_COLS = 500


# Safe builtins whitelist
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "format": format,
    "frozenset": frozenset, "hasattr": hasattr, "hash": hash, "int": int,
    "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "next": next, "print": lambda *a, **kw: None,  # print is silenced
    "range": range, "repr": repr, "reversed": reversed, "round": round,
    "set": set, "slice": slice, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "type": type, "zip": zip,
    "True": True, "False": False, "None": None,
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
}


class ExecutionResult:
    """Container for sandboxed execution output."""

    def __init__(
        self,
        success: bool,
        result_df: Optional[pd.DataFrame] = None,
        error: Optional[str] = None,
        execution_time_ms: float = 0,
        rows_produced: int = 0,
        cols_produced: int = 0,
        truncated: bool = False,
    ):
        self.success = success
        self.result_df = result_df
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.rows_produced = rows_produced
        self.cols_produced = cols_produced
        self.truncated = truncated

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "success": self.success,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "rows_produced": self.rows_produced,
            "cols_produced": self.cols_produced,
            "truncated": self.truncated,
        }
        if self.error:
            d["error"] = self.error
        return d


def execute_in_sandbox(
    code: str,
    df: pd.DataFrame,
    timeout_seconds: int = _TIMEOUT_SECONDS,
) -> ExecutionResult:
    """Execute generated Pandas code in a restricted environment.

    The code receives `df` and must store its output in `result`.
    """
    import math
    import datetime
    import re as re_mod
    import json
    import collections

    # Build restricted namespace
    sandbox_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
        "math": math,
        "datetime": datetime,
        "re": re_mod,
        "json": json,
        "collections": collections,
        "df": df.copy(),  # Protect original data
    }
    sandbox_locals: Dict[str, Any] = {}

    start = time.perf_counter()
    exec_error: Optional[str] = None
    result_holder: Dict[str, Any] = {"result": None, "error": None}

    def _run():
        try:
            exec(code, sandbox_globals, sandbox_locals)  # noqa: S102
            result_holder["result"] = sandbox_locals.get("result")
        except Exception:
            result_holder["error"] = traceback.format_exc()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if thread.is_alive():
        return ExecutionResult(
            success=False,
            error=f"Execution timed out after {timeout_seconds}s. "
                  "Simplify the transformation or reduce data volume.",
            execution_time_ms=elapsed_ms,
        )

    if result_holder["error"]:
        return ExecutionResult(
            success=False,
            error=result_holder["error"],
            execution_time_ms=elapsed_ms,
        )

    result = result_holder["result"]
    if result is None:
        return ExecutionResult(
            success=False,
            error="Code did not produce a 'result' variable.",
            execution_time_ms=elapsed_ms,
        )

    # Coerce non-DataFrame results
    if not isinstance(result, pd.DataFrame):
        try:
            if isinstance(result, pd.Series):
                result = result.to_frame()
            elif isinstance(result, (list, dict)):
                result = pd.DataFrame(result)
            elif isinstance(result, (int, float, str)):
                result = pd.DataFrame({"result": [result]})
            else:
                result = pd.DataFrame({"result": [str(result)]})
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"Could not convert result to DataFrame: {e}",
                execution_time_ms=elapsed_ms,
            )

    truncated = False
    if len(result) > _MAX_OUTPUT_ROWS:
        result = result.head(_MAX_OUTPUT_ROWS)
        truncated = True
    if len(result.columns) > _MAX_OUTPUT_COLS:
        result = result.iloc[:, :_MAX_OUTPUT_COLS]
        truncated = True

    return ExecutionResult(
        success=True,
        result_df=result,
        execution_time_ms=elapsed_ms,
        rows_produced=len(result),
        cols_produced=len(result.columns),
        truncated=truncated,
    )
