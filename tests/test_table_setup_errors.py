"""
Unit tests for table setup failure reporting.

Regression coverage for ISSUE-004: `TableManager.setup()` used to return a bare
False for every failure mode, so the UI could only say "Failed to setup table X"
and the real cause (missing object vs. no privilege vs. no warehouse) was lost.
"""

import pytest

from backend.core.table_managers.standard import StandardTableManager
from backend.core.test_executor import TestExecutor
from backend.models.test_config import TableConfig, TableType


class _StubDriverError(Exception):
    """Stands in for a Snowflake driver exception."""


class _StubPool:
    """Minimal pool stub: returns no rows, or raises a configured error."""

    def __init__(self, error: str | None = None):
        self.error = error

    async def execute_query(self, query, *args, **kwargs):
        if self.error is not None:
            raise _StubDriverError(self.error)
        return []


def _manager(error: str | None) -> StandardTableManager:
    manager = StandardTableManager(
        TableConfig(
            name="T",
            table_type=TableType.STANDARD,
            database="DB",
            schema_name="SC",
            columns={},
        )
    )
    manager.pool = _StubPool(error)
    return manager


@pytest.mark.asyncio
async def test_missing_object_reports_absence():
    manager = _manager(None)

    assert await manager.setup() is False
    assert "does not exist" in manager.setup_error
    assert "DB.SC.T" in manager.setup_error


@pytest.mark.asyncio
async def test_not_authorized_does_not_claim_absence_only():
    manager = _manager(
        "002003 (02000): SQL compilation error: "
        "Object 'DB.SC.T' does not exist or not authorized."
    )

    assert await manager.setup() is False
    assert "not authorized" in manager.setup_error
    assert "grants" in manager.setup_error


@pytest.mark.asyncio
async def test_no_warehouse_is_distinguished():
    manager = _manager(
        "000606 (57P03): No active warehouse selected in the current session."
    )

    assert await manager.setup() is False
    assert "warehouse" in manager.setup_error.lower()
    # Must NOT be misreported as a missing table.
    assert "does not exist (or the current role cannot see it)" not in manager.setup_error


@pytest.mark.asyncio
async def test_generic_error_is_surfaced_verbatim():
    manager = _manager("Connection reset by peer")

    assert await manager.setup() is False
    assert "Connection reset by peer" in manager.setup_error


@pytest.mark.asyncio
async def test_failure_modes_produce_distinct_messages():
    errors = []
    for error in (
        None,
        "Object 'DB.SC.T' does not exist or not authorized.",
        "No active warehouse selected in the current session.",
        "Connection reset by peer",
    ):
        manager = _manager(error)
        await manager.setup()
        errors.append(manager.setup_error)

    assert len(set(errors)) == len(errors), f"messages collided: {errors}"
    assert all(e and "Failed to setup table" not in e for e in errors)


@pytest.mark.asyncio
async def test_executor_prefers_specific_reason():
    manager = _manager(None)
    await manager.setup()

    described = TestExecutor._describe_setup_failure(manager)

    assert described.startswith("Table setup failed: ")
    assert "does not exist" in described


def test_executor_falls_back_when_no_reason_recorded():
    manager = _manager(None)  # setup() never called, so setup_error is None

    described = TestExecutor._describe_setup_failure(manager)

    assert described == "Failed to setup table T"
