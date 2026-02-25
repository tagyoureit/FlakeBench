# FlakeBench

> **Performance benchmarking tool for Snowflake and Postgres databases**
> "3DMark for databases" — Test Standard Tables, Hybrid Tables, Interactive
> Tables, Dynamic Tables, and Postgres

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.11+-green)

## Overview

FlakeBench is a performance testing tool for benchmarking and comparing
Snowflake table types and Postgres databases. It provides real-time metrics
visualization, configurable test templates, and side-by-side comparison of
results.

**Supported table types:**

- **Standard** — Traditional Snowflake tables
- **Hybrid** — Unistore hybrid tables
- **Interactive** — Interactive (HTAP) tables
- **Dynamic** — Dynamic tables with auto-refresh
- **Postgres** — PostgreSQL (including Snowflake via Postgres wire protocol)

## Key Features

- **Real-time dashboard** — Live metrics updates every 1 second via WebSocket
- **Configurable templates** — Select tables/views, pick warehouses, tune
  workload parameters; templates stored in Snowflake
- **Comparison view** — Side-by-side comparison of up to 5 test results with
  CSV export
- **AI SQL generation** — Auto-generate canonical queries (point lookup, range
  scan, insert, update) matched to your table type and backend
- **Cost analysis** — Estimated credit consumption and cost efficiency metrics
  per test run
- **Connection management** — Store and manage multiple database connections
  with AES-256-GCM encrypted credentials
- **Test templates** — Pre-built YAML scenarios (OLTP, OLAP, mixed workload,
  high concurrency, R180 POC) plus DB-stored templates created via the UI

## Architecture

**Tech Stack:**

- **Backend:** FastAPI (async Python)
- **Frontend:** HTMX + Alpine.js (server-driven UI with client-side reactivity)
- **Styling:** Tailwind CSS
- **Charts:** Chart.js
- **Database:** Snowflake (primary), Postgres (optional)

**Why this stack?** No build step required (no npm, no webpack). Lightweight
(~30KB total JS). Well-suited for real-time WebSocket-driven updates.

## Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) — Fast Python package manager
- Snowflake account with appropriate permissions
- (Optional) Postgres database for cross-database comparison

## Quick Start

### 1. Clone and install

```bash
git clone <repository-url>
cd FlakeBench

# Install dependencies
uv sync

# Create environment file from template
cp env.example .env
```

### 2. Configure environment

Edit `.env` and set your Snowflake bootstrap credentials:

```bash
SNOWFLAKE_ACCOUNT=your_account.region
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=FLAKEBENCH
SNOWFLAKE_SCHEMA=TEST_RESULTS
SNOWFLAKE_ROLE=FLAKEBENCH_ROLE
```

> **Note:** Using ACCOUNTADMIN is not recommended. Run `sql/setup_role.sql` to
> create a dedicated FLAKEBENCH_ROLE with minimal privileges (see Step 3).

These credentials are used for the control plane (results storage, schema
management, connection table). Benchmark target connections are configured via
the Settings page.

### 3. Create the FlakeBench role

Using ACCOUNTADMIN is an anti-pattern. Run the role setup script to create a
dedicated role with minimal privileges:

```bash
# In Snowflake (via SnowSQL, Snowsight, or snow CLI)
# Review and customize sql/setup_role.sql, then execute it
snow sql -f sql/setup_role.sql
```

The script creates `FLAKEBENCH_ROLE` with permissions for:
- Control plane tables in `FLAKEBENCH.TEST_RESULTS`
- Warehouse usage for `COMPUTE_WH`

Edit the script to add grants for your benchmark databases/warehouses.

### 4. Initialize database schema

```bash
uv run python -m backend.setup_schema
```

### 5. Start the application

```bash
# Development mode (with auto-reload)
uv run uvicorn backend.main:app --reload [--host 127.0.0.1 --port 8000]

# Production mode
uv run uvicorn backend.main:app [--host 0.0.0.0 --port 8000]
```

### 6. Open your browser

Navigate to: <http://localhost:8000>

### 7. Verify it works

```bash
curl http://localhost:8000/health
```

## Configuration

### Environment Variables (`.env`)

**Required** — Snowflake bootstrap connection:

| Variable | Description |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Account identifier (e.g., `xy12345.us-east-1`) |
| `SNOWFLAKE_USER` | Username |
| `SNOWFLAKE_PASSWORD` | Password |
| `SNOWFLAKE_WAREHOUSE` | Warehouse for control-plane queries |
| `SNOWFLAKE_DATABASE` | Database for results storage (default: `FLAKEBENCH`) |
| `SNOWFLAKE_SCHEMA` | Schema (default: `PUBLIC`) |
| `SNOWFLAKE_ROLE` | Role |

**Security:**

| Variable | Description |
|---|---|
| `FLAKEBENCH_CREDENTIAL_KEY` | 32-character key for AES-256-GCM encryption of stored credentials |

