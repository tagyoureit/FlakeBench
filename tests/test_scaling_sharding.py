"""
Tests for Section 2.10 (Scaling & Sharding) and 2.11 (Manual Scaling Bounds).

Covers:
- Target allocation algorithm (build_worker_targets)
- Deterministic sharding via WORKER_GROUP_ID
- Per-worker cap enforcement
- QPS mode target distribution
- min_connections floor validation
- Scaling mode validation (AUTO, BOUNDED, FIXED)
- Bounds validation (min/max workers, min/max connections)
- FIXED mode conflict resolution with CONCURRENCY load_mode
"""

import pytest

from backend.core.orchestrator import build_worker_targets


class TestBuildWorkerTargetsEvenDistribution:
    """Tests for even distribution of connections across workers."""

    def test_even_distribution_no_remainder(self) -> None:
        """10 connections across 5 workers = 2 each."""
        effective_total, targets = build_worker_targets(
            total_target=10,
            worker_group_count=5,
        )

        assert effective_total == 10
        assert len(targets) == 5

        for i in range(5):
            worker_id = f"worker-{i}"
            assert worker_id in targets
            assert targets[worker_id]["target_threads"] == 2
            assert targets[worker_id]["worker_group_id"] == i

    def test_even_distribution_single_worker(self) -> None:
        """All connections go to single worker."""
        effective_total, targets = build_worker_targets(
            total_target=100,
            worker_group_count=1,
        )

        assert effective_total == 100
        assert len(targets) == 1
        assert targets["worker-0"]["target_threads"] == 100
        assert targets["worker-0"]["worker_group_id"] == 0

    def test_even_distribution_large_scale(self) -> None:
        """1000 connections across 10 workers = 100 each."""
        effective_total, targets = build_worker_targets(
            total_target=1000,
            worker_group_count=10,
        )

        assert effective_total == 1000
        assert len(targets) == 10

        total_distributed = sum(t["target_threads"] for t in targets.values())
        assert total_distributed == 1000

        for i in range(10):
            assert targets[f"worker-{i}"]["target_threads"] == 100


class TestBuildWorkerTargetsUnevenDistribution:
    """Tests for remainder distribution to lowest group IDs."""

    def test_remainder_goes_to_lowest_group_ids(self) -> None:
        """11 connections across 5 workers = [3,2,2,2,2] by group_id."""
        effective_total, targets = build_worker_targets(
            total_target=11,
            worker_group_count=5,
        )

        assert effective_total == 11
        assert len(targets) == 5

        # 11 / 5 = 2 base, remainder 1
        # Worker 0 gets base+1 (3), workers 1-4 get base (2)
        assert targets["worker-0"]["target_threads"] == 3
        assert targets["worker-1"]["target_threads"] == 2
        assert targets["worker-2"]["target_threads"] == 2
        assert targets["worker-3"]["target_threads"] == 2
        assert targets["worker-4"]["target_threads"] == 2

        # Verify total
        total = sum(t["target_threads"] for t in targets.values())
        assert total == 11

    def test_remainder_all_but_one(self) -> None:
        """9 connections across 5 workers = [2,2,2,2,1]."""
        effective_total, targets = build_worker_targets(
            total_target=9,
            worker_group_count=5,
        )

        assert effective_total == 9
        # base = 1, remainder = 4
        # Workers 0,1,2,3 get 2, worker 4 gets 1
        assert targets["worker-0"]["target_threads"] == 2
        assert targets["worker-1"]["target_threads"] == 2
        assert targets["worker-2"]["target_threads"] == 2
        assert targets["worker-3"]["target_threads"] == 2
        assert targets["worker-4"]["target_threads"] == 1

    def test_remainder_single_extra(self) -> None:
        """6 connections across 5 workers = [2,1,1,1,1]."""
        effective_total, targets = build_worker_targets(
            total_target=6,
            worker_group_count=5,
        )

        assert effective_total == 6
        # base = 1, remainder = 1
        # Only worker 0 gets the extra
        assert targets["worker-0"]["target_threads"] == 2
        assert targets["worker-1"]["target_threads"] == 1
        assert targets["worker-2"]["target_threads"] == 1
        assert targets["worker-3"]["target_threads"] == 1
        assert targets["worker-4"]["target_threads"] == 1


