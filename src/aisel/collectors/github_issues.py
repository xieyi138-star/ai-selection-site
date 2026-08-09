"""Issue responsiveness via GraphQL (one request per repo instead of N+1)."""
from __future__ import annotations

import datetime as dt
import statistics

import httpx

from aisel.collectors.base import request_json

GQL = "https://api.github.com/graphql"
WINDOW_DAYS = 90
PAGE_SIZE = 100
# Must be high enough to actually reach the 90-day cutoff. Measured 2026-08-09:
# vllm 1773 issues/90d, llama.cpp 1281, ollama 675 — a 3-page (300) cap would
# silently truncate all three. Truncation is not merely "fewer samples": it
# keeps only the NEWEST issues, which are systematically less likely to be
# closed yet, so the close ratio that feeds the responsive axis would be biased
# downward exactly for high-traffic repos. Pages are only fetched until the
# cutoff is reached, so this ceiling costs nothing for the small repos.
MAX_PAGES = 40
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
    no_response = 0
    cursor: str | None = None
    covered = False

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
            else:
                no_response += 1
        page = issues["pageInfo"]
        if stop or not page["hasNextPage"]:
            covered = True
            break
        cursor = page["endCursor"]

    if not covered:
        # Ran out of pages before reaching the cutoff. Every count below would
        # understate the window, and the sample would be biased toward the
        # newest (least-likely-closed) issues. Refuse to publish a truncated
        # number as if it were measured.
        raise RuntimeError(
            f"{owner}/{name}: more than {MAX_PAGES * PAGE_SIZE} issues in the "
            f"last {WINDOW_DAYS} days; raise MAX_PAGES rather than truncating")

    return {
        "issue_first_response_p50_hours": (
            float(statistics.median(latencies)) if latencies else NO_SAMPLE),
        "issues_opened_90d": float(opened),
        "issues_closed_90d": float(closed),
        "issues_no_response_90d": float(no_response),
    }
