import datetime as dt

import httpx
import respx

from aisel.collectors.github_issues import collect

GQL = "https://api.github.com/graphql"


def _issue(created, first_comment_at, author="reporter", commenter="maintainer",
           closed_at=None):
    nodes = ([] if first_comment_at is None
             else [{"createdAt": first_comment_at, "author": {"login": commenter}}])
    return {"createdAt": created, "closedAt": closed_at,
            "author": {"login": author}, "comments": {"nodes": nodes}}


@respx.mock
def test_median_first_response_ignores_self_replies_and_uncommented_issues():
    payload = {"data": {"repository": {"issues": {"nodes": [
        _issue("2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z"),   #  2h
        _issue("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),   #  6h
        _issue("2026-08-03T00:00:00Z", "2026-08-03T10:00:00Z"),   # 10h
        # self-reply only -> not a response
        _issue("2026-08-04T00:00:00Z", "2026-08-04T01:00:00Z", commenter="reporter"),
        # no comments at all -> excluded from median
        _issue("2026-08-05T00:00:00Z", None),
    ], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
    respx.post(GQL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=dt.date(2026, 8, 9))

    assert out["issue_first_response_p50_hours"] == 6.0
    assert out["issues_opened_90d"] == 5.0
    # 2 of the 5 got no external response: the self-reply and the uncommented one.
    assert out["issues_no_response_90d"] == 2.0


@respx.mock
def test_no_responded_issues_yields_sentinel():
    payload = {"data": {"repository": {"issues": {"nodes": [
        _issue("2026-08-05T00:00:00Z", None),
    ], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
    respx.post(GQL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=dt.date(2026, 8, 9))

    assert out["issue_first_response_p50_hours"] == -1.0
    assert out["issues_opened_90d"] == 1.0


@respx.mock
def test_counts_closed_issues_in_window():
    payload = {"data": {"repository": {"issues": {"nodes": [
        _issue("2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z",
               closed_at="2026-08-02T00:00:00Z"),
        _issue("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
    ], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
    respx.post(GQL).mock(return_value=httpx.Response(200, json=payload))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=dt.date(2026, 8, 9))

    assert out["issues_closed_90d"] == 1.0
