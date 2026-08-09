"""Activity signals from the GitHub REST API.

Commit count in the window is derived from the Link header with per_page=1 —
one request instead of paginating thousands of commits.
"""
from __future__ import annotations

import datetime as dt
import re

import httpx

from aisel.collectors.base import request_json, request_with_retry

API = "https://api.github.com"
WINDOW_DAYS = 90
NEVER_RELEASED = 9999.0
CONTRIB_PAGE_CAP = 5  # cap at 500 commits; enough for a bus-factor proxy

_LAST_PAGE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')


def _commits_in_window(client: httpx.Client, owner: str, name: str, since: str) -> float:
    # Needs the raw Response: the count lives in the Link header, not the body.
    # request_with_retry (not a bare client call) keeps retry parity — an
    # unretried 5xx here would cost this repo all five metrics for the day.
    resp = request_with_retry(client, "GET", f"{API}/repos/{owner}/{name}/commits",
                              params={"since": since, "per_page": 1})
    link = resp.headers.get("Link", "")
    if not link:
        # With per_page=1 GitHub omits Link only for 0- or 1-commit windows,
        # so the body length IS the count here.
        return float(len(resp.json()))
    m = _LAST_PAGE.search(link)
    if m:
        return float(m.group(1))
    # Header present but unparseable: a format change or a stripping proxy.
    # Falling back to len(body) would report "1 commit" — a plausible, wrong,
    # persisted measurement. Refuse to guess (CONSTITUTION.md rule 2).
    raise ValueError(
        f"unparseable Link header for {owner}/{name}: {link!r}")


def _distinct_authors(client: httpx.Client, owner: str, name: str, since: str) -> float:
    authors: set[str] = set()
    for page in range(1, CONTRIB_PAGE_CAP + 1):
        batch = request_json(client, "GET", f"{API}/repos/{owner}/{name}/commits",
                             params={"since": since, "per_page": 100, "page": page})
        if not batch:
            break
        for commit in batch:
            author = commit.get("author")
            if author and author.get("login"):
                authors.add(author["login"])
        if len(batch) < 100:
            break
    return float(len(authors))


def collect(client: httpx.Client, owner: str, name: str,
            today: dt.date | None = None) -> dict[str, float]:
    today = today or dt.datetime.now(dt.UTC).date()
    since = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat() + "T00:00:00Z"

    meta = request_json(client, "GET", f"{API}/repos/{owner}/{name}")
    releases = request_json(client, "GET", f"{API}/repos/{owner}/{name}/releases",
                            params={"per_page": 1})

    if releases:
        published = dt.datetime.fromisoformat(
            releases[0]["published_at"].replace("Z", "+00:00")).date()
        days_since_release = float((today - published).days)
    else:
        days_since_release = NEVER_RELEASED

    return {
        "stars_total": float(meta["stargazers_count"]),
        "forks_total": float(meta["forks_count"]),
        "commits_90d": _commits_in_window(client, owner, name, since),
        "days_since_last_release": days_since_release,
        "contributors_90d": _distinct_authors(client, owner, name, since),
    }
