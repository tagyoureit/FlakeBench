import pytest


def test_templates_normalize_preset_to_custom():
    from backend.api.routes import templates as templates_api

    cfg = {
        "workload_type": "MIXED",
        # Old UI/defaults could have drifted; preset must win.
        "custom_point_lookup_pct": 25,
        "custom_range_scan_pct": 25,
        "custom_insert_pct": 25,
        "custom_update_pct": 25,
    }

    out = templates_api._normalize_template_config(cfg)  # type: ignore[attr-defined]
    assert out["workload_type"] == "CUSTOM"
    assert out["custom_point_lookup_pct"] == 25
    assert out["custom_range_scan_pct"] == 25
    assert out["custom_insert_pct"] == 35
    assert out["custom_update_pct"] == 15
    assert "SELECT * FROM {table}" in out["custom_point_lookup_query"]


def test_templates_normalize_custom_requires_sum_100():
    from backend.api.routes import templates as templates_api

    cfg = {
        "workload_type": "CUSTOM",
        "custom_point_lookup_query": "SELECT 1",
        "custom_range_scan_query": "SELECT 1",
        "custom_insert_query": "INSERT INTO t VALUES (1)",
        "custom_update_query": "UPDATE t SET x=1",
        "custom_point_lookup_pct": 50,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 10,
        "custom_update_pct": 10,
    }
    with pytest.raises(ValueError, match="sum to 100"):
        templates_api._normalize_template_config(cfg)  # type: ignore[attr-defined]


def test_templates_normalize_custom_requires_sql_when_pct_gt_0():
    from backend.api.routes import templates as templates_api

    cfg = {
        "workload_type": "CUSTOM",
        "custom_point_lookup_query": "",
        "custom_range_scan_query": "SELECT 1",
        "custom_insert_query": "INSERT INTO t VALUES (1)",
        "custom_update_query": "UPDATE t SET x=1",
        "custom_point_lookup_pct": 100,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 0,
        "custom_update_pct": 0,
    }
    with pytest.raises(ValueError, match="custom_point_lookup_query"):
        templates_api._normalize_template_config(cfg)  # type: ignore[attr-defined]


def test_custom_schedule_exact_counts():
    from backend.core.test_executor import TestExecutor

    weights = {"POINT_LOOKUP": 25, "RANGE_SCAN": 25, "INSERT": 35, "UPDATE": 15}
    schedule = TestExecutor._build_smooth_weighted_schedule(weights)
    assert len(schedule) == 100
    for k, w in weights.items():
        assert schedule.count(k) == w


@pytest.mark.asyncio
async def test_failure_records_preserve_query_text_and_kind():
    """
    Regression: failures must persist real SQL + correct query_kind so UI can later
    display true error reasons by operation type.
    """
    from backend.core.test_executor import TestExecutor
    from backend.models import TableConfig, TableType, TestScenario, WorkloadType

    class StubPool:
        warehouse = "TEST_WH"

        async def execute_query(self, *args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("boom")

        async def execute_query_with_info(self, *args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("boom")

    class StubManager:
        def __init__(self):
            self.config = TableConfig(
                name="T1",
                table_type=TableType.STANDARD,
                columns={
                    "id": "NUMBER",
                    "data": "VARCHAR",
                    "timestamp": "TIMESTAMP_NTZ",
                },
                database="DB",
                schema_name="SCHEMA",
            )
            self.pool = StubPool()

        def get_full_table_name(self) -> str:  # noqa: D401
            return "DB.SCHEMA.T1"

    scenario = TestScenario(
        name="failure-records",
        duration_seconds=1,
        concurrent_connections=1,
        workload_type=WorkloadType.MIXED,
        table_configs=[
            TableConfig(
                name="T1",
                table_type=TableType.STANDARD,
                columns={
                    "id": "NUMBER",
                    "data": "VARCHAR",
                    "timestamp": "TIMESTAMP_NTZ",
                },
                database="DB",
                schema_name="SCHEMA",
            )
        ],
        collect_query_history=True,
    )

    ex = TestExecutor(scenario)
    ex.table_managers = [StubManager()]  # type: ignore[assignment]

    await ex._execute_read(worker_id=0, warmup=False)  # type: ignore[attr-defined]
    await ex._execute_write(worker_id=0, warmup=False)  # type: ignore[attr-defined]

    recs = list(ex.get_query_execution_records())
    assert recs, "expected query execution records"

    read_fail = next(
        r
        for r in recs
        if not r.success and r.query_kind in {"RANGE_SCAN", "POINT_LOOKUP"}
    )
    assert read_fail.query_text != "READ_FAILED"
    assert "SELECT" in read_fail.query_text.upper()

    write_fail = next(
        r for r in recs if not r.success and r.query_kind in {"INSERT", "UPDATE"}
    )
    assert write_fail.query_text != "WRITE_FAILED"
    assert any(k in write_fail.query_text.upper() for k in ("INSERT", "UPDATE"))
