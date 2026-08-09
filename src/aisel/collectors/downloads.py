"""Real-usage signals. pypistats (180d retention) replaces BigQuery — see the
Global Constraints in the plan for why."""
from __future__ import annotations

import datetime as dt

import httpx

from aisel.collectors.base import request_json
from aisel.config import RepoSpec

PYPISTATS = "https://pypistats.org/api/packages/{pkg}/overall"
NPM_RANGE = "https://api.npmjs.org/downloads/range/{start}:{end}/{pkg}"
DOCKERHUB = "https://hub.docker.com/v2/repositories/{repo}/"

WINDOW = 30


def _split_windows(series: dict[dt.date, float], today: dt.date) -> tuple[float, float]:
    """Return (sum over last 30d, sum over the 30d before that)."""
    recent_start = today - dt.timedelta(days=WINDOW)
    prev_start = today - dt.timedelta(days=WINDOW * 2)
    recent = sum(v for d, v in series.items() if recent_start <= d < today)
    prev = sum(v for d, v in series.items() if prev_start <= d < recent_start)
    return float(recent), float(prev)


def _pypi(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    payload = request_json(client, "GET", PYPISTATS.format(pkg=pkg))
    series: dict[dt.date, float] = {}
    for row in payload["data"]:
        if row.get("category") not in (None, "with_mirrors"):
            continue
        series[dt.date.fromisoformat(row["date"])] = float(row["downloads"])
    recent, prev = _split_windows(series, today)
    return {"downloads_pypi_30d": recent, "downloads_pypi_prev30d": prev}


def _npm(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    start = today - dt.timedelta(days=WINDOW * 2)
    payload = request_json(client, "GET", NPM_RANGE.format(
        start=start.isoformat(), end=today.isoformat(), pkg=pkg))
    series = {dt.date.fromisoformat(r["day"]): float(r["downloads"])
              for r in payload["downloads"]}
    recent, prev = _split_windows(series, today)
    return {"downloads_npm_30d": recent, "downloads_npm_prev30d": prev}


def _dockerhub(client: httpx.Client, repo: str) -> dict[str, float]:
    payload = request_json(client, "GET", DOCKERHUB.format(repo=repo))
    return {"dockerhub_pulls_total": float(payload["pull_count"])}


def collect(client: httpx.Client, spec: RepoSpec,
            today: dt.date | None = None) -> dict[str, float]:
    today = today or dt.datetime.now(dt.UTC).date()
    out: dict[str, float] = {}
    if spec.pypi_package:
        out.update(_pypi(client, spec.pypi_package, today))
    if spec.npm_package:
        out.update(_npm(client, spec.npm_package, today))
    if spec.dockerhub_repo:
        out.update(_dockerhub(client, spec.dockerhub_repo))
    return out
