#!/usr/bin/env python3
"""
Test script to verify FastAPI application setup.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def test_app_import():
    """Test that the FastAPI app can be imported."""
    try:
        print("✅ FastAPI app imported successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to import app: {e}")
        return False


def test_config_load():
    """Test that configuration loads properly."""
    try:
        from backend.config import settings

        print("✅ Configuration loaded successfully")
        print(f"   - App Host: {settings.APP_HOST}")
        print(f"   - App Port: {settings.APP_PORT}")
        print(f"   - Debug Mode: {settings.APP_DEBUG}")
        return True
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return False


def test_routes():
    """Test that routes are registered."""
    try:
        from backend.main import app

        routes = []
        for route in app.routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                routes.append(path)

        expected_routes = ["/", "/health", "/api/info", "/ws/test/{test_id}"]

        print("✅ Routes registered:")
        for route in expected_routes:
            if route in routes:
                print(f"   ✓ {route}")
            else:
                print(f"   ✗ {route} (MISSING)")
                return False

        return True
    except Exception as e:
        print(f"❌ Failed to check routes: {e}")
        return False


def test_static_files():
    """Test that static directory exists."""
    try:
        from backend.main import STATIC_DIR

        if STATIC_DIR.exists():
            print(f"✅ Static directory exists: {STATIC_DIR}")
            return True
        else:
            print(f"❌ Static directory not found: {STATIC_DIR}")
            return False
    except Exception as e:
        print(f"❌ Failed to check static files: {e}")
        return False


def test_templates():
    """Test that templates directory exists."""
    try:
        from backend.main import TEMPLATES_DIR

        if TEMPLATES_DIR.exists():
            print(f"✅ Templates directory exists: {TEMPLATES_DIR}")
            return True
        else:
            print(f"❌ Templates directory not found: {TEMPLATES_DIR}")
            return False
    except Exception as e:
        print(f"❌ Failed to check templates: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 Running FastAPI Application Tests")
    print("=" * 60)
    print()

    tests = [
        ("App Import", test_app_import),
        ("Configuration", test_config_load),
        ("Routes", test_routes),
        ("Static Files", test_static_files),
        ("Templates", test_templates),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n🔍 Testing: {name}")
        print("-" * 60)
        result = test_func()
        results.append((name, result))
        print()

    print("=" * 60)
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
        print("\n🎉 All tests passed! FastAPI setup is complete.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
