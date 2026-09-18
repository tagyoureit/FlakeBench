"""
Tests for SQL shape validation of fixed-arity custom query kinds.

Shared cases live in tests/fixtures/query_shape_cases.json so the Python
validator and its JS mirror in configure.html are checked against one list.
"""

import json
from pathlib import Path

import pytest

from backend.api.routes.templates_modules.sql_shape import (
    count_placeholders,
    validate_query_shape,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "query_shape_cases.json"


def _load_cases() -> list[dict]:
    with _FIXTURE.open() as f:
        return json.load(f)["cases"]


@pytest.mark.parametrize(
    "case",
    _load_cases(),
    ids=lambda c: f"{c['kind']}-{c['reason'][:45]}",
)
def test_query_shape_cases(case: dict) -> None:
    """Every shared fixture case validates as expected."""
    error = validate_query_shape(case["kind"], case["sql"])
    if case["valid"]:
        assert error is None, f"expected valid ({case['reason']}), got: {error}"
    else:
        assert error is not None, f"expected invalid ({case['reason']}), got None"


def test_point_lookup_arity_message_names_the_count() -> None:
    error = validate_query_shape(
        "POINT_LOOKUP",
        'SELECT 1 FROM t WHERE "O_ORDERDATE" = ? AND "O_CUSTKEY" BETWEEN ? AND ? + 2399',
    )
    assert error is not None
    assert "exactly 1 bind placeholder; found 3" in error
    # Points the user at both the right field and the escape hatch.
    assert "Range Scan" in error
    assert "Generic SQL" in error


def test_range_scan_rejects_point_lookup_shape_with_pointer() -> None:
    error = validate_query_shape("RANGE_SCAN", "SELECT 1 FROM t WHERE id = ?")
    assert error is not None
    assert "requires a range predicate" in error
    assert "Point Lookup" in error


def test_point_lookup_rejects_range_operator_at_correct_arity() -> None:
    error = validate_query_shape("RANGE_SCAN", "SELECT 1 FROM t WHERE ts >= ?")
    assert error is None
    error = validate_query_shape("POINT_LOOKUP", "SELECT 1 FROM t WHERE ts >= ?")
    assert error is not None
    assert "must not use a range predicate" in error
    assert ">=" in error


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("WHERE id = ?", 1),
        ("WHERE id BETWEEN ? AND ? + 100", 2),
        ("WHERE id = $1", 1),
        ("WHERE a = $1 AND b = $2", 2),
        ("WHERE label = 'a?b' AND id = ?", 1),
        ("WHERE label = 'it''s a ?' AND id = ?", 1),
        ("WHERE id = ? -- trailing ? in comment", 1),
        ("/* ? ? ? */ WHERE id = ?", 1),
        ("WHERE 1=1", 0),
    ],
)
def test_count_placeholders(sql: str, expected: int) -> None:
    assert count_placeholders(sql) == expected


def test_unvalidated_kinds_and_blank_sql_return_none() -> None:
    assert validate_query_shape("INSERT", "INSERT INTO t VALUES (?, ?, ?)") is None
    assert validate_query_shape("GENERIC_SQL", "SELECT ? ? ?") is None
    assert validate_query_shape("POINT_LOOKUP", "") is None
    assert validate_query_shape("POINT_LOOKUP", "   ") is None
    # Kind matching is case-insensitive and whitespace tolerant.
    assert (
        validate_query_shape(" point_lookup ", "WHERE id BETWEEN ? AND ?") is not None
    )


def _base_cfg(**overrides) -> dict:
    cfg = {
        "workload_type": "CUSTOM",
        "custom_point_lookup_query": "SELECT * FROM t WHERE id = ?",
        "custom_range_scan_query": "SELECT * FROM t WHERE id BETWEEN ? AND ? + 100",
        "custom_insert_query": "INSERT INTO t VALUES (?)",
        "custom_update_query": "UPDATE t SET x = ? WHERE id = ?",
        "custom_point_lookup_pct": 100,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 0,
        "custom_update_pct": 0,
        "target_point_lookup_p95_latency_ms": -1,
        "target_point_lookup_p99_latency_ms": -1,
        "target_point_lookup_error_rate_pct": -1,
    }
    cfg.update(overrides)
    return cfg


