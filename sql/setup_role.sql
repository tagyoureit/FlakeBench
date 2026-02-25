-- =============================================================================
-- FlakeBench Role Setup
-- =============================================================================
-- Creates a dedicated role with minimal privileges for FlakeBench.
-- Using ACCOUNTADMIN is an anti-pattern - use this role instead.
--
-- Run this script once before using FlakeBench (standalone or SPCS).
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- Create the FlakeBench database and schema if they don't exist
CREATE DATABASE IF NOT EXISTS FLAKEBENCH;
CREATE SCHEMA IF NOT EXISTS FLAKEBENCH.TEST_RESULTS;

-- Create a dedicated role for FlakeBench
CREATE ROLE IF NOT EXISTS FLAKEBENCH_ROLE;

-- =============================================================================
-- Transfer Ownership (gives FLAKEBENCH_ROLE full control)
-- =============================================================================

-- Transfer ownership of the database and schema to FLAKEBENCH_ROLE
GRANT OWNERSHIP ON DATABASE FLAKEBENCH TO ROLE FLAKEBENCH_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE COPY CURRENT GRANTS;

-- Transfer ownership of all existing tables to FLAKEBENCH_ROLE
GRANT OWNERSHIP ON ALL TABLES IN SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON ALL VIEWS IN SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE COPY CURRENT GRANTS;

-- Future objects in the schema will be owned by FLAKEBENCH_ROLE
GRANT OWNERSHIP ON FUTURE TABLES IN SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE;
GRANT OWNERSHIP ON FUTURE VIEWS IN SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE FLAKEBENCH_ROLE;

-- =============================================================================
-- Warehouse Access (required for all installs)
-- =============================================================================

-- Grant warehouse usage (control plane warehouse)
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE FLAKEBENCH_ROLE;

-- =============================================================================
-- Role Hierarchy
-- =============================================================================

-- Grant role to SYSADMIN (for SPCS service ownership)
GRANT ROLE FLAKEBENCH_ROLE TO ROLE SYSADMIN;

-- Grant role to your user (for standalone usage)
-- Uncomment and replace <your_username> with your Snowflake username:
-- GRANT ROLE FLAKEBENCH_ROLE TO USER <your_username>;

-- =============================================================================
-- Benchmark Target Permissions (customize for your setup)
-- =============================================================================
-- For running benchmarks, grant access to the databases/warehouses you'll test.
-- Uncomment and modify these as needed:

-- Example: Grant access to a benchmark database
-- GRANT USAGE ON DATABASE UNISTORE_BENCHMARK TO ROLE FLAKEBENCH_ROLE;
-- GRANT USAGE ON SCHEMA UNISTORE_BENCHMARK.PUBLIC TO ROLE FLAKEBENCH_ROLE;
-- GRANT SELECT ON ALL TABLES IN SCHEMA UNISTORE_BENCHMARK.PUBLIC TO ROLE FLAKEBENCH_ROLE;

-- Example: Grant access to a benchmark warehouse
-- GRANT USAGE ON WAREHOUSE PERFTESTING_XS_INTERACTIVE_1 TO ROLE FLAKEBENCH_ROLE;

-- =============================================================================
-- Verify setup
-- =============================================================================
SHOW GRANTS TO ROLE FLAKEBENCH_ROLE;
