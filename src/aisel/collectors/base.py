"""Shared HTTP + persistence helpers. No collector may call httpx directly."""
from __future__ import annotations

import datetime as dt
import math
import time
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import MetricDaily

RETRY_STATUS = {429, 500, 502, 503, 504}
RATE_LIMIT_STATUS = {403, 429}

# A server-supplied wait longer than this is not a retry, it is a hang. The
# pipeline isolates a failed repo and retries tomorrow; blocking the whole run
# for an hour is worse than losing one repo for a day.
MAX_RETRY_AFTER_S = 300.0
# GitHub: "Otherwise, wait for at least one minute before retrying."
RATE_LIMIT_FALLBACK_WAIT_S = 60.0


def _sane_delay(seconds: float) -> float | None:
    """Clamp a server-supplied delay. inf/nan would sleep forever."""
    if not math.isfinite(seconds):
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Seconds the server asked us to wait, or None if it did not ask.

    **Must never raise.** This runs on every response, including 200s, so an
    exception here would take down the whole retry layer — precisely the
    failure the retry layer exists to prevent.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        pass
    else:
        return _sane_delay(seconds)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        # RFC 2822 permits "-0000" (UTC, sender's zone unknown) and bare dates;
        # parsedate_to_datetime returns a NAIVE datetime for those, and
        # subtracting it from an aware now() raises TypeError. Treat as UTC.
        when = when.replace(tzinfo=dt.UTC)
    return _sane_delay((when - dt.datetime.now(dt.UTC)).total_seconds())


def _looks_rate_limited(resp: httpx.Response) -> bool:
    """Is this 403/429 GitHub's secondary rate limit rather than a dead token?

    Per GitHub's "About secondary rate limits", Retry-After is only sometimes
    present; x-ratelimit-remaining: 0 and the message body are the documented
    fallbacks. A 403 matching none of these is a broken credential and must
    fail immediately — retrying it would disguise "the token is dead" as
    "the collector is slow", and we would not find out for days.
    """
    if resp.headers.get("Retry-After") is not None:
        return True
    if resp.headers.get("x-ratelimit-remaining") == "0":
        return True
    try:
        body = resp.text[:500].lower()
    except Exception:  # noqa: BLE001 - a body we cannot read is not evidence
        return False
    return "secondary rate limit" in body or "abuse detection" in body


def request_with_retry(client: httpx.Client, method: str, url: str,
                       max_attempts: int = 4, backoff: float = 1.0,
                       **kwargs) -> httpx.Response:
    """Retrying request that returns the Response, for callers needing headers.

    Nothing may bypass this: an unretried transient 5xx costs one repo a day of
    data, which breaks the P0 gate's 7-consecutive-days requirement and restarts
    the clock.

    Honours Retry-After when GitHub sends it. Measured 2026-08-09: paginating
    vllm's issues tripped GitHub's secondary rate limit at page 18 with
    `403 Retry-After: 60`. Exponential backoff caps out around 4s here, so
    guessing the wait instead of reading it simply fails.
    """
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        resp = client.request(method, url, **kwargs)
        wait = _retry_after_seconds(resp)
        rate_limited = (resp.status_code in RATE_LIMIT_STATUS
                        and _looks_rate_limited(resp))
        retryable = resp.status_code in RETRY_STATUS or rate_limited
        if not retryable:
            resp.raise_for_status()
            return resp
        last = resp
        if attempt < max_attempts - 1:
            if wait is None:
                wait = (RATE_LIMIT_FALLBACK_WAIT_S if rate_limited
                        else backoff * (2 ** attempt))
            time.sleep(wait)
    assert last is not None
    last.raise_for_status()
    raise RuntimeError("unreachable")


def request_json(client: httpx.Client, method: str, url: str,
                 max_attempts: int = 4, backoff: float = 1.0, **kwargs):
    return request_with_retry(client, method, url,
                              max_attempts=max_attempts, backoff=backoff,
                              **kwargs).json()


def write_metrics(engine: Engine, repo_id: int, date: dt.date,
                  values: dict[str, float]) -> None:
    """Upsert one row per metric. Re-running the same day overwrites."""
    with session_scope(engine) as s:
        for metric, value in values.items():
            if value is None:
                continue
            row = (s.query(MetricDaily)
                    .filter_by(repo_id=repo_id, date=date, metric=metric)
                    .one_or_none())
            if row is None:
                s.add(MetricDaily(repo_id=repo_id, date=date,
                                  metric=metric, value=float(value)))
            else:
                row.value = float(value)
