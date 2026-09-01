"""
Interactive Table Manager (Existing Objects Only)

Benchmarks objects queried through Snowflake interactive warehouses. Two shapes
are supported:

1. Interactive tables — created with ``CREATE INTERACTIVE TABLE``, which requires
   a ``CLUSTER BY`` clause.
2. Zero-copy — a standard table queried directly through an interactive
   warehouse, with no copy or conversion. Snowflake documents standard tables as
   performing comparably to interactive tables.

Table creation is intentionally not supported by this app.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.core.table_managers.standard import StandardTableManager
from backend.core.warehouse_info import get_warehouse_info

logger = logging.getLogger(__name__)

# SHOW INTERACTIVE TABLES column index for the cluster key, e.g. "(O_ORDERKEY)".
_COL_CLUSTER_BY = 4

# Cache warming is converged once probe latency drops below this threshold.
_WARM_LATENCY_TARGET_MS = 200.0
# ...or once two consecutive probes land within this delta of each other.
_WARM_LATENCY_STABLE_DELTA_MS = 50.0
# Pause between probes so warming has a chance to make progress.
_WARM_PROBE_INTERVAL_S = 0.1


class InteractiveTableManager(StandardTableManager):
    """
    Manages existing objects benchmarked through an interactive warehouse.

    Inherits schema introspection from StandardTableManager and adds
    interactive-specific detection, warehouse attachment checks, and cache
    warming.
    """

    def __init__(self, config):
        super().__init__(config)
        # True when the object is a real interactive table, False when it is a
        # standard object used zero-copy, None until determined.
        self.is_interactive_table: bool | None = None

    async def _fetch_interactive_metadata(self) -> dict[str, Any] | None:
        """Look the object up via SHOW INTERACTIVE TABLES.

        Returns:
            Dict with ``clustering_key`` when the object is an interactive
            table, otherwise None (including when the lookup is unsupported).
        """
        if not (self.database and self.schema_name):
            return None

        try:
            rows = await self.pool.execute_query(
                f"SHOW INTERACTIVE TABLES LIKE '{self.table_name}' "
                f"IN SCHEMA {self.database}.{self.schema_name}"
            )
        except Exception as exc:
            # Account may not have interactive tables enabled; not an error.
            logger.debug(
                "SHOW INTERACTIVE TABLES failed for %s: %s", self.table_name, exc
            )
            return None

        if not rows:
            return None

        row = rows[0]
        cluster_by_raw = (
            str(row[_COL_CLUSTER_BY] or "").strip()
            if len(row) > _COL_CLUSTER_BY
            else ""
        )
        return {"clustering_key": cluster_by_raw.strip("()").strip() or None}

    async def table_exists(self) -> bool:
        """Check the object exists as an interactive table, table, or view.

        Interactive tables are checked first. A miss is not fatal: standard
        tables are valid zero-copy targets for an interactive warehouse, so the
        standard lookup runs as a fallback.
        """
        metadata = await self._fetch_interactive_metadata()
        if metadata is not None:
            self.is_interactive_table = True
            self.object_type = "INTERACTIVE_TABLE"
            return True

        exists = await super().table_exists()
        if exists:
            self.is_interactive_table = False
            logger.info(
                "%s is not an interactive table; benchmarking zero-copy through "
                "an interactive warehouse",
                self.get_full_table_name(),
            )
        return exists

    async def get_table_stats(self) -> dict[str, Any]:
        """Get table statistics plus interactive-specific metadata."""
        # INFORMATION_SCHEMA.TABLES does not describe interactive tables, so the
        # parent's TABLE fast path does not apply to them.
        stats = await super().get_table_stats()

        metadata = await self._fetch_interactive_metadata()
        if metadata is not None:
            self.is_interactive_table = True
            if metadata.get("clustering_key"):
                stats["clustering_key"] = metadata["clustering_key"]
        elif self.is_interactive_table is None:
            self.is_interactive_table = False

        stats["is_interactive_table"] = self.is_interactive_table
        return stats

    async def validate_schema(self) -> bool:
        """Introspect the schema, warning when no clustering key is present.

        A missing clustering key means queries cannot prune partitions, which
        risks the fixed 5-second interactive warehouse timeout. This is a
        warning, not a failure — the object is still benchmarkable.
        """
        if not await super().validate_schema():
            return False

        clustering_key = (self._stats or {}).get("clustering_key")
        if not clustering_key:
            metadata = await self._fetch_interactive_metadata()
            clustering_key = (metadata or {}).get("clustering_key")

        if not clustering_key:
            logger.warning(
                "%s has no clustering key. Interactive warehouses enforce a "
                "5-second query timeout; without partition pruning, queries may "
                "time out or fall back to the fallback warehouse.",
                self.get_full_table_name(),
            )

        return True

    async def check_warehouse_attachment(self, warehouse_name: str) -> bool | None:
        """Check whether this table is attached to an interactive warehouse.

        Attachment signals Snowflake to proactively maintain the table in cache.
        Unattached tables are still queryable; their data is cached on demand.

        Args:
            warehouse_name: Interactive warehouse to inspect.

        Returns:
            True or False when attachment could be determined, None when the
            warehouse could not be inspected. None means indeterminate — do not
            report it as "not attached".
        """
        info = await get_warehouse_info(self.pool, warehouse_name)
        if info is None:
            return None
        return info.has_table_attached(self.get_full_table_name())

    async def warm_cache(
        self, warehouse_name: str, timeout_s: int = 120
    ) -> dict[str, Any]:
        """Warm the interactive warehouse cache with repeated probe queries.

        Runs a cheap probe until latency converges or the timeout expires. The
        pool's existing warehouse context is used; no ``USE WAREHOUSE`` is
        issued per iteration.

        Args:
            warehouse_name: Interactive warehouse being warmed, for logging and
                the returned payload.
            timeout_s: Maximum wall-clock seconds to spend warming.

        Returns:
            Dict with ``cold_latency_ms``, ``warm_latency_ms``, ``iterations``,
            ``converged``, ``warehouse`` and ``table``. ``error`` is included
            when no probe succeeded.
        """
        full_name = self.get_full_table_name()
        probe_sql = f"SELECT 1 FROM {full_name} LIMIT 1"

        result: dict[str, Any] = {
            "warehouse": warehouse_name,
            "table": full_name,
            "cold_latency_ms": None,
            "warm_latency_ms": None,
            "iterations": 0,
            "converged": False,
        }

        # Start the clock only after setup, so timeout covers probing alone.
        deadline = time.monotonic() + max(1, timeout_s)
        previous_ms: float | None = None
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            started = time.monotonic()
            try:
                await self.pool.execute_query(probe_sql)
            except Exception as exc:
                last_error = exc
                logger.debug("Cache warming probe failed for %s: %s", full_name, exc)
                break

            elapsed_ms = (time.monotonic() - started) * 1000.0
            result["iterations"] += 1
            if result["cold_latency_ms"] is None:
                result["cold_latency_ms"] = round(elapsed_ms, 2)
            result["warm_latency_ms"] = round(elapsed_ms, 2)

            is_fast = elapsed_ms < _WARM_LATENCY_TARGET_MS
            is_stable = (
                previous_ms is not None
                and abs(previous_ms - elapsed_ms) < _WARM_LATENCY_STABLE_DELTA_MS
            )
            if is_fast or is_stable:
                result["converged"] = True
                break

            previous_ms = elapsed_ms
            await asyncio.sleep(_WARM_PROBE_INTERVAL_S)

        if result["iterations"] == 0:
            result["error"] = (
                str(last_error) if last_error else "no probe completed before timeout"
            )
            logger.warning(
                "Cache warming produced no measurements for %s: %s",
                full_name,
                result["error"],
            )
        else:
            logger.info(
                "Cache warming %s on %s: %s iterations, %sms -> %sms (converged=%s)",
                full_name,
                warehouse_name,
                result["iterations"],
                result["cold_latency_ms"],
                result["warm_latency_ms"],
                result["converged"],
            )

        return result
