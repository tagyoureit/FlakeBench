"""
Database Schema Setup Script

Creates the necessary database schema for storing benchmark test results.
Executes the SQL DDL from (rerunnable, idempotent):
- sql/schema/results_tables.sql
- sql/schema/templates_table.sql
- sql/schema/template_value_pools_table.sql
- sql/schema/test_logs_table.sql

Usage:
    uv run python -m backend.setup_schema
"""

import sys
from pathlib import Path

import snowflake.connector
from snowflake.connector import DictCursor

from backend.config import settings


def read_schema_sql() -> str:
    """
    Read the schema SQL files (results + templates) and concatenate them.

    Note: `templates_table.sql` assumes the target schema is already selected,
    which is done in `results_tables.sql` via `USE SCHEMA ...`.
    """
    schema_dir = Path(__file__).parent.parent / "sql" / "schema"
    schema_files = [
        schema_dir / "results_tables.sql",
        schema_dir / "templates_table.sql",
        schema_dir / "template_value_pools_table.sql",
        schema_dir / "test_logs_table.sql",
        schema_dir / "control_tables.sql",
    ]

    contents: list[str] = []
    for schema_file in schema_files:
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")
        with open(schema_file, "r") as f:
            contents.append(f.read())

    return "\n\n".join(contents)


def execute_sql_statements(cursor, sql_content: str) -> None:
    """Execute SQL statements, handling multi-statement execution."""
    statements = []
    current_statement = []

    for line in sql_content.split("\n"):
        stripped = line.strip()

        if not stripped or stripped.startswith("--"):
            continue

        current_statement.append(line)

        if stripped.endswith(";"):
            statement = "\n".join(current_statement)
            statements.append(statement)
            current_statement = []

    total = len(statements)
    print(f"\n📋 Found {total} SQL statements to execute\n")

    for idx, statement in enumerate(statements, 1):
        try:
            first_line = statement.strip().split("\n")[0][:80]
            print(f"[{idx}/{total}] Executing: {first_line}...")

            cursor.execute(statement)

            result = cursor.fetchone()
            if result:
                print(f"  ✓ Success: {result}")
            else:
                print("  ✓ Success")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            if "already exists" not in str(e).lower():
                raise


def setup_schema() -> None:
    """Main setup function."""
    print("=" * 80)
    print("🏗️  Unistore Benchmark - Database Schema Setup")
    print("=" * 80)

    print("\n📊 Snowflake Configuration:")
    print(f"  Account: {settings.SNOWFLAKE_ACCOUNT}")
    print(f"  User: {settings.SNOWFLAKE_USER}")
    print(f"  Database: {settings.RESULTS_DATABASE}")
    print(f"  Schema: {settings.RESULTS_SCHEMA}")
    print(f"  Warehouse: {settings.SNOWFLAKE_WAREHOUSE}")

    try:
        print("\n🔌 Connecting to Snowflake...")
        conn = snowflake.connector.connect(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            role=settings.SNOWFLAKE_ROLE,
        )

        print("  ✓ Connected successfully")

        cursor = conn.cursor(DictCursor)

        print("\n📖 Reading schema SQL file...")
        sql_content = read_schema_sql()
        print(f"  ✓ Loaded {len(sql_content)} characters")

        print("\n🚀 Executing schema setup...")
        execute_sql_statements(cursor, sql_content)

        print("\n🎉 Schema setup completed successfully!")

        print("\n📊 Verifying tables...")
        cursor.execute(f"""
            SELECT table_name, row_count 
            FROM {settings.RESULTS_DATABASE}.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{settings.RESULTS_SCHEMA}'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)

        tables = cursor.fetchall()
        print(f"\n✅ Created {len(tables)} tables:")
        for table in tables:
            print(f"  • {table['TABLE_NAME']}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 80)
        print("✅ Database schema setup complete!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Schema setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_schema()
