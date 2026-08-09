import datetime as dt

import httpx
import pytest
import respx

from aisel.collectors.base import request_json, request_with_retry, write_metrics
from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily, Repo, UseCase


@respx.mock
def test_request_with_retry_returns_the_response_so_headers_survive():
    """Callers that need pagination headers must not have to bypass retry."""
    respx.get("https://api.example/z").mock(return_value=httpx.Response(
        200, json={"ok": True}, headers={"Link": '<https://x>; rel="last"'}))
    with httpx.Client() as c:
        resp = request_with_retry(c, "GET", "https://api.example/z")
    assert resp.headers["Link"] == '<https://x>; rel="last"'
    assert resp.json() == {"ok": True}


@respx.mock
def test_request_json_retries_on_500_then_succeeds():
    route = respx.get("https://api.example/x").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_request_json_raises_after_exhausting_retries():
    respx.get("https://api.example/y").mock(return_value=httpx.Response(503))
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        request_json(c, "GET", "https://api.example/y", max_attempts=2)


def _seed(engine):
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        s.add(Repo(id=1, owner="o", name="n", use_case_id="u",
                   pypi_package=None, npm_package=None,
                   dockerhub_repo=None, is_top=False))


def test_write_metrics_is_idempotent(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    d = dt.date(2026, 8, 9)

    write_metrics(engine, 1, d, {"stars_total": 10.0})
    write_metrics(engine, 1, d, {"stars_total": 11.0})

    with session_scope(engine) as s:
        rows = s.query(MetricDaily).all()
        assert len(rows) == 1
        assert rows[0].value == 11.0
