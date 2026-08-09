import datetime as dt

from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily, Repo, UseCase


def test_can_persist_and_read_back_a_metric(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)

    with session_scope(engine) as s:
        s.add(UseCase(id="agent-orchestration", name="Agent Orchestration", description="d"))
        s.add(Repo(id=1, owner="langchain-ai", name="langgraph",
                   use_case_id="agent-orchestration", pypi_package="langgraph",
                   npm_package=None, dockerhub_repo=None, is_top=True))

    with session_scope(engine) as s:
        s.add(MetricDaily(repo_id=1, date=dt.date(2026, 8, 9),
                          metric="stars_total", value=1234.0))

    with session_scope(engine) as s:
        row = s.query(MetricDaily).one()
        assert row.metric == "stars_total"
        assert row.value == 1234.0
        assert row.repo.name == "langgraph"


def test_metric_unique_key_allows_upsert_semantics(tmp_path):
    """同一 (repo, date, metric) 只能有一行——幂等写入的基础。"""
    from sqlalchemy.exc import IntegrityError

    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        s.add(Repo(id=1, owner="o", name="n", use_case_id="u",
                   pypi_package=None, npm_package=None, dockerhub_repo=None, is_top=False))
    with session_scope(engine) as s:
        s.add(MetricDaily(repo_id=1, date=dt.date(2026, 8, 9), metric="m", value=1.0))

    try:
        with session_scope(engine) as s:
            s.add(MetricDaily(repo_id=1, date=dt.date(2026, 8, 9), metric="m", value=2.0))
    except IntegrityError:
        pass
    else:
        raise AssertionError("expected IntegrityError on duplicate (repo_id, date, metric)")
