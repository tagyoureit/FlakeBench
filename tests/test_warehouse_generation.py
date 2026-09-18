"""
Regression tests for warehouse generation reporting.

Guards against fabricating a warehouse generation where Snowflake reports none.

Per Snowflake docs:
- GENERATION applies only to WAREHOUSE_TYPE = STANDARD. CREATE INTERACTIVE
  WAREHOUSE accepts neither GENERATION nor RESOURCE_CONSTRAINT, and
  ENABLE_QUERY_ACCELERATION is not a valid interactive warehouse property.
  https://docs.snowflake.com/en/sql-reference/sql/create-interactive-warehouse
- The standard-warehouse default generation is now '2' (BCR-2250), so a blank
  generation column must NOT be reported as Gen1.
  https://docs.snowflake.com/en/user-guide/warehouses-gen2

SHOW WAREHOUSES column indices verified against a live account.
"""

from backend.api.routes.warehouses import _parse_warehouse_row

# Live SHOW WAREHOUSES output has 38 columns.
_HDR_LEN = 38


def _row(**kw) -> tuple:
    """Build a SHOW WAREHOUSES row with only the columns under test populated."""
    r: list = [None] * _HDR_LEN
    r[0] = kw.get("name", "WH")
    r[1] = kw.get("state", "SUSPENDED")
    r[2] = kw.get("type", "STANDARD")
    r[3] = kw.get("size")
    r[4] = kw.get("min_cluster", 1)
    r[5] = kw.get("max_cluster", 1)
    r[6] = 0
    r[22] = kw.get("enable_qas", "false")
    r[23] = kw.get("qas_scale", 8)
    r[30] = "STANDARD"
    r[32] = kw.get("resource_constraint", "")
    r[33] = kw.get("generation", "")
    r[34] = kw.get("qtm")
    r[35] = kw.get("mxpl")
    return tuple(r)


class TestInteractiveWarehouseGeneration:
    """Interactive warehouses have no generation and no QAS."""

    def test_interactive_reports_no_generation(self):
        wh = _parse_warehouse_row(
            _row(name="PERFTESTING_M_INTERACTIVE_1", type="INTERACTIVE", size="Medium")
        )
        assert wh["is_interactive"] is True
        assert wh["generation"] is None, "must not fabricate a generation"
        assert wh["resource_constraint"] is None

    def test_interactive_reports_no_qas(self):
        # SHOW WAREHOUSES returns enable_query_acceleration='false' and a scale
        # factor of 8 for interactive warehouses, but QAS does not apply.
        wh = _parse_warehouse_row(
            _row(
                name="BTQ_REALTIME_WH",
                type="INTERACTIVE",
                size="X-Small",
                enable_qas="false",
                qas_scale=8,
            )
        )
        assert wh["enable_query_acceleration"] is None
        assert wh["query_acceleration_max_scale_factor"] is None

    def test_interactive_retains_size_and_clusters(self):
        # Size and MIN/MAX_CLUSTER_COUNT *are* valid interactive properties.
        wh = _parse_warehouse_row(
            _row(
                name="IWH", type="INTERACTIVE", size="Large", min_cluster=3, max_cluster=3
            )
        )
        assert wh["size"] == "Large"
        assert wh["min_cluster_count"] == 3
        assert wh["max_cluster_count"] == 3


class TestStandardWarehouseGeneration:
    """Standard warehouses report generation from the authoritative column."""

    def test_gen2_from_generation_column(self):
        wh = _parse_warehouse_row(
            _row(size="Large", resource_constraint="STANDARD_GEN_2", generation="2")
        )
        assert wh["generation"] == "2"
        assert wh["resource_constraint"] == "STANDARD_GEN_2"

    def test_gen1_from_generation_column(self):
        wh = _parse_warehouse_row(
            _row(size="X-Small", resource_constraint="STANDARD_GEN_1", generation="1")
        )
        assert wh["generation"] == "1"
        assert wh["resource_constraint"] == "STANDARD_GEN_1"

    def test_unset_generation_is_none_not_gen1(self):
        # Blank generation means "not explicitly set". The account default is
        # Gen2 (BCR-2250), so reporting Gen1 here would be wrong.
        wh = _parse_warehouse_row(_row(name="CORTEX_ANALYST_WH", size="Large"))
        assert wh["is_interactive"] is False
        assert wh["generation"] is None
        assert wh["resource_constraint"] is None

    def test_qas_still_reported_for_standard(self):
        wh = _parse_warehouse_row(
            _row(size="Large", enable_qas="true", qas_scale=2, generation="2")
        )
        assert wh["enable_query_acceleration"] is True
        assert wh["query_acceleration_max_scale_factor"] == 2


class TestAdaptiveWarehouseGeneration:
    """Adaptive warehouses have no generation."""

    def test_adaptive_reports_no_generation(self):
        wh = _parse_warehouse_row(
            _row(name="ADAPTIVE_WH", type="ADAPTIVE", state="ENABLED", qtm=2, mxpl="X-Large")
        )
        assert wh["is_adaptive"] is True
        assert wh["is_interactive"] is False
        assert wh["generation"] is None
        assert wh["resource_constraint"] is None
        assert wh["max_query_performance_level"] == "X-Large"
        assert wh["query_throughput_multiplier"] == 2


class TestRowLengthTolerance:
    """Older/shorter SHOW WAREHOUSES rows must not raise."""

    def test_short_row_does_not_crash(self):
        wh = _parse_warehouse_row(tuple([None] * 24))
        assert wh["generation"] is None
        assert wh["is_interactive"] is False

    def test_generation_column_index_is_33(self):
        # Guard the index: generation sits between resource_constraint (32) and
        # query_throughput_multiplier (34).
        wh = _parse_warehouse_row(_row(size="Large", generation="2"))
        assert wh["generation"] == "2"
