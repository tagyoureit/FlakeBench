import pytest


@pytest.mark.asyncio
async def test_is_hybrid_table_detects_by_column_name():
    from backend.core.table_profiler import _is_hybrid_table

    # SHOW TABLES columns vary by Snowflake version; ensure we key off column names.
    desc = [(f"COL_{i}",) for i in range(20)] + [
        ("is_hybrid",),
        ("is_iceberg",),
        ("is_dynamic",),
        ("is_immutable",),
    ]
    idx_is_hybrid = 20
    row = tuple([None] * idx_is_hybrid + ["Y", "N", "N", "N"])

    class Cursor:
        def __init__(self):
            self.description = desc

        def execute(self, query: str):  # noqa: ANN201
            return None

        def fetchall(self):  # noqa: ANN201
            return [row]

        def close(self):  # noqa: ANN201
            return None

    class Conn:
        def cursor(self):  # noqa: ANN201
            return Cursor()

    from contextlib import asynccontextmanager

    class Pool:
        async def _run_in_executor(self, func, *args):  # noqa: ANN001, ANN201
            return func(*args)

        @asynccontextmanager
        async def get_connection(self):  # noqa: ANN201
            yield Conn()

    assert await _is_hybrid_table(Pool(), "DB.SCHEMA.TBL") is True


@pytest.mark.asyncio
async def test_is_hybrid_table_fallback_tail_flags():
    from backend.core.table_profiler import _is_hybrid_table

    class Pool:
        async def execute_query(self, query: str):  # noqa: ANN201
            # Tail flags: is_hybrid, is_iceberg, is_dynamic, is_immutable
            return [("a", "b", "c", "d", "Y", "N", "N", "N")]

    assert await _is_hybrid_table(Pool(), "DB.SCHEMA.TBL") is True


@pytest.mark.asyncio
async def test_profile_snowflake_table_skip_bounds_when_disabled():
    """
    Regression: ai_adjust_sql should not trigger MIN/MAX scans on large HYBRID tables.

    We verify include_bounds=False avoids MIN/MAX while still detecting key/time columns.
    """
    from backend.core.table_profiler import profile_snowflake_table

    class Pool:
        async def execute_query(self, query: str):  # noqa: ANN201
            q = str(query or "").upper()
            if "SELECT MIN(" in q or "SELECT MAX(" in q:
                raise AssertionError("MIN/MAX should not run when include_bounds=False")
            if q.startswith("DESCRIBE TABLE"):
                return [
                    ("O_ORDERKEY", "NUMBER(38,0)"),
                    ("O_ORDERDATE", "DATE"),
                    ("O_ORDERSTATUS", "VARCHAR(1)"),
                ]
            if q.startswith("SHOW TABLES LIKE"):
                # Tail flags: is_hybrid, is_iceberg, is_dynamic, is_immutable
                return [("x", "x", "x", "x", "Y", "N", "N", "N")]
            return []

    prof = await profile_snowflake_table(Pool(), "DB.SCHEMA.TBL", include_bounds=False)
    assert prof.id_column is not None
    assert prof.time_column is not None
    assert prof.id_min is None
    assert prof.id_max is None
    assert prof.time_min is None
    assert prof.time_max is None
