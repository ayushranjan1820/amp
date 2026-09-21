"""Layer 1 — Input Layer: Extract schema + sample from data sources.

Best practice: never send full datasets to the LLM.
Only schema (column names, dtypes) and a small sample (first 5 rows) are passed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Maximum rows sent to LLM as sample
_MAX_SAMPLE_ROWS = 5
# Maximum inline data size before we refuse (10 MB)
_MAX_INLINE_BYTES = 10 * 1024 * 1024


def extract_schema_and_sample(
    df: pd.DataFrame,
    sample_rows: int = _MAX_SAMPLE_ROWS,
) -> Dict[str, Any]:
    """Extract schema info and a small sample from a DataFrame.

    Returns:
        {
            "columns": [{"name": str, "dtype": str, "nullable": bool, "unique_count": int}],
            "row_count": int,
            "sample": [[...], ...],
            "sample_columns": [str, ...],
        }
    """
    cols_info: List[Dict[str, Any]] = []
    for col in df.columns:
        series = df[col]
        cols_info.append({
            "name": str(col),
            "dtype": str(series.dtype),
            "nullable": bool(series.isnull().any()),
            "unique_count": int(series.nunique()),
            "null_count": int(series.isnull().sum()),
        })

    sample_df = df.head(sample_rows)
    sample_rows_data = sample_df.values.tolist()
    # Serialize non-serializable cells
    clean_sample: List[List[Any]] = []
    for row in sample_rows_data:
        clean_row = []
        for cell in row:
            if pd.isna(cell):
                clean_row.append(None)
            elif hasattr(cell, "isoformat"):
                clean_row.append(cell.isoformat())
            else:
                clean_row.append(cell)
        clean_sample.append(clean_row)

    return {
        "columns": cols_info,
        "row_count": len(df),
        "sample": clean_sample,
        "sample_columns": [str(c) for c in df.columns],
    }


def schema_to_text(schema: Dict[str, Any]) -> str:
    """Human/LLM-readable text representation of a schema digest."""
    lines = [f"Dataset: {schema['row_count']} rows, {len(schema['columns'])} columns\n"]
    lines.append("Columns:")
    for c in schema["columns"]:
        nullable = "nullable" if c["nullable"] else "not-null"
        lines.append(
            f"  - {c['name']} ({c['dtype']}, {nullable}, "
            f"{c['unique_count']} unique, {c['null_count']} nulls)"
        )
    lines.append(f"\nSample ({min(len(schema['sample']), _MAX_SAMPLE_ROWS)} rows):")
    header = " | ".join(schema["sample_columns"])
    lines.append(f"  {header}")
    lines.append(f"  {'-' * len(header)}")
    for row in schema["sample"][:_MAX_SAMPLE_ROWS]:
        cells = [str(c) if c is not None else "NULL" for c in row]
        lines.append(f"  {' | '.join(cells)}")
    return "\n".join(lines)


def parse_inline_data(raw: str, fmt: Optional[str] = None) -> pd.DataFrame:
    """Parse user-supplied inline data (CSV or JSON) into a DataFrame.

    Raises ValueError for unsupported or oversized input.
    """
    if len(raw.encode("utf-8")) > _MAX_INLINE_BYTES:
        raise ValueError(
            f"Inline data exceeds {_MAX_INLINE_BYTES // (1024*1024)} MB limit. "
            "Please upload the file or provide a database reference."
        )

    detected = fmt or _detect_format(raw)

    if detected == "csv":
        return pd.read_csv(io.StringIO(raw))
    elif detected == "json":
        data = json.loads(raw)
        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            if "data" in data:
                return pd.DataFrame(data["data"])
            return pd.DataFrame([data])
        raise ValueError("JSON must be an array of objects or {\"data\": [...]}.")
    elif detected == "tsv":
        return pd.read_csv(io.StringIO(raw), sep="\t")
    else:
        raise ValueError(
            f"Unsupported data format: '{detected}'. Supported: csv, json, tsv."
        )


def _detect_format(raw: str) -> str:
    """Auto-detect whether inline data is CSV, JSON, or TSV."""
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        return "json"
    # Check for tab-separated
    first_line = stripped.split("\n")[0] if "\n" in stripped else stripped
    if "\t" in first_line and "," not in first_line:
        return "tsv"
    return "csv"
