#!/usr/bin/env python3
"""Manually trigger update_parent_run_aggregate for a given parent run ID."""

import asyncio
import sys

sys.path.insert(0, "/Users/rgoldin/Programming/unistore_performance_analysis")

from backend.core.results_store import update_parent_run_aggregate


async def main():
    parent_run_id = (
        sys.argv[1] if len(sys.argv) > 1 else "a6678746-1dfa-41f6-a00e-d1c7641ac9af"
    )
    print(f"Refreshing aggregate for parent_run_id: {parent_run_id}")
    await update_parent_run_aggregate(parent_run_id=parent_run_id)
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
