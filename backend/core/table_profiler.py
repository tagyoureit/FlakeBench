"""
Table Profiler (Snowflake-first)

Provides lightweight, low-cost table "profiling" to support adaptive workload
query generation across:
- blank slate benchmark-created tables
- existing production schemas being evaluated for migration

This module intentionally avoids heavy scans. It uses:
- DESCRIBE TABLE (column names/types)
- MIN/MAX aggregates on chosen key columns (ID + optional time column)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableProfile:
    full_table_name: str

    id_column: Optional[str] = None
    id_min: Optional[int] = None
    id_max: Optional[int] = None

    time_column: Optional[str] = None
    time_min: Optional[datetime] = None
    time_max: Optional[datetime] = None


def _pick_id_column(columns: dict[str, str]) -> Optional[str]:
    """
    Pick a likely key column (used for point lookups / updates).

    This is intentionally heuristic because Snowflake constraints are often absent
    on standard tables. We prioritize common naming conventions and numeric types.
    """

    def _is_numeric_type(typ: str) -> bool:
        t = str(typ or "").upper()
        return any(x in t for x in ("NUMBER", "INT", "BIGINT", "DECIMAL"))

    # Prefer exact ID, then *_ID / *ID numeric-ish columns, then *_KEY / *KEY numeric-ish.
    if "ID" in columns:
        return "ID"

    id_like: list[str] = []
    key_like: list[str] = []
    contains_id: list[str] = []
    contains_key: list[str] = []

    for name, typ in columns.items():
        if not _is_numeric_type(typ):
            continue
        n = str(name or "").upper()
        if n.endswith("_ID") or (n.endswith("ID") and n != "ID"):
            id_like.append(n)
            continue
        if n.endswith("_KEY") or n.endswith("KEY"):
            key_like.append(n)
            continue
        if "ID" in n:
            contains_id.append(n)
            continue
        if "KEY" in n:
            contains_key.append(n)
            continue

    for bucket in (id_like, key_like, contains_id, contains_key):
        if bucket:
            return bucket[0]

    return None


def _pick_time_column(columns: dict[str, str]) -> Optional[str]:
    # Prefer common time columns, else any DATE/TIMESTAMP-ish column.
    preferred = [
        "TIMESTAMP",
        "CREATED_AT",
        "UPDATED_AT",
        "EVENT_TIME",
        "CREATED",
        "UPDATED",
        "DATE",
    ]
    for name in preferred:
        if name in columns and any(
            t in columns[name] for t in ("TIMESTAMP", "DATE", "TIME")
        ):
            return name

    for name, typ in columns.items():
        if any(t in typ for t in ("TIMESTAMP", "DATE", "TIME")):
            return name

    return None


def _id_candidates(columns: dict[str, str]) -> list[str]:
    """
    Return ordered candidate key columns based on naming + type heuristics.
    """

    def _is_numeric_type(typ: str) -> bool:
        t = str(typ or "").upper()
        return any(x in t for x in ("NUMBER", "INT", "BIGINT", "DECIMAL"))

    # Prefer exact ID if present (even if not numeric), but still allow other candidates.
    candidates: list[str] = []
    if "ID" in columns:
        candidates.append("ID")

    id_like: list[str] = []
    key_like: list[str] = []
    contains_id: list[str] = []
    contains_key: list[str] = []

    for name, typ in columns.items():
        n = str(name or "").upper()
        if n == "ID":
            continue
        if not _is_numeric_type(typ):
            continue
        if n.endswith("_ID") or n.endswith("ID"):
            id_like.append(n)
            continue
        if n.endswith("_KEY") or n.endswith("KEY"):
            key_like.append(n)
            continue
        if "ID" in n:
            contains_id.append(n)
            continue
        if "KEY" in n:
            contains_key.append(n)
            continue

    for bucket in (id_like, key_like, contains_id, contains_key):
        for c in bucket:
            if c not in candidates:
                candidates.append(c)
    return candidates


async def _best_key_candidate_from_sample(
    pool, full_table_name: str, candidates: Sequence[str], *, sample_rows: int
) -> Optional[str]:
    """
    Choose the best key candidate by distinctness on a random SAMPLE.

    This avoids full-table COUNT(DISTINCT ...) on very large customer tables.
    """
    eval_cols = [str(c).upper() for c in candidates if str(c).strip()][:8]
    if not eval_cols:
        return None

    sample_n = max(1000, min(int(sample_rows), 20000))
    parts: list[str] = []
    for idx, col in enumerate(eval_cols):
        parts.append(f'COUNT_IF("{col}" IS NULL) AS NULLS_{idx}')
        parts.append(f'COUNT(DISTINCT "{col}") AS DISTINCT_{idx}')

    rows = await pool.execute_query(
        f"""
        SELECT
          COUNT(*) AS N,
          {", ".join(parts)}
        FROM {full_table_name}
        SAMPLE ({sample_n} ROWS)
        """
    )
    if not rows or not rows[0]:
        return eval_cols[0]

    row = rows[0]
    try:
        n = int(row[0] or 0)
    except Exception:
        n = 0
    if n <= 0:
        return eval_cols[0]

    best_col: str | None = None
    best_ratio = -1.0
    best_distinct = -1

    # Columns appear as: N, NULLS_0, DISTINCT_0, NULLS_1, DISTINCT_1, ...
    base = 1
    for idx, col in enumerate(eval_cols):
        nulls_raw = row[base + (2 * idx)]
        dist_raw = row[base + (2 * idx) + 1]
        nulls = int(nulls_raw or 0)
        distinct = int(dist_raw or 0)
        non_null = max(1, n - nulls)
        ratio = float(distinct) / float(non_null)

        if ratio > best_ratio or (ratio == best_ratio and distinct > best_distinct):
            best_ratio = ratio
            best_distinct = distinct
            best_col = col

    # "Usable key" threshold: nearly unique in sample and not mostly NULL.
    if best_col is not None and best_ratio >= 0.98:
        return best_col
    return None


async def profile_snowflake_table(pool, full_table_name: str) -> TableProfile:
    """
    Profile a Snowflake table using minimal metadata queries.

    pool must provide: `await pool.execute_query(query, params=None)`
    """
    desc_rows = await pool.execute_query(f"DESCRIBE TABLE {full_table_name}")
    # Rows look like: (name, type, kind, null?, default?, ..., comment)
    columns: dict[str, str] = {}
    for row in desc_rows:
        if not row:
            continue
        col_name = str(row[0]).upper()
        col_type = str(row[1]).upper() if len(row) > 1 else ""
        columns[col_name] = col_type

    candidates = _id_candidates(columns)
    id_col: Optional[str]
    if not candidates:
        id_col = None
    elif len(candidates) == 1:
        id_col = candidates[0]
    else:
        # Break ties via SAMPLE-based distinctness (cheap) before falling back to first candidate.
        id_col = await _best_key_candidate_from_sample(
            pool, full_table_name, candidates, sample_rows=5000
        )
        if id_col is None:
            id_col = candidates[0]
    time_col = _pick_time_column(columns)

    id_min: Optional[int] = None
    id_max: Optional[int] = None
    if id_col:
        rows = await pool.execute_query(
            f'SELECT MIN("{id_col}") AS MIN_ID, MAX("{id_col}") AS MAX_ID FROM {full_table_name}'
        )
        if rows and len(rows[0]) >= 2:
            id_min = int(rows[0][0]) if rows[0][0] is not None else None
            id_max = int(rows[0][1]) if rows[0][1] is not None else None

    time_min: Optional[datetime] = None
    time_max: Optional[datetime] = None
    if time_col:
        rows = await pool.execute_query(
            f'SELECT MIN("{time_col}") AS MIN_T, MAX("{time_col}") AS MAX_T FROM {full_table_name}'
        )
        if rows and len(rows[0]) >= 2:
            time_min = rows[0][0]
            time_max = rows[0][1]

    profile = TableProfile(
        full_table_name=full_table_name,
        id_column=id_col,
        id_min=id_min,
        id_max=id_max,
        time_column=time_col,
        time_min=time_min,
        time_max=time_max,
    )

    logger.info(
        "Profiled table %s: id=%s[%s..%s], time=%s[%s..%s]",
        full_table_name,
        profile.id_column,
        profile.id_min,
        profile.id_max,
        profile.time_column,
        profile.time_min,
        profile.time_max,
    )
    return profile
