"""
Warehouse type introspection.

Resolves warehouse metadata from ``SHOW WAREHOUSES`` so callers can branch on
warehouse *type* (interactive, adaptive, standard) rather than inferring it from
the table type being benchmarked. A standard table queried through an interactive
warehouse is a supported zero-copy pattern, so table type alone is not a reliable
signal for resume behaviour or credit rates.

Column indices are verified against live ``SHOW WAREHOUSES`` output and mirror
the constants in ``backend/api/routes/warehouses.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# SHOW WAREHOUSES column indices (0-based), verified against live account output.
_COL_NAME = 0
_COL_STATE = 1
_COL_TYPE = 2
_COL_SIZE = 3
# Attached tables for cache warming, comma-separated fully-qualified names.
# Present on interactive warehouses; empty for other warehouse types.
_COL_TABLES = 37

WAREHOUSE_TYPE_INTERACTIVE = "INTERACTIVE"
WAREHOUSE_TYPE_ADAPTIVE = "ADAPTIVE"
WAREHOUSE_TYPE_STANDARD = "STANDARD"

# Snowflake caps proactive cache warming at 10 tables per interactive warehouse.
PROACTIVE_WARMING_TABLE_LIMIT = 10

# Interactive warehouses have a fixed 5-second statement timeout.
INTERACTIVE_STATEMENT_TIMEOUT_SECONDS = 5


class _QueryExecutor(Protocol):
    """Minimal protocol for the async connection pool used by callers."""

    async def execute_query(
        self, sql: str, *args: Any, **kwargs: Any
    ) -> list[tuple]: ...


@dataclass(frozen=True)
class WarehouseInfo:
    """Normalized subset of ``SHOW WAREHOUSES`` output for one warehouse."""

    name: str
    state: str
    warehouse_type: str
    size: str | None
    attached_tables: tuple[str, ...] = field(default=())

    @property
    def is_interactive(self) -> bool:
        """True when this is an interactive warehouse."""
        return self.warehouse_type == WAREHOUSE_TYPE_INTERACTIVE

    @property
    def is_adaptive(self) -> bool:
        """True when this is an adaptive warehouse."""
        return self.warehouse_type == WAREHOUSE_TYPE_ADAPTIVE

    @property
    def is_suspended(self) -> bool:
        """True when the warehouse is not currently serving queries.

        Adaptive warehouses report ENABLED/DISABLED rather than
        STARTED/SUSPENDED, so only an explicit SUSPENDED state counts.
        """
        return self.state == "SUSPENDED"

    def has_table_attached(self, table_fqn: str) -> bool:
        """Check whether a fully-qualified table is attached for cache warming.

        Args:
            table_fqn: Fully-qualified ``DB.SCHEMA.TABLE`` name.

        Returns:
            True when the table appears in the warehouse's attached table list.
        """
        target = table_fqn.strip().upper()
        return target in self.attached_tables


def _parse_attached_tables(raw: Any) -> tuple[str, ...]:
    """Split the comma-separated ``tables`` column into normalized FQNs."""
    if not raw:
        return ()
    return tuple(part.strip().upper() for part in str(raw).split(",") if part.strip())


def parse_warehouse_row(row: tuple) -> WarehouseInfo:
    """Convert one ``SHOW WAREHOUSES`` row into a :class:`WarehouseInfo`.

    Args:
        row: A single result row from ``SHOW WAREHOUSES``.

    Returns:
        Parsed warehouse metadata. Missing trailing columns are tolerated so
        this keeps working if Snowflake adds or reorders later columns.
    """
    n = len(row)

    def _get(idx: int) -> Any:
        return row[idx] if n > idx else None

    size = _get(_COL_SIZE)
    return WarehouseInfo(
        name=str(_get(_COL_NAME) or ""),
        state=str(_get(_COL_STATE) or "").upper(),
        warehouse_type=str(_get(_COL_TYPE) or WAREHOUSE_TYPE_STANDARD).upper(),
        # Adaptive warehouses report an empty size. Interactive and standard
        # warehouses always report a definite size (e.g. "X-Small", "Medium"),
        # so None here means adaptive or a failed read — never "use a default".
        size=str(size).strip() or None if size is not None else None,
        attached_tables=_parse_attached_tables(_get(_COL_TABLES)),
    )


async def get_warehouse_info(
    pool: _QueryExecutor, warehouse_name: str
) -> WarehouseInfo | None:
    """Look up metadata for a single warehouse.

    Args:
        pool: Async connection pool exposing ``execute_query``.
        warehouse_name: Warehouse to inspect.

    Returns:
        Parsed metadata, or None when the warehouse is not found or the lookup
        fails. None means "unknown" — callers must not treat it as a negative.
    """
    name = (warehouse_name or "").strip()
    if not name:
        return None

    try:
        rows = await pool.execute_query(f"SHOW WAREHOUSES LIKE '{name}'")
    except Exception as exc:
        logger.debug("SHOW WAREHOUSES failed for %s: %s", name, exc)
        return None

    if not rows:
        logger.debug("Warehouse %s not found", name)
        return None

    return parse_warehouse_row(rows[0])


async def is_interactive_warehouse(
    pool: _QueryExecutor, warehouse_name: str
) -> bool | None:
    """Check whether a warehouse is an interactive warehouse.

    Args:
        pool: Async connection pool exposing ``execute_query``.
        warehouse_name: Warehouse to inspect.

    Returns:
        True or False when the warehouse type is known, None when it could not
        be determined. Callers should treat None as indeterminate rather than
        assuming a standard warehouse.
    """
    info = await get_warehouse_info(pool, warehouse_name)
    if info is None:
        return None
    return info.is_interactive
