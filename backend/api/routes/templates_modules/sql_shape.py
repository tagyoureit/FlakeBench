"""
SQL shape validation for fixed-arity custom query kinds.

POINT_LOOKUP and RANGE_SCAN are fixed-shape kinds: the executor binds a
hardcoded number of parameters for each (see ``backend/core/test_executor.py``,
the POINT_LOOKUP and RANGE_SCAN branches). Saving SQL whose shape does not match
its kind produces an opaque ``Bind variable ? not set`` driver error once per
query at run time, so the mismatch is rejected at save time instead.

Arbitrary placeholder counts and per-placeholder types belong to GENERIC_SQL,
which has its own parameter spec mechanism.
"""

import re

POINT_LOOKUP_KIND = "POINT_LOOKUP"
RANGE_SCAN_KIND = "RANGE_SCAN"

# Kinds this module validates. INSERT/UPDATE already size their binds from the
# placeholder count, and GENERIC_SQL validates its own arity against its
# configured parameter specs.
VALIDATED_KINDS = (POINT_LOOKUP_KIND, RANGE_SCAN_KIND)

_KIND_LABELS = {
    POINT_LOOKUP_KIND: "Point Lookup",
    RANGE_SCAN_KIND: "Range Scan",
}

_GENERIC_SQL_HINT = (
    "or switch to a Generic SQL query, which accepts any number of "
    "placeholders with per-placeholder types"
)

# Comments and string literals are stripped before inspection so that a literal
# containing '?' does not inflate the placeholder count and a comment mentioning
# BETWEEN does not trigger a false range-predicate match.
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTED_RE = re.compile(r"'(?:[^']|'')*'")

_PG_PLACEHOLDER_RE = re.compile(r"\$\d+")

# A range predicate is BETWEEN, or an inequality bound to a placeholder. The
# inequality must be placeholder-bound: "WHERE a > b AND id = ?" is a point
# lookup, not a range scan.
_BETWEEN_RE = re.compile(r"\bBETWEEN\b")
_INEQUALITY_RE = re.compile(r"(>=|<=|>|<)\s*(?:\?|\$\d+)")

# The lookbehind is required: without it ">=" and "<=" both match as equality.
_PLACEHOLDER_EQUALITY_RE = re.compile(r"(?<![<>!])=\s*(?:\?|\$\d+)")


def _strip_noise(sql: str) -> str:
    """Remove comments and single-quoted literals from ``sql``."""
    stripped = _BLOCK_COMMENT_RE.sub(" ", sql)
    stripped = _LINE_COMMENT_RE.sub(" ", stripped)
    return _SINGLE_QUOTED_RE.sub("''", stripped)


def count_placeholders(sql: str) -> int:
    """
    Count bind placeholders in ``sql``, ignoring comments and string literals.

    Counts ``?`` (Snowflake) and falls back to ``$N`` (Postgres) when no ``?``
    is present, matching the executor's binding behavior.
    """
    normalized = _strip_noise(str(sql or ""))
    q_count = normalized.count("?")
    if q_count > 0:
        return q_count
    return len(_PG_PLACEHOLDER_RE.findall(normalized))


def _describe_range_operator(upper_sql: str) -> str | None:
    """Return the range operator found in ``upper_sql``, or None."""
    if _BETWEEN_RE.search(upper_sql):
        return "BETWEEN"
    match = _INEQUALITY_RE.search(upper_sql)
    return match.group(1) if match else None


def validate_query_shape(kind: str, sql: str) -> str | None:
    """
    Validate that ``sql`` matches the expected shape for ``kind``.

    Returns an error message describing the mismatch, or None when the SQL is
    valid for the kind. Kinds outside :data:`VALIDATED_KINDS` always return
    None.

    Expected shapes:

    - POINT_LOOKUP: exactly one placeholder, bound by an equality predicate,
      with no range predicate.
    - RANGE_SCAN: one or two placeholders, with at least one range predicate.
      One placeholder is valid for the single-param time-cutoff form.
    """
    kind_u = str(kind or "").strip().upper()
    if kind_u not in VALIDATED_KINDS:
        return None

    text = str(sql or "").strip()
    if not text:
        return None

    label = _KIND_LABELS[kind_u]
    normalized = _strip_noise(text)
    upper = normalized.upper()
    placeholders = count_placeholders(text)
    range_operator = _describe_range_operator(upper)

    if kind_u == POINT_LOOKUP_KIND:
        if placeholders != 1:
            suffix = (
                f"This looks like a Range Scan (found {range_operator}) — "
                f"use the Range Scan query instead, {_GENERIC_SQL_HINT}."
                if range_operator
                else f"Use a single-placeholder equality predicate, {_GENERIC_SQL_HINT}."
            )
            return (
                f"{label} requires exactly 1 bind placeholder; found "
                f"{placeholders}. {suffix}"
            )
        if range_operator:
            return (
                f"{label} must not use a range predicate (found "
                f"{range_operator}). Use the Range Scan query instead, "
                f"{_GENERIC_SQL_HINT}."
            )
        if not _PLACEHOLDER_EQUALITY_RE.search(normalized):
            return (
                f"{label} requires an equality predicate bound to a "
                f"placeholder (e.g. WHERE col = ?)."
            )
        return None

    # RANGE_SCAN
    if placeholders not in (1, 2):
        return (
            f"{label} requires 1 or 2 bind placeholders; found {placeholders}. "
            f"Reduce the predicate to a single range, {_GENERIC_SQL_HINT}."
        )
    if not range_operator:
        return (
            f"{label} requires a range predicate (BETWEEN, >, >=, <, <=). "
            f"This looks like a Point Lookup — use the Point Lookup query "
            f"instead, {_GENERIC_SQL_HINT}."
        )
    return None
