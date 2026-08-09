import datetime as dt

import httpx
import respx

from aisel.collectors.downloads import collect
from aisel.config import RepoSpec


def _spec(**kw):
    base = dict(owner="o", name="n", use_case_id="u", pypi_package=None,
                npm_package=None, dockerhub_repo=None, is_top=False)
    base.update(kw)
    return RepoSpec(**base)


@respx.mock
def test_pypi_splits_recent_and_previous_windows():
    days = []
    # 60 days: older 30 at 100/day, newer 30 at 200/day
    for i in range(60):
        d = dt.date(2026, 6, 11) + dt.timedelta(days=i)
        days.append({"date": d.isoformat(), "downloads": 100 if i < 30 else 200,
                     "category": "with_mirrors"})
    respx.get("https://pypistats.org/api/packages/langgraph/overall").mock(
        return_value=httpx.Response(200, json={"data": days}))

    with httpx.Client() as c:
        out = collect(c, _spec(pypi_package="langgraph"), today=dt.date(2026, 8, 10))

    assert out["downloads_pypi_30d"] == 6000.0
    assert out["downloads_pypi_prev30d"] == 3000.0


@respx.mock
def test_npm_and_dockerhub_are_collected_when_configured():
    respx.get(url__regex=r"https://api\.npmjs\.org/downloads/range/.*").mock(
        return_value=httpx.Response(200, json={"downloads": [
            {"day": (dt.date(2026, 6, 11) + dt.timedelta(days=i)).isoformat(),
             "downloads": 10}
            for i in range(60)
        ]}))
    respx.get("https://hub.docker.com/v2/repositories/vllm/vllm-openai/").mock(
        return_value=httpx.Response(200, json={"pull_count": 4200000}))

    with httpx.Client() as c:
        out = collect(c, _spec(npm_package="langchain",
                               dockerhub_repo="vllm/vllm-openai"),
                      today=dt.date(2026, 8, 10))

    assert out["downloads_npm_30d"] == 300.0
    assert out["downloads_npm_prev30d"] == 300.0
    assert out["dockerhub_pulls_total"] == 4200000.0


def test_repo_with_no_packages_yields_empty_dict():
    with httpx.Client() as c:
        assert collect(c, _spec(), today=dt.date(2026, 8, 10)) == {}
