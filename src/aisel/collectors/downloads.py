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


def _require(payload, key: str, what: str):
    """Fetch a required key, naming the subject when it is missing.

    A bare KeyError several frames from its cause costs hours at 3am; the
    sibling collectors all name the repo they were working on.
    """
    try:
        return payload[key]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"{what}: missing key {key!r}") from exc


def _split_windows(series: dict[dt.date, float],
                   today: dt.date) -> tuple[float, float, int, int]:
    """Return (recent 30d sum, previous 30d sum, recent days, previous days).

    The day counts are not decoration. A package younger than 60 days has a
    FULL recent window and a PARTIAL previous one, so perfectly flat traffic
    reads as explosive growth — a plausible, flattering, wrong number. From the
    sums alone nothing downstream can tell "quiet last month" from "did not
    exist last month". `metrics_daily` stores one bare float per metric and
    cannot be backfilled, so the coverage is recorded here or never.

    Deliberately does NOT raise on a short window, unlike github_issues' hard
    truncation check: a short history is the normal state of a genuinely new
    package, and refusing to collect it would be worse than collecting it with
    its coverage stated.
    """
    recent_start = today - dt.timedelta(days=WINDOW)
    prev_start = today - dt.timedelta(days=WINDOW * 2)
    recent = {d: v for d, v in series.items() if recent_start <= d < today}
    prev = {d: v for d, v in series.items() if prev_start <= d < recent_start}
    return (float(sum(recent.values())), float(sum(prev.values())),
            len(recent), len(prev))


def _pypi(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    payload = request_json(client, "GET", PYPISTATS.format(pkg=pkg))
    series: dict[dt.date, float] = {}
    for row in _require(payload, "data", f"pypistats payload for {pkg!r}"):
        # Every date appears twice, once per category. Take without_mirrors:
        # mirror traffic is bulk-sync bots, not somebody installing the package,
        # and this axis exists to measure real adoption rather than volume.
        # It is also the number pypistats.org itself displays — a reader who
        # checks our figure against the public page must find them equal.
        if row.get("category") not in (None, "without_mirrors"):
            continue
        series[dt.date.fromisoformat(row["date"])] = float(row["downloads"])
    recent, prev, recent_days, prev_days = _split_windows(series, today)
    return {
        "downloads_pypi_30d": recent,
        "downloads_pypi_prev30d": prev,
        "downloads_pypi_days_30d": float(recent_days),
        "downloads_pypi_days_prev30d": float(prev_days),
    }


def _npm(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    start = today - dt.timedelta(days=WINDOW * 2)
    payload = request_json(client, "GET", NPM_RANGE.format(
        start=start.isoformat(), end=today.isoformat(), pkg=pkg))
    rows = _require(payload, "downloads", f"npm payload for {pkg!r}")
    series = {dt.date.fromisoformat(r["day"]): float(r["downloads"]) for r in rows}
    recent, prev, recent_days, prev_days = _split_windows(series, today)
    return {
        "downloads_npm_30d": recent,
        "downloads_npm_prev30d": prev,
        "downloads_npm_days_30d": float(recent_days),
        "downloads_npm_days_prev30d": float(prev_days),
    }


def _dockerhub(client: httpx.Client, repo: str) -> dict[str, float]:
    payload = request_json(client, "GET", DOCKERHUB.format(repo=repo))
    return {"dockerhub_pulls_total": float(
        _require(payload, "pull_count", f"docker hub payload for {repo!r}"))}


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
