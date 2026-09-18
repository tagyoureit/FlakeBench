"""Run FlakeBench templates sequentially against the SPCS-hosted application.

Each run is created, started, and polled to a terminal state before the next
begins, so runs never overlap and contend for the same warehouse. A fresh OAuth
token is minted per run, which keeps long sequences from dying on token expiry.

Benchmark runs execute client-side: the orchestrator spawns worker subprocesses
inside whichever host serves the API. Driving the SPCS deployment therefore keeps
load generation inside SPCS. Pointing this script at a local server would move
load generation onto the local machine and make results incomparable.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spcs_auth import auth_header, get_token

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
DEFAULT_POLL_SECONDS = 20
DEFAULT_MAX_RUN_SECONDS = 3000
DEFAULT_SETTLE_SECONDS = 15
REQUEST_TIMEOUT_SECONDS = 120


def log(message: str) -> None:
    """Emit a timestamped progress line.

    Args:
        message: Text to print.
    """
    print(f"[{datetime.now(UTC):%H:%M:%S}] {message}", flush=True)


def latin_square(templates: Sequence[str]) -> list[str]:
    """Order templates so each occupies every within-cycle position once.

    Rotating the order prevents cache-warmth from aliasing onto a single
    configuration: whichever template runs first benefits from an uncontended
    data cache, so that advantage must be shared evenly.

    Args:
        templates: Template identifiers, one per configuration.

    Returns:
        A sequence of ``len(templates) ** 2`` identifiers.
    """
    count = len(templates)
    return [
        templates[(cycle + slot) % count]
        for cycle in range(count)
        for slot in range(count)
    ]


def create_run(base_url: str, template_id: str, headers: dict[str, str]) -> str:
    """Create a run from a template.

    Args:
        base_url: Application base URL including scheme.
        template_id: Template to instantiate.
        headers: Authorization headers.

    Returns:
        The new run identifier.

    Raises:
        requests.HTTPError: If the run cannot be created.
    """
    response = requests.post(
        f"{base_url}/api/runs/",
        json={"template_id": template_id},
        headers={**headers, "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 300:
        raise requests.HTTPError(
            f"Create failed ({response.status_code}): {response.text[:300]}"
        )
    return str(response.json()["run_id"])


def start_run(base_url: str, run_id: str, headers: dict[str, str]) -> None:
    """Start a previously created run.

    Args:
        base_url: Application base URL including scheme.
        run_id: Run to start.
        headers: Authorization headers.

    Raises:
        requests.HTTPError: If the run cannot be started.
    """
    response = requests.post(
        f"{base_url}/api/runs/{run_id}/start",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 300:
        raise requests.HTTPError(
            f"Start failed ({response.status_code}): {response.text[:300]}"
        )


def poll_until_terminal(
    base_url: str,
    run_id: str,
    endpoint: str,
    connection: str,
    poll_seconds: int,
    max_run_seconds: int,
) -> str:
    """Poll a run until it reaches a terminal status.

    Status is read from ``/api/tests/{id}``; there is no ``GET /api/runs/{id}/``
    route. Transient polling errors are tolerated so a brief network blip does
    not abandon an in-flight run.

    Args:
        base_url: Application base URL including scheme.
        run_id: Run to poll.
        endpoint: SPCS ingress hostname, for token refresh.
        connection: connections.toml entry, for token refresh.
        poll_seconds: Delay between polls.
        max_run_seconds: Give up after this long.

    Returns:
        The terminal status, or ``"timeout"`` if the limit was reached.
    """
    began = time.monotonic()
    last_status: str | None = None

    while True:
        elapsed = time.monotonic() - began
        if elapsed > max_run_seconds:
            log(f"    TIMEOUT after {elapsed:.0f}s (last status={last_status})")
            return "timeout"

        time.sleep(poll_seconds)
        try:
            response = requests.get(
                f"{base_url}/api/tests/{run_id}",
                headers=auth_header(get_token(endpoint, connection=connection)),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code >= 300:
                continue
            status = str(response.json().get("status") or "").lower()
        except (requests.RequestException, ValueError, KeyError) as exc:
            log(f"    poll error, continuing: {type(exc).__name__}")
            continue

        if status != last_status:
            log(f"    status={status} t={elapsed:.0f}s")
            last_status = status
        if status in TERMINAL_STATUSES:
            return status


def run_sequence(
    base_url: str,
    endpoint: str,
    connection: str,
    templates: Sequence[str],
    poll_seconds: int,
    max_run_seconds: int,
    settle_seconds: int,
) -> list[tuple[str, str]]:
    """Execute templates one at a time, waiting for each to finish.

    Args:
        base_url: Application base URL including scheme.
        endpoint: SPCS ingress hostname.
        connection: connections.toml entry for credentials.
        templates: Ordered template identifiers to run.
        poll_seconds: Delay between status polls.
        max_run_seconds: Per-run timeout.
        settle_seconds: Pause between runs.

    Returns:
        Pairs of template identifier and final status, in execution order.
    """
    total = len(templates)
    outcomes: list[tuple[str, str]] = []

    for index, template_id in enumerate(templates, start=1):
        headers = auth_header(get_token(endpoint, connection=connection))
        try:
            run_id = create_run(base_url, template_id, headers)
            log(f"({index}/{total}) {template_id} -> run {run_id}")
            start_run(base_url, run_id, headers)
        except requests.HTTPError as exc:
            log(f"({index}/{total}) {template_id} LAUNCH FAILED: {exc}")
            outcomes.append((template_id, "launch_failed"))
            break

        status = poll_until_terminal(
            base_url, run_id, endpoint, connection, poll_seconds, max_run_seconds
        )
        log(f"({index}/{total}) {template_id} finished: {status}")
        outcomes.append((template_id, status))
        time.sleep(settle_seconds)

    return outcomes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run FlakeBench templates sequentially against the SPCS app."
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="SPCS ingress hostname without scheme",
    )
    parser.add_argument(
        "--template",
        action="append",
        required=True,
        metavar="TEMPLATE_ID",
        help="Template to run; repeat once per configuration",
    )
    parser.add_argument(
        "--order",
        choices=("latin-square", "as-given"),
        default="latin-square",
        help="latin-square runs N cycles balancing position (default); "
        "as-given runs the templates once in the order supplied",
    )
    parser.add_argument(
        "--connection",
        default="default",
        help="connections.toml entry for credentials (default: default)",
    )
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-run-seconds", type=int, default=DEFAULT_MAX_RUN_SECONDS)
    parser.add_argument("--settle-seconds", type=int, default=DEFAULT_SETTLE_SECONDS)
    return parser.parse_args()


def main() -> None:
    """Run the requested template sequence and print a summary."""
    args = _parse_args()
    base_url = f"https://{args.endpoint}"
    templates = (
        latin_square(args.template)
        if args.order == "latin-square"
        else list(args.template)
    )

    log(f"running {len(templates)} runs against {base_url} (order={args.order})")
    outcomes = run_sequence(
        base_url=base_url,
        endpoint=args.endpoint,
        connection=args.connection,
        templates=templates,
        poll_seconds=args.poll_seconds,
        max_run_seconds=args.max_run_seconds,
        settle_seconds=args.settle_seconds,
    )

    log("=== SUMMARY ===")
    for template_id, status in outcomes:
        log(f"  {template_id}: {status}")

    if any(status != "completed" for _, status in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