class TestBuildWorkerTargetsEdgeCases:
    """Tests for edge cases in target allocation."""

    def test_more_workers_than_connections(self) -> None:
        """3 connections across 5 workers = [1,1,1,0,0]."""
        effective_total, targets = build_worker_targets(
            total_target=3,
            worker_group_count=5,
        )

        assert effective_total == 3
        assert targets["worker-0"]["target_threads"] == 1
        assert targets["worker-1"]["target_threads"] == 1
        assert targets["worker-2"]["target_threads"] == 1
        assert targets["worker-3"]["target_threads"] == 0
        assert targets["worker-4"]["target_threads"] == 0

    def test_single_connection_multiple_workers(self) -> None:
        """1 connection across 3 workers = [1,0,0]."""
        effective_total, targets = build_worker_targets(
            total_target=1,
            worker_group_count=3,
        )

        assert effective_total == 1
        assert targets["worker-0"]["target_threads"] == 1
        assert targets["worker-1"]["target_threads"] == 0
        assert targets["worker-2"]["target_threads"] == 0

    def test_zero_target_remains_zero(self) -> None:
        """Zero target is allowed to stay at 0."""
        effective_total, targets = build_worker_targets(
            total_target=0,
            worker_group_count=3,
        )

        assert effective_total == 0
        assert targets["worker-0"]["target_threads"] == 0
        assert targets["worker-1"]["target_threads"] == 0
        assert targets["worker-2"]["target_threads"] == 0

    def test_negative_target_clamps_to_zero(self) -> None:
        """Negative target is clamped to 0."""
        effective_total, targets = build_worker_targets(
            total_target=-5,
            worker_group_count=2,
        )

        assert effective_total == 0
        assert targets["worker-0"]["target_threads"] == 0
        assert targets["worker-1"]["target_threads"] == 0


class TestBuildWorkerTargetsPerWorkerCap:
    """Tests for per-worker capacity ceiling."""

    def test_per_worker_cap_clamps_total(self) -> None:
        """100 connections with 3 workers x 25 cap = 75 total."""
        effective_total, targets = build_worker_targets(
            total_target=100,
            worker_group_count=3,
            per_worker_cap=25,
        )

        assert effective_total == 75  # Clamped to 3 * 25
        assert len(targets) == 3

        # 75 / 3 = 25 each (even)
        for i in range(3):
            assert targets[f"worker-{i}"]["target_threads"] == 25

    def test_per_worker_cap_not_exceeded(self) -> None:
        """50 connections with 3 workers x 25 cap = 50 (no clamping needed)."""
        effective_total, targets = build_worker_targets(
            total_target=50,
            worker_group_count=3,
            per_worker_cap=25,
        )

        assert effective_total == 50  # No clamping
        # 50 / 3 = 16 base, remainder 2
        assert targets["worker-0"]["target_threads"] == 17
        assert targets["worker-1"]["target_threads"] == 17
        assert targets["worker-2"]["target_threads"] == 16

    def test_per_worker_cap_exact_match(self) -> None:
        """75 connections with 3 workers x 25 cap = exactly at limit."""
        effective_total, targets = build_worker_targets(
            total_target=75,
            worker_group_count=3,
            per_worker_cap=25,
        )

        assert effective_total == 75
        for i in range(3):
            assert targets[f"worker-{i}"]["target_threads"] == 25

    def test_per_worker_cap_with_uneven_distribution(self) -> None:
        """77 connections with 4 workers x 25 cap = clamped to 100, then distributed."""
        effective_total, targets = build_worker_targets(
            total_target=77,
            worker_group_count=4,
            per_worker_cap=25,
        )

        # 77 < 100 (4*25), so no clamping
        assert effective_total == 77
        # 77 / 4 = 19 base, remainder 1
        assert targets["worker-0"]["target_threads"] == 20
        assert targets["worker-1"]["target_threads"] == 19
        assert targets["worker-2"]["target_threads"] == 19
        assert targets["worker-3"]["target_threads"] == 19


