import datetime as dt

from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily
from aisel import pipeline

YAML = """
use_cases:
  - id: u
    name: U
repos:
  - slug: o/good
    use_case: u
  - slug: o/bad
    use_case: u
"""


def _write_cfg(tmp_path):
    p = tmp_path / "repos.yaml"
    p.write_text(YAML, encoding="utf-8")
    return p


def test_one_repo_failing_does_not_abort_the_run(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    cfg = _write_cfg(tmp_path)

    def fake_activity(client, owner, name, today=None):
        if name == "bad":
            raise RuntimeError("boom")
        return {"stars_total": 7.0}

    monkeypatch.setattr(pipeline.github_activity, "collect", fake_activity)
    monkeypatch.setattr(pipeline.github_issues, "collect",
                        lambda *a, **k: {"issues_opened_90d": 3.0})
    monkeypatch.setattr(pipeline.downloads, "collect", lambda *a, **k: {})

    report = pipeline.run(engine, cfg, today=dt.date(2026, 8, 9), token="x")

    assert report.total == 2
    assert report.ok == 1
    assert report.failures[0][0] == "o/bad"

    with session_scope(engine) as s:
        metrics = {m.metric for m in s.query(MetricDaily).all()}
    assert metrics == {"stars_total", "issues_opened_90d"}


def test_the_github_token_is_never_sent_to_third_party_hosts(tmp_path, monkeypatch):
    """httpx sends a client's default headers to EVERY host. One shared client
    would post the GitHub bearer token to pypistats.org, api.npmjs.org and
    hub.docker.com on every daily run. None of them needs authentication."""
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    cfg = _write_cfg(tmp_path)
    seen: dict[str, object] = {}

    def capture(client, spec, today=None):
        seen["download_auth"] = client.headers.get("Authorization")
        return {}

    def check_gh(client, owner, name, today=None):
        seen["github_auth"] = client.headers.get("Authorization")
        return {"stars_total": 1.0}

    monkeypatch.setattr(pipeline.github_activity, "collect", check_gh)
    monkeypatch.setattr(pipeline.github_issues, "collect", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.downloads, "collect", capture)

    pipeline.run(engine, cfg, today=dt.date(2026, 8, 9), token="sekrit")

    assert seen["github_auth"] == "Bearer sekrit"   # GitHub still authenticated
    assert seen["download_auth"] is None            # third parties get nothing


def test_rerunning_the_same_day_does_not_duplicate_rows(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    cfg = _write_cfg(tmp_path)

    monkeypatch.setattr(pipeline.github_activity, "collect",
                        lambda *a, **k: {"stars_total": 7.0})
    monkeypatch.setattr(pipeline.github_issues, "collect", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.downloads, "collect", lambda *a, **k: {})

    for _ in range(2):
        pipeline.run(engine, cfg, today=dt.date(2026, 8, 9), token="x")

    with session_scope(engine) as s:
        assert s.query(MetricDaily).count() == 2  # 2 repos x 1 metric
