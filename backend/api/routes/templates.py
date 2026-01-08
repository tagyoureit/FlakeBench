"""
API routes for test scenario template management.

Manages templates stored in Snowflake TEST_TEMPLATES table.
"""

from datetime import UTC, datetime
import logging
import re
from uuid import uuid4
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.connectors import snowflake_pool
from backend.api.error_handling import http_exception
from backend.core.table_profiler import profile_snowflake_table

router = APIRouter()
logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Z0-9_]+$")

_CUSTOM_QUERY_FIELDS: tuple[str, str, str, str] = (
    "custom_point_lookup_query",
    "custom_range_scan_query",
    "custom_insert_query",
    "custom_update_query",
)
_CUSTOM_PCT_FIELDS: tuple[str, str, str, str] = (
    "custom_point_lookup_pct",
    "custom_range_scan_pct",
    "custom_insert_pct",
    "custom_update_pct",
)

# Canonical SQL templates for saved CUSTOM workloads. These are intentionally generic:
# execution substitutes `{table}` with the fully-qualified table name.
_DEFAULT_CUSTOM_QUERIES: dict[str, str] = {
    "custom_point_lookup_query": "SELECT * FROM {table} WHERE id = ?",
    "custom_range_scan_query": (
        "SELECT * FROM {table} WHERE id BETWEEN ? AND ? + 100 ORDER BY id LIMIT 100"
    ),
    "custom_insert_query": (
        "INSERT INTO {table} (id, data, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)"
    ),
    "custom_update_query": (
        "UPDATE {table} SET data = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?"
    ),
}

_PRESET_PCTS: dict[str, dict[str, int]] = {
    # READ_ONLY: 50/50 point vs range, 0 writes
    "READ_ONLY": {
        "custom_point_lookup_pct": 50,
        "custom_range_scan_pct": 50,
        "custom_insert_pct": 0,
        "custom_update_pct": 0,
    },
    # WRITE_ONLY: 70/30 insert vs update, 0 reads
    "WRITE_ONLY": {
        "custom_point_lookup_pct": 0,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 70,
        "custom_update_pct": 30,
    },
    # READ_HEAVY: 80% reads (40/40), 20% writes (15/5)
    "READ_HEAVY": {
        "custom_point_lookup_pct": 40,
        "custom_range_scan_pct": 40,
        "custom_insert_pct": 15,
        "custom_update_pct": 5,
    },
    # WRITE_HEAVY: 80% writes (60/20), 20% reads (10/10)
    "WRITE_HEAVY": {
        "custom_point_lookup_pct": 10,
        "custom_range_scan_pct": 10,
        "custom_insert_pct": 60,
        "custom_update_pct": 20,
    },
    # MIXED: 50% reads (25/25), 50% writes (35/15)
    "MIXED": {
        "custom_point_lookup_pct": 25,
        "custom_range_scan_pct": 25,
        "custom_insert_pct": 35,
        "custom_update_pct": 15,
    },
}


def _upper_str(v: Any) -> str:
    return str(v or "").strip().upper()


def _validate_ident(name: Any, *, label: str) -> str:
    """
    Validate a Snowflake identifier component (DATABASE / SCHEMA / TABLE / COLUMN).

    For now we intentionally restrict to unquoted identifiers:
    - letters, digits, underscore
    - uppercased

    This avoids SQL injection and keeps generated SQL predictable.
    """
    value = _upper_str(name)
    if not value:
        raise ValueError(f"Missing {label}")
    if not _IDENT_RE.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r} (expected [A-Z0-9_]+)")
    return value


def _quote_ident(name: str) -> str:
    # Identifiers are already validated to [A-Z0-9_]+, so this is safe.
    return f'"{name}"'


def _full_table_name(database: str, schema: str, table: str) -> str:
    db = _validate_ident(database, label="database")
    sch = _validate_ident(schema, label="schema")
    tbl = _validate_ident(table, label="table")
    return f"{_quote_ident(db)}.{_quote_ident(sch)}.{_quote_ident(tbl)}"


def _results_prefix() -> str:
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


def _coerce_int(v: Any, *, label: str) -> int:
    try:
        # Allow numeric strings and floats; coerce to int.
        out = int(float(v))
    except Exception as e:
        raise ValueError(f"Invalid {label}: {v!r}") from e
    return out


def _normalize_template_config(cfg: Any) -> dict[str, Any]:
    """
    Normalize template config to an authoritative CUSTOM workload definition.

    Contract:
    - Any preset workload_type (READ_ONLY/WRITE_ONLY/READ_HEAVY/WRITE_HEAVY/MIXED)
      is rewritten to workload_type=CUSTOM with explicit custom_*_pct + custom_*_query.
    - CUSTOM workloads are validated server-side (pct sum, required SQL).
    """
    if not isinstance(cfg, dict):
        raise ValueError("Template config must be a JSON object")

    out: dict[str, Any] = dict(cfg)
    wt_raw = str(out.get("workload_type") or "").strip()
    wt = wt_raw.upper() if wt_raw else "MIXED"

    if wt != "CUSTOM":
        if wt not in _PRESET_PCTS:
            raise ValueError(
                f"Invalid workload_type: {wt_raw!r} (expected one of "
                f"{sorted([*list(_PRESET_PCTS.keys()), 'CUSTOM'])})"
            )
        out["workload_type"] = "CUSTOM"
        out.update(_DEFAULT_CUSTOM_QUERIES)
        out.update(_PRESET_PCTS[wt])
        return out

    # CUSTOM: normalize and validate.
    out["workload_type"] = "CUSTOM"

    # Normalize query strings.
    for k in _CUSTOM_QUERY_FIELDS:
        out[k] = str(out.get(k) or "").strip()

    # Normalize pct fields.
    for k in _CUSTOM_PCT_FIELDS:
        out[k] = _coerce_int(out.get(k) or 0, label=k)
        if out[k] < 0 or out[k] > 100:
            raise ValueError(f"{k} must be between 0 and 100 (got {out[k]})")

    total = sum(int(out[k]) for k in _CUSTOM_PCT_FIELDS)
    if total != 100:
        raise ValueError(
            f"Custom query percentages must sum to 100 (currently {total})."
        )

    required_pairs = [
        ("custom_point_lookup_pct", "custom_point_lookup_query"),
        ("custom_range_scan_pct", "custom_range_scan_query"),
        ("custom_insert_pct", "custom_insert_query"),
        ("custom_update_pct", "custom_update_query"),
    ]
    for pct_k, sql_k in required_pairs:
        if int(out.get(pct_k) or 0) > 0 and not str(out.get(sql_k) or "").strip():
            raise ValueError(f"{sql_k} is required when {pct_k} > 0")

    return out


