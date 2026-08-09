import pytest

from aisel.config import RepoSpec, load_repos

VALID = """
use_cases:
  - id: agent-orchestration
    name: Agent Orchestration
    description: Frameworks that sequence LLM calls and tools.
repos:
  - slug: langchain-ai/langgraph
    use_case: agent-orchestration
    pypi: langgraph
    top: true
  - slug: crewAIInc/crewAI
    use_case: agent-orchestration
    pypi: crewai
"""


def test_load_repos_parses_slug_and_defaults(tmp_path):
    p = tmp_path / "repos.yaml"
    p.write_text(VALID, encoding="utf-8")
    specs = load_repos(p)
    assert specs[0] == RepoSpec(
        owner="langchain-ai", name="langgraph",
        use_case_id="agent-orchestration",
        pypi_package="langgraph", npm_package=None,
        dockerhub_repo=None, is_top=True,
    )
    assert specs[1].is_top is False


def test_load_repos_rejects_unknown_use_case(tmp_path):
    p = tmp_path / "repos.yaml"
    p.write_text(VALID.replace("use_case: agent-orchestration",
                               "use_case: nope", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown use_case 'nope'"):
        load_repos(p)


def test_load_repos_rejects_malformed_slug(tmp_path):
    p = tmp_path / "repos.yaml"
    p.write_text(VALID.replace("langchain-ai/langgraph", "langgraph"), encoding="utf-8")
    with pytest.raises(ValueError, match="slug must be 'owner/name'"):
        load_repos(p)


def test_sync_to_db_upserts_by_slug_without_duplicating(tmp_path):
    """sync_to_db is a DB-mutating upsert that every later task depends on.

    Re-running it daily must not duplicate rows, and an edited roster must
    actually take effect — a silent no-op on update would freeze the roster.
    """
    from aisel.config import sync_to_db
    from aisel.db import get_engine, init_db, session_scope
    from aisel.models import Repo, UseCase

    p = tmp_path / "repos.yaml"
    p.write_text(VALID, encoding="utf-8")
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)

    sync_to_db(engine, p)
    sync_to_db(engine, p)  # second run must be a no-op, not a duplicate

    with session_scope(engine) as s:
        assert s.query(UseCase).count() == 1
        assert s.query(Repo).count() == 2
        assert s.get(UseCase, "agent-orchestration").name == "Agent Orchestration"
        row = s.query(Repo).filter_by(owner="langchain-ai", name="langgraph").one()
        assert row.is_top is True
        assert row.pypi_package == "langgraph"
        assert row.npm_package is None

    # An edited roster must take effect on the existing row, keyed on slug.
    p.write_text(VALID.replace("    top: true\n", ""), encoding="utf-8")
    sync_to_db(engine, p)

    with session_scope(engine) as s:
        assert s.query(Repo).count() == 2  # updated in place, not appended
        row = s.query(Repo).filter_by(owner="langchain-ai", name="langgraph").one()
        assert row.is_top is False
