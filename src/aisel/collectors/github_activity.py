"""Activity signals from the GitHub REST API.

Commit count in the window is derived from the Link header with per_page=1 —
one request instead of paginating thousands of commits.
"""
from __future__ import annotations

import datetime as dt
import re

import httpx

from aisel.collectors.base import request_json

API = "https://api.github.com"
WINDOW_DAYS = 90
NEVER_RELEASED = 9999.0
CONTRIB_PAGE_CAP = 5  # cap at 500 commits; enough for a bus-factor proxy

_LAST_PAGE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')


def _commits_in_window(client: httpx.Client, owner: str, name: str, since: str) -> float:
    # Direct client.get (not request_json): we need response *headers* (Link),
    # which the request_json wrapper discards after returning parsed JSON.
    resp = client.get(f"{API}/repos/{owner}/{name}/commits",
                      params={"since": since, "per_page": 1})
    resp.raise_for_status()
    link = resp.headers.get("Link", "")
    m = _LAST_PAGE.search(link)
    if m:
        return float(m.group(1))
    return float(len(resp.json()))


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