class TemplateConfig(BaseModel):
    """Template configuration structure."""

    table_type: str
    database: str
    schema: str
    table_name: str
    workload_type: str
    duration: int
    concurrent_connections: int
    warehouse_size: str


class TemplateCreate(BaseModel):
    """Request model for creating a template."""

    template_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    config: Dict[str, Any]
    tags: Optional[Dict[str, str]] = None


class TemplateUpdate(BaseModel):
    """Request model for updating a template."""

    template_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    config: Optional[Dict[str, Any]] = None
    tags: Optional[Dict[str, str]] = None


class TemplateResponse(BaseModel):
    """Response model for template data."""

    template_id: str
    template_name: str
    description: Optional[str]
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    tags: Optional[Dict[str, str]]
    usage_count: int
    last_used_at: Optional[datetime]


def _row_to_dict(row, columns):
    """Convert result row tuple to dictionary."""
    return dict(zip([col.lower() for col in columns], row))


class AiPrepareResponse(BaseModel):
    template_id: str
    ai_available: bool
    ai_error: Optional[str] = None
    pool_id: Optional[str] = None
    key_column: Optional[str] = None
    time_column: Optional[str] = None
    insert_columns: List[str] = Field(default_factory=list)
    update_columns: List[str] = Field(default_factory=list)
    projection_columns: List[str] = Field(default_factory=list)
    domain_label: Optional[str] = None
    pools: Dict[str, int] = Field(default_factory=dict)
    message: str


class AiAdjustSqlRequest(BaseModel):
    config: Dict[str, Any]


class AiAdjustSqlResponse(BaseModel):
    # Echo back adjusted config fields (client applies these locally; nothing is persisted until save).
    workload_type: str = "CUSTOM"
    custom_point_lookup_query: str
    custom_range_scan_query: str
    custom_insert_query: str
    custom_update_query: str
    custom_point_lookup_pct: int
    custom_range_scan_pct: int
    custom_insert_pct: int
    custom_update_pct: int
    columns: Dict[str, str] = Field(default_factory=dict)
    ai_workload: Dict[str, Any] = Field(default_factory=dict)
    toast_level: str
    summary: str


@router.get("/", response_model=List[TemplateResponse])
async def list_templates():
    """
    List all available test configuration templates.

    Returns:
        List of all templates with metadata
    """
    try:
        pool = snowflake_pool.get_default_pool()

        query = """
        SELECT 
            TEMPLATE_ID,
            TEMPLATE_NAME,
            DESCRIPTION,
            CONFIG,
            CREATED_AT,
            UPDATED_AT,
            CREATED_BY,
            TAGS,
            USAGE_COUNT,
            LAST_USED_AT
        FROM UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES
        ORDER BY UPDATED_AT DESC
        """

        results = await pool.execute_query(query)

        columns = [
            "TEMPLATE_ID",
            "TEMPLATE_NAME",
            "DESCRIPTION",
            "CONFIG",
            "CREATED_AT",
            "UPDATED_AT",
            "CREATED_BY",
            "TAGS",
            "USAGE_COUNT",
            "LAST_USED_AT",
        ]

        templates = []
        for row in results:
            row_dict = _row_to_dict(row, columns)
            # Parse JSON strings from VARIANT columns
            import json

            config = row_dict["config"]
            if isinstance(config, str):
                config = json.loads(config)
            tags = row_dict["tags"]
            if isinstance(tags, str) and tags:
                tags = json.loads(tags)

            templates.append(
                {
                    "template_id": row_dict["template_id"],
                    "template_name": row_dict["template_name"],
                    "description": row_dict["description"],
                    "config": config,
                    "created_at": row_dict["created_at"],
                    "updated_at": row_dict["updated_at"],
                    "created_by": row_dict["created_by"],
                    "tags": tags,
                    "usage_count": row_dict["usage_count"] or 0,
                    "last_used_at": row_dict["last_used_at"],
                }
            )

        return templates

    except Exception as e:
        raise http_exception("list templates", e)