| Scenario | Behavior |
|---|---|
| No key set | Uses default key, shows warning in UI |
| Key set | Uses your key, no warning |
| Key changed after credentials stored | Existing credentials become unreadable — re-enter them |

For production, always set `FLAKEBENCH_CREDENTIAL_KEY` to a unique 32-character
value.

**Optional** — Connection pool and executor tuning:

| Variable | Default | Description |
|---|---|---|
| `SNOWFLAKE_POOL_SIZE` | 5 | Control-plane connection pool size |
| `SNOWFLAKE_MAX_OVERFLOW` | 10 | Max overflow connections |
| `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES` | 8 | Max concurrent `connect()` calls for benchmark pools |
| `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS` | 16 | Thread pool for results persistence |
| `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS` | 256 | Default cap for per-node benchmark threads |
| `WS_PING_INTERVAL` | 30 | WebSocket ping interval (seconds) |
| `POSTGRES_CONNECT_ON_STARTUP` | false | Initialize Postgres pool at startup |

See `env.example` for the full list including timeouts, live metrics, and app
settings.

### Connection Management

FlakeBench supports two methods for database authentication:

**1. Environment variables (`.env`):**
- Used by the control plane (results storage, schema management)
- Fallback for templates without a stored connection

**2. Stored connections (Settings → Connections):**
- Managed via the UI with credentials encrypted in Snowflake (AES-256-GCM)
- Select per-template on the Configure page
- Supports multiple connections to different accounts/databases

Connections store only authentication details (account, user, password, role).
Database, schema, and warehouse are configured per-template.

**To add a connection:**
1. Go to **Settings** → **Connections**
2. Click **Add Connection**
3. Enter connection details: name, type (SNOWFLAKE or POSTGRES), account/host,
   role, and credentials
4. Credentials are encrypted at rest

### Postgres Startup Behavior

Postgres is optional. By default, the app does **not** connect to Postgres at
startup. Set `POSTGRES_CONNECT_ON_STARTUP=true` to initialize the Postgres pool
during FastAPI startup.

## Usage Guide

### Creating a Test

1. Click **"New Test"** in the navigation
2. Select table type (Standard / Hybrid / Interactive / Dynamic / Postgres)
3. **Select a connection** (optional) — choose a stored connection or leave
   blank to use `.env` credentials
4. Configure settings:
   - **Table:** Choose an existing database/schema/table (or view) from dropdowns
   - **Warehouse:** Size, multi-cluster, scaling policy
   - **Test parameters:** Duration + load mode (fixed workers or auto-scale target)
   - **Queries, mix, and targets:** Templates store all SQL (4 canonical queries)
     and the per-query mix % + SLO targets (P95/P99 latency + error%)
     - **Mix preset:** Quickly adjusts weights (does not change SQL)
     - **Generate SQL for This Table Type:** Auto-fills the 4 canonical queries
       (point lookup / range scan / insert / update) to match the selected table
       and backend (Snowflake vs Postgres)
     - Preview-only — no DB writes happen until you save the template
5. Click **"Start Test"**

Views are supported for benchmarking but are read-only. Use `READ_ONLY`
workloads when selecting a view.

After saving a template, you can optionally run **"Prepare AI Workload (Pools +
Metadata)"** to persist large value pools for high-concurrency runs (stored in
`TEMPLATE_VALUE_POOLS`) and avoid generating values at runtime.

### Real-Time Dashboard

The dashboard updates every 1 second with:
- Operations per second (read/write/query)
- Latency percentiles (p50, p95, p99, max)
- Throughput (rows/sec, MB/sec)
- Error rates and error types
- Live charts

### Comparing Tests

1. Navigate to **"Compare"**
2. Search and select up to 5 completed tests
3. View side-by-side metrics comparison
4. Export comparison as CSV

### Smoke Check (4 Variations)

Run a quick, on-demand smoke check across the four table-type variations
(STANDARD, HYBRID, INTERACTIVE, POSTGRES). This validates that each variation
completes and produces metrics, and prints an AI analysis summary per run.

The smoke runner is self-contained: it creates small smoke tables in
`RESULTS_DATABASE.SMOKE_DATA`, builds temporary templates, runs the tests, and
cleans up unless you opt to keep the data. Postgres smoke setup is attempted
only if a Postgres connection is available (otherwise it is skipped).

Requirements:
- App server running at `http://127.0.0.1:8000` (or set `BASE_URL`)
- SnowCLI installed and configured (the smoke setup uses `snow sql`)
- Results schema created via `uv run python -m backend.setup_schema`

```bash
task test:variations:smoke
```

Setup only (no tests):

```bash
task test:variations:setup
```

Cleanup only (drops smoke tables/templates):

```bash
task test:variations:cleanup
```

Optional overrides:

```bash
BASE_URL="http://127.0.0.1:8000" \
MAX_WAIT_SECONDS=300 \
POLL_INTERVAL_SECONDS=5 \
METRICS_WAIT_SECONDS=30 \
DURATION_SECONDS=45 \
WARMUP_SECONDS=0 \
SMOKE_ROWS=300 \
SMOKE_SCHEMA=SMOKE_DATA \
SMOKE_WAREHOUSE=SMOKE_WH \
SMOKE_CONCURRENCY=5 \
KEEP_SMOKE_DATA=true \
SKIP_POSTGRES=true \
task test:variations:smoke
```

Long smoke test:

```bash
task test:variations:smoke:long
```

## Project Structure

```text
FlakeBench/
├── backend/
│   ├── api/                # REST and WebSocket routes
│   ├── connectors/         # Database connection pools
│   ├── core/               # Test execution engine, table managers, cost calculator
│   ├── models/             # Pydantic data models
│   ├── websocket/          # WebSocket streaming, metrics, helpers
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS, JS, images
├── config/
│   └── test_scenarios/     # Pre-built YAML test scenario templates
├── docs/                   # Project documentation (see docs/index.md)
├── scripts/                # Utility scripts
├── sql/
│   └── schema/             # Results storage DDL
├── tests/                  # Test suite
└── env.example             # Environment variable template
```

## Metrics Collected

### Performance Metrics

- **Operations/second** — Read, write, query throughput
- **Latency** — p50, p95, p99, max response times
- **Throughput** — Rows/sec, MB/sec
- **Errors** — Error count, error rate, error types

### Cost Metrics

- **Credit consumption** — Warehouse compute credits used during test
- **Cost efficiency** — Estimated cost per operation

## Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_connectors.py

# Run with coverage
uv run pytest --cov=backend --cov-report=html
```

## Troubleshooting

### Connection Issues

**Snowflake connection fails:**
- Check credentials in `.env`
- Verify network connectivity
- Ensure warehouse is running
- Check role has necessary privileges

**WebSocket disconnects:**
- Check firewall settings
- Increase `WS_PING_INTERVAL` in `.env`
- Verify stable network connection

### Port Already in Use

```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port
uv run uvicorn backend.main:app --port 8001
```

### Import Errors

```bash
# Make sure you're in the project root
cd /path/to/FlakeBench

# Reinstall dependencies
uv sync
```

### Configuration Not Loading

```bash
# Check that .env file exists
ls -la .env

# Verify environment variables
uv run python -c "from backend.config import settings; print(settings.APP_HOST)"
```

### Performance Issues

**Dashboard slow to update:**
- Check browser console for errors
- Verify WebSocket connection is stable

**High concurrency stalls at start (connection spin-up):**
- The benchmark creates a dedicated per-test Snowflake pool sized to the
  requested concurrency
- If startup is slow, reduce `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES` to avoid
  overwhelming the client with too many concurrent `connect()` calls
- Ensure results persistence has its own threads via
  `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS`

**Tests timeout:**
- Increase warehouse size
- Reduce concurrency level
- Check for long-running queries
- Verify adequate connection pool size / executor capacity:
  `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS` is a default safety cap for
  per-node benchmark threads (adjust as needed for your hardware)

**Need to simulate thousands of users:**
- See `docs/scaling.md` for the current concurrency model and the recommended
  multi-process/multi-node approach

## Available Endpoints

| Endpoint | Description |
|---|---|
| `http://localhost:8000` | Home page |
| `http://localhost:8000/health` | Health check |
| `http://localhost:8000/api/info` | API info |
| `http://localhost:8000/api/docs` | Interactive Swagger UI |
| `http://localhost:8000/api/redoc` | ReDoc API docs |
| `http://localhost:8000/dashboard` | Real-time dashboard |
| `http://localhost:8000/configure` | Test configuration |
| `http://localhost:8000/comparison` | Results comparison |
| `http://localhost:8000/history` | Test history |
| `http://localhost:8000/templates` | Template management |
| `http://localhost:8000/analysis` | Analysis view |
| `http://localhost:8000/settings` | Settings and connections |

## Development Workflow

1. Make changes to backend code
2. Server auto-reloads (if using `--reload` flag)
3. Test changes at <http://localhost:8000>
4. Check logs in terminal output
5. Run tests with `uv run pytest`

## Documentation

- [Documentation Index](docs/index.md) — Entry point for all project docs
- [Architecture Overview](docs/architecture-overview.md)
- [Operations & Runbooks](docs/operations-and-runbooks.md)
- [Scaling & Concurrency Model](docs/scaling.md)
- [FlakeBench Docs Skill](docs/SKILL.md) — Agent-oriented docs index

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- UI powered by [HTMX](https://htmx.org/) and [Alpine.js](https://alpinejs.dev/)
- Charts by [Chart.js](https://www.chartjs.org/)
- Package management by [uv](https://github.com/astral-sh/uv)

---

**Status:** Active Development
**Version:** 0.1.0