def test_normalizer_rejects_mismatched_point_lookup() -> None:
    from backend.api.routes import templates as templates_api

    cfg = _base_cfg(
        custom_point_lookup_query="SELECT * FROM t WHERE id BETWEEN ? AND ? + 10",
    )
    with pytest.raises(ValueError, match="exactly 1 bind placeholder"):
        templates_api._normalize_template_config(cfg)


def test_normalizer_ignores_mismatched_sql_at_zero_weight() -> None:
    """A leftover default in an unused field must not block a save."""
    from backend.api.routes import templates as templates_api

    cfg = _base_cfg(
        custom_range_scan_query="SELECT * FROM t WHERE id = ?",
        custom_range_scan_pct=0,
    )
    # Point lookup carries all the weight and is well-formed, so this normalizes.
    out = templates_api._normalize_template_config(cfg)
    assert out["workload_type"] == "CUSTOM"


def test_normalizer_accepts_valid_shapes() -> None:
    from backend.api.routes import templates as templates_api

    cfg = _base_cfg(
        custom_point_lookup_pct=50,
        custom_range_scan_pct=50,
        target_range_scan_p95_latency_ms=-1,
        target_range_scan_p99_latency_ms=-1,
        target_range_scan_error_rate_pct=-1,
    )
    out = templates_api._normalize_template_config(cfg)
    assert out["custom_point_lookup_pct"] == 50


# --- API surface: config validation must return 400, not a generic 500 --------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


_BAD_SHAPE_CFG = {
    "custom_point_lookup_query": "SELECT * FROM t WHERE id BETWEEN ? AND ? + 10",
}


def _payload() -> dict:
    return {
        "template_name": "shape-test",
        "description": None,
        "config": _base_cfg(**_BAD_SHAPE_CFG),
    }


def test_create_template_returns_400_with_message(client) -> None:
    """Regression: config ValueError used to surface as a generic 500."""
    resp = client.post("/api/templates/", json=_payload())
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_config"
    assert "exactly 1 bind placeholder" in detail["message"]


def test_update_template_returns_400_with_message(client) -> None:
    from unittest.mock import AsyncMock, patch

    # The update path loads the existing template before normalizing the config,
    # so stub that lookup out to reach the validation branch.
    existing = {"template_id": "t-1", "usage_count": 0}
    with (
        patch(
            "backend.api.routes.templates.snowflake_pool.get_default_pool",
            return_value=AsyncMock(),
        ),
        patch(
            "backend.api.routes.templates.get_template",
            new=AsyncMock(return_value=existing),
        ),
    ):
        resp = client.put("/api/templates/t-1", json=_payload())
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_config"
    assert "exactly 1 bind placeholder" in detail["message"]


def test_create_template_surfaces_weight_sum_message(client) -> None:
    """The same fix un-swallows the pre-existing weights-must-sum-to-100 error."""
    payload = _payload()
    payload["config"] = _base_cfg(custom_point_lookup_pct=42)
    resp = client.post("/api/templates/", json=payload)
    assert resp.status_code == 400, resp.text
    assert "sum to 100.00" in resp.json()["detail"]["message"]


# --- GENERIC_SQL placeholder column extraction and save ordering --------------