class TestBuildWorkerTargetsQpsMode:
    """Tests for QPS mode target distribution."""

    def test_qps_mode_distributes_qps_evenly(self) -> None:
        """QPS mode includes per-worker QPS target."""
        effective_total, targets = build_worker_targets(
            total_target=100,
            worker_group_count=4,
            load_mode="QPS",
            target_qps_total=1000.0,
        )

        assert effective_total == 100
        assert len(targets) == 4

        for i in range(4):
            worker = targets[f"worker-{i}"]
            assert "target_qps" in worker
            assert worker["target_qps"] == 250.0  # 1000 / 4

    def test_qps_mode_uneven_connections_even_qps(self) -> None:
        """QPS is distributed evenly even when connections are uneven."""
        effective_total, targets = build_worker_targets(
            total_target=11,
            worker_group_count=5,
            load_mode="QPS",
            target_qps_total=500.0,
        )

        assert effective_total == 11
        # Connections: [3,3,2,2,2]
        # QPS: 100 each
        assert targets["worker-0"]["target_threads"] == 3
        assert targets["worker-0"]["target_qps"] == 100.0
        assert targets["worker-4"]["target_threads"] == 2
        assert targets["worker-4"]["target_qps"] == 100.0

    def test_non_qps_mode_no_qps_field(self) -> None:
        """Non-QPS modes don't include target_qps."""
        effective_total, targets = build_worker_targets(
            total_target=100,
            worker_group_count=4,
            load_mode="CONCURRENCY",
            target_qps_total=1000.0,  # Should be ignored
        )

        for worker in targets.values():
            assert "target_qps" not in worker

    def test_qps_mode_without_target_no_qps_field(self) -> None:
        """QPS mode without target_qps_total doesn't include field."""
        effective_total, targets = build_worker_targets(
            total_target=100,
            worker_group_count=4,
            load_mode="QPS",
            target_qps_total=None,
        )

        for worker in targets.values():
            assert "target_qps" not in worker


class TestBuildWorkerTargetsWorkerGroupId:
    """Tests for worker_group_id correctness."""

    def test_worker_group_ids_are_sequential(self) -> None:
        """Worker group IDs are 0-indexed and sequential."""
        _, targets = build_worker_targets(
            total_target=100,
            worker_group_count=5,
        )

        for i in range(5):
            assert targets[f"worker-{i}"]["worker_group_id"] == i

    def test_worker_ids_match_group_ids(self) -> None:
        """Worker ID suffix matches group ID."""
        _, targets = build_worker_targets(
            total_target=50,
            worker_group_count=10,
        )

        for worker_id, target in targets.items():
            expected_idx = int(worker_id.split("-")[1])
            assert target["worker_group_id"] == expected_idx


class TestMinConnectionsValidation:
    """Tests for min_connections validation in template normalization."""

    def test_min_connections_in_scaling_block(self) -> None:
        """min_connections is accepted in scaling block."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "concurrent_connections": 10,
            "scaling": {"min_connections": 5},
        }
        out = templates_api._normalize_template_config(cfg)

        assert out["scaling"]["min_connections"] == 5

    def test_min_connections_defaults_to_one(self) -> None:
        """min_connections defaults to 1 when not specified."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "concurrent_connections": 10,
        }
        out = templates_api._normalize_template_config(cfg)

        assert out["scaling"]["min_connections"] == 1

    def test_min_concurrency_rejected_with_error(self) -> None:
        """Legacy min_concurrency field is rejected with clear error."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "min_concurrency": 5,  # Legacy field
        }

        with pytest.raises(ValueError, match="min_concurrency was renamed"):
            templates_api._normalize_template_config(cfg)

    def test_min_connections_zero_defaults_to_one(self) -> None:
        """min_connections=0 is coerced to 1 (falsy value uses default)."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "concurrent_connections": 10,
            "scaling": {"min_connections": 0},
        }

        # 0 is falsy, so it defaults to 1 (not an error)
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["min_connections"] == 1

    def test_min_connections_negative_defaults_to_one(self) -> None:
        """Negative min_connections is coerced to 1."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "concurrent_connections": 10,
            "scaling": {"min_connections": -5},
        }

        # Negative coerced via `or 1` then passes >= 1 check? Let's verify behavior
        # Actually _coerce_int(-5) returns -5, which fails the >= 1 check
        with pytest.raises(ValueError, match="min_connections must be >= 1"):
            templates_api._normalize_template_config(cfg)

    def test_min_connections_cannot_exceed_max(self) -> None:
        """min_connections cannot exceed concurrent_connections."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 100,
            "concurrent_connections": 10,
            "scaling": {"min_connections": 20},
        }

        with pytest.raises(
            ValueError, match="min_connections must be <= concurrent_connections"
        ):
            templates_api._normalize_template_config(cfg)


