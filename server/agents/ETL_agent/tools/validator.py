"""Layer 6 — Critic / Validation Layer: Validate execution results and enable self-healing.

Checks:
1. Execution success (no runtime errors)
2. Schema correctness (expected columns/types present)
3. Logical correctness (row count sanity, no all-null output)
4. Output schema enforcement (Layer 8)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

# Typical INFORMATION_SCHEMA.TABLES-style columns (SQL standard / PostgreSQL / MySQL).
_INFO_SCHEMA_TABLES_CORE = frozenset({"table_schema", "table_name", "table_type"})
_INFO_SCHEMA_TABLES_EXTRA = frozenset({
    "table_catalog",
    "self_referencing_column_name",
    "reference_generation",
    "user_defined_type_catalog",
    "user_defined_type_schema",
    "user_defined_type_name",
    "commit_action",
})


def looks_like_information_schema_tables_output(df: pd.DataFrame) -> bool:
    """True when extract SQL likely queried information_schema.tables instead of a user table."""
    if df.empty or len(df.columns) < 3:
        return False
    cols = frozenset(str(c).lower() for c in df.columns)
    if not _INFO_SCHEMA_TABLES_CORE.issubset(cols):
        return False
    allowed = _INFO_SCHEMA_TABLES_CORE | _INFO_SCHEMA_TABLES_EXTRA
    return cols.issubset(allowed)


class ValidationResult:
    """Outcome of a validation pass."""

    def __init__(
        self,
        valid: bool,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_execution_result(
    result_df: pd.DataFrame,
    original_df: pd.DataFrame,
    expected_schema: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """Validate the transformed DataFrame against quality checks.

    Args:
        result_df: The output DataFrame from sandboxed execution.
        original_df: The input DataFrame (for comparison / sanity checks).
        expected_schema: Optional expected output schema from planner.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Empty result check
    if result_df.empty:
        errors.append(
            "Transformation produced an empty DataFrame. "
            "The logic may be filtering out all rows."
        )
        return ValidationResult(valid=False, errors=errors)

    # 2. All-null check
    if result_df.isnull().all().all():
        errors.append(
            "All values in the result are NULL/NaN. "
            "The transformation logic may have an error."
        )
        return ValidationResult(valid=False, errors=errors)

    # 2b. Catalog metadata mistaken for row data (bad extract SQL)
    if looks_like_information_schema_tables_output(result_df):
        errors.append(
            "The result looks like **database catalog metadata** (information_schema-style: "
            "table_schema, table_name, table_type), not rows from your application table. "
            "The extract step must use `SELECT ... FROM your_schema.your_table` (the actual table), "
            "not `information_schema.tables`, `pg_catalog`, or similar."
        )
        return ValidationResult(valid=False, errors=errors)

    # 3. Row count sanity
    if len(result_df) == 0:
        errors.append("Result has 0 rows.")
    elif len(original_df) > 0:
        ratio = len(result_df) / len(original_df)
        if ratio > 100:
            warnings.append(
                f"Result has {len(result_df)} rows vs {len(original_df)} input rows "
                f"({ratio:.0f}x expansion). Verify this is expected (e.g. explode/cross join)."
            )

    # 4. Schema enforcement (Layer 8)
    if expected_schema:
        expected_cols = expected_schema.get("columns", [])
        expected_types = expected_schema.get("types", [])

        for i, col_name in enumerate(expected_cols):
            if col_name not in result_df.columns:
                errors.append(
                    f"Expected column '{col_name}' missing from output. "
                    f"Available columns: {list(result_df.columns)}"
                )
            elif i < len(expected_types):
                expected_type = expected_types[i].lower()
                actual_type = str(result_df[col_name].dtype).lower()
                if not _types_compatible(actual_type, expected_type):
                    warnings.append(
                        f"Column '{col_name}': expected type '{expected_type}', "
                        f"got '{actual_type}'."
                    )

    # 5. Duplicate column check
    dup_cols = result_df.columns[result_df.columns.duplicated()].tolist()
    if dup_cols:
        warnings.append(f"Duplicate column names in output: {dup_cols}")

    # 6. High null ratio warning
    for col in result_df.columns:
        null_ratio = result_df[col].isnull().mean()
        if null_ratio > 0.9:
            warnings.append(
                f"Column '{col}' is {null_ratio:.0%} null in the output."
            )

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)


def build_critic_prompt(
    user_query: str,
    code: str,
    error_message: str,
    schema_text: str,
    attempt: int,
) -> str:
    """Build a self-healing prompt for the LLM to fix broken code."""
    return f"""You are a critic agent reviewing failed ETL code. Fix the code.

ORIGINAL USER REQUEST:
{user_query}

DATASET SCHEMA:
{schema_text}

FAILED CODE (attempt {attempt}/{_MAX_RETRIES + 1}):
{code}

ERROR:
{error_message}

STRICT RULES (same as original generation):
1. Only use: pandas (as pd), numpy (as np), math, datetime, re, json, collections
2. NO: os, sys, subprocess, open(), exec(), eval(), file I/O, network calls
3. The input DataFrame is available as `df`.
4. Store the final result in a variable named `result` (must be a DataFrame).
5. Keep code minimal — fix the error, don't rewrite unnecessarily.

Generate ONLY the corrected Python code. No markdown fences, no explanation.
"""


def _types_compatible(actual: str, expected: str) -> bool:
    """Loose type matching between pandas dtypes and expected type strings."""
    type_groups = {
        "string": {"object", "string", "str", "category"},
        "float": {"float64", "float32", "float", "number", "numeric"},
        "int": {"int64", "int32", "int16", "int8", "int", "integer"},
        "bool": {"bool", "boolean"},
        "datetime": {"datetime64[ns]", "datetime", "date", "timestamp"},
    }
    for group_name, aliases in type_groups.items():
        if expected in aliases and actual in aliases:
            return True
        if expected == group_name and actual in aliases:
            return True
    # Fallback: if expected is a substring of actual
    return expected in actual