@router.post("/ai/adjust-sql", response_model=AiAdjustSqlResponse)
async def ai_adjust_sql(req: AiAdjustSqlRequest):
    """
    Preview-only AI adjustment for the canonical 4-query CUSTOM workload.

    Contract:
    - Does NOT write anything to Snowflake results tables.
    - Returns updated custom_*_query strings and percentages for the client to apply.
    - If a required key/time column is missing, the affected SQL is blank and its % is 0
      (and the remaining % is redistributed to keep the total at 100).
    - Returns a toast summary (success=green, warning=yellow).
    """
    try:
        pool = snowflake_pool.get_default_pool()
        cfg = _normalize_template_config(req.config)

        db = _validate_ident(cfg.get("database"), label="database")
        sch = _validate_ident(cfg.get("schema"), label="schema")
        tbl = _validate_ident(cfg.get("table_name"), label="table")
        full_name = _full_table_name(db, sch, tbl)

        concurrency = int(cfg.get("concurrent_connections") or 1)
        concurrency = max(1, concurrency)

        # AI availability check (fast).
        ai_available = False
        ai_error: str | None = None
        try:
            await pool.execute_query("SELECT AI_COMPLETE('claude-4-sonnet', 'test')")
            ai_available = True
        except Exception as e:
            ai_available = False
            ai_error = str(e)

        # Profile table for key/time columns (cheap).
        prof = await profile_snowflake_table(pool, full_name)
        key_col = prof.id_column
        time_col = prof.time_column

        # Choose insert/update columns (heuristic; AI can refine here when available).
        desc_rows = await pool.execute_query(f"DESCRIBE TABLE {full_name}")
        col_types: dict[str, str] = {}
        col_null_ok: dict[str, bool] = {}
        col_default: dict[str, str] = {}
        for row in desc_rows:
            if not row:
                continue
            kind = (
                str(row[2]).upper() if len(row) > 2 and row[2] is not None else "COLUMN"
            )
            if kind != "COLUMN":
                continue
            name = str(row[0]).upper()
            typ = str(row[1]).upper() if len(row) > 1 else ""
            col_types[name] = typ
            null_raw = (
                str(row[3]).strip().upper()
                if len(row) > 3 and row[3] is not None
                else ""
            )
            default_raw = (
                str(row[4]).strip() if len(row) > 4 and row[4] is not None else ""
            )
            col_null_ok[name] = null_raw != "N"
            col_default[name] = default_raw

        def _is_key_or_id_like(col: str) -> bool:
            c = str(col or "").strip().upper()
            if not c:
                return False
            if c == (key_col or ""):
                return True
            # Treat common identifier/key suffixes as non-updatable.
            return c == "ID" or c.endswith("ID") or c.endswith("KEY")

        def _pick_update_column() -> str | None:
            preferred = ["UPDATED_AT", "STATUS", "STATE", "UPDATED", "MODIFIED_AT"]
            for c in preferred:
                if c in col_types and (not _is_key_or_id_like(c)):
                    return c
            for c in col_types.keys():
                if not _is_key_or_id_like(c):
                    return c
            return None

        update_col = _pick_update_column()
        if update_col and _is_key_or_id_like(update_col):
            update_col = None

        issues: list[str] = []
        range_mode: str | None = None

        def _has_default(col: str) -> bool:
            d = (col_default.get(col) or "").strip()
            return bool(d and d.upper() not in {"NULL", "NONE"})

        required_cols: list[str] = []
        for c in col_types.keys():
            if not col_null_ok.get(c, True) and not _has_default(c):
                required_cols.append(c)
        if len(required_cols) > 8:
            issues.append(
                f"Table has {len(required_cols)} required columns; INSERT may need manual adjustment."
            )

        insert_cols: list[str] = []
        # Prefer required + key + time + a couple of string columns.
        for c in required_cols[:8]:
            insert_cols.append(c)
        if key_col:
            kc = key_col.upper()
            if kc not in insert_cols:
                insert_cols.append(kc)
        if time_col and time_col.upper() not in insert_cols:
            insert_cols.append(time_col.upper())
        for c, typ in col_types.items():
            if c in insert_cols:
                continue
            if any(x in typ for x in ("VARCHAR", "STRING", "TEXT")):
                insert_cols.append(c)
            if len(insert_cols) >= 6:
                break
        if not insert_cols:
            insert_cols = list(col_types.keys())[:3]

        # Optional: ask Cortex to refine insert/update/range choices and provide a user-facing summary.
        ai_summary_from_model: str | None = None
        if ai_available:
            try:
                import json

                # Sample a small set of columns + rows for better column/domain selection.
                sample_cols: list[str] = []
                if key_col:
                    sample_cols.append(key_col.upper())
                if time_col and time_col.upper() not in sample_cols:
                    sample_cols.append(time_col.upper())
                for c, typ in col_types.items():
                    if c in sample_cols:
                        continue
                    if len(sample_cols) >= 12:
                        break
                    sample_cols.append(c)

                obj_parts: list[str] = []
                for c in sample_cols:
                    c_ident = _validate_ident(c, label="column")
                    obj_parts.append(f"'{c_ident}'")
                    obj_parts.append(_quote_ident(c_ident))
                obj_expr = (
                    f"OBJECT_CONSTRUCT_KEEP_NULL({', '.join(obj_parts)})"
                    if obj_parts
                    else "OBJECT_CONSTRUCT()"
                )
                sample_rows = await pool.execute_query(
                    f"SELECT {obj_expr} FROM {full_name} SAMPLE (20 ROWS)"
                )
                sample_payload = [r[0] for r in sample_rows if r]

                cols_for_prompt = []
                for c in list(col_types.keys())[:250]:
                    cols_for_prompt.append({"name": c, "type": col_types.get(c, "")})

                prompt = (
                    "You are adjusting a 4-statement benchmark workload for a Snowflake table.\n"
                    "Your output will be shown to the user.\n\n"
                    f"TABLE: {db}.{sch}.{tbl}\n"
                    f"KEY_COLUMN (may be null): {key_col or None}\n"
                    f"TIME_COLUMN (may be null): {time_col or None}\n\n"
                    "COLUMNS (name/type):\n"
                    f"{json.dumps(cols_for_prompt, ensure_ascii=False)}\n\n"
                    "REQUIRED_COLUMNS (must be included in insert_columns if feasible):\n"
                    f"{json.dumps(required_cols, ensure_ascii=False)}\n\n"
                    "SAMPLE_ROWS (JSON objects):\n"
                    f"{json.dumps(sample_payload, ensure_ascii=False, default=str)}\n\n"
                    "Return STRICT JSON ONLY with:\n"
                    "- summary: string (1-2 sentences describing what you changed)\n"
                    "- insert_columns: [string] (columns to include in INSERT placeholders)\n"
                    "- update_columns: [string] (columns to include in UPDATE set clause)\n"
                    '- range_mode: one of ["TIME_CUTOFF","ID_BETWEEN",null]\n'
                    "- issues: [string] (empty if all OK)\n"
                    "\n"
                    "Rules:\n"
                    "- If KEY_COLUMN is null: update_columns must be empty.\n"
                    "- update_columns must NOT include any columns ending with ID or KEY.\n"
                    "- If TIME_COLUMN is null and KEY_COLUMN is null: range_mode must be null.\n"
                    "- Prefer TIME_CUTOFF if TIME_COLUMN exists; otherwise ID_BETWEEN if KEY_COLUMN exists.\n"
                    "- Keep insert_columns <= 8 and update_columns <= 2.\n"
                )

                ai_resp = await pool.execute_query(
                    "SELECT AI_COMPLETE(model => ?, prompt => ?, model_parameters => PARSE_JSON(?), response_format => PARSE_JSON(?)) AS RESP",
                    params=[
                        "claude-4-sonnet",
                        prompt,
                        json.dumps({"temperature": 0, "max_tokens": 600}),
                        json.dumps(
                            {
                                "type": "json",
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string"},
                                        "insert_columns": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "update_columns": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "range_mode": {
                                            "type": ["string", "null"],
                                        },
                                        "issues": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": [
                                        "summary",
                                        "insert_columns",
                                        "update_columns",
                                        "range_mode",
                                        "issues",
                                    ],
                                },
                            }
                        ),
                    ],
                )

                raw = ai_resp[0][0] if ai_resp and ai_resp[0] else None
                parsed: dict[str, Any] | None = None
                if isinstance(raw, dict):
                    parsed = raw
                elif isinstance(raw, str) and raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        parsed = None

                if isinstance(parsed, dict):
                    ai_summary_from_model = (
                        str(parsed.get("summary") or "").strip() or None
                    )
                    ai_issues = parsed.get("issues")
                    if isinstance(ai_issues, list):
                        issues.extend(str(x) for x in ai_issues if str(x).strip())

                    ai_ins = parsed.get("insert_columns")
                    if isinstance(ai_ins, list) and ai_ins:
                        cleaned: list[str] = []
                        for c in ai_ins:
                            cu = _upper_str(c)
                            if cu and cu in col_types:
                                cleaned.append(cu)
                            if len(cleaned) >= 8:
                                break
                        if cleaned:
                            insert_cols = cleaned

                    ai_upd = parsed.get("update_columns")
                    if isinstance(ai_upd, list) and ai_upd and key_col:
                        cleaned_u: list[str] = []
                        for c in ai_upd:
                            cu = _upper_str(c)
                            if not cu or cu == (key_col or ""):
                                continue
                            if _is_key_or_id_like(cu):
                                continue
                            if cu in col_types:
                                cleaned_u.append(cu)
                            if len(cleaned_u) >= 2:
                                break
                        if cleaned_u:
                            update_col = cleaned_u[0]

                    rm = parsed.get("range_mode")
                    if rm in ("TIME_CUTOFF", "ID_BETWEEN"):
                        range_mode = str(rm)
            except Exception as e:
                # If Cortex fails mid-flight, fall back to heuristics (do not warn the user unless
                # there are actual workload issues like missing key/time columns or blank SQL).
                logger.debug("AI planning failed in /ai/adjust-sql: %s", e)

        # Build SQL templates (blank + pct=0 if missing key/time as requested).
        select_list = "*"
        point_sql = ""
        update_sql = ""
        if key_col:
            point_sql = f'SELECT {select_list} FROM {{table}} WHERE "{key_col}" = ?'
            if update_col:
                update_sql = (
                    f'UPDATE {{table}} SET "{update_col}" = ? WHERE "{key_col}" = ?'
                )

        # Range scan: prefer time-based; fall back to id-based if key exists; else blank.
        range_sql = ""
        if range_mode == "ID_BETWEEN":
            # Explicit override (only valid when key exists).
            if key_col:
                range_sql = (
                    f'SELECT {select_list} FROM {{table}} WHERE "{key_col}" BETWEEN ? AND ? + 100 '
                    f'ORDER BY "{key_col}" LIMIT 100'
                )
            else:
                range_mode = None
        elif time_col:
            range_sql = (
                f'SELECT {select_list} FROM {{table}} WHERE "{time_col}" >= ? '
                f'ORDER BY "{time_col}" DESC LIMIT 100'
            )
            range_mode = "TIME_CUTOFF"
        elif key_col:
            range_sql = (
                f'SELECT {select_list} FROM {{table}} WHERE "{key_col}" BETWEEN ? AND ? + 100 '
                f'ORDER BY "{key_col}" LIMIT 100'
            )
            range_mode = "ID_BETWEEN"

        # Insert (always placeholders; params generated in executor).
        cols_sql = ", ".join(f'"{c}"' for c in insert_cols)
        ph_sql = ", ".join("?" for _ in insert_cols)
        insert_sql = (
            f"INSERT INTO {{table}} ({cols_sql}) VALUES ({ph_sql})"
            if insert_cols
            else ""
        )

        # Percentages: start from preset mix (already normalized to CUSTOM by _normalize_template_config).
        p_point = int(cfg.get("custom_point_lookup_pct") or 0)
        p_range = int(cfg.get("custom_range_scan_pct") or 0)
        p_ins = int(cfg.get("custom_insert_pct") or 0)
        p_upd = int(cfg.get("custom_update_pct") or 0)

        # Missing key disables POINT + UPDATE.
        if not key_col:
            if p_point > 0:
                issues.append("No usable key column detected; POINT_LOOKUP disabled.")
                p_range += p_point
                p_point = 0
            if p_upd > 0:
                issues.append("No usable key column detected; UPDATE disabled.")
                p_ins += p_upd
                p_upd = 0
        elif not update_sql and p_upd > 0:
            issues.append("No usable update column detected; UPDATE disabled.")
            p_ins += p_upd
            p_upd = 0

        # Missing time AND key disables RANGE.
        if not range_sql and p_range > 0:
            issues.append("No usable time/key column detected; RANGE_SCAN disabled.")
            p_ins += p_range
            p_range = 0

        # Ensure total=100 (guardrail). Any rounding goes to INSERT.
        total = p_point + p_range + p_ins + p_upd
        if total != 100:
            p_ins += 100 - total

        # Blank SQL if pct==0 for disabled operations.
        if p_point == 0:
            point_sql = ""
        if p_range == 0:
            range_sql = ""
        if p_upd == 0:
            update_sql = ""

        ai_summary: str
        toast_level = "success"
        if ai_available and ai_summary_from_model:
            ai_summary = ai_summary_from_model
        elif ai_available:
            ai_summary = (
                f"AI adjusted workload SQL. key={key_col or '∅'} time={time_col or '∅'} "
                f"mode={range_mode or '∅'}"
            )
        else:
            toast_level = "warning"
            ai_summary = (
                "AI not available in this account; using heuristic SQL adjustment."
            )

        if issues:
            toast_level = "warning"
            ai_summary = ai_summary + " Issues: " + " ".join(issues)

        # Return a minimal columns map so the saved template can validate against the customer table.
        cols_map: dict[str, str] = {}
        for c in {
            *(insert_cols or []),
            *([key_col] if key_col else []),
            *([time_col] if time_col else []),
        }:
            if not c:
                continue
            c_u = str(c).upper()
            cols_map[c_u] = col_types.get(c_u, "VARCHAR")

        ai_workload = {
            "available": ai_available,
            "model": "claude-4-sonnet",
            "availability_error": ai_error,
            "key_column": key_col,
            "time_column": time_col,
            "range_mode": range_mode,
            "insert_columns": insert_cols,
            "update_columns": [update_col] if update_col else [],
        }

        return AiAdjustSqlResponse(
            custom_point_lookup_query=point_sql,
            custom_range_scan_query=range_sql,
            custom_insert_query=insert_sql,
            custom_update_query=update_sql,
            custom_point_lookup_pct=p_point,
            custom_range_scan_pct=p_range,
            custom_insert_pct=p_ins,
            custom_update_pct=p_upd,
            columns=cols_map,
            ai_workload=ai_workload,
            toast_level=toast_level,
            summary=ai_summary,
        )
    except Exception as e:
        raise http_exception("ai adjust sql", e)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    """
    Get a specific template by ID.

    Args:
        template_id: UUID of the template

    Returns:
        Template data
    """
    try:
        pool = snowflake_pool.get_default_pool()

        query = f"""
        SELECT 
            TEMPLATE_ID,
            TEMPLATE_NAME,
            DESCRIPTION,
            CONFIG,
            CREATED_AT,
            UPDATED_AT,
            CREATED_BY,
            TAGS,
            USAGE_COUNT,
            LAST_USED_AT
        FROM UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES
        WHERE TEMPLATE_ID = '{template_id}'
        """

        results = await pool.execute_query(query)

        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {template_id}",
            )

        columns = [
            "TEMPLATE_ID",
            "TEMPLATE_NAME",
            "DESCRIPTION",
            "CONFIG",
            "CREATED_AT",
            "UPDATED_AT",
            "CREATED_BY",
            "TAGS",
            "USAGE_COUNT",
            "LAST_USED_AT",
        ]
        row_dict = _row_to_dict(results[0], columns)

        # Parse JSON strings from VARIANT columns
        import json

        config = row_dict["config"]
        if isinstance(config, str):
            config = json.loads(config)
        tags = row_dict["tags"]
        if isinstance(tags, str) and tags:
            tags = json.loads(tags)

        return {
            "template_id": row_dict["template_id"],
            "template_name": row_dict["template_name"],
            "description": row_dict["description"],
            "config": config,
            "created_at": row_dict["created_at"],
            "updated_at": row_dict["updated_at"],
            "created_by": row_dict["created_by"],
            "tags": tags,
            "usage_count": row_dict["usage_count"] or 0,
            "last_used_at": row_dict["last_used_at"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("get template", e)


@router.post("/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(template: TemplateCreate):
    """
    Create a new test configuration template.

    Args:
        template: Template data

    Returns:
        Created template with generated ID
    """
    try:
        pool = snowflake_pool.get_default_pool()

        template_id = str(uuid4())
        now = datetime.now(UTC)

        import json

        normalized_cfg = _normalize_template_config(template.config)
        # If a template payload includes AI workload prep artifacts (e.g. from duplicating
        # an existing template), they are not valid for a *new* template.
        # Pools are keyed by TEMPLATE_ID, so carrying over the old pool_id would create
        # a confusing "prepared" UI state while having no backing rows.
        ai_workload = normalized_cfg.get("ai_workload")
        if isinstance(ai_workload, dict):
            ai_workload.pop("pool_id", None)
            ai_workload.pop("pools", None)
            ai_workload.pop("prepared_at", None)
            normalized_cfg["ai_workload"] = ai_workload
        config_json = json.dumps(normalized_cfg)
        tags_json = json.dumps(template.tags) if template.tags else None
        now_iso = now.isoformat()

        # Use bound parameters to avoid JSON parsing issues from string interpolation
        # (e.g., escaped quotes/backslashes inside the JSON payload).
        #
        # Note: Snowflake can reject PARSE_JSON(?) inside a VALUES clause with qmark binding,
        # so we use INSERT ... SELECT ... instead.
        query = """
        INSERT INTO UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES (
            TEMPLATE_ID, TEMPLATE_NAME, DESCRIPTION, CONFIG, CREATED_AT, UPDATED_AT, TAGS, USAGE_COUNT
        )
        SELECT
            ?,
            ?,
            ?,
            PARSE_JSON(?),
            ?,
            ?,
            PARSE_JSON(?),
            0
        """
        await pool.execute_query(
            query,
            params=[
                template_id,
                template.template_name,
                template.description,
                config_json,
                now_iso,
                now_iso,
                tags_json,
            ],
        )

        return await get_template(template_id)

    except Exception as e:
        raise http_exception("create template", e)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(template_id: str, template: TemplateUpdate):
    """
    Update an existing template.

    Args:
        template_id: UUID of the template to update
        template: Updated template data

    Returns:
        Updated template
    """
    try:
        pool = snowflake_pool.get_default_pool()

        # Check if template exists by trying to get it
        try:
            existing = await get_template(template_id)
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                raise
            raise

        usage_count = int(existing.get("usage_count") or 0)
        if usage_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This template has test results and can no longer be edited. "
                    "Copy it to create an editable version."
                ),
            )

        updates = []
        params: list[Any] = []

        if template.template_name is not None:
            updates.append("TEMPLATE_NAME = ?")
            params.append(template.template_name)

        if template.description is not None:
            updates.append("DESCRIPTION = ?")
            params.append(template.description)

        if template.config is not None:
            import json

            normalized_cfg = _normalize_template_config(template.config)
            config_json = json.dumps(normalized_cfg)
            updates.append("CONFIG = PARSE_JSON(?)")
            params.append(config_json)

        if template.tags is not None:
            import json

            tags_json = json.dumps(template.tags)
            updates.append("TAGS = PARSE_JSON(?)")
            params.append(tags_json)

        updates.append("UPDATED_AT = ?")
        params.append(datetime.now(UTC).isoformat())

        query = f"""
        UPDATE UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES
        SET {", ".join(updates)}
        WHERE TEMPLATE_ID = ?
        """

        params.append(template_id)
        await pool.execute_query(query, params=params)

        return await get_template(template_id)

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("update template", e)


@router.post("/{template_id}/ai/prepare", response_model=AiPrepareResponse)
async def prepare_ai_template(template_id: str):
    """
    Prepare a template for "AI adjusted" workloads:
    - Check Cortex availability (AI_COMPLETE smoke test)
    - Profile the target table (key/time columns)
    - Generate and persist value pools using Snowflake SAMPLE into TEMPLATE_VALUE_POOLS
    - Persist the resulting metadata into TEST_TEMPLATES.CONFIG (no runtime AI calls)
    """
    try:
        pool = snowflake_pool.get_default_pool()

        tpl = await get_template(template_id)
        usage_count = int(tpl.get("usage_count") or 0)
        if usage_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This template has test results and can no longer be edited. "
                    "Copy it to create an editable version."
                ),
            )

        cfg = tpl.get("config") or {}
        if not isinstance(cfg, dict):
            raise HTTPException(
                status_code=400, detail="Template config must be a JSON object"
            )

        db = _validate_ident(cfg.get("database"), label="database")
        sch = _validate_ident(cfg.get("schema"), label="schema")
        tbl = _validate_ident(cfg.get("table_name"), label="table")
        full_name = _full_table_name(db, sch, tbl)

        concurrency = int(cfg.get("concurrent_connections") or 1)
        concurrency = max(1, concurrency)

        # ------------------------------------------------------------------
        # 1) Cortex availability check (fast)
        # ------------------------------------------------------------------
        ai_available = False
        ai_error: str | None = None
        try:
            await pool.execute_query("SELECT AI_COMPLETE('claude-4-sonnet', 'test')")
            ai_available = True
        except Exception as e:
            ai_available = False
            ai_error = str(e)

        # ------------------------------------------------------------------
        # 2) Profile table (heuristics) for key/time columns
        # ------------------------------------------------------------------
        profile = await profile_snowflake_table(pool, full_name)
        key_col = profile.id_column
        time_col = profile.time_column

        # Pull full DESCRIBE metadata so we can choose safe insert/update columns.
        desc_rows = await pool.execute_query(f"DESCRIBE TABLE {full_name}")
        col_types: dict[str, str] = {}
        col_null_ok: dict[str, bool] = {}
        col_default: dict[str, str] = {}
        for row in desc_rows:
            if not row:
                continue
            name = str(row[0]).upper()
            typ = str(row[1]).upper() if len(row) > 1 else ""
            kind = str(row[2]).upper() if len(row) > 2 else "COLUMN"
            if kind != "COLUMN":
                continue
            null_raw = (
                str(row[3]).upper() if len(row) > 3 and row[3] is not None else "Y"
            )
            default_raw = (
                str(row[4]).strip() if len(row) > 4 and row[4] is not None else ""
            )
            col_types[name] = typ
            col_null_ok[name] = null_raw != "N"
            col_default[name] = default_raw

        def _has_default(col: str) -> bool:
            d = (col_default.get(col) or "").strip()
            return bool(d) and d.upper() != "NULL"

        required_cols = [
            c
            for c in col_types.keys()
            if (not col_null_ok.get(c, True)) and (not _has_default(c))
        ]

        def _is_simple_type(typ: str) -> bool:
            t = (typ or "").upper()
            return any(
                x in t
                for x in (
                    "NUMBER",
                    "INT",
                    "DECIMAL",
                    "FLOAT",
                    "DOUBLE",
                    "VARCHAR",
                    "CHAR",
                    "STRING",
                    "TEXT",
                    "BOOLEAN",
                    "DATE",
                    "TIME",
                    "TIMESTAMP",
                )
            )

        def _is_complex_type(typ: str) -> bool:
            t = (typ or "").upper()
            return any(
                x in t
                for x in (
                    "VARIANT",
                    "OBJECT",
                    "ARRAY",
                    "GEOGRAPHY",
                    "GEOMETRY",
                    "BINARY",
                )
            )

        # Heuristic insert/update column selection:
        # - Always include required columns (or inserts will fail)
        # - Prefer including key/time columns if present
        # - Avoid complex types unless required
        insert_cols: list[str] = []
        insert_cols.extend(required_cols)
        if key_col and key_col not in insert_cols:
            insert_cols.append(key_col)
        if (
            time_col
            and time_col not in insert_cols
            and _is_simple_type(col_types.get(time_col.upper(), ""))
        ):
            insert_cols.append(time_col)

        # Add a few optional simple columns to improve realism (cap total width).
        for c, typ in col_types.items():
            if c in insert_cols:
                continue
            if _is_complex_type(typ):
                continue
            if len(insert_cols) >= 20:
                break
            if any(
                k in c
                for k in (
                    "STATUS",
                    "STATE",
                    "TYPE",
                    "CATEGORY",
                    "AMOUNT",
                    "PRICE",
                    "NAME",
                    "REGION",
                )
            ):
                insert_cols.append(c)

        # If we still have very few columns, fill with additional simple columns.
        if len(insert_cols) < 8:
            for c, typ in col_types.items():
                if c in insert_cols:
                    continue
                if _is_complex_type(typ):
                    continue
                if not _is_simple_type(typ):
                    continue
                if len(insert_cols) >= 12:
                    break
                insert_cols.append(c)

        update_cols: list[str] = []

        def _is_key_or_id_like_col(col: str) -> bool:
            c = str(col or "").strip().upper()
            if not c:
                return False
            if c == (key_col or ""):
                return True
            return c == "ID" or c.endswith("ID") or c.endswith("KEY")

        preferred_update = [
            "UPDATED_AT",
            "UPDATED",
            "STATUS",
            "STATE",
            "LAST_UPDATED",
            "MODIFIED_AT",
        ]
        for p in preferred_update:
            if (
                p in col_types
                and p != (key_col or "")
                and not _is_key_or_id_like_col(p)
                and not _is_complex_type(col_types[p])
            ):
                update_cols = [p]
                break
        if not update_cols:
            for c, typ in col_types.items():
                if c == (key_col or ""):
                    continue
                if _is_key_or_id_like_col(c):
                    continue
                if _is_complex_type(typ):
                    continue
                if _is_simple_type(typ):
                    update_cols = [c]
                    break

        projection_cols: list[str] = []
        domain_label: str | None = None
        ai_notes: str | None = None

        # ------------------------------------------------------------------
        # 2.5) If Cortex is available, ask AI for a refined plan (bounded + validated)
        # ------------------------------------------------------------------
        ai_plan: dict[str, Any] | None = None
        if ai_available:
            try:
                import json

                # Sample a small set of columns and rows for domain inference.
                sample_cols: list[str] = []
                if key_col:
                    sample_cols.append(key_col.upper())
                if time_col and time_col.upper() not in sample_cols:
                    sample_cols.append(time_col.upper())
                for c, typ in col_types.items():
                    if c in sample_cols:
                        continue
                    if _is_complex_type(typ):
                        continue
                    if len(sample_cols) >= 12:
                        break
                    sample_cols.append(c)

                obj_parts: list[str] = []
                for c in sample_cols:
                    c_ident = _validate_ident(c, label="column")
                    obj_parts.append(f"'{c_ident}'")
                    obj_parts.append(_quote_ident(c_ident))
                obj_expr = (
                    f"OBJECT_CONSTRUCT_KEEP_NULL({', '.join(obj_parts)})"
                    if obj_parts
                    else "OBJECT_CONSTRUCT()"
                )
                sample_rows = await pool.execute_query(
                    f"SELECT {obj_expr} FROM {full_name} SAMPLE (20 ROWS)"
                )
                sample_payload = [r[0] for r in sample_rows if r]

                cols_for_prompt = []
                for c in list(col_types.keys())[:200]:
                    cols_for_prompt.append(
                        {
                            "name": c,
                            "type": col_types.get(c, ""),
                            "nullable": bool(col_null_ok.get(c, True)),
                            "default": col_default.get(c, "") or None,
                        }
                    )

                prompt = (
                    "You are helping configure a benchmark workload for a Snowflake table.\n"
                    f"TABLE: {db}.{sch}.{tbl}\n\n"
                    "COLUMNS (name/type/nullable/default):\n"
                    f"{json.dumps(cols_for_prompt, ensure_ascii=False)}\n\n"
                    "REQUIRED_COLUMNS (must be included in insert_columns):\n"
                    f"{json.dumps(required_cols)}\n\n"
                    "SAMPLE_ROWS (JSON objects):\n"
                    f"{json.dumps(sample_payload, ensure_ascii=False, default=str)}\n\n"
                    "Return STRICT JSON only with this schema:\n"
                    "{\n"
                    '  "domain_label": string,\n'
                    '  "insert_columns": [string],\n'
                    '  "update_columns": [string],\n'
                    '  "projection_columns": [string],\n'
                    '  "notes": string\n'
                    "}\n\n"
                    "Rules:\n"
                    "- Column names MUST be UPPERCASE and must exist in the provided columns list.\n"
                    "- insert_columns MUST include all REQUIRED_COLUMNS.\n"
                    "- update_columns MUST NOT include any columns ending with ID or KEY.\n"
                    "- Avoid VARIANT/OBJECT/ARRAY/BINARY unless REQUIRED.\n"
                    "- Keep insert_columns <= 20 and projection_columns <= 20.\n"
                )

                ai_rows = await pool.execute_query(
                    "SELECT AI_COMPLETE('claude-4-sonnet', ?)", params=[prompt]
                )
                raw = str(ai_rows[0][0]) if ai_rows and ai_rows[0] else ""
                try:
                    parsed = json.loads(raw)
                except Exception:
                    # Best-effort recovery if the model wrapped JSON with prose/code fences.
                    start = raw.find("{")
                    end = raw.rfind("}")
                    if start >= 0 and end > start:
                        parsed = json.loads(raw[start : end + 1])
                    else:
                        raise
                # Some models return a JSON *string* containing JSON. Normalize that too.
                if isinstance(parsed, str):
                    parsed_str = parsed.strip()
                    if parsed_str.startswith("{") and parsed_str.endswith("}"):
                        parsed = json.loads(parsed_str)
                if isinstance(parsed, dict):
                    ai_plan = parsed
            except Exception as e:
                logger.debug("AI plan generation failed; using heuristics: %s", e)

        def _sanitize_cols(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            out: list[str] = []
            for v in value:
                s = str(v or "").strip().upper()
                if not s:
                    continue
                if s in col_types:
                    out.append(s)
            # de-dupe, preserve order
            seen: set[str] = set()
            deduped: list[str] = []
            for c in out:
                if c in seen:
                    continue
                seen.add(c)
                deduped.append(c)
            return deduped

        if ai_plan:
            domain_label = (
                str(ai_plan.get("domain_label")).strip()
                if ai_plan.get("domain_label") is not None
                else None
            )
            ai_notes = (
                str(ai_plan.get("notes")).strip()
                if ai_plan.get("notes") is not None
                else None
            )

            proposed_insert = _sanitize_cols(ai_plan.get("insert_columns"))[:20]
            proposed_update = _sanitize_cols(ai_plan.get("update_columns"))[:5]
            proposed_proj = _sanitize_cols(ai_plan.get("projection_columns"))[:20]

            # Never update key/id-like columns.
            filtered_update: list[str] = []
            for c in proposed_update:
                if _is_key_or_id_like_col(c):
                    continue
                filtered_update.append(c)
            proposed_update = filtered_update[:5]

            # Ensure required columns are present in insert list.
            for c in required_cols:
                if c not in proposed_insert:
                    proposed_insert.insert(0, c)

            # Filter out complex types unless required.
            filtered_insert: list[str] = []
            for c in proposed_insert:
                if c in required_cols:
                    filtered_insert.append(c)
                    continue
                if _is_complex_type(col_types.get(c, "")):
                    continue
                filtered_insert.append(c)
            proposed_insert = filtered_insert[:20]

            if proposed_insert:
                insert_cols = proposed_insert
            if proposed_update:
                update_cols = proposed_update[:1]
            if proposed_proj:
                projection_cols = proposed_proj

        # ------------------------------------------------------------------
        # 3) Build value pools in Snowflake (no large data transfer through API)
        # ------------------------------------------------------------------
        pool_id = str(uuid4())

        # If template already has pools, keep history (new POOL_ID) but avoid reusing it.
        # (We intentionally do not delete old pools; template config will point at the new pool_id.)

        pools_created: dict[str, int] = {}

        # 3.1 Key pool (for point lookups / updates)
        if key_col:
            # Use a big enough pool to reduce collisions under high concurrency.
            target_n = max(5000, concurrency * 50)
            target_n = min(1_000_000, target_n)
            sample_n = min(1_000_000, max(target_n * 2, target_n))

            key_ident = _validate_ident(key_col, label="key_column")
            key_expr = _quote_ident(key_ident)

            insert_key_pool = f"""
            INSERT INTO {_results_prefix()}.TEMPLATE_VALUE_POOLS (
                POOL_ID, TEMPLATE_ID, POOL_KIND, COLUMN_NAME, SEQ, VALUE
            )
            SELECT
                ?, ?, 'KEY', ?, SEQ4(), TO_VARIANT(KEY_VAL)
            FROM (
                SELECT DISTINCT {key_expr} AS KEY_VAL
                FROM {full_name} SAMPLE ({sample_n} ROWS)
                WHERE {key_expr} IS NOT NULL
            )
            LIMIT {target_n}
            """
            await pool.execute_query(
                insert_key_pool, params=[pool_id, template_id, key_ident]
            )
            pools_created["KEY"] = int(target_n)

        # 3.2 Range pool (time cutoffs) for time-based scans
        if time_col:
            target_n = max(2000, concurrency * 10)
            target_n = min(1_000_000, target_n)
            sample_n = min(1_000_000, max(target_n * 2, target_n))

            time_ident = _validate_ident(time_col, label="time_column")
            time_expr = _quote_ident(time_ident)

            insert_time_pool = f"""
            INSERT INTO {_results_prefix()}.TEMPLATE_VALUE_POOLS (
                POOL_ID, TEMPLATE_ID, POOL_KIND, COLUMN_NAME, SEQ, VALUE
            )
            SELECT
                ?, ?, 'RANGE', ?, SEQ4(), TO_VARIANT(T_VAL)
            FROM (
                SELECT DISTINCT {time_expr} AS T_VAL
                FROM {full_name} SAMPLE ({sample_n} ROWS)
                WHERE {time_expr} IS NOT NULL
            )
            LIMIT {target_n}
            """
            await pool.execute_query(
                insert_time_pool, params=[pool_id, template_id, time_ident]
            )
            pools_created["RANGE"] = int(target_n)

        # 3.3 Row pool for inserts (sample rows packed as VARIANT objects)
        row_pool_n = max(2000, concurrency * 10)
        row_pool_n = min(100_000, row_pool_n)
        if insert_cols:
            obj_parts: list[str] = []
            for c in insert_cols:
                c_ident = _validate_ident(c, label="column")
                obj_parts.append(f"'{c_ident}'")
                obj_parts.append(_quote_ident(c_ident))
            obj_expr = f"OBJECT_CONSTRUCT_KEEP_NULL({', '.join(obj_parts)})"

            insert_row_pool = f"""
            INSERT INTO {_results_prefix()}.TEMPLATE_VALUE_POOLS (
                POOL_ID, TEMPLATE_ID, POOL_KIND, COLUMN_NAME, SEQ, VALUE
            )
            SELECT
                ?, ?, 'ROW', NULL, SEQ4(), {obj_expr}
            FROM {full_name} SAMPLE ({row_pool_n} ROWS)
            """
            await pool.execute_query(insert_row_pool, params=[pool_id, template_id])

        # ------------------------------------------------------------------
        # 4) Count inserted pool sizes (exact) and persist plan metadata into template config
        # ------------------------------------------------------------------
        counts: dict[str, int] = {}
        count_rows = await pool.execute_query(
            f"""
            SELECT POOL_KIND, COUNT(*) AS N
            FROM {_results_prefix()}.TEMPLATE_VALUE_POOLS
            WHERE TEMPLATE_ID = ?
              AND POOL_ID = ?
            GROUP BY POOL_KIND
            """,
            params=[template_id, pool_id],
        )
        for kind, n in count_rows:
            counts[str(kind)] = int(n or 0)

        ai_workload = {
            "available": ai_available,
            "model": "claude-4-sonnet",
            "availability_error": ai_error,
            "prepared_at": datetime.now(UTC).isoformat(),
            "pool_id": pool_id,
            "key_column": key_col,
            "time_column": time_col,
            "concurrency": concurrency,
            "pools": counts,
            "insert_columns": insert_cols,
            "update_columns": update_cols,
            "projection_columns": projection_cols,
            "domain_label": domain_label,
            "ai_notes": ai_notes,
        }

        # Store only the columns we will touch (keeps CONFIG small and avoids inserting into arbitrary columns).
        selected_cols: dict[str, str] = {}
        cols_to_store: set[str] = set()
        cols_to_store.update([c for c in insert_cols if c])
        cols_to_store.update([c for c in update_cols if c])
        if key_col:
            cols_to_store.add(key_col)
        if time_col:
            cols_to_store.add(time_col)
        for c in cols_to_store:
            c_ident = _validate_ident(c, label="column")
            selected_cols[c_ident] = col_types.get(c_ident, "VARCHAR")

        cfg2 = {**cfg, "columns": selected_cols, "ai_workload": ai_workload}
        # Keep existing template_name/description at top-level columns; only CONFIG changes here.
        await update_template(template_id, TemplateUpdate(config=cfg2))

        msg = (
            "AI workloads prepared."
            if ai_available
            else "AI not available in this account; persisted heuristic pools only."
        )
        return AiPrepareResponse(
            template_id=template_id,
            ai_available=ai_available,
            ai_error=ai_error,
            pool_id=pool_id,
            key_column=key_col,
            time_column=time_col,
            insert_columns=sorted({c for c in insert_cols if c}),
            update_columns=update_cols,
            projection_columns=projection_cols,
            domain_label=domain_label,
            pools=counts,
            message=msg,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("prepare AI template", e)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str):
    """
    Delete a template.

    Args:
        template_id: UUID of the template to delete
    """
    try:
        pool = snowflake_pool.get_default_pool()

        # Check if template exists by trying to get it first
        try:
            await get_template(template_id)
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                raise
            raise

        prefix = _results_prefix()

        # Delete all test artifacts associated with this template_id.
        # Template id is stored inside TEST_RESULTS.TEST_CONFIG (VARIANT).
        #
        # Child tables first (for cleanliness; constraints are informational in Snowflake).
        await pool.execute_query(
            f"""
            DELETE FROM {prefix}.TEST_LOGS
            WHERE TEST_ID IN (
                SELECT TEST_ID
                FROM {prefix}.TEST_RESULTS
                WHERE TEST_CONFIG:"template_id"::string = ?
            )
            """,
            params=[template_id],
        )
        await pool.execute_query(
            f"""
            DELETE FROM {prefix}.METRICS_SNAPSHOTS
            WHERE TEST_ID IN (
                SELECT TEST_ID
                FROM {prefix}.TEST_RESULTS
                WHERE TEST_CONFIG:"template_id"::string = ?
            )
            """,
            params=[template_id],
        )
        await pool.execute_query(
            f"""
            DELETE FROM {prefix}.QUERY_EXECUTIONS
            WHERE TEST_ID IN (
                SELECT TEST_ID
                FROM {prefix}.TEST_RESULTS
                WHERE TEST_CONFIG:"template_id"::string = ?
            )
            """,
            params=[template_id],
        )
        await pool.execute_query(
            f"""
            DELETE FROM {prefix}.TEST_RESULTS
            WHERE TEST_CONFIG:"template_id"::string = ?
            """,
            params=[template_id],
        )

        # Pools are keyed by template_id (not test_id).
        await pool.execute_query(
            f"DELETE FROM {prefix}.TEMPLATE_VALUE_POOLS WHERE TEMPLATE_ID = ?",
            params=[template_id],
        )

        # Finally delete the template record.
        await pool.execute_query(
            f"DELETE FROM {prefix}.TEST_TEMPLATES WHERE TEMPLATE_ID = ?",
            params=[template_id],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("delete template", e)


@router.post("/{template_id}/use", response_model=Dict[str, Any])
async def use_template(template_id: str):
    """
    Mark a template as used and increment usage counter.

    Args:
        template_id: UUID of the template

    Returns:
        Success message and updated usage count
    """
    try:
        pool = snowflake_pool.get_default_pool()

        now = datetime.now(UTC).isoformat()
        query = f"""
        UPDATE UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES
        SET 
            USAGE_COUNT = USAGE_COUNT + 1,
            LAST_USED_AT = '{now}'
        WHERE TEMPLATE_ID = '{template_id}'
        """

        await pool.execute_query(query)

        template = await get_template(template_id)

        return {
            "message": "Template usage recorded",
            "template_id": template_id,
            "usage_count": template["usage_count"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise http_exception("record template usage", e)
