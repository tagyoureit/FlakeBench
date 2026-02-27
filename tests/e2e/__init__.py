"""
End-to-End Tests for FlakeBench.

These tests run against real infrastructure:
- Real Snowflake database (E2E_TEST schema)
- Real WebSocket connections
- Real browser automation (Playwright)

Run with: E2E_TEST=1 uv run pytest tests/e2e/ -v
"""
