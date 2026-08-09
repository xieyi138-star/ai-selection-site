"""Issue responsiveness via GraphQL (one request per repo instead of N+1)."""
from __future__ import annotations

import datetime as dt
import statistics

import httpx

from aisel.collectors.base import request_json

GQL = "https://api.github.com/graphql"
WINDOW_DAYS = 90
PAGE_SIZE = 100
MAX_PAGES = 3          # up to 300 issues; plenty for a 90-day median
NO_SAMPLE = -1.0

QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(first:%d, after:$cursor, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes {
        createdAt
        closedAt
        author { login }
        comments(first:5) { nodes { createdAt author { login } } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""" % PAGE_SIZE


def _ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first_external_response_hours(issue: dict) -> float | None:
    author = (issue.get("author") or {}).get("login")
    created = _ts(issue["createdAt"])
    for comment in issue["comments"]["nodes"]:
        commenter = (comment.get("author") or {}).get("login")
        if commenter and commenter != author:
            return (_ts(comment["createdAt"]) - created).total_seconds() / 3600.0
    return None


def collect(client: httpx.Client, owner: str, name: str,
            today: dt.date | None = None) -> dict[str, float]:
    today = today or dt.datetime.now(dt.UTC).date()
    cutoff = dt.datetime.combine(today - dt.timedelta(days=WINDOW_DAYS),
                                 dt.time.min, tzinfo=dt.UTC)

    latencies: list[float] = []
    opened = 0
    closed = 0
    cursor: str | None = None

    for _ in range(MAX_PAGES):
        payload = request_json(
            client, "POST", GQL,
            json={"query": QUERY,
                  "variables": {"owner": owner, "name": name, "cursor": cursor}},
        )
        issues = payload["data"]["repository"]["issues"]
        stop = False
        for issue in issues["nodes"]:
            if _ts(issue["createdAt"]) < cutoff:
                stop = True
                break
            opened += 1
            if issue.get("closedAt"):
                closed += 1
            hours = _first_external_response_hours(issue)
            if hours is not None:
                latencies.append(hours)
        page = issues["pageInfo"]
        if stop or not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    return {
        "issue_first_response_p50_hours": (
            float(statistics.median(latencies)) if latencies else NO_SAMPLE),
        "issues_opened_90d": float(opened),
        "issues_closed_90d": float(closed),
    }
