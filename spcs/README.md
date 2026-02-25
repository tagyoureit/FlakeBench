# FlakeBench SPCS Deployment

Deploy FlakeBench to Snowpark Container Services.

## Prerequisites

1. **Snowflake Account** with SPCS enabled
2. **snow CLI** installed and configured
3. **Docker** installed locally

## Setup Snowflake Objects

```sql
-- Create database and schema (if not exists)
CREATE DATABASE IF NOT EXISTS FLAKEBENCH;
CREATE SCHEMA IF NOT EXISTS FLAKEBENCH.TEST_RESULTS;

-- Create image repository (use a schema you have privileges on)
CREATE IMAGE REPOSITORY IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_REPO;

-- Create compute pool (CPU_X64_M: 6 vCPU, 28 GiB memory)
-- Use CPU_X64_S (3 vCPU, 13 GiB) for dev/testing to save costs
CREATE COMPUTE POOL IF NOT EXISTS FLAKEBENCH_POOL
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_M;

-- Grant BIND SERVICE ENDPOINT to your role (required for public endpoints)
GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE SYSADMIN;
```

## Create Application Role (Recommended)

Using ACCOUNTADMIN is an anti-pattern. Run the shared role setup script:

```bash
# Review and customize the script first
snow sql -f sql/setup_role.sql
```

Or run the SQL directly in Snowsight. The script is located at `sql/setup_role.sql`
and creates `FLAKEBENCH_ROLE` with:
- Control plane permissions for `FLAKEBENCH.TEST_RESULTS`
- Warehouse access for `COMPUTE_WH`

**Important:** Edit the script to add grants for your benchmark databases/warehouses
before running benchmarks.

## Build and Push Image

```bash
# Login to Snowflake image registry
snow spcs image-registry login --connection default

# Get your registry URL
snow spcs image-registry url --connection default
# Output: <account>.registry.snowflakecomputing.com

# Build for linux/amd64 (required for SPCS)
docker build --platform linux/amd64 -t flakebench:latest .

# Tag for Snowflake registry
docker tag flakebench:latest \
  <account>.registry.snowflakecomputing.com/flakebench/public/flakebench_repo/flakebench:latest

# Push to Snowflake
docker push \
  <account>.registry.snowflakecomputing.com/flakebench/public/flakebench_repo/flakebench:latest
```

## Deploy Service

```sql
-- Create the service
CREATE SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE
  IN COMPUTE POOL FLAKEBENCH_POOL
  FROM SPECIFICATION $$
spec:
  containers:
  - name: flakebench
    image: /FLAKEBENCH/TEST_RESULTS/FLAKEBENCH_REPO/flakebench:latest
    env:
      SNOWFLAKE_DATABASE: "FLAKEBENCH"
      SNOWFLAKE_SCHEMA: "TEST_RESULTS"
      SNOWFLAKE_WAREHOUSE: "COMPUTE_WH"
      SNOWFLAKE_ROLE: "FLAKEBENCH_ROLE"
    readinessProbe:
      port: 8080
      path: /health
  endpoints:
  - name: app
    port: 8080
    public: true
$$
  MIN_INSTANCES = 1
  MAX_INSTANCES = 1;

-- Check service status
SELECT SYSTEM$GET_SERVICE_STATUS('FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE');

-- Get the public URL
SHOW ENDPOINTS IN SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE;
```

**Note on resource limits:** Resource limits (`resources.requests`/`limits`) are optional. 
They're useful when sharing compute pools between services, but on a dedicated pool they 
can cause OOMKilled errors if set too low. Omit them unless you have a specific need.

## Grant Access to Users

```sql
-- Grant service endpoint access to a consumer role
GRANT SERVICE ROLE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE!ALL_ENDPOINTS_USAGE 
  TO ROLE <consumer_role>;

-- If consumer needs to see benchmark results, also grant data access
GRANT USAGE ON DATABASE FLAKEBENCH TO ROLE <consumer_role>;
GRANT USAGE ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE <consumer_role>;
GRANT SELECT ON ALL TABLES IN SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE <consumer_role>;
```

## External Access (Outbound Connections)

SPCS blocks all outbound network traffic by default. To allow FlakeBench to:
- **Test connections** to Snowflake accounts (including your own via public endpoint)
- **Run benchmarks** against external targets (other Snowflake accounts, Postgres)

You need External Access Integrations (EAIs):

```sql
-- Run as ACCOUNTADMIN
USE ROLE ACCOUNTADMIN;

-- Network rule for Snowflake connections
CREATE OR REPLACE NETWORK RULE SANDBOX.SPCS.SNOWFLAKE_EGRESS_RULE
  TYPE = HOST_PORT
  MODE = EGRESS
  VALUE_LIST = ('*.snowflakecomputing.com:443');

-- Network rule for Snowflake Postgres connections  
CREATE OR REPLACE NETWORK RULE SANDBOX.SPCS.POSTGRES_EGRESS_RULE
  TYPE = HOST_PORT
  MODE = EGRESS
  VALUE_LIST = ('*.postgres.snowflake.app:5432');

-- Create EAIs
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION SNOWFLAKE_EAI
  ALLOWED_NETWORK_RULES = (SANDBOX.SPCS.SNOWFLAKE_EGRESS_RULE)
  ENABLED = TRUE;

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION POSTGRES_EAI
  ALLOWED_NETWORK_RULES = (SANDBOX.SPCS.POSTGRES_EGRESS_RULE)
  ENABLED = TRUE;

-- Grant to service role
GRANT USAGE ON INTEGRATION SNOWFLAKE_EAI TO ROLE FLAKEBENCH_ROLE;
GRANT USAGE ON INTEGRATION POSTGRES_EAI TO ROLE FLAKEBENCH_ROLE;
```

