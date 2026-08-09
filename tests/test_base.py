import datetime as dt
import time

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


@respx.mock
def test_secondary_rate_limit_403_is_retried_and_obeys_retry_after(monkeypatch):
    """GitHub answers a tripped secondary limit with 403 + Retry-After: 60.
    Measured on vllm 2026-08-09. Exponential backoff tops out near 4s here, so
    guessing the wait instead of reading the header simply fails."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    route = respx.get("https://api.example/rl").mock(side_effect=[
        httpx.Response(403, headers={"Retry-After": "60"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/rl") == {"ok": True}
    assert route.call_count == 2
    assert slept == [60.0]  # obeyed the header, did not use backoff


@respx.mock
def test_bare_403_fails_immediately_instead_of_being_retried():
    """A dead token must surface as an error, not be disguised as slowness."""
    route = respx.get("https://api.example/forbidden").mock(
        return_value=httpx.Response(403, json={"message": "Bad credentials"}))
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        request_json(c, "GET", "https://api.example/forbidden")
    assert route.call_count == 1  # not retried


@respx.mock
def test_retry_after_http_date_without_offset_does_not_crash_the_retry_layer(monkeypatch):
    """RFC 2822 allows a date with no explicit offset; parsedate_to_datetime
    returns a NAIVE datetime for it, and subtracting that from an aware now()
    raises TypeError. This helper runs on EVERY response, so raising here would
    take down the whole retry layer — the exact failure it exists to prevent."""
    from email.utils import format_datetime

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    # format_datetime always emits RFC 2822 in English regardless of locale;
    # strftime("%a %b") would produce unparseable names on a non-English host.
    future = format_datetime(
        dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
    ).replace(" +0000", "")  # deliberately strip the offset
    route = respx.get("https://api.example/date").mock(side_effect=[
        httpx.Response(403, headers={"Retry-After": future}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/date") == {"ok": True}
    assert route.call_count == 2
    assert 0 < slept[0] <= 30


@respx.mock
def test_absurd_retry_after_falls_back_instead_of_sleeping_forever(monkeypatch):
    """float('inf') parses fine and would sleep until the heat death."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    respx.get("https://api.example/inf").mock(side_effect=[
        httpx.Response(503, headers={"Retry-After": "inf"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/inf") == {"ok": True}
    assert slept == [1.0]  # fell back to backoff, did not honour "inf"


@respx.mock
def test_secondary_limit_403_without_retry_after_is_still_retried(monkeypatch):
    """GitHub's own docs: on a secondary limit "if the retry-after response
    header is present..." — i.e. it is conditional. x-ratelimit-remaining: 0 and
    the message body are the documented fallbacks. Treating such a 403 as a dead
    token would abandon a repo that merely needed to wait."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    route = respx.get("https://api.example/sec").mock(side_effect=[
        httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/sec") == {"ok": True}
    assert route.call_count == 2
    assert slept == [60.0]  # GitHub: "wait for at least one minute"


@respx.mock
def test_secondary_limit_detected_from_the_message_body(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    route = respx.get("https://api.example/body").mock(side_effect=[
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/body") == {"ok": True}
    assert route.call_count == 2


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
