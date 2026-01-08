#!/usr/bin/env python3
"""
Test script for database connection pools.

Tests Snowflake and Postgres connection pools with various scenarios.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.config import settings

pytestmark = pytest.mark.asyncio


def _snowflake_unreachable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        ("ip/token" in msg and "not allowed" in msg)
        or ("is not allowed to access snowflake" in msg)
        or ("failed to connect to db" in msg)
        or ("(08001)" in msg)
    )


async def test_snowflake_pool():
    """Test Snowflake connection pool."""
    print("\n🔍 Testing Snowflake Connection Pool")
    print("=" * 60)

    if (
        settings.SNOWFLAKE_ACCOUNT.startswith("your_")
        or settings.SNOWFLAKE_USER.startswith("your_")
        or not settings.SNOWFLAKE_PASSWORD
    ):
        pytest.skip("Snowflake credentials not configured; skipping integration test")

    try:
        from backend.connectors.snowflake_pool import SnowflakeConnectionPool

        # Create pool
        pool = SnowflakeConnectionPool(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            database=settings.SNOWFLAKE_DATABASE,
            schema=settings.SNOWFLAKE_SCHEMA,
            role=settings.SNOWFLAKE_ROLE,
            pool_size=2,
            max_overflow=3,
        )

        print("✅ Pool created")

        # Initialize pool
        try:
            await pool.initialize()
        except Exception as e:
            pytest.skip(f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}")
        print("✅ Pool initialized")

        # Get pool stats
        stats = await pool.get_pool_stats()
        print(f"📊 Pool stats: {stats}")

        # Test simple query
        print("\n🔍 Testing simple query...")
        try:
            async with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_VERSION()")
                version = cursor.fetchone()
                cursor.close()
                print(f"✅ Snowflake version: {version[0]}")
        except Exception as e:
            if _snowflake_unreachable(e):
                pytest.skip(
                    f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}"
                )
            raise

        # Test execute_query helper
        print("\n🔍 Testing execute_query helper...")
        try:
            results = await pool.execute_query("SELECT CURRENT_WAREHOUSE()")
            print(f"✅ Current warehouse: {results[0][0]}")
        except Exception as e:
            if _snowflake_unreachable(e):
                pytest.skip(
                    f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}"
                )
            raise

        # Test concurrent connections
        print("\n🔍 Testing concurrent connections...")

        async def query_task(n):
            async with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_USER()")
                result = cursor.fetchone()
                cursor.close()
                print(f"  Task {n}: {result[0]}")
                return result

        tasks = [query_task(i) for i in range(5)]
        await asyncio.gather(*tasks)
        print("✅ Concurrent queries completed")

        # Final stats
        stats = await pool.get_pool_stats()
        print(f"\n📊 Final pool stats: {stats}")

        # Close pool
        await pool.close_all()
        print("✅ Pool closed")

    except Exception as e:
        if _snowflake_unreachable(e):
            pytest.skip(f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}")
        print(f"❌ Snowflake test failed: {e}")
        import traceback

        traceback.print_exc()
        pytest.fail(f"Snowflake pool test failed: {e}")


async def test_postgres_pool():
    """Test Postgres connection pool."""
    print("\n🔍 Testing Postgres Connection Pool")
    print("=" * 60)

    if not settings.ENABLE_POSTGRES:
        print("⏭️  Postgres disabled in settings, skipping...")
        pytest.skip("Postgres disabled in settings; skipping integration test")

    if not settings.POSTGRES_PASSWORD:
        print("⏭️  Postgres password not configured, skipping...")
        pytest.skip("Postgres password not configured; skipping integration test")

    try:
        from backend.connectors.postgres_pool import PostgresConnectionPool

        # Create pool
        pool = PostgresConnectionPool(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database=settings.POSTGRES_DATABASE,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            min_size=2,
            max_size=5,
        )

        print("✅ Pool created")

        # Initialize pool
        try:
            await pool.initialize()
        except Exception as e:
            pytest.skip(
                f"Postgres not reachable ({settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}): {e}"
            )
        print("✅ Pool initialized")

        # Get pool stats
        stats = await pool.get_pool_stats()
        print(f"📊 Pool stats: {stats}")

        # Test simple query
        print("\n🔍 Testing simple query...")
        version = await pool.fetch_val("SELECT version()")
        print(f"✅ Postgres version: {version[:50]}...")

        # Test health check
        print("\n🔍 Testing health check...")
        is_healthy = await pool.is_healthy()
        print(f"✅ Health check: {'Healthy' if is_healthy else 'Unhealthy'}")

        # Test concurrent queries
        print("\n🔍 Testing concurrent connections...")

        async def query_task(n):
            result = await pool.fetch_val("SELECT current_user")
            print(f"  Task {n}: {result}")
            return result

        tasks = [query_task(i) for i in range(5)]
        await asyncio.gather(*tasks)
        print("✅ Concurrent queries completed")

        # Final stats
        stats = await pool.get_pool_stats()
        print(f"\n📊 Final pool stats: {stats}")

        # Close pool
        await pool.close()
        print("✅ Pool closed")

    except Exception as e:
        print(f"❌ Postgres test failed: {e}")
        import traceback

        traceback.print_exc()
        pytest.fail(f"Postgres pool test failed: {e}")


async def test_connection_pool_exhaustion():
    """Test connection pool behavior when exhausted."""
    print("\n🔍 Testing Connection Pool Exhaustion")
    print("=" * 60)

    if (
        settings.SNOWFLAKE_ACCOUNT.startswith("your_")
        or settings.SNOWFLAKE_USER.startswith("your_")
        or not settings.SNOWFLAKE_PASSWORD
    ):
        pytest.skip("Snowflake credentials not configured; skipping integration test")

    try:
        from backend.connectors.snowflake_pool import SnowflakeConnectionPool

        # Create small pool
        pool = SnowflakeConnectionPool(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            pool_size=2,
            max_overflow=1,  # Max 3 total connections
        )

        try:
            await pool.initialize()
        except Exception as e:
            pytest.skip(f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}")
        print("✅ Pool initialized (max 3 connections)")

        # Hold 3 connections
        connections = []
        contexts = []

        print("\n🔍 Acquiring 3 connections (should succeed)...")
        for i in range(3):
            ctx = pool.get_connection()
            conn = await ctx.__aenter__()
            connections.append(conn)
            contexts.append(ctx)
            print(f"  ✓ Acquired connection {i + 1}")

        stats = await pool.get_pool_stats()
        print(f"📊 Pool exhausted: {stats}")

        # Try to get one more (should fail or wait)
        print("\n🔍 Trying to acquire 4th connection (should fail)...")
        try:
            ctx = pool.get_connection()

            # Set a short timeout
            try:
                conn = await asyncio.wait_for(ctx.__aenter__(), timeout=2.0)
                print("  ✓ Got 4th connection (unexpected)")
                await ctx.__aexit__(None, None, None)
            except asyncio.TimeoutError:
                print("  ✓ Timeout as expected (pool exhausted)")

        except Exception as e:
            print(f"  ✓ Failed as expected: {e}")

        # Release connections
        print("\n🔍 Releasing connections...")
        for i, (conn, ctx) in enumerate(zip(connections, contexts)):
            await ctx.__aexit__(None, None, None)
            print(f"  ✓ Released connection {i + 1}")

        stats = await pool.get_pool_stats()
        print(f"📊 Pool after release: {stats}")

        await pool.close_all()
        print("✅ Test completed")

    except Exception as e:
        if _snowflake_unreachable(e):
            pytest.skip(f"Snowflake not reachable ({settings.SNOWFLAKE_ACCOUNT}): {e}")
        print(f"❌ Pool exhaustion test failed: {e}")
        import traceback

        traceback.print_exc()
        pytest.fail(f"Pool exhaustion test failed: {e}")


async def main():
    """Run all connection pool tests."""
    print("=" * 60)
    print("🧪 Running Database Connection Pool Tests")
    print("=" * 60)

    # Check configuration
    print("\n📋 Configuration:")
    print(f"  Snowflake Account: {settings.SNOWFLAKE_ACCOUNT}")
    print(f"  Snowflake User: {settings.SNOWFLAKE_USER}")
    print(f"  Postgres Enabled: {settings.ENABLE_POSTGRES}")
    print(f"  Postgres Host: {settings.POSTGRES_HOST}")

    if settings.SNOWFLAKE_ACCOUNT == "your_account.region":
        print("\n⚠️  WARNING: Using default configuration!")
        print("⚠️  Please update .env file with your Snowflake credentials")
        print("⚠️  Tests will likely fail without valid credentials")
        print()

        response = input("Continue anyway? (y/n): ")
        if response.lower() != "y":
            print("Exiting...")
            return 1

    tests = [
        ("Snowflake Pool", test_snowflake_pool),
        ("Postgres Pool", test_postgres_pool),
        ("Pool Exhaustion", test_connection_pool_exhaustion),
    ]

    results = []
    for name, test_func in tests:
        result = await test_func()
        results.append((name, result))

    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print()
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
