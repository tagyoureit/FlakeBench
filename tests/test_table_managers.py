#!/usr/bin/env python3
"""
Test script for table managers.

Tests table manager factory, validation, and basic interface.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import TableType, TableConfig
from backend.core.table_managers import (
    create_table_manager,
    StandardTableManager,
    HybridTableManager,
    InteractiveTableManager,
    PostgresTableManager,
)


def test_factory():
    """Test table manager factory."""
    print("\n🔍 Testing Table Manager Factory")
    print("=" * 60)

    try:
        # Standard table
        standard_config = TableConfig(
            name="test_standard",
            table_type=TableType.STANDARD,
            columns={"id": "NUMBER", "value": "VARCHAR"},
            clustering_keys=["id"],
        )
        manager = create_table_manager(standard_config)
        assert isinstance(manager, StandardTableManager)
        print(f"✅ Standard table manager created: {manager.table_name}")

        # Hybrid table
        hybrid_config = TableConfig(
            name="test_hybrid",
            table_type=TableType.HYBRID,
            primary_key=["id"],
            columns={"id": "NUMBER", "value": "VARCHAR"},
        )
        manager = create_table_manager(hybrid_config)
        assert isinstance(manager, HybridTableManager)
        print(f"✅ Hybrid table manager created: {manager.table_name}")

        # Interactive table (placeholder)
        interactive_config = TableConfig(
            name="test_interactive",
            table_type=TableType.INTERACTIVE,
            cluster_by=["date"],
            columns={"id": "NUMBER", "date": "DATE"},
        )
        manager = create_table_manager(interactive_config)
        assert isinstance(manager, InteractiveTableManager)
        print(
            f"✅ Interactive table manager created (placeholder): {manager.table_name}"
        )

        # Postgres table
        postgres_config = TableConfig(
            name="test_postgres",
            table_type=TableType.POSTGRES,
            columns={"id": "NUMBER", "value": "VARCHAR"},
        )
        manager = create_table_manager(postgres_config)
        assert isinstance(manager, PostgresTableManager)
        print(f"✅ Postgres table manager created: {manager.table_name}")

        return True

    except Exception as e:
        print(f"❌ Factory test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_standard_manager():
    """Test standard table manager validation."""
    print("\n🔍 Testing StandardTableManager")
    print("=" * 60)

    try:
        config = TableConfig(
            name="test_standard",
            table_type=TableType.STANDARD,
            columns={
                "id": "NUMBER",
                "date": "DATE",
                "customer_id": "VARCHAR(100)",
                "amount": "DECIMAL(10,2)",
            },
            clustering_keys=["date", "customer_id"],
            data_retention_days=7,
            database="TEST_DB",
            schema_name="PUBLIC",
        )

        manager = StandardTableManager(config)

        # Test full table name
        full_name = manager.get_full_table_name()
        assert full_name == "TEST_DB.PUBLIC.test_standard"
        print(f"✅ Full table name: {full_name}")

        # Test column definitions
        columns = manager.get_column_definitions()
        assert len(columns) == 4
        print(f"✅ Column definitions: {len(columns)} columns")

        # Test properties
        assert not manager.is_created
        print("✅ Initial state: not created")

        return True

    except Exception as e:
        print(f"❌ Standard manager test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_hybrid_manager():
    """Test hybrid table manager validation."""
    print("\n🔍 Testing HybridTableManager")
    print("=" * 60)

    try:
        config = TableConfig(
            name="test_hybrid",
            table_type=TableType.HYBRID,
            primary_key=["id"],
            columns={
                "id": "NUMBER",
                "customer_id": "VARCHAR(100)",
                "date": "DATE",
                "amount": "DECIMAL(10,2)",
            },
            indexes=[
                {"name": "idx_customer", "columns": ["customer_id"]},
                {"name": "idx_date", "columns": ["date"], "include": ["amount"]},
            ],
        )

        manager = HybridTableManager(config)

        # Test configuration
        assert manager.config.primary_key == ["id"]
        assert len(manager.config.indexes or []) == 2
        print(f"✅ Hybrid manager configured: PK={manager.config.primary_key}")

        # Test validation (hybrid without PK should fail)
        try:
            bad_config = TableConfig(
                name="bad_hybrid",
                table_type=TableType.HYBRID,
                columns={"id": "NUMBER"},
            )
            HybridTableManager(bad_config)
            print("❌ Should have failed: hybrid without PK")
            return False
        except ValueError as e:
            print(f"✅ Validation works: {e}")

        return True

    except Exception as e:
        print(f"❌ Hybrid manager test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_postgres_manager():
    """Test Postgres table manager type conversion."""
    print("\n🔍 Testing PostgresTableManager")
    print("=" * 60)

    try:
        config = TableConfig(
            name="test_postgres",
            table_type=TableType.POSTGRES,
            primary_key=["id"],
            columns={
                "id": "NUMBER",
                "name": "VARCHAR(100)",
                "created_at": "TIMESTAMP",
                "data": "VARIANT",
            },
            postgres_indexes=[
                {"name": "idx_name", "columns": ["name"], "type": "btree"},
                {"name": "idx_data", "columns": ["data"], "type": "gin"},
            ],
        )

        manager = PostgresTableManager(config)

        # Test type conversion
        col_def = "id NUMBER"
        pg_def = manager._convert_to_postgres_type(col_def)
        assert "NUMERIC" in pg_def
        print(f"✅ Type conversion: {col_def} -> {pg_def}")

        col_def = "data VARIANT"
        pg_def = manager._convert_to_postgres_type(col_def)
        assert "JSONB" in pg_def
        print(f"✅ Type conversion: {col_def} -> {pg_def}")

        # Test indexes configured
        assert len(manager.config.postgres_indexes or []) == 2
        print(
            f"✅ Postgres indexes configured: {len(manager.config.postgres_indexes or [])}"
        )

        return True

    except Exception as e:
        print(f"❌ Postgres manager test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_interactive_manager():
    """Test interactive table manager placeholder."""
    print("\n🔍 Testing InteractiveTableManager (Placeholder)")
    print("=" * 60)

    try:
        config = TableConfig(
            name="test_interactive",
            table_type=TableType.INTERACTIVE,
            cluster_by=["date"],
            columns={"id": "NUMBER", "date": "DATE"},
        )

        manager = InteractiveTableManager(config)

        # Should fail for now
        assert not manager.is_created
        print("✅ Interactive manager created (placeholder)")
        print("⚠️  Interactive tables not yet fully supported")

        # Test validation (interactive without CLUSTER BY should fail)
        try:
            bad_config = TableConfig(
                name="bad_interactive",
                table_type=TableType.INTERACTIVE,
                columns={"id": "NUMBER"},
            )
            InteractiveTableManager(bad_config)
            print("❌ Should have failed: interactive without CLUSTER BY")
            return False
        except ValueError as e:
            print(f"✅ Validation works: {e}")

        return True

    except Exception as e:
        print(f"❌ Interactive manager test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all table manager tests."""
    print("=" * 60)
    print("🧪 Running Table Manager Tests")
    print("=" * 60)
    print("\nThese tests validate:")
    print("- Factory pattern and manager creation")
    print("- Configuration validation")
    print("- Type conversions and SQL generation")
    print("\nNOTE: These tests do NOT require database connections.")
    print("Database integration tests require valid credentials.")

    tests = [
        ("Factory", test_factory),
        ("StandardTableManager", test_standard_manager),
        ("HybridTableManager", test_hybrid_manager),
        ("PostgresTableManager", test_postgres_manager),
        ("InteractiveTableManager", test_interactive_manager),
    ]

    results = []
    for name, test_func in tests:
        result = test_func()
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
    sys.exit(main())