@pytest.mark.parametrize(
    ("label", "sql", "expected"),
    [
        (
            "quoted multi-line (house style)",
            'SELECT "O_ORDERKEY" FROM t\nWHERE "O_ORDERDATE" = ?\n'
            '  AND "O_CUSTKEY" BETWEEN ? AND ? + 999999',
            [
                ("O_ORDERDATE", "="),
                ("O_CUSTKEY", "BETWEEN_START"),
                ("O_CUSTKEY", "BETWEEN_END"),
            ],
        ),
        (
            "unquoted",
            "WHERE O_ORDERDATE = ? AND O_CUSTKEY BETWEEN ? AND ?",
            [
                ("O_ORDERDATE", "="),
                ("O_CUSTKEY", "BETWEEN_START"),
                ("O_CUSTKEY", "BETWEEN_END"),
            ],
        ),
        ("quoted >=", 'WHERE "O_ORDERDATE" >= ?', [("O_ORDERDATE", ">=")]),
        ("bare >=", "WHERE O_ORDERDATE >= ?", [("O_ORDERDATE", ">=")]),
        ("bare <=", "WHERE X <= ?", [("X", "<=")]),
        ("bare <>", "WHERE X <> ?", [("X", "<>")]),
        ("qualified quoted", 'WHERE t."O_ORDERKEY" = ?', [("O_ORDERKEY", "=")]),
        ("bracketed", "WHERE [O_ORDERKEY] = ?", [("O_ORDERKEY", "=")]),
        (
            "quoted IN list",
            'WHERE "O_ORDERSTATUS" IN (?, ?, ?)',
            [("O_ORDERSTATUS", "IN"), ("O_ORDERSTATUS", "IN"), ("O_ORDERSTATUS", "IN")],
        ),
    ],
)
def test_extract_placeholder_columns(label: str, sql: str, expected: list) -> None:
    """Every placeholder must resolve to a column, whatever the identifier style.

    Regression: quoted identifiers previously returned [], so /ai/prepare
    generated no parameters and the run failed at warmup.
    """
    from backend.api.routes.templates import _extract_placeholder_columns

    got = _extract_placeholder_columns(sql)
    assert [(c["column"], c["operator"]) for c in got] == expected, label
    # Positions must be dense and ordered, or the spec/placeholder zip misaligns.
    assert [c["position"] for c in got] == list(range(len(expected)))


def test_extract_covers_every_placeholder_in_house_style_sql() -> None:
    from backend.api.routes.templates import _extract_placeholder_columns

    sql = (
        'SELECT "O_ORDERKEY", "O_ORDERDATE" FROM {table}\n'
        'WHERE "O_ORDERDATE" = ?\n  AND "O_CUSTKEY" BETWEEN ? AND ? + 999999'
    )
    assert len(_extract_placeholder_columns(sql)) == sql.count("?")


def _generic_cfg(parameters, sql=None, weight=100.0):
    return {
        "workload_type": "CUSTOM",
        "custom_point_lookup_pct": 0,
        "custom_range_scan_pct": 0,
        "custom_insert_pct": 0,
        "custom_update_pct": 0,
        "generic_queries": [
            {
                "id": "GENERIC_SQL_1",
                "query_kind": "GENERIC_SQL",
                "operation_type": "READ",
                "weight_pct": weight,
                "sql": sql
                or 'SELECT 1 FROM t WHERE "O_ORDERDATE" = ? AND "O_CUSTKEY" BETWEEN ? AND ? + 99',
                "parameters": parameters,
            }
        ],
        "target_generic_p95_latency_ms": -1,
        "target_generic_p99_latency_ms": -1,
        "target_generic_error_rate_pct": -1,
    }


def test_generic_empty_parameters_is_saveable_before_prepare() -> None:
    """Empty parameters is the legitimate pre-prepare state.

    /ai/prepare is POST /{template_id}/ai/prepare and needs a saved template, so
    blocking this save would deadlock every new generic entry.
    """
    from backend.api.routes import templates as templates_api

    out = templates_api._normalize_template_config(_generic_cfg([]))
    assert out["generic_queries"][0]["parameters"] == []


def test_generic_parameter_count_mismatch_is_rejected() -> None:
    from backend.api.routes import templates as templates_api

    one_param = [
        {"position": 1, "strategy": "sample_from_table", "column": "O_ORDERDATE"}
    ]
    with pytest.raises(ValueError, match="3 placeholder.*1 parameter"):
        templates_api._normalize_template_config(_generic_cfg(one_param))


def test_generic_matching_parameter_count_is_accepted() -> None:
    from backend.api.routes import templates as templates_api

    params = [
        {"position": 1, "strategy": "sample_from_table", "column": "O_ORDERDATE"},
        {"position": 2, "strategy": "sample_from_table", "column": "O_CUSTKEY"},
        {
            "position": 3,
            "strategy": "offset_from_previous",
            "depends_on": 2,
            "offset": 0,
        },
    ]
    out = templates_api._normalize_template_config(_generic_cfg(params))
    assert len(out["generic_queries"][0]["parameters"]) == 3