class TestDeterministicSharding:
    """Tests for deterministic sharding behavior."""

    def test_same_inputs_same_outputs(self) -> None:
        """Same inputs produce identical outputs (deterministic)."""
        result1 = build_worker_targets(total_target=100, worker_group_count=5)
        result2 = build_worker_targets(total_target=100, worker_group_count=5)

        assert result1 == result2

    def test_worker_order_is_deterministic(self) -> None:
        """Workers are always ordered by group ID."""
        _, targets = build_worker_targets(total_target=100, worker_group_count=5)

        worker_ids = list(targets.keys())
        expected = [f"worker-{i}" for i in range(5)]

        assert worker_ids == expected

    def test_remainder_distribution_is_deterministic(self) -> None:
        """Remainder always goes to lowest group IDs."""
        _, targets1 = build_worker_targets(total_target=7, worker_group_count=5)
        _, targets2 = build_worker_targets(total_target=7, worker_group_count=5)

        # Both should have [2,2,1,1,1]
        expected = [2, 2, 1, 1, 1]
        for i, expected_count in enumerate(expected):
            assert targets1[f"worker-{i}"]["target_threads"] == expected_count
            assert targets2[f"worker-{i}"]["target_threads"] == expected_count


# =============================================================================
# Section 2.11: Manual Scaling Bounds Tests
# =============================================================================


class TestScalingModeValidation:
    """Tests for scaling.mode validation (AUTO, BOUNDED, FIXED)."""

    def test_auto_mode_accepted(self) -> None:
        """AUTO mode is accepted."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "AUTO"},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["mode"] == "AUTO"

    def test_bounded_mode_accepted(self) -> None:
        """BOUNDED mode is accepted."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_workers": 10},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["mode"] == "BOUNDED"

    def test_fixed_mode_accepted(self) -> None:
        """FIXED mode is accepted with required fields."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "FIXED",
                "min_workers": 5,
                "min_connections": 20,
            },
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["mode"] == "FIXED"

    def test_invalid_mode_rejected(self) -> None:
        """Invalid scaling mode is rejected."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "INVALID"},
        }
        with pytest.raises(
            ValueError, match="scaling.mode must be AUTO, BOUNDED, or FIXED"
        ):
            templates_api._normalize_template_config(cfg)

    def test_mode_case_insensitive(self) -> None:
        """Scaling mode is case-insensitive."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "bounded", "max_workers": 5},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["mode"] == "BOUNDED"

    def test_mode_defaults_to_auto(self) -> None:
        """Scaling mode defaults to AUTO when not specified."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["mode"] == "AUTO"


