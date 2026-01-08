import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse


def _make_request(path: str, *, hx: bool = False) -> Request:
    headers = []
    if hx:
        headers.append((b"hx-request", b"true"))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_dashboard_test_renders_live_for_prepared(monkeypatch):
    from backend import main as main_app

    test_id = "test-prepared"

    class StubRunning:
        status = "PREPARED"

    async def fake_get(_: str):
        return StubRunning()

    monkeypatch.setattr(main_app.registry, "get", fake_get)

    req = _make_request(f"/dashboard/{test_id}")
    resp = await main_app.dashboard_test(req, test_id)

    assert not isinstance(resp, RedirectResponse)
    assert resp.context.get("test_id") == test_id
    assert resp.template.name == "pages/dashboard.html"


@pytest.mark.asyncio
async def test_dashboard_test_redirects_for_terminal_status(monkeypatch):
    from backend import main as main_app

    test_id = "test-completed"

    class StubRunning:
        status = "COMPLETED"

    async def fake_get(_: str):
        return StubRunning()

    monkeypatch.setattr(main_app.registry, "get", fake_get)

    req = _make_request(f"/dashboard/{test_id}")
    resp = await main_app.dashboard_test(req, test_id)

    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert resp.headers.get("location") == f"/dashboard/history/{test_id}"


@pytest.mark.asyncio
async def test_dashboard_test_redirects_when_not_in_registry(monkeypatch):
    from backend import main as main_app

    test_id = "test-missing"

    async def fake_get(_: str):
        return None

    monkeypatch.setattr(main_app.registry, "get", fake_get)

    req = _make_request(f"/dashboard/{test_id}")
    resp = await main_app.dashboard_test(req, test_id)

    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert resp.headers.get("location") == f"/dashboard/history/{test_id}"


@pytest.mark.asyncio
async def test_dashboard_test_htmx_terminal_sets_hx_redirect(monkeypatch):
    from backend import main as main_app

    test_id = "test-completed-htmx"

    class StubRunning:
        status = "FAILED"

    async def fake_get(_: str):
        return StubRunning()

    monkeypatch.setattr(main_app.registry, "get", fake_get)

    req = _make_request(f"/dashboard/{test_id}", hx=True)
    resp = await main_app.dashboard_test(req, test_id)

    assert not isinstance(resp, RedirectResponse)
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect") == f"/dashboard/history/{test_id}"