Then attach the EAIs to your service:

```sql
USE ROLE FLAKEBENCH_ROLE;
ALTER SERVICE FLAKEBENCH_SERVICE SET 
  EXTERNAL_ACCESS_INTEGRATIONS = (SNOWFLAKE_EAI, POSTGRES_EAI);
```

**Note:** The internal SPCS OAuth connection (used for saving results) works without EAI - 
it uses an internal endpoint. EAIs are only needed for connections to external endpoints.

### Target Account Network Policies

If the target Snowflake account has a **network policy** restricting inbound connections, 
you must add the SPCS egress IP ranges to the target account's allowed list. SPCS outbound 
traffic goes through NAT gateways with specific public IP addresses.

**Step 1:** Get the egress IP ranges from the account where SPCS is running:

```sql
SELECT SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES();
-- Returns JSON like: [{"ipv4_prefix":"153.45.59.0/24",...},{"ipv4_prefix":"153.45.69.0/24",...}]
```

**Step 2:** Add those CIDRs to the **target account's** network policy:

```sql
-- Run in the TARGET account (the one you're connecting TO)
ALTER NETWORK POLICY <policy_name> 
SET ALLOWED_IP_LIST = (
    -- existing IPs...
    '153.45.59.0/24',  -- SPCS egress range 1
    '153.45.69.0/24'   -- SPCS egress range 2
);
```

**Important notes:**
- The egress IPs are region-specific. Run `SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES()` in your 
  SPCS account to get the correct ranges for your region.
- These IPs have expiration dates (shown in the JSON output). Check periodically for updates.
- Without this, you'll see "IP not allowed by network policy" errors when testing connections.

## Update Service

When you push a new image version:

```sql
ALTER SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE FROM SPECIFICATION $$
spec:
  containers:
  - name: flakebench
    image: /FLAKEBENCH/TEST_RESULTS/FLAKEBENCH_REPO/flakebench:<new_tag>
    env:
      SNOWFLAKE_DATABASE: "FLAKEBENCH"
      SNOWFLAKE_SCHEMA: "TEST_RESULTS"
      SNOWFLAKE_WAREHOUSE: "COMPUTE_WH"
      SNOWFLAKE_ROLE: "FLAKEBENCH_ROLE"
    readinessProbe:
      port: 8080
      path: /health
  endpoints:
  - name: app
    port: 8080
    public: true
$$;
```

## Endpoint URL

SPCS service URLs change when you use `ALTER SERVICE FROM SPECIFICATION`. To get a **stable URL**, create a Gateway.

### Option 1: Stable URL with Gateway (Recommended)

```sql
-- Grant gateway creation privileges (run as ACCOUNTADMIN)
GRANT CREATE GATEWAY ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE;
GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE FLAKEBENCH_ROLE;

-- Create gateway pointing to your service endpoint (run as FLAKEBENCH_ROLE)
USE ROLE FLAKEBENCH_ROLE;
CREATE GATEWAY FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_GATEWAY
FROM SPECIFICATION $$
spec:
  type: traffic_split
  split_type: custom
  targets:
  - type: endpoint
    value: FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE!app
    weight: 100
$$;

-- Get the STABLE gateway URL (this URL never changes)
DESC GATEWAY FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_GATEWAY;
```

Now when you update your service with `ALTER SERVICE FROM SPECIFICATION`, the gateway URL stays the same.

### Option 2: Query Current URL

If you don't use a gateway, get the current service URL:

```sql
SHOW ENDPOINTS IN SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE;
```

## Troubleshooting

### Query Timeout Errors

**Symptom:** Benchmark queries fail with "Statement reached its statement or warehouse timeout of 5 second(s)" or similar.

**Cause:** The warehouse has a restrictive `STATEMENT_TIMEOUT_IN_SECONDS` setting that's too short for benchmark workloads.

**Fix Options:**

1. **SQL (permanent):** Increase the warehouse timeout:
   ```sql
   ALTER WAREHOUSE <warehouse_name> SET STATEMENT_TIMEOUT_IN_SECONDS = 600;
   ```

2. **Environment variable (per-service):** Set the session-level override in your service spec:
   ```yaml
   env:
     SNOWFLAKE_BENCHMARK_STATEMENT_TIMEOUT: "600"
   ```
   This overrides the warehouse setting for benchmark sessions only. Set to `0` to use the warehouse default.

### General Debugging

```sql
-- View service logs
SELECT SYSTEM$GET_SERVICE_LOGS('FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE', 0, 'flakebench');

-- Check service status
SELECT SYSTEM$GET_SERVICE_STATUS('FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE');

-- Suspend/resume service
ALTER SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE SUSPEND;
ALTER SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE RESUME;

-- Drop service (will need to get new URL on recreate)
DROP SERVICE FLAKEBENCH.TEST_RESULTS.FLAKEBENCH_SERVICE;
```

## Running Standalone (Local Development)

The same codebase runs locally without Docker:

```bash
# Install dependencies
uv sync

# Run with hot reload
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The app automatically detects the environment:
- **SPCS**: Uses OAuth token from `/snowflake/session/token`
- **Standalone**: Uses credentials from `.env` file
