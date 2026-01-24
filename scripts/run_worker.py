#!/usr/bin/env python3
"""Run a headless benchmark worker from a template id."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from backend.core.test_registry import registry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a headless benchmark worker for multi-node orchestration."
    )
    parser.add_argument("--template-id", required=True, help="Template ID to run.")
    parser.add_argument(
        "--worker-group-id",
        type=int,
        default=0,
        help="Worker group index for deterministic sharding.",
    )
    parser.add_argument(
        "--worker-group-count",
        type=int,
        default=1,
        help="Total number of worker groups.",
    )
    parser.add_argument(
        "--parent-run-id",
        default=None,
        help="Parent multi-node run id (optional, stored in test_config).",
    )
    parser.add_argument(
        "--node-id",
        default=None,
        help="Node identifier (optional, stored in test_config).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Override concurrent_connections for this worker.",
    )
    parser.add_argument(
        "--min-concurrency",
        type=int,
        default=None,
        help="Override min_concurrency (QPS mode).",
    )
    parser.add_argument(
        "--start-concurrency",
        type=int,
        default=None,
        help="Override start_concurrency (FIND_MAX_CONCURRENCY).",
    )
    parser.add_argument(
        "--target-qps",
        type=float,
        default=None,
        help="Override target_qps (QPS mode).",
    )
    return parser


async def _run_worker(args: argparse.Namespace) -> int:
    overrides = {
        "worker_group_id": int(args.worker_group_id),
        "worker_group_count": int(args.worker_group_count),
    }
    if args.concurrency is not None:
        overrides["concurrent_connections"] = int(args.concurrency)
    if args.min_concurrency is not None:
        overrides["min_concurrency"] = int(args.min_concurrency)
    if args.start_concurrency is not None:
        overrides["start_concurrency"] = int(args.start_concurrency)
    if args.target_qps is not None:
        overrides["target_qps"] = float(args.target_qps)
    template_overrides: dict[str, Any] = {}
    if args.parent_run_id:
        template_overrides["parent_run_id"] = str(args.parent_run_id)
    if args.node_id:
        template_overrides["node_id"] = str(args.node_id)

    running = await registry.start_from_template(
        str(args.template_id),
        auto_start=True,
        overrides=overrides,
        template_overrides=template_overrides or None,
    )
    test_id = str(running.test_id)
    print(f"[worker] started test_id={test_id}")

    if running.task is not None:
        await running.task

    status_raw = running.executor.status
    status = str(getattr(status_raw, "value", status_raw)).upper()
    print(f"[worker] completed test_id={test_id} status={status}")
    return 0 if status == "COMPLETED" else 1


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_run_worker(args))
    except KeyboardInterrupt:
        print("[worker] interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
