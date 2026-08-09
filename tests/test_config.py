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
