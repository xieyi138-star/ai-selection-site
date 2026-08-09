import httpx
import pytest
import respx

from aisel.collectors.github_activity import collect

API = "https://api.github.com"


@respx.mock
def test_collect_reads_counts_and_derives_commit_total_from_link_header():
    respx.get(f"{API}/repos/o/n").mock(return_value=httpx.Response(
        200, json={"stargazers_count": 5000, "forks_count": 700}))
    # per_page=1 ⇒ last page number == total commit count in window
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"sha": "a"}],
            headers={"Link": f'<{API}/repos/o/n/commits?page=342>; rel="last"'}))
    respx.get(f"{API}/repos/o/n/releases").mock(return_value=httpx.Response(
        200, json=[{"published_at": "2026-07-10T00:00:00Z"}]))
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "100"}).mock(
        return_value=httpx.Response(200, json=[
            {"author": {"login": "alice"}},
            {"author": {"login": "bob"}},
            {"author": {"login": "alice"}},
            {"author": None},
        ]))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=__import__("datetime").date(2026, 8, 9))

    assert out["stars_total"] == 5000
    assert out["forks_total"] == 700
    assert out["commits_90d"] == 342
    assert out["days_since_last_release"] == 30
    assert out["contributors_90d"] == 2


@respx.mock
def test_no_releases_yields_sentinel_and_single_page_commits_count_as_one():
    respx.get(f"{API}/repos/o/n").mock(return_value=httpx.Response(
        200, json={"stargazers_count": 1, "forks_count": 0}))
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=[{"sha": "a"}]))  # no Link header
    respx.get(f"{API}/repos/o/n/releases").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "100"}).mock(
        return_value=httpx.Response(200, json=[{"author": {"login": "alice"}}]))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=__import__("datetime").date(2026, 8, 9))

    assert out["commits_90d"] == 1
    assert out["days_since_last_release"] == 9999.0  # sentinel: never released
    assert out["contributors_90d"] == 1


@respx.mock
def test_unparseable_link_header_raises_instead_of_guessing():
    """A parse failure must not masquerade as "this repo had 1 commit".

    Falling back to len(body) here would write a plausible wrong number into
    metrics_daily as if it were measured — CONSTITUTION.md rule 2.
    """
    respx.get(f"{API}/repos/o/n").mock(return_value=httpx.Response(
        200, json={"stargazers_count": 1, "forks_count": 0}))
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"sha": "a"}],
            headers={"Link": '<https://api.github.com/x>; rel="somethingelse"'}))
    respx.get(f"{API}/repos/o/n/releases").mock(return_value=httpx.Response(200, json=[]))

    with httpx.Client() as c:
        with pytest.raises(ValueError, match="unparseable Link header"):
            collect(c, "o", "n", today=__import__("datetime").date(2026, 8, 9))


@respx.mock
def test_commit_count_request_is_retried_on_transient_5xx(monkeypatch):
    """Nothing may bypass retry: one unretried 5xx costs this repo all five
    metrics for the day, which breaks the P0 gate's 7-consecutive-days run."""
    import aisel.collectors.base as base
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)

    respx.get(f"{API}/repos/o/n").mock(return_value=httpx.Response(
        200, json={"stargazers_count": 1, "forks_count": 0}))
    commits = respx.get(f"{API}/repos/o/n/commits",
                        params__contains={"per_page": "1"}).mock(side_effect=[
        httpx.Response(502),
        httpx.Response(200, json=[{"sha": "a"}],
                       headers={"Link": f'<{API}/x?page=7>; rel="last"'}),
    ])
    respx.get(f"{API}/repos/o/n/releases").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/repos/o/n/commits", params__contains={"per_page": "100"}).mock(
        return_value=httpx.Response(200, json=[{"author": {"login": "alice"}}]))

    with httpx.Client() as c:
        out = collect(c, "o", "n", today=__import__("datetime").date(2026, 8, 9))

    assert commits.call_count == 2   # retried, not abandoned
    assert out["commits_90d"] == 7
