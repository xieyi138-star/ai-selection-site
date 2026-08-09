"""Shared HTTP + persistence helpers. No collector may call httpx directly."""
from __future__ import annotations

import datetime as dt
import time

import httpx
from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import MetricDaily

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(client: httpx.Client, method: str, url: str,
                       max_attempts: int = 4, backoff: float = 1.0,
                       **kwargs) -> httpx.Response:
    """Retrying request that returns the Response, for callers needing headers.

    Nothing may bypass this: an unretried transient 5xx costs one repo a day of
    data, which breaks the P0 gate's 7-consecutive-days requirement and restarts
    the clock.
    """
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        resp = client.request(method, url, **kwargs)
        if resp.status_code not in RETRY_STATUS:
            resp.raise_for_status()
            return resp
        last = resp
        if attempt < max_attempts - 1:
            time.sleep(backoff * (2 ** attempt))
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
