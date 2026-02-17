# Methodology and Realism Contract

This document codifies correctness, methodology, and realism requirements for
analytical workload benchmarking.

## Scope

This spec does not replace baseline runner behavior. It makes inherited controls
explicit and defines OLAP-specific requirements so benchmark conclusions remain
defensible.

## Inherited Benchmark Controls

The following controls are inherited from existing template/app behavior and are
part of the OLAP benchmark contract:

- cache policy controls
- warmup and measurement phase controls
- trial/repeat controls
- load mode controls (`CONCURRENCY`, `QPS`, `FIND_MAX_CONCURRENCY`)

Required: persist these run-control settings as methodology metadata for each test.

## Pre-Flight Correctness Gate

Before performance runs begin, execute a correctness gate per analytical template:

1. Validate SQL shape and placeholder mapping.
2. Execute reference checks for non-approx analytical queries.
3. Validate `APPROX_COUNT_DISTINCT` against configured error tolerance.
4. Mark template as pass/fail and block benchmark execution on failure.

### Approximate Function Tolerance

`APPROX_COUNT_DISTINCT` must use a configurable maximum relative error threshold.

Suggested defaults:

- `max_relative_error_pct`: `2.0`
- report percentiles: `approx_error_pct_p50`, `approx_error_pct_p95`

**Relative error formula:**

```python
def compute_relative_error(approx_value: int, exact_value: int) -> float:
    """
    Compute relative error percentage for APPROX_COUNT_DISTINCT validation.
    
    Formula: |approx - exact| / exact * 100
    
    Returns:
        Relative error as a percentage (e.g., 1.5 means 1.5% error)
    """
    if exact_value == 0:
        return 0.0 if approx_value == 0 else float('inf')
    return abs(approx_value - exact_value) / exact_value * 100

# Example validation
approx = 1_023_456
exact = 1_000_000
error_pct = compute_relative_error(approx, exact)  # 2.3456%

if error_pct > config.max_relative_error_pct:
    raise CorrectnessGateError(
        f"APPROX_COUNT_DISTINCT error {error_pct:.2f}% exceeds threshold "
        f"{config.max_relative_error_pct}%"
    )
```

## Repeatability and Confidence

Each benchmark run should include:

- `trial_index` and `trial_count`
- `seed`
- `run_temperature` (`cold` or `warm`)
- confidence summary for headline metrics (`confidence_level`, interval width)

**Repeatability metadata fields:**

```python
@dataclass
class RepeatabilityMetadata:
    """Metadata required for reproducible benchmark runs."""
    
    # Trial tracking
    trial_index: int          # Current trial number (1-based)
    trial_count: int          # Total trials configured
    
    # Random state
    seed: int                 # Master seed for reproducibility
    worker_seeds: list[int]   # Per-worker seeds derived from master
    
    # Environment state
    run_temperature: str      # "cold" or "warm"
    cache_policy: str         # RESULT_CACHE setting
    warmup_queries: int       # Number of warmup queries executed
    
    # Confidence metrics
    confidence_level: float   # e.g., 0.95 for 95% CI
    confidence_interval_pct: float  # Half-width of CI as % of mean
    
    # Profile versioning
    profile_sql_hash: str     # Hash of SQL templates at profile time
    profile_timestamp: datetime  # When column profiles were captured

def compute_profile_sql_hash(queries: list[AnalyticalQuery]) -> str:
    """Compute hash of all SQL templates for staleness detection."""
    import hashlib
    combined = "".join(sorted(q.sql for q in queries))
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
```

### Profile Staleness Check

Column profiles may become stale if SQL templates are modified after profiling.
The system should warn when profiles don't match current SQL:

```python
def check_profile_staleness(
    stored_hash: str,
    current_queries: list[AnalyticalQuery]
) -> Optional[str]:
    """Check if column profiles are stale. Returns warning message if stale."""
    current_hash = compute_profile_sql_hash(current_queries)
    
    if stored_hash != current_hash:
        return (
            f"Column profiles may be stale. SQL hash changed from "
            f"{stored_hash} to {current_hash}. Consider re-running Prepare."
        )
    return None
```

Minimum recommendation:

- at least 3 trials for directional comparisons
- at least 5 trials for publication-quality comparisons

## Realism Profiles

Realism is optional and backward-compatible. Missing realism config defaults to
`BASELINE`.

| Profile | Goal | Typical knobs |
|---------|------|---------------|
| `BASELINE` | Preserve current behavior | none |
| `REALISTIC` | Light production-like skew and nulls | `null_rate`, `skew_factor` |
| `STRESS_SKEW` | Heavy hotspot behavior | high `skew_factor` |
| `NULL_HEAVY` | Null semantics stress | high `null_rate` |
| `LATE_ARRIVAL` | Event-time vs ingest-time lag | `late_arrival_lag_days` |
| `SELECTIVITY_SWEEP` | Same query at multiple selectivity bands | `selectivity_band` |

Suggested config shape:

```yaml
realism:
  profile: "REALISTIC"
  null_rate: 0.15
  skew_factor: 1.8
  late_arrival_lag_days: [0, 1, 3, 7]
  selectivity_band: [0.001, 0.01, 0.1, 0.5]
```

## Configuration Precedence

Realism settings follow a **per-parameter overrides template** merge rule, consistent
with existing configuration patterns in the codebase (see `configure.html` deep-merge).

| Level | Scope | Example |
|-------|-------|---------|
| Template-level `realism` | Default for all queries in template | `null_rate: 0.15` |
| Per-parameter override | Specific parameter in a query | `null_rate: 0.35` |

**Merge rule:** Per-parameter config **overrides** template-level profile defaults.

```yaml
# Template level - sets defaults
realism:
  profile: "REALISTIC"  # implies null_rate: 0.15

# Per-parameter (overrides template default)
parameters:
  - name: "channel"
    strategy: "nullable_sample"
    null_rate: 0.35  # THIS WINS over template's 0.15
```

**Implementation pattern (follows existing codebase):**

```python
def resolve_null_rate(param_config: ParameterConfig, template_realism: RealismConfig) -> float:
    """Per-parameter overrides template, template overrides global default."""
    if param_config.null_rate is not None:
        return param_config.null_rate
    if template_realism and template_realism.null_rate is not None:
        return template_realism.null_rate
    return 0.0  # Global default
```

## Realism Validation Matrix

Every release should include at least one scenario from each category:

1. skewed category distribution
2. NULL-heavy dimensions
3. late-arriving event records
4. selective and non-selective filters

Store realized realism attributes in `olap_metrics` to support comparisons:

- realized null rate
- realized selectivity
- realized skew concentration
- realized late-arrival lag distribution

## Acceptance Checklist

- [ ] inherited run-control settings persisted with each test
- [ ] correctness gate enabled for OLAP templates
- [ ] approx distinct tolerance configured and reported
- [ ] trial/seed metadata persisted
- [ ] realism profile defaults to backward-compatible baseline
- [ ] realism scenario metrics visible in compare outputs
