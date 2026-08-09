import datetime as dt

import httpx
import pytest
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
    # 60 days: older 30 at 100/day, newer 30 at 200/day.
    # Each date carries BOTH categories, as the real API does. The mirror rows
    # are ten times larger, so a wrong filter fails loudly (66000/33000) rather
    # than being off by a plausible-looking few percent.
    for i in range(60):
        d = dt.date(2026, 6, 11) + dt.timedelta(days=i)
        n = 100 if i < 30 else 200
        days.append({"date": d.isoformat(), "downloads": n,
                     "category": "without_mirrors"})
        days.append({"date": d.isoformat(), "downloads": n * 10,
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
            # Must start at prev_start (today - 60d), same as the pypi fixture.
            # Starting a day later silently yields 29 days in the prev window.
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
    """"No package declared" is a measurement, not a failure — the scoring layer
    maps the empty result to unknown confidence. This is the one case where
    returning nothing is correct rather than a swallowed error."""
    with httpx.Client() as c:
        assert collect(c, _spec(), today=dt.date(2026, 8, 10)) == {}


@respx.mock
def test_malformed_pypistats_payload_raises_instead_of_reporting_zero():
    """A shape change upstream must not read as "this package has no downloads".
    Zero is a plausible, publishable, wrong number — CONSTITUTION.md rule 2."""
    respx.get("https://pypistats.org/api/packages/langgraph/overall").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"}))
    with httpx.Client() as c:
        with pytest.raises(KeyError):
            collect(c, _spec(pypi_package="langgraph"), today=dt.date(2026, 8, 10))


@respx.mock
def test_malformed_npm_payload_raises_instead_of_reporting_zero():
    respx.get(url__regex=r"https://api\.npmjs\.org/downloads/range/.*").mock(
        return_value=httpx.Response(200, json={"error": "package not found"}))
    with httpx.Client() as c:
        with pytest.raises(KeyError):
            collect(c, _spec(npm_package="nope"), today=dt.date(2026, 8, 10))