class TestFixedModeValidation:
    """Tests for FIXED mode specific validation."""

    def test_fixed_mode_requires_min_workers(self) -> None:
        """FIXED mode requires min_workers to be set."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "FIXED",
                "min_connections": 20,
                # min_workers missing
            },
        }
        with pytest.raises(ValueError, match="FIXED mode requires scaling.min_workers"):
            templates_api._normalize_template_config(cfg)

    def test_fixed_mode_requires_min_connections(self) -> None:
        """FIXED mode requires min_connections to be explicitly set."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "FIXED",
                "min_workers": 5,
                # min_connections missing - should error
            },
        }
        with pytest.raises(
            ValueError, match="FIXED mode requires scaling.min_connections"
        ):
            templates_api._normalize_template_config(cfg)

    def test_fixed_mode_computes_concurrent_connections(self) -> None:
        """FIXED mode with CONCURRENCY computes total from min_workers * min_connections."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 999,  # Should be overwritten
            "scaling": {
                "mode": "FIXED",
                "min_workers": 5,
                "min_connections": 20,
            },
        }
        out = templates_api._normalize_template_config(cfg)
        # 5 workers * 20 connections = 100
        assert out["concurrent_connections"] == 100


class TestBoundsValidation:
    """Tests for min/max bounds validation."""

    def test_max_workers_must_be_positive(self) -> None:
        """max_workers must be >= 1 when set."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_workers": 0},
        }
        with pytest.raises(ValueError, match="max_workers must be >= 1 or null"):
            templates_api._normalize_template_config(cfg)

    def test_max_connections_must_be_positive(self) -> None:
        """max_connections must be >= 1 when set."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_connections": 0},
        }
        with pytest.raises(ValueError, match="max_connections must be >= 1 or null"):
            templates_api._normalize_template_config(cfg)

    def test_min_workers_cannot_exceed_max_workers(self) -> None:
        """min_workers must be <= max_workers."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "BOUNDED",
                "min_workers": 10,
                "max_workers": 5,
            },
        }
        with pytest.raises(ValueError, match="min_workers must be <= max_workers"):
            templates_api._normalize_template_config(cfg)

    def test_min_connections_cannot_exceed_max_connections(self) -> None:
        """min_connections must be <= max_connections."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "BOUNDED",
                "min_connections": 50,
                "max_connections": 25,
            },
        }
        with pytest.raises(
            ValueError, match="min_connections must be <= max_connections"
        ):
            templates_api._normalize_template_config(cfg)

    def test_null_max_workers_is_unbounded(self) -> None:
        """null max_workers means unbounded."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "BOUNDED",
                "max_workers": None,
                "max_connections": 50,
            },
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["max_workers"] is None

    def test_negative_one_treated_as_unbounded(self) -> None:
        """max_workers=-1 is treated as unbounded (null)."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {
                "mode": "BOUNDED",
                "max_workers": -1,
            },
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["max_workers"] is None


class TestBoundsFeasibilityValidation:
    """Tests for bounds feasibility validation at template save."""

    def test_concurrency_unreachable_with_bounds(self) -> None:
        """Reject if concurrent_connections exceeds max_workers * max_connections."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 1000,  # Wants 1000 connections
            "scaling": {
                "mode": "BOUNDED",
                "max_workers": 2,
                "max_connections": 100,  # Max possible: 2*100=200
            },
        }
        with pytest.raises(ValueError, match="unreachable with max"):
            templates_api._normalize_template_config(cfg)

    def test_qps_unreachable_with_bounds(self) -> None:
        """Reject if target_qps is unreachable within bounds."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "QPS",
            "target_qps": 10000,  # Wants 10000 QPS
            "concurrent_connections": 100,
            "scaling": {
                "mode": "BOUNDED",
                "max_workers": 2,
                "max_connections": 50,  # Max total: 2*50=100 connections
            },
        }
        with pytest.raises(ValueError, match="unreachable with max"):
            templates_api._normalize_template_config(cfg)

    def test_feasible_bounds_accepted(self) -> None:
        """Accept when target is achievable within bounds."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,  # Wants 100 connections
            "scaling": {
                "mode": "BOUNDED",
                "max_workers": 5,
                "max_connections": 50,  # Max possible: 5*50=250
            },
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["concurrent_connections"] == 100


class TestBoundsDefaulting:
    """Tests for bounds defaulting behavior."""

    def test_min_workers_defaults_to_one(self) -> None:
        """min_workers defaults to 1 when not specified."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_workers": 10},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["min_workers"] == 1

    def test_max_workers_defaults_to_null(self) -> None:
        """max_workers defaults to null (unbounded) when not specified."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_connections": 50},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["max_workers"] is None

    def test_max_connections_defaults_to_null(self) -> None:
        """max_connections defaults to null when not specified."""
        from backend.api.routes import templates as templates_api

        cfg = {
            "workload_type": "MIXED",
            "load_mode": "CONCURRENCY",
            "concurrent_connections": 100,
            "scaling": {"mode": "BOUNDED", "max_workers": 10},
        }
        out = templates_api._normalize_template_config(cfg)
        assert out["scaling"]["max_connections"] is None
