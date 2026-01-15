"""
API routes for database/schema/table discovery.

This powers the Configure UI dropdowns so users select from *existing* objects.

Supported backends:
- Snowflake (standard/hybrid/interactive tables): list databases, schemas, tables, and views
- Postgres family (POSTGRES / SNOWFLAKE_POSTGRES): list databases, schemas, tables, and views

Notes:
- For Postgres-family connections, we dynamically query available databases by connecting to the
  `postgres` database (which always exists), then connect to the user-selected database for
  schema/table discovery.
- These endpoints intentionally avoid returning full DDL or any data; they only return names/types.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.connectors import postgres_pool, snowflake_pool
from backend.models.test_config import TableType

router = APIRouter()
logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Z0-9_]+$")


def _upper_str(v: Any) -> str:
    return str(v or "").strip().upper()


def _validate_ident(value: Any, *, label: str) -> str:
    """
    Validate identifier components we interpolate into SHOW commands.

    Snowflake SHOW statements do not support bind variables for object identifiers, so we enforce:
    - unquoted identifiers only
    - [A-Z0-9_]+
    """

    name = _upper_str(value)
    if not name:
        raise ValueError(f"Missing {label}")
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"Invalid {label}: {name!r} (expected [A-Z0-9_]+)")
    return name


def _table_type(value: Any) -> TableType:
    if not value:
        return TableType.STANDARD
    raw = str(value).strip().lower()
    return TableType(raw)


def _is_postgres_family(t: TableType) -> bool:
    return t in (
        TableType.POSTGRES,
        TableType.SNOWFLAKE_POSTGRES,
    )


def _get_postgres_pool(table_type: TableType):
    if table_type == TableType.SNOWFLAKE_POSTGRES:
        return postgres_pool.get_snowflake_postgres_pool()
    return postgres_pool.get_default_pool()


def _postgres_pool_type(table_type: TableType) -> str:
    """Return pool_type string for fetch_from_database()."""
    if table_type == TableType.SNOWFLAKE_POSTGRES:
        return "snowflake_postgres"
    return "default"


@router.get("/databases", response_model=list[dict[str, Any]])
async def list_databases(table_type: str = Query("standard")):
    """
    List available databases.

    - Snowflake: returns all databases visible to the configured role.
    - Postgres-family: connects to 'postgres' DB and queries pg_database.
    """

    t = _table_type(table_type)
    if _is_postgres_family(t):
        pool_type = _postgres_pool_type(t)
        try:
            # Connect to 'postgres' database (always exists) to list available databases
            rows = await postgres_pool.fetch_from_database(
                database="postgres",
                query="""
                    SELECT datname
                    FROM pg_database
                    WHERE datistemplate = false
                      AND datallowconn = true
                    ORDER BY datname
                """,
                pool_type=pool_type,
            )
            # Preserve original case for Postgres (it's case-sensitive)
            return [{"name": str(r["datname"]), "type": "DATABASE"} for r in rows]
        except Exception as e:
            logger.warning(f"Failed to list Postgres databases: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to connect to Postgres: {e}",
            ) from e

    sf = snowflake_pool.get_default_pool()
    rows = await sf.execute_query("SHOW DATABASES")

    out: list[dict[str, Any]] = []
    for row in rows:
        # SHOW DATABASES: name is typically at index 1 (created_on, name, ...)
        name = None
        if row and len(row) > 1:
            name = row[1]
        elif row:
            name = row[0]
        name_str = _upper_str(name)
        if name_str:
            out.append({"name": name_str, "type": "DATABASE"})

    out.sort(key=lambda x: x["name"])
    return out


@router.get("/schemas", response_model=list[dict[str, Any]])
async def list_schemas(
    table_type: str = Query("standard"),
    database: str | None = Query(None),
):
    """
    List schemas in a database.

    - Snowflake: requires database, lists schemas in that database.
    - Postgres-family: requires database, connects to that database to list schemas.
    """

    t = _table_type(table_type)
    if _is_postgres_family(t):
        db_name = str(database or "").strip()
        if not db_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing database parameter",
            )
        pool_type = _postgres_pool_type(t)
        try:
            rows = await postgres_pool.fetch_from_database(
                database=db_name,
                query="""
                    SELECT schema_name
                    FROM information_schema.schemata
                    ORDER BY schema_name
                """,
                pool_type=pool_type,
            )
            return [{"name": str(r["schema_name"]), "type": "SCHEMA"} for r in rows]
        except Exception as e:
            logger.warning(f"Failed to list schemas in {db_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to connect to database '{db_name}': {e}",
            ) from e

    try:
        db = _validate_ident(database, label="database")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    sf = snowflake_pool.get_default_pool()
    rows = await sf.execute_query(f"SHOW SCHEMAS IN DATABASE {db}")

    out: list[dict[str, Any]] = []
    for row in rows:
        # SHOW SCHEMAS: name is typically at index 1
        name = None
        if row and len(row) > 1:
            name = row[1]
        elif row:
            name = row[0]
        name_str = _upper_str(name)
        if name_str:
            out.append({"name": name_str, "type": "SCHEMA"})

    out.sort(key=lambda x: x["name"])
    return out


def _include_views(t: TableType) -> bool:
    """
    Determine whether to include views for a given table type.

    - STANDARD: tables + views (views can be built on standard tables)
    - HYBRID / INTERACTIVE: tables only (views don't make sense on these)
    - Postgres family: tables + views
    """
    if t in (TableType.HYBRID, TableType.INTERACTIVE):
        return False
    return True


@router.get("/objects", response_model=list[dict[str, Any]])
async def list_objects(
    table_type: str = Query("standard"),
    database: str | None = Query(None),
    schema: str | None = Query(None),
):
    """
    List tables (and optionally views) in a schema.

    Returns objects as:
      { "name": "...", "type": "TABLE" | "VIEW" }

    For HYBRID and INTERACTIVE table types, only tables are returned (no views).
    For STANDARD and Postgres-family types, both tables and views are returned.
    """

    t = _table_type(table_type)
    include_views = _include_views(t)

    if _is_postgres_family(t):
        db_name = str(database or "").strip()
        schema_name = str(schema or "").strip()
        if not db_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing database"
            )
        if not schema_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing schema"
            )

        pool_type = _postgres_pool_type(t)
        try:
            # Tables
            table_rows = await postgres_pool.fetch_from_database(
                db_name,
                """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = $1
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """,
                schema_name,
                pool_type=pool_type,
            )

            out: list[dict[str, Any]] = [
                {"name": str(r["table_name"]), "type": "TABLE"} for r in table_rows
            ]

            # Views (only if applicable for this table type)
            if include_views:
                view_rows = await postgres_pool.fetch_from_database(
                    db_name,
                    """
                        SELECT table_name
                        FROM information_schema.views
                        WHERE table_schema = $1
                        ORDER BY table_name
                    """,
                    schema_name,
                    pool_type=pool_type,
                )
                out.extend(
                    {"name": str(r["table_name"]), "type": "VIEW"} for r in view_rows
                )

            out.sort(key=lambda x: (x["type"], x["name"]))
            return out
        except Exception as e:
            logger.warning(f"Failed to list objects in {db_name}.{schema_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to connect to database '{db_name}': {e}",
            ) from e

    try:
        db = _validate_ident(database, label="database")
        sch = _validate_ident(schema, label="schema")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    sf = snowflake_pool.get_default_pool()

    # SHOW TABLES is the most reliable across Snowflake editions/features.
    table_rows = await sf.execute_query(f"SHOW TABLES IN SCHEMA {db}.{sch}")

    out: list[dict[str, Any]] = []

    for row in table_rows:
        # SHOW TABLES: name at index 1
        name = None
        if row and len(row) > 1:
            name = row[1]
        elif row:
            name = row[0]
        name_str = _upper_str(name)
        if name_str:
            out.append({"name": name_str, "type": "TABLE"})

    # Views (only for STANDARD table type)
    if include_views:
        view_rows = await sf.execute_query(f"SHOW VIEWS IN SCHEMA {db}.{sch}")
        for row in view_rows:
            # SHOW VIEWS: name at index 1
            name = None
            if row and len(row) > 1:
                name = row[1]
            elif row:
                name = row[0]
            name_str = _upper_str(name)
            if name_str:
                out.append({"name": name_str, "type": "VIEW"})

    out.sort(key=lambda x: (x["type"], x["name"]))
    return out
