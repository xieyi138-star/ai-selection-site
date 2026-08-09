# AI 技术选型站 · P0 + P1a + P1b 施工计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成一条每日自动运行的判优流水线——采集 40 个 AI 生态 repo 的四维指标、对 Top 20 实跑 quickstart、生成带置信度的选型结论页，并通过 5 人盲测关口。

**Architecture:** Python 单体包 `aisel`，三段串联：`collectors/`（各数据源 → 长表 `metrics_daily`）→ `scoring/`（原始指标 → 四轴评级 → verdict + 依据快照）→ `render/`（verdict → 环节页 markdown）。沙箱实跑独立成 `sandbox/`，在 GitHub Actions 的 ubuntu runner 上执行并回写 `runs` 表。全部调度走 GitHub Actions cron，本机零常驻服务。

**Tech Stack:** Python 3.12 / SQLAlchemy 2.x / SQLite / httpx / PyYAML / pytest / GitHub Actions

对应设计规格：`docs/superpowers/specs/2026-08-09-github-ai-selection-site-design.md`

---

## Global Constraints

- Python **3.12**（本机实测 3.12.10）。不使用 3.13+ 语法。
- **数据库用 SQLite**，经 SQLAlchemy 2.x ORM 访问。规格 §11 写的是 Postgres；40 repo × 365 天 ≈ 1.5 万行，SQLite 完全够用且零安装。P2 建站时换 Postgres 只需改连接串。**业务代码中不得出现任何 SQLite 专有 SQL。**
  **例外**：为**消除方言行为差异**而做的连接期配置是允许且必需的，须按 `engine.dialect.name` 分支并注释说明。目前仅一处：SQLite 的 `PRAGMA foreign_keys=ON`（pysqlite 默认关闭外键，Postgres 默认开启；不开会让 dev/test 静默接受 prod 会拒绝的孤儿行）。这类配置服务于本约束的**目的**——不让 dev 与 prod 行为分叉——而不是违反它。
- **不使用 BigQuery。** 规格 §4.1 原定 PyPI 走 BigQuery；实测其 `file_downloads` 表按日分区即达数十 GB，按日查询一个月会耗尽 1TB/月免费额度。改用 `pypistats.org` API（180 天日粒度、免费、限速 ~30 req/min）。**趋势窗口因此为 180 天，不是 12 个月，页面上必须如实标注为 "180d trend"。**
- **本机无 Docker**（实测 `docker` not found）。所有 quickstart 实跑只在 GitHub Actions `ubuntu-latest` runner 上执行，该 runner 预装 Docker。**任何任务都不得要求本地起容器。**
- 所有时间戳一律 **UTC**，数据库中存 naive UTC datetime。
- `metrics_daily` 写入必须**幂等**：唯一键 `(repo_id, date, metric)`，重复运行覆盖而非追加。
- 网络请求一律经 `collectors/base.py` 的重试包装：要 JSON 用 `request_json`，要响应头（如 `Link` 分页头）用 `request_with_retry`。
  **禁止任何绕过重试的裸 `client` 调用。** 理由不是洁癖：P0 关口要求**连续 7 天无缺口**，任一 repo 在某天因一次未重试的瞬时 5xx 而采集失败，就是当日缺口，7 天时钟从头开始。一次 502 的代价是一周。
- **测不到就不许猜。** 解析外部响应时，「格式不符合预期」必须抛异常，不得退回一个看起来合理的默认值。合理的默认值会被当成测量结果写进 `metrics_daily`，违反 `CONSTITUTION.md` 规则 2。单个 repo 抛异常是安全的——`pipeline.run` 逐 repo 隔离，只丢那一个、次日重试。
- **置信度必须随每条 verdict 输出**；`confidence == "low"` 的条目**禁止**取得 `recommendation == "primary"`。此约束由 Task 14 的测试强制。
- 首批范围固定：**5 个环节 × 6–10 候选 = 40 repo**；**Top 20 = 每环节前 4**。
- 密钥只从环境变量读，`.env` 进 `.gitignore`，仓库内只留 `.env.example`。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 包定义与依赖 |
| `.env.example` / `.gitignore` | 密钥模板与忽略规则 |
| `CONSTITUTION.md` | 规格 §8 三条不可违反的守则（付费不影响排位等）的唯一出处 |
| `config/repos.yaml` | 40 repo 清单：环节归属、各生态包名、是否 Top 20 |
| `src/aisel/db.py` | engine / session / `init_db()` |
| `src/aisel/models.py` | ORM：`use_cases` `repos` `metrics_daily` `runs` `verdicts` |
| `src/aisel/config.py` | 载入并校验 `repos.yaml` |
| `src/aisel/collectors/base.py` | HTTP 重试包装 + `write_metrics()` 幂等写入 |
| `src/aisel/collectors/github_activity.py` | stars / forks / commits_90d / days_since_last_release / contributors_90d |
| `src/aisel/collectors/github_issues.py` | GraphQL 取 issue 首响中位时间、90 天开关数 |
| `src/aisel/collectors/downloads.py` | pypistats + npm + Docker Hub |
| `src/aisel/pipeline.py` | 串联所有 collector，CLI 入口 |
| `src/aisel/sandbox/manifest.py` | quickstart 定义的加载与校验 |
| `src/aisel/sandbox/runner.py` | 执行 quickstart、回写 `runs` |
| `src/aisel/sandbox/classify.py` | 失败原因分类 |
| `config/quickstarts.yaml` | Top 20 各自的 quickstart 命令 |
| `src/aisel/scoring/axes.py` | 原始指标 → 四轴评级 |
| `src/aisel/scoring/confidence.py` | 置信度分级 |
| `src/aisel/scoring/verdict.py` | 生成 verdict + 依据快照 |
| `src/aisel/render/stage_page.py` | verdict → 环节页 markdown |
| `scripts/verify_packages.py` | HTTP 实证每个声明的包名真实存在（测试抓不到的错误类别） |
| `scripts/gate_p0.py` | P0 关口验证 |
| `scripts/calibrate.py` | 阈值标定：打印真实数据分布 |
| `.github/workflows/collect.yml` | 每日采集 |
| `.github/workflows/quickstart.yml` | Top 20 沙箱实跑 |
| `blindtest/protocol.md` | 盲测提问脚本 |
| `blindtest/records/` | 每人一份记录 |

---

## Task 1: 项目骨架与数据模型

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`
- Create: `src/aisel/__init__.py`, `src/aisel/db.py`, `src/aisel/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces: `aisel.db.get_engine(url: str | None = None) -> Engine`、`aisel.db.session_scope(engine: Engine)`（contextmanager，yield `Session`，退出时 commit／异常时 rollback）、`aisel.db.init_db(engine: Engine) -> None`；ORM 类 `UseCase` `Repo` `MetricDaily` `QuickstartRun` `Verdict`（字段见下方代码）

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "aisel"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "SQLAlchemy>=2.0,<3.0",
    "httpx>=0.27",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "respx>=0.21"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: 写 `.gitignore`、`.env.example`、`CONSTITUTION.md`**

`CONSTITUTION.md`（落实规格 §8 与 §12 风险 5 —— 这两条在 P0/P1 阶段没有代码可挂靠，但必须在仓库里有唯一出处，否则将来加变现功能时无人记得）:

```markdown
# Constitution

Rules that must never be broken, even when breaking them would improve a
short-term number. That is precisely why they live here and not in someone's
memory.

## 1. Money never moves the ranking

No payment of any kind — sponsorship, listing fee, partnership, consulting
client relationship — may influence a repo's rank, rating, or recommendation.
Sponsors may buy clearly labelled display slots and nothing else.

Test for a violation: *would breaking this rule improve revenue?* If yes, the
rule is load-bearing and must stay locked.

## 2. Never claim to know what we cannot measure

Every verdict carries a confidence grade derived from signal completeness. A
repo with no real usage signal is graded `low` and may never be labelled a
primary recommendation. Pretending to know once destroys the only asset this
project has.

## 3. Verdicts state measurable facts, not opinions

Rationales cite observed metrics and the date they were observed. No
subjective disparagement of a project or its maintainers. Every verdict keeps
an evidence snapshot so it can be replayed against the data that produced it.
```

`.gitignore`:
```
.env
__pycache__/
*.pyc
.pytest_cache/
*.db
.venv/
build/
dist/
*.egg-info/
```

`.env.example`:
```
# GitHub personal access token, scope: public_repo (read-only is enough)
GITHUB_TOKEN=ghp_xxx
# SQLite path; override to a Postgres URL at P2
AISEL_DB_URL=sqlite:///aisel.db
```

- [ ] **Step 3: 写失败的测试 `tests/test_models.py`**

```python
import datetime as dt

import pytest

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


def test_orphan_foreign_key_is_rejected(tmp_path):
    """SQLite leaves FK enforcement off by default; Postgres does not.

    Without the connect-time PRAGMA, a stale repo_id inserts silently in dev
    and fails only in production. Every later task writes rows keyed on
    repo_id, so this guard protects the whole pipeline.
    """
    from sqlalchemy.exc import IntegrityError

    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)

    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(MetricDaily(repo_id=999, date=dt.date(2026, 8, 9),
                              metric="stars_total", value=1.0))
```

- [ ] **Step 4: 跑测试确认失败**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.db'`

- [ ] **Step 5: 写 `src/aisel/db.py`**

```python
"""Engine / session helpers. SQLite now, Postgres at P2 via AISEL_DB_URL."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from aisel.models import Base

DEFAULT_URL = "sqlite:///aisel.db"


def _enforce_sqlite_foreign_keys(engine: Engine) -> None:
    """pysqlite leaves foreign keys OFF; Postgres has them ON.

    Without this, dev and test silently accept orphan rows that production
    would reject — the exact dev/prod divergence the SQLite-now/Postgres-later
    decision is supposed to avoid.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or os.environ.get("AISEL_DB_URL", DEFAULT_URL))
    _enforce_sqlite_foreign_keys(engine)
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine):
    factory = sessionmaker(bind=engine)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 6: 写 `src/aisel/models.py`**

```python
"""ORM models. Metrics are stored long-format (one row per metric) so new
metrics never require a migration."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UseCase(Base):
    __tablename__ = "use_cases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    repos: Mapped[list["Repo"]] = relationship(back_populates="use_case")


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repo_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(128))
    use_case_id: Mapped[str] = mapped_column(ForeignKey("use_cases.id"))
    pypi_package: Mapped[str | None] = mapped_column(String(128), nullable=True)
    npm_package: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dockerhub_repo: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_top: Mapped[bool] = mapped_column(Boolean, default=False)

    use_case: Mapped[UseCase] = relationship(back_populates="repos")

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


class MetricDaily(Base):
    __tablename__ = "metrics_daily"
    __table_args__ = (
        UniqueConstraint("repo_id", "date", "metric", name="uq_metric_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)

    repo: Mapped[Repo] = relationship()


class QuickstartRun(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    run_at: Mapped[dt.datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))          # pass | fail
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    log_tail: Mapped[str] = mapped_column(Text, default="")
    repo_commit: Mapped[str] = mapped_column(String(64), default="")

    repo: Mapped[Repo] = relationship()


class Verdict(Base):
    __tablename__ = "verdicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    use_case_id: Mapped[str] = mapped_column(ForeignKey("use_cases.id"))
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    rank: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(24))  # primary|conditional|avoid|insufficient_data
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(8))       # high|medium|low
    rationale: Mapped[str] = mapped_column(Text)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime)

    repo: Mapped[Repo] = relationship()
```

- [ ] **Step 7: 跑测试确认通过**

Run: `python -m pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 8: 提交**

```bash
git add pyproject.toml .gitignore .env.example CONSTITUTION.md src/aisel tests/test_models.py docs/
git commit -m "feat: project skeleton, ORM models, sqlite engine helpers, constitution"
```

---

## Task 2: repo 清单配置与校验

**Files:**
- Create: `config/repos.yaml`, `src/aisel/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `aisel.models.Repo` / `UseCase`（Task 1）
- Produces:
  - `aisel.config.RepoSpec` — frozen dataclass，字段顺序 `owner, name, use_case_id, pypi_package, npm_package, dockerhub_repo, is_top`
  - `aisel.config.UseCaseSpec` — frozen dataclass，字段 `id, name, description`
  - `aisel.config.load_repos(path: str | Path) -> list[RepoSpec]`
  - `aisel.config.load_use_cases_and_repos(path) -> tuple[list[UseCaseSpec], list[RepoSpec]]`
  - `aisel.config.sync_to_db(engine: Engine, path: str | Path) -> None` — 按 slug upsert 进 `use_cases` / `repos` 表

> **候选清单如何确定**：`repos.yaml` 的初始 40 条不靠记忆填写。执行本任务时，对每个环节用 GitHub Search API 按 `topic` + `stars>500` 拉候选，人工筛掉明显不属于该环节的，取前 6–10 个；每环节前 4 标 `is_top: true`。筛选过程与理由写进 `config/repos.yaml` 的注释。

- [ ] **Step 1: 写失败的测试 `tests/test_config.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.config'`

- [ ] **Step 3: 写 `src/aisel/config.py`**

```python
"""Load and validate the repo roster."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import Repo, UseCase


@dataclass(frozen=True)
class RepoSpec:
    owner: str
    name: str
    use_case_id: str
    pypi_package: str | None
    npm_package: str | None
    dockerhub_repo: str | None
    is_top: bool


@dataclass(frozen=True)
class UseCaseSpec:
    id: str
    name: str
    description: str


def _parse_doc(raw: dict) -> tuple[list[UseCaseSpec], list[RepoSpec]]:
    use_cases = [
        UseCaseSpec(u["id"], u["name"], u.get("description", ""))
        for u in raw.get("use_cases", [])
    ]
    known = {u.id for u in use_cases}

    specs: list[RepoSpec] = []
    for entry in raw.get("repos", []):
        slug = entry["slug"]
        if slug.count("/") != 1:
            raise ValueError(f"slug must be 'owner/name', got {slug!r}")
        owner, name = slug.split("/")
        uc = entry["use_case"]
        if uc not in known:
            raise ValueError(f"unknown use_case {uc!r} for {slug}")
        specs.append(RepoSpec(
            owner=owner, name=name, use_case_id=uc,
            pypi_package=entry.get("pypi"),
            npm_package=entry.get("npm"),
            dockerhub_repo=entry.get("dockerhub"),
            is_top=bool(entry.get("top", False)),
        ))
    return use_cases, specs


def load_use_cases_and_repos(path: str | Path) -> tuple[list[UseCaseSpec], list[RepoSpec]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return _parse_doc(raw)


def load_repos(path: str | Path) -> list[RepoSpec]:
    return load_use_cases_and_repos(path)[1]


def sync_to_db(engine: Engine, path: str | Path) -> None:
    """Upsert use_cases and repos from YAML into the DB, keyed on slug."""
    use_cases, specs = load_use_cases_and_repos(path)
    with session_scope(engine) as s:
        for u in use_cases:
            row = s.get(UseCase, u.id)
            if row is None:
                s.add(UseCase(id=u.id, name=u.name, description=u.description))
            else:
                row.name, row.description = u.name, u.description
        s.flush()
        for spec in specs:
            row = (s.query(Repo)
                    .filter_by(owner=spec.owner, name=spec.name)
                    .one_or_none())
            if row is None:
                row = Repo(owner=spec.owner, name=spec.name)
                s.add(row)
            row.use_case_id = spec.use_case_id
            row.pypi_package = spec.pypi_package
            row.npm_package = spec.npm_package
            row.dockerhub_repo = spec.dockerhub_repo
            row.is_top = spec.is_top
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: 用 GitHub Search 生成真实的 `config/repos.yaml`**

对下列 5 个环节各跑一次搜索，取 stars>500 的结果人工筛选出 6–10 个真属于该环节的候选，每环节前 4 标 `top: true`。查包名时到 PyPI / npm / Docker Hub 页面核对，**不得凭印象填写**。

```bash
for t in llm-agent rag vector-database llm-inference llm-observability; do
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/search/repositories?q=topic:$t+stars:>500&sort=stars&per_page=20" \
    | python -c "import sys,json;[print(r['full_name'], r['stargazers_count'], (r['description'] or '')[:70]) for r in json.load(sys.stdin)['items']]"
  echo "---- $t ----"
done
```

环节 id 固定为：`agent-orchestration` / `rag` / `vector-db` / `inference` / `observability`。

- [ ] **Step 6: 校验清单结构**

Run:
```bash
python -c "
from aisel.config import load_use_cases_and_repos
u, r = load_use_cases_and_repos('config/repos.yaml')
print('use_cases:', len(u)); print('repos:', len(r)); print('top:', sum(x.is_top for x in r))
from collections import Counter; print(Counter(x.use_case_id for x in r))
"
```
Expected: `use_cases: 5`、`repos: 40`、`top: 20`，且每个环节的计数在 6–10 之间。

- [ ] **Step 6b: 逐个包名 HTTP 实证（不可跳过）**

**这一步不能靠肉眼核对。** 包名写错一个，那个 repo 的下载量永远取不到 → 采用量永远判为 `unknown` → 判优静默把它降级，而且**单元测试永远抓不到**，因为测试用的是 mock。把「我核对过了」变成「HTTP 说它存在」。

创建 `scripts/verify_packages.py`：

```python
"""Prove every declared package name resolves. A typo here is invisible to the
test suite (collectors are mocked) and silently zeroes a repo's adoption axis."""
from __future__ import annotations

import argparse

import httpx

from aisel.config import load_repos

ENDPOINTS = {
    "pypi": "https://pypi.org/pypi/{}/json",
    "npm": "https://registry.npmjs.org/{}",
    "dockerhub": "https://hub.docker.com/v2/repositories/{}/",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/repos.yaml")
    args = parser.parse_args()

    bad: list[str] = []
    signalless: list[str] = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for spec in load_repos(args.config):
            slug = f"{spec.owner}/{spec.name}"
            declared = {
                "pypi": spec.pypi_package,
                "npm": spec.npm_package,
                "dockerhub": spec.dockerhub_repo,
            }
            if not any(declared.values()):
                signalless.append(slug)
                continue
            for kind, value in declared.items():
                if not value:
                    continue
                url = ENDPOINTS[kind].format(value)
                resp = client.get(url)
                if resp.status_code != 200:
                    bad.append(f"{slug}  {kind}={value}  HTTP {resp.status_code}  {url}")

    for slug in signalless:
        print(f"NO-PACKAGE  {slug}  -> adoption axis will be 'unknown' (allowed, must be deliberate)")
    for line in bad:
        print(f"BAD  {line}")
    print(f"\n{len(bad)} bad, {len(signalless)} without any package")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `python scripts/verify_packages.py`
Expected: **退出码 0，零条 `BAD`**。

任一 404 → 那个包名是错的。**回去查真实包名（到 pypi.org / npmjs.com 搜该项目），不要删掉字段了事**——删字段等于永久放弃该 repo 的采用量信号。

`NO-PACKAGE` 行是允许的（ComfyUI 这类纯 GitHub 项目确实不发包），但每一条都必须是**你确认过它确实不发包**，而不是懒得填。把确认过的写进 `repos.yaml` 注释。

- [ ] **Step 7: 提交**

```bash
git add config/repos.yaml src/aisel/config.py tests/test_config.py
git commit -m "feat: repo roster config with validation and db sync"
```

---

## Task 3: GitHub 活性采集器

**Files:**
- Create: `src/aisel/collectors/__init__.py`, `src/aisel/collectors/base.py`, `src/aisel/collectors/github_activity.py`
- Test: `tests/test_base.py`, `tests/test_github_activity.py`

**Interfaces:**
- Consumes: `aisel.models`（Task 1）
- Produces:
  - `aisel.collectors.base.request_with_retry(client, method, url, max_attempts=4, backoff=1.0, **kw) -> httpx.Response`（带重试，返回原始 Response，供需要响应头的调用方）
  - `aisel.collectors.base.request_json(client, method, url, **kw) -> dict | list`（`request_with_retry` 的薄封装，取 `.json()`）
  - `aisel.collectors.base.write_metrics(engine, repo_id, date, values: dict[str, float]) -> None`（幂等）
  - `aisel.collectors.github_activity.collect(client, owner, name) -> dict[str, float]`，返回键：`stars_total` `forks_total` `commits_90d` `days_since_last_release` `contributors_90d`

- [ ] **Step 1: 写失败的测试 `tests/test_base.py`**

```python
import datetime as dt
import time

import httpx
import pytest
import respx

from aisel.collectors.base import request_json, request_with_retry, write_metrics
from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily, Repo, UseCase


@respx.mock
def test_request_with_retry_returns_the_response_so_headers_survive():
    """Callers that need pagination headers must not have to bypass retry."""
    respx.get("https://api.example/z").mock(return_value=httpx.Response(
        200, json={"ok": True}, headers={"Link": '<https://x>; rel="last"'}))
    with httpx.Client() as c:
        resp = request_with_retry(c, "GET", "https://api.example/z")
    assert resp.headers["Link"] == '<https://x>; rel="last"'
    assert resp.json() == {"ok": True}


@respx.mock
def test_request_json_retries_on_500_then_succeeds():
    route = respx.get("https://api.example/x").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_request_json_raises_after_exhausting_retries():
    respx.get("https://api.example/y").mock(return_value=httpx.Response(503))
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        request_json(c, "GET", "https://api.example/y", max_attempts=2)


@respx.mock
def test_secondary_rate_limit_403_is_retried_and_obeys_retry_after(monkeypatch):
    """GitHub answers a tripped secondary limit with 403 + Retry-After: 60.
    Measured on vllm 2026-08-09. Exponential backoff tops out near 4s here, so
    guessing the wait instead of reading the header simply fails."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    route = respx.get("https://api.example/rl").mock(side_effect=[
        httpx.Response(403, headers={"Retry-After": "60"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/rl") == {"ok": True}
    assert route.call_count == 2
    assert slept == [60.0]  # obeyed the header, did not use backoff


@respx.mock
def test_bare_403_fails_immediately_instead_of_being_retried():
    """A dead token must surface as an error, not be disguised as slowness."""
    route = respx.get("https://api.example/forbidden").mock(
        return_value=httpx.Response(403, json={"message": "Bad credentials"}))
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        request_json(c, "GET", "https://api.example/forbidden")
    assert route.call_count == 1  # not retried


@respx.mock
def test_retry_after_http_date_without_offset_does_not_crash_the_retry_layer(monkeypatch):
    """RFC 2822 allows a date with no explicit offset; parsedate_to_datetime
    returns a NAIVE datetime for it, and subtracting that from an aware now()
    raises TypeError. This helper runs on EVERY response, so raising here would
    take down the whole retry layer — the exact failure it exists to prevent."""
    from email.utils import format_datetime

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    # format_datetime always emits RFC 2822 in English regardless of locale;
    # strftime("%a %b") would produce unparseable names on a non-English host.
    future = format_datetime(
        dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
    ).replace(" +0000", "")  # deliberately strip the offset
    route = respx.get("https://api.example/date").mock(side_effect=[
        httpx.Response(403, headers={"Retry-After": future}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/date") == {"ok": True}
    assert route.call_count == 2
    assert 0 < slept[0] <= 30


@respx.mock
def test_absurd_retry_after_falls_back_instead_of_sleeping_forever(monkeypatch):
    """float('inf') parses fine and would sleep until the heat death."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    respx.get("https://api.example/inf").mock(side_effect=[
        httpx.Response(503, headers={"Retry-After": "inf"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/inf") == {"ok": True}
    assert slept == [1.0]  # fell back to backoff, did not honour "inf"


@respx.mock
def test_secondary_limit_403_without_retry_after_is_still_retried(monkeypatch):
    """GitHub's own docs: on a secondary limit "if the retry-after response
    header is present..." — i.e. it is conditional. x-ratelimit-remaining: 0 and
    the message body are the documented fallbacks. Treating such a 403 as a dead
    token would abandon a repo that merely needed to wait."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    route = respx.get("https://api.example/sec").mock(side_effect=[
        httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/sec") == {"ok": True}
    assert route.call_count == 2
    assert slept == [60.0]  # GitHub: "wait for at least one minute"


@respx.mock
def test_secondary_limit_detected_from_the_message_body(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    route = respx.get("https://api.example/body").mock(side_effect=[
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
        httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as c:
        assert request_json(c, "GET", "https://api.example/body") == {"ok": True}
    assert route.call_count == 2


def _seed(engine):
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        s.add(Repo(id=1, owner="o", name="n", use_case_id="u",
                   pypi_package=None, npm_package=None,
                   dockerhub_repo=None, is_top=False))


def test_write_metrics_is_idempotent(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    d = dt.date(2026, 8, 9)

    write_metrics(engine, 1, d, {"stars_total": 10.0})
    write_metrics(engine, 1, d, {"stars_total": 11.0})

    with session_scope(engine) as s:
        rows = s.query(MetricDaily).all()
        assert len(rows) == 1
        assert rows[0].value == 11.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.collectors'`

- [ ] **Step 3: 写 `src/aisel/collectors/base.py`**

```python
"""Shared HTTP + persistence helpers. No collector may call httpx directly."""
from __future__ import annotations

import datetime as dt
import math
import time
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import MetricDaily

RETRY_STATUS = {429, 500, 502, 503, 504}
RATE_LIMIT_STATUS = {403, 429}

# A server-supplied wait longer than this is not a retry, it is a hang. The
# pipeline isolates a failed repo and retries tomorrow; blocking the whole run
# for an hour is worse than losing one repo for a day.
MAX_RETRY_AFTER_S = 300.0
# GitHub: "Otherwise, wait for at least one minute before retrying."
RATE_LIMIT_FALLBACK_WAIT_S = 60.0


def _sane_delay(seconds: float) -> float | None:
    """Clamp a server-supplied delay. inf/nan would sleep forever."""
    if not math.isfinite(seconds):
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Seconds the server asked us to wait, or None if it did not ask.

    **Must never raise.** This runs on every response, including 200s, so an
    exception here would take down the whole retry layer — precisely the
    failure the retry layer exists to prevent.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        pass
    else:
        return _sane_delay(seconds)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        # RFC 2822 permits "-0000" (UTC, sender's zone unknown) and bare dates;
        # parsedate_to_datetime returns a NAIVE datetime for those, and
        # subtracting it from an aware now() raises TypeError. Treat as UTC.
        when = when.replace(tzinfo=dt.UTC)
    return _sane_delay((when - dt.datetime.now(dt.UTC)).total_seconds())


def _looks_rate_limited(resp: httpx.Response) -> bool:
    """Is this 403/429 GitHub's secondary rate limit rather than a dead token?

    Per GitHub's "About secondary rate limits", Retry-After is only sometimes
    present; x-ratelimit-remaining: 0 and the message body are the documented
    fallbacks. A 403 matching none of these is a broken credential and must
    fail immediately — retrying it would disguise "the token is dead" as
    "the collector is slow", and we would not find out for days.
    """
    if resp.headers.get("Retry-After") is not None:
        return True
    if resp.headers.get("x-ratelimit-remaining") == "0":
        return True
    try:
        body = resp.text[:500].lower()
    except Exception:  # noqa: BLE001 - a body we cannot read is not evidence
        return False
    return "secondary rate limit" in body or "abuse detection" in body


def request_with_retry(client: httpx.Client, method: str, url: str,
                       max_attempts: int = 4, backoff: float = 1.0,
                       **kwargs) -> httpx.Response:
    """Retrying request that returns the Response, for callers needing headers.

    Nothing may bypass this: an unretried transient 5xx costs one repo a day of
    data, which breaks the P0 gate's 7-consecutive-days requirement and restarts
    the clock.

    Honours Retry-After when GitHub sends it. Measured 2026-08-09: paginating
    vllm's issues tripped GitHub's secondary rate limit at page 18 with
    `403 Retry-After: 60`. Exponential backoff caps out around 4s here, so
    guessing the wait instead of reading it simply fails.
    """
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        resp = client.request(method, url, **kwargs)
        wait = _retry_after_seconds(resp)
        rate_limited = (resp.status_code in RATE_LIMIT_STATUS
                        and _looks_rate_limited(resp))
        retryable = resp.status_code in RETRY_STATUS or rate_limited
        if not retryable:
            resp.raise_for_status()
            return resp
        last = resp
        if attempt < max_attempts - 1:
            if wait is None:
                wait = (RATE_LIMIT_FALLBACK_WAIT_S if rate_limited
                        else backoff * (2 ** attempt))
            time.sleep(wait)
    assert last is not None
    last.raise_for_status()
    raise RuntimeError("unreachable")


def request_json(client: httpx.Client, method: str, url: str,
                 max_attempts: int = 4, backoff: float = 1.0, **kwargs):
    return request_with_retry(client, method, url,
                              max_attempts=max_attempts, backoff=backoff,
                              **kwargs).json()


def write_metrics(engine: Engine, repo_id: int, date: dt.date,
                  values: dict[str, float]) -> None:
    """Upsert one row per metric. Re-running the same day overwrites."""
    with session_scope(engine) as s:
        for metric, value in values.items():
            if value is None:
                continue
            row = (s.query(MetricDaily)
                    .filter_by(repo_id=repo_id, date=date, metric=metric)
                    .one_or_none())
            if row is None:
                s.add(MetricDaily(repo_id=repo_id, date=date,
                                  metric=metric, value=float(value)))
            else:
                row.value = float(value)
```

`src/aisel/collectors/__init__.py` 内容为空。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_base.py -v`
Expected: 10 passed

- [ ] **Step 5: 写失败的测试 `tests/test_github_activity.py`**

```python
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
```

> 若 `@respx.mock` 装饰器与 pytest 的 `monkeypatch` fixture 组合出问题，改用 `with respx.mock:` 上下文管理器写法即可——**要证明的东西不变**：该请求在 502 后重试且最终解析出 7。改了要在报告里写明。

- [ ] **Step 6: 跑测试确认失败**

Run: `python -m pytest tests/test_github_activity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.collectors.github_activity'`

- [ ] **Step 7: 写 `src/aisel/collectors/github_activity.py`**

```python
"""Activity signals from the GitHub REST API.

Commit count in the window is derived from the Link header with per_page=1 —
one request instead of paginating thousands of commits.
"""
from __future__ import annotations

import datetime as dt
import re

import httpx

from aisel.collectors.base import request_json, request_with_retry

API = "https://api.github.com"
WINDOW_DAYS = 90
NEVER_RELEASED = 9999.0
CONTRIB_PAGE_CAP = 5  # cap at 500 commits; enough for a bus-factor proxy

_LAST_PAGE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')


def _commits_in_window(client: httpx.Client, owner: str, name: str, since: str) -> float:
    # Needs the raw Response: the count lives in the Link header, not the body.
    # request_with_retry (not a bare client call) keeps retry parity — an
    # unretried 5xx here would cost this repo all five metrics for the day.
    resp = request_with_retry(client, "GET", f"{API}/repos/{owner}/{name}/commits",
                              params={"since": since, "per_page": 1})
    link = resp.headers.get("Link", "")
    if not link:
        # With per_page=1 GitHub omits Link only for 0- or 1-commit windows,
        # so the body length IS the count here.
        return float(len(resp.json()))
    m = _LAST_PAGE.search(link)
    if m:
        return float(m.group(1))
    # Header present but unparseable: a format change or a stripping proxy.
    # Falling back to len(body) would report "1 commit" — a plausible, wrong,
    # persisted measurement. Refuse to guess (CONSTITUTION.md rule 2).
    raise ValueError(
        f"unparseable Link header for {owner}/{name}: {link!r}")


def _distinct_authors(client: httpx.Client, owner: str, name: str, since: str) -> float:
    authors: set[str] = set()
    for page in range(1, CONTRIB_PAGE_CAP + 1):
        batch = request_json(client, "GET", f"{API}/repos/{owner}/{name}/commits",
                             params={"since": since, "per_page": 100, "page": page})
        if not batch:
            break
        for commit in batch:
            author = commit.get("author")
            if author and author.get("login"):
                authors.add(author["login"])
        if len(batch) < 100:
            break
    return float(len(authors))


def collect(client: httpx.Client, owner: str, name: str,
            today: dt.date | None = None) -> dict[str, float]:
    today = today or dt.datetime.now(dt.UTC).date()
    since = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat() + "T00:00:00Z"

    meta = request_json(client, "GET", f"{API}/repos/{owner}/{name}")
    releases = request_json(client, "GET", f"{API}/repos/{owner}/{name}/releases",
                            params={"per_page": 1})

    if releases:
        published = dt.datetime.fromisoformat(
            releases[0]["published_at"].replace("Z", "+00:00")).date()
        days_since_release = float((today - published).days)
    else:
        days_since_release = NEVER_RELEASED

    return {
        "stars_total": float(meta["stargazers_count"]),
        "forks_total": float(meta["forks_count"]),
        "commits_90d": _commits_in_window(client, owner, name, since),
        "days_since_last_release": days_since_release,
        "contributors_90d": _distinct_authors(client, owner, name, since),
    }
```

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/test_github_activity.py -v`
Expected: 4 passed

- [ ] **Step 9: 对真实 repo 手工验一次**

Run:
```bash
python -c "
import httpx, os, datetime as dt
from aisel.collectors.github_activity import collect
h={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'}
with httpx.Client(headers=h, timeout=30) as c:
    print(collect(c,'langchain-ai','langgraph'))
"
```
Expected: `stars_total` 与 GitHub 网页显示的 star 数一致（±1 天波动可接受）。**不一致就停下来查，不要继续。**

- [ ] **Step 10: 提交**

```bash
git add src/aisel/collectors tests/test_base.py tests/test_github_activity.py
git commit -m "feat: http retry base, idempotent metric writes, github activity collector"
```

---

## Task 4: GitHub issue 响应采集器（GraphQL）

**Files:**
- Create: `src/aisel/collectors/github_issues.py`
- Test: `tests/test_github_issues.py`

**Interfaces:**
- Consumes: `aisel.collectors.base.request_json`（Task 3）
- Produces: `aisel.collectors.github_issues.collect(client, owner, name, today=None) -> dict[str, float]`，键：`issue_first_response_p50_hours`（无样本时为 `-1.0`）、`issues_opened_90d`、`issues_closed_90d`、`issues_no_response_90d`

> **为什么要单独采 `issues_no_response_90d`**：2026-08-09 实测 langgraph 90 天内 180 个 issue，**36 个（20%）无人回复**。首响中位数只统计「有回复的那些」——一个 80% 提问被无视、但回的那 20% 一小时内回的仓库，会被判成响应"strong"。这条目前**只采不评分**（spec §4.2 未列它），但必须从第一天就采：`metrics_daily` 是增量累积的，今天不采就永远补不回来，而采集器在 7 天时钟启动后改动会让时钟重来。

> 用 GraphQL 而非 REST：REST 需为每个 issue 再取一次 comments（N+1，40 repo × 50 issue ≈ 2000 请求/天）。GraphQL 一个请求即可带回 issue 与其首条评论，40 请求/天。

- [ ] **Step 1: 写失败的测试 `tests/test_github_issues.py`**

```python
import datetime as dt

import httpx
import pytest
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


@respx.mock
def test_truncated_window_raises_rather_than_reporting_a_partial_count(monkeypatch):
    """Exhausting MAX_PAGES before reaching the cutoff means every count is an
    undercount — and the surviving sample is the NEWEST issues, which are
    systematically less likely to be closed, so the close ratio would be biased
    downward exactly for the busiest repos. Measured 2026-08-09: vllm 1773
    issues/90d, llama.cpp 1281, ollama 675.
    """
    import aisel.collectors.github_issues as gi

    monkeypatch.setattr(gi, "PAGE_DELAY_S", 0.0)  # 40 pages x 1s would stall the suite

    # Every page: full, entirely in-window, and claiming another page follows.
    page = {"data": {"repository": {"issues": {
        "nodes": [_issue("2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z")
                  for _ in range(gi.PAGE_SIZE)],
        "pageInfo": {"hasNextPage": True, "endCursor": "c"}}}}}
    route = respx.post(GQL).mock(return_value=httpx.Response(200, json=page))

    with httpx.Client() as c:
        with pytest.raises(RuntimeError, match="raise MAX_PAGES"):
            collect(c, "o", "n", today=dt.date(2026, 8, 9))

    assert route.call_count == gi.MAX_PAGES  # tried the full budget first


@respx.mock
def test_graphql_errors_payload_raises_a_diagnosable_message():
    """GraphQL answers errors with HTTP 200 and a null data payload. Without an
    explicit check this surfaced as a bare TypeError several frames from its
    cause — correct but undiagnosable, which costs hours at 3am."""
    respx.post(GQL).mock(return_value=httpx.Response(200, json={
        "data": None,
        "errors": [{"message": "Could not resolve to a Repository named 'o/nope'."}]}))
    with httpx.Client() as c:
        with pytest.raises(RuntimeError, match="Could not resolve to a Repository"):
            collect(c, "o", "nope", today=dt.date(2026, 8, 9))


@respx.mock
def test_null_repository_without_an_errors_array_also_raises():
    respx.post(GQL).mock(return_value=httpx.Response(
        200, json={"data": {"repository": None}}))
    with httpx.Client() as c:
        with pytest.raises(RuntimeError, match="no repository"):
            collect(c, "o", "gone", today=dt.date(2026, 8, 9))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_github_issues.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `src/aisel/collectors/github_issues.py`**

```python
"""Issue responsiveness via GraphQL (one request per repo instead of N+1)."""
from __future__ import annotations

import datetime as dt
import statistics
import time

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
# Retry recovers from the secondary rate limit; throttling avoids provoking it.
# Measured 2026-08-09: 17 back-to-back GraphQL pages against vllm tripped it.
# Only the few high-traffic repos pay this — everyone else exits after one page.
PAGE_DELAY_S = 1.0
NO_SAMPLE = -1.0

# Why comments(first:5): we need the first comment by someone other than the
# issue author, so the window only has to outlast a reporter's own follow-ups.
# Measured 2026-08-09 across all 3,234 issues in the 90-day windows of langgraph,
# vllm and llama.cpp: widening 5 -> 15 reclassifies 2 issues (0.19% of the
# no-response bucket). Issues with 5+ leading author-only comments are rare
# (0 / 0 / 3 respectively) and mostly never got an external reply anyway.
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
        # GraphQL answers errors with HTTP 200 and a null payload, which would
        # otherwise surface as a bare TypeError several frames away.
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL error for {owner}/{name}: {payload['errors']}")
        repository = (payload.get("data") or {}).get("repository")
        if repository is None:
            raise RuntimeError(f"GraphQL returned no repository for {owner}/{name}")
        issues = repository["issues"]
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
        time.sleep(PAGE_DELAY_S)

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_github_issues.py -v`
Expected: 4 passed

- [ ] **Step 5: 对真实 repo 手工验一次并人工抽查**

Run:
```bash
python -c "
import httpx, os, datetime as dt
from aisel.collectors.github_issues import collect
h={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN']}
with httpx.Client(headers=h, timeout=60) as c:
    print(collect(c,'langchain-ai','langgraph'))
"
```
然后到该 repo 的 issue 列表随机点开 3 个近期 issue，人工核对首次他人回复的间隔是否与中位数量级相符。**量级不符就停下来查。**

- [ ] **Step 6: 提交**

```bash
git add src/aisel/collectors/github_issues.py tests/test_github_issues.py
git commit -m "feat: issue responsiveness collector via graphql"
```

---

## Task 5: 下载量采集器（pypistats / npm / Docker Hub）

**Files:**
- Create: `src/aisel/collectors/downloads.py`
- Test: `tests/test_downloads.py`

**Interfaces:**
- Consumes: `aisel.collectors.base.request_json`（Task 3）
- Produces: `aisel.collectors.downloads.collect(client, spec: RepoSpec) -> dict[str, float]`，键（仅在对应包名存在时出现）：`downloads_pypi_30d`、`downloads_pypi_prev30d`、`downloads_pypi_days_30d`、`downloads_pypi_days_prev30d`、`downloads_npm_30d`、`downloads_npm_prev30d`、`downloads_npm_days_30d`、`downloads_npm_days_prev30d`、`dockerhub_pulls_total`
- 同时导出 `aisel.collectors.downloads._require(payload, key, what)` 供三个私有取数函数复用（缺键时抛带主体名的 `RuntimeError`）

> `prev30d` 是趋势的基础：`当前 30 天 / 前一个 30 天`。pypistats 只保留 180 天，因此规格中的「12 个月趋势」在 MVP 降级为「180 天窗口内的 30d vs prev30d」，页面必须标注为 180d。

- [ ] **Step 1: 写失败的测试 `tests/test_downloads.py`**

```python
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
    assert out["downloads_pypi_days_30d"] == 30.0
    assert out["downloads_pypi_days_prev30d"] == 30.0  # both windows complete


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
    assert out["downloads_npm_days_30d"] == 30.0
    assert out["downloads_npm_days_prev30d"] == 30.0
    assert out["dockerhub_pulls_total"] == 4200000.0


@respx.mock  # no routes registered: any real network call fails hermetically
def test_repo_with_no_packages_yields_empty_dict():
    """"No package declared" is a measurement, not a failure — the scoring layer
    maps the empty result to unknown confidence. This is the one case where
    returning nothing is correct rather than a swallowed error."""
    with httpx.Client() as c:
        assert collect(c, _spec(), today=dt.date(2026, 8, 10)) == {}


@respx.mock
def test_short_history_shows_up_in_the_day_counts_not_hidden_in_the_sums():
    """A package younger than 60 days has a FULL recent window and a PARTIAL
    previous one, so perfectly flat traffic reads as 3x growth. The sums alone
    cannot separate "quiet last month" from "did not exist last month"; the day
    counts can, and metrics_daily cannot be backfilled."""
    days = [{"date": (dt.date(2026, 8, 9) - dt.timedelta(days=k)).isoformat(),
             "downloads": 100, "category": "without_mirrors"}
            for k in range(40)]  # only 40 days of history
    respx.get("https://pypistats.org/api/packages/newpkg/overall").mock(
        return_value=httpx.Response(200, json={"data": days}))

    with httpx.Client() as c:
        out = collect(c, _spec(pypi_package="newpkg"), today=dt.date(2026, 8, 10))

    assert out["downloads_pypi_days_30d"] == 30.0       # complete
    assert out["downloads_pypi_days_prev30d"] == 10.0   # partial -> trend invalid
    # A naive 3000/1000 would announce 3x growth from perfectly flat traffic.
    assert out["downloads_pypi_30d"] == 3000.0
    assert out["downloads_pypi_prev30d"] == 1000.0


@respx.mock
def test_malformed_pypistats_payload_raises_instead_of_reporting_zero():
    """A shape change upstream must not read as "this package has no downloads".
    Zero is a plausible, publishable, wrong number — CONSTITUTION.md rule 2."""
    respx.get("https://pypistats.org/api/packages/langgraph/overall").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"}))
    with httpx.Client() as c:
        with pytest.raises(RuntimeError, match="pypistats payload for 'langgraph'"):
            collect(c, _spec(pypi_package="langgraph"), today=dt.date(2026, 8, 10))


@respx.mock
def test_malformed_npm_payload_raises_instead_of_reporting_zero():
    respx.get(url__regex=r"https://api\.npmjs\.org/downloads/range/.*").mock(
        return_value=httpx.Response(200, json={"error": "package not found"}))
    with httpx.Client() as c:
        with pytest.raises(RuntimeError, match="npm payload for 'nope'"):
            collect(c, _spec(npm_package="nope"), today=dt.date(2026, 8, 10))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_downloads.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `src/aisel/collectors/downloads.py`**

```python
"""Real-usage signals. pypistats (180d retention) replaces BigQuery — see the
Global Constraints in the plan for why."""
from __future__ import annotations

import datetime as dt

import httpx

from aisel.collectors.base import request_json
from aisel.config import RepoSpec

PYPISTATS = "https://pypistats.org/api/packages/{pkg}/overall"
NPM_RANGE = "https://api.npmjs.org/downloads/range/{start}:{end}/{pkg}"
DOCKERHUB = "https://hub.docker.com/v2/repositories/{repo}/"

WINDOW = 30


def _require(payload, key: str, what: str):
    """Fetch a required key, naming the subject when it is missing.

    A bare KeyError several frames from its cause costs hours at 3am; the
    sibling collectors all name the repo they were working on.
    """
    try:
        return payload[key]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"{what}: missing key {key!r}") from exc


def _split_windows(series: dict[dt.date, float],
                   today: dt.date) -> tuple[float, float, int, int]:
    """Return (recent 30d sum, previous 30d sum, recent days, previous days).

    The day counts are not decoration. A package younger than 60 days has a
    FULL recent window and a PARTIAL previous one, so perfectly flat traffic
    reads as explosive growth — a plausible, flattering, wrong number. From the
    sums alone nothing downstream can tell "quiet last month" from "did not
    exist last month". `metrics_daily` stores one bare float per metric and
    cannot be backfilled, so the coverage is recorded here or never.

    Deliberately does NOT raise on a short window, unlike github_issues' hard
    truncation check: a short history is the normal state of a genuinely new
    package, and refusing to collect it would be worse than collecting it with
    its coverage stated.
    """
    recent_start = today - dt.timedelta(days=WINDOW)
    prev_start = today - dt.timedelta(days=WINDOW * 2)
    recent = {d: v for d, v in series.items() if recent_start <= d < today}
    prev = {d: v for d, v in series.items() if prev_start <= d < recent_start}
    return (float(sum(recent.values())), float(sum(prev.values())),
            len(recent), len(prev))


def _pypi(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    payload = request_json(client, "GET", PYPISTATS.format(pkg=pkg))
    series: dict[dt.date, float] = {}
    for row in _require(payload, "data", f"pypistats payload for {pkg!r}"):
        # Every date appears twice, once per category. Take without_mirrors:
        # mirror traffic is bulk-sync bots, not somebody installing the package,
        # and this axis exists to measure real adoption rather than volume.
        # It is also the number pypistats.org itself displays — a reader who
        # checks our figure against the public page must find them equal.
        if row.get("category") not in (None, "without_mirrors"):
            continue
        series[dt.date.fromisoformat(row["date"])] = float(row["downloads"])
    recent, prev, recent_days, prev_days = _split_windows(series, today)
    return {
        "downloads_pypi_30d": recent,
        "downloads_pypi_prev30d": prev,
        "downloads_pypi_days_30d": float(recent_days),
        "downloads_pypi_days_prev30d": float(prev_days),
    }


def _npm(client: httpx.Client, pkg: str, today: dt.date) -> dict[str, float]:
    start = today - dt.timedelta(days=WINDOW * 2)
    payload = request_json(client, "GET", NPM_RANGE.format(
        start=start.isoformat(), end=today.isoformat(), pkg=pkg))
    rows = _require(payload, "downloads", f"npm payload for {pkg!r}")
    series = {dt.date.fromisoformat(r["day"]): float(r["downloads"]) for r in rows}
    recent, prev, recent_days, prev_days = _split_windows(series, today)
    return {
        "downloads_npm_30d": recent,
        "downloads_npm_prev30d": prev,
        "downloads_npm_days_30d": float(recent_days),
        "downloads_npm_days_prev30d": float(prev_days),
    }


def _dockerhub(client: httpx.Client, repo: str) -> dict[str, float]:
    payload = request_json(client, "GET", DOCKERHUB.format(repo=repo))
    return {"dockerhub_pulls_total": float(
        _require(payload, "pull_count", f"docker hub payload for {repo!r}"))}


def collect(client: httpx.Client, spec: RepoSpec,
            today: dt.date | None = None) -> dict[str, float]:
    today = today or dt.datetime.now(dt.UTC).date()
    out: dict[str, float] = {}
    if spec.pypi_package:
        out.update(_pypi(client, spec.pypi_package, today))
    if spec.npm_package:
        out.update(_npm(client, spec.npm_package, today))
    if spec.dockerhub_repo:
        out.update(_dockerhub(client, spec.dockerhub_repo))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_downloads.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 对真实包核账**

Run:
```bash
python -c "
import httpx, datetime as dt
from aisel.collectors.downloads import collect
from aisel.config import RepoSpec
s=RepoSpec('langchain-ai','langgraph','agent-orchestration','langgraph',None,None,True)
with httpx.Client(timeout=30) as c: print(collect(c,s))
"
```
到 `https://pypistats.org/packages/langgraph` 网页对照近 30 天总量，**量级不符就停**。

- [ ] **Step 6: 提交**

```bash
git add src/aisel/collectors/downloads.py tests/test_downloads.py
git commit -m "feat: download collectors for pypistats, npm, docker hub"
```

---

## Task 6: pipeline 编排

**Files:**
- Create: `src/aisel/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2–5 全部
- Produces: `aisel.pipeline.run(engine, config_path, today=None, token=None) -> PipelineReport`；`PipelineReport` dataclass 字段 `total: int`、`ok: int`、`failures: list[tuple[str, str]]`（slug, 错误摘要）。CLI：`python -m aisel.pipeline --config config/repos.yaml`

> 单个 repo 采集失败**不得中断整轮**——记进 `failures` 继续跑。否则一个下架的包会让当天全部数据缺失。

- [ ] **Step 1: 写失败的测试 `tests/test_pipeline.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.pipeline'`

- [ ] **Step 3: 写 `src/aisel/pipeline.py`**

```python
"""Daily collection orchestrator. One repo failing must never abort the run."""
from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import Engine

from aisel.collectors import downloads, github_activity, github_issues
from aisel.collectors.base import write_metrics
from aisel.config import load_repos, sync_to_db
from aisel.db import get_engine, init_db, session_scope
from aisel.models import Repo


@dataclass
class PipelineReport:
    total: int = 0
    ok: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def run(engine: Engine, config_path: str | Path,
        today: dt.date | None = None, token: str | None = None) -> PipelineReport:
    today = today or dt.datetime.now(dt.UTC).date()
    token = token or os.environ.get("GITHUB_TOKEN", "")

    init_db(engine)
    sync_to_db(engine, config_path)
    specs = load_repos(config_path)

    with session_scope(engine) as s:
        ids = {(r.owner, r.name): r.id for r in s.query(Repo).all()}

    report = PipelineReport(total=len(specs))
    gh_headers = {"Authorization": f"Bearer {token}",
                  "Accept": "application/vnd.github+json"}

    # TWO clients, deliberately. httpx sends a client's default headers to every
    # host it talks to, so a single shared client would post the GitHub bearer
    # token to pypistats.org, api.npmjs.org and hub.docker.com on every daily
    # run. None of those needs authentication at all.
    with httpx.Client(headers=gh_headers, timeout=60) as gh_client, \
            httpx.Client(timeout=60) as public_client:
        for spec in specs:
            slug = f"{spec.owner}/{spec.name}"
            try:
                values: dict[str, float] = {}
                values.update(github_activity.collect(gh_client, spec.owner, spec.name,
                                                      today=today))
                values.update(github_issues.collect(gh_client, spec.owner, spec.name,
                                                    today=today))
                values.update(downloads.collect(public_client, spec, today=today))
                write_metrics(engine, ids[(spec.owner, spec.name)], today, values)
                report.ok += 1
            except Exception as exc:  # noqa: BLE001 - report, never abort
                report.failures.append((slug, f"{type(exc).__name__}: {exc}"))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily metrics")
    parser.add_argument("--config", default="config/repos.yaml")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    report = run(get_engine(args.db), args.config)
    print(f"collected {report.ok}/{report.total}")
    for slug, err in report.failures:
        print(f"  FAIL {slug}: {err}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 全量跑一次真实采集**

Run: `python -m aisel.pipeline --config config/repos.yaml`
Expected: `collected 40/40`。有 FAIL 的逐条查明原因并修复配置或采集器；**不允许带着未解释的失败进入下一任务。**

- [ ] **Step 6: 提交**

```bash
git add src/aisel/pipeline.py tests/test_pipeline.py
git commit -m "feat: daily collection pipeline with per-repo failure isolation"
```

---

## Task 7: 每日采集 workflow

**Files:**
- Create: `.github/workflows/collect.yml`
- Modify: `.gitignore`（允许提交 `data/aisel.db`）

**Interfaces:**
- Consumes: `aisel.pipeline`（Task 6）
- Produces: 每日运行后把 `data/aisel.db` 提交回仓库，供后续任务与 P1b 直接读取

> 数据库随仓库走：40 repo × 365 天 ≈ 1.5 万行、体积在数 MB 量级，提交进 git 最省事，也让每日快照天然带版本历史。P2 换 Postgres 时替换本 workflow。

- [ ] **Step 1: 改 `.gitignore`，把数据库放行**

将 `*.db` 一行替换为：
```
*.db
!data/aisel.db
```

- [ ] **Step 2: 写 `.github/workflows/collect.yml`**

```yaml
name: collect

on:
  schedule:
    - cron: "17 3 * * *"   # 03:17 UTC daily
  workflow_dispatch:

permissions:
  contents: write

jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Collect
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          AISEL_DB_URL: sqlite:///data/aisel.db
        run: |
          mkdir -p data
          python -m aisel.pipeline --config config/repos.yaml

      # `if: always()` is load-bearing, not boilerplate. The collect step exits
      # non-zero when ANY single repo fails, so without this one transient
      # failure would discard all 40 repos' data for the day — and the P0 gate
      # requires 7 consecutive days with no gaps, so that one blip would reset
      # the clock by a week. Keep the data, let the run go red.
      - name: Commit snapshot
        if: always()
        run: |
          git config user.name  "aisel-bot"
          git config user.email "aisel-bot@users.noreply.github.com"
          git add data/aisel.db
          git diff --staged --quiet || git commit -m "chore: metrics snapshot $(date -u +%F)"
          git push
```

- [ ] **Step 3: 手动触发一次并确认**

推送后到 Actions 页面点 `Run workflow`。
Expected: 绿色通过，且仓库出现一条 `chore: metrics snapshot YYYY-MM-DD` 提交。**红色就看日志修到绿，不要往下走。**

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/collect.yml .gitignore
git commit -m "ci: daily collection workflow committing db snapshot"
```

---

## Task 8: P0 关口验证

**Files:**
- Create: `scripts/gate_p0.py`
- Test: `tests/test_gate_p0.py`

**Interfaces:**
- Consumes: `aisel.models`（Task 1）
- Produces: `scripts/gate_p0.check_continuity(engine, days=7, today=None) -> list[str]`，返回违规描述列表（空 = 通过）。CLI 退出码 0 = 通过、1 = 不通过。

**关口判据（规格 §9 P0）**：连续 7 天无缺口；抽查 5 个 repo 数字与官方页面一致。

- [ ] **Step 1: 写失败的测试 `tests/test_gate_p0.py`**

```python
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily, Repo, UseCase
import gate_p0


def _seed(engine, n_repos=2):
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        for i in range(1, n_repos + 1):
            s.add(Repo(id=i, owner="o", name=f"n{i}", use_case_id="u",
                       pypi_package=None, npm_package=None,
                       dockerhub_repo=None, is_top=False))


def _fill(engine, repo_id, dates):
    with session_scope(engine) as s:
        for d in dates:
            s.add(MetricDaily(repo_id=repo_id, date=d,
                              metric="stars_total", value=1.0))


def test_full_coverage_passes(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    today = dt.date(2026, 8, 9)
    days = [today - dt.timedelta(days=i) for i in range(1, 8)]
    _fill(engine, 1, days)
    _fill(engine, 2, days)

    assert gate_p0.check_continuity(engine, days=7, today=today) == []


def test_missing_day_is_reported_with_repo_and_date(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    today = dt.date(2026, 8, 9)
    days = [today - dt.timedelta(days=i) for i in range(1, 8)]
    _fill(engine, 1, days)
    _fill(engine, 2, [d for d in days if d != dt.date(2026, 8, 5)])

    problems = gate_p0.check_continuity(engine, days=7, today=today)
    assert len(problems) == 1
    assert "o/n2" in problems[0] and "2026-08-05" in problems[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_gate_p0.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate_p0'`

- [ ] **Step 3: 写 `scripts/gate_p0.py`**

```python
"""P0 gate: every repo must have at least one metric on each of the last N days."""
from __future__ import annotations

import argparse
import datetime as dt

from sqlalchemy import Engine

from aisel.db import get_engine, session_scope
from aisel.models import MetricDaily, Repo


def check_continuity(engine: Engine, days: int = 7,
                     today: dt.date | None = None) -> list[str]:
    today = today or dt.datetime.now(dt.UTC).date()
    expected = {today - dt.timedelta(days=i) for i in range(1, days + 1)}

    problems: list[str] = []
    with session_scope(engine) as s:
        for repo in s.query(Repo).order_by(Repo.owner, Repo.name).all():
            have = {d for (d,) in s.query(MetricDaily.date)
                    .filter(MetricDaily.repo_id == repo.id).distinct()}
            for missing in sorted(expected - have):
                problems.append(f"{repo.owner}/{repo.name} missing {missing}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 gate check")
    parser.add_argument("--db", default=None)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    problems = check_continuity(get_engine(args.db), days=args.days)
    if problems:
        print(f"GATE P0 FAILED — {len(problems)} gap(s):")
        for p in problems[:50]:
            print("  " + p)
        return 1
    print("GATE P0 PASSED — no gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_gate_p0.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 提交，然后等 7 天**

```bash
git add scripts/gate_p0.py tests/test_gate_p0.py
git commit -m "feat: p0 gate continuity check"
```

采集 workflow 连跑 7 天后执行：
```bash
AISEL_DB_URL=sqlite:///data/aisel.db python scripts/gate_p0.py --days 7
```
Expected: `GATE P0 PASSED — no gaps`

- [ ] **Step 6: 人工对账 5 个 repo**

随机抽 5 个 repo，把库里最新一天的 `stars_total`、`downloads_pypi_30d`（或 npm/docker）与官方页面显示值对照：

```bash
AISEL_DB_URL=sqlite:///data/aisel.db python -c "
import datetime as dt
from aisel.db import get_engine, session_scope
from aisel.models import MetricDaily, Repo
e=get_engine()
with session_scope(e) as s:
    latest = s.query(MetricDaily.date).order_by(MetricDaily.date.desc()).first()[0]
    for r in s.query(Repo).limit(5):
        vals={m.metric:m.value for m in s.query(MetricDaily).filter_by(repo_id=r.id, date=latest)}
        print(r.owner+'/'+r.name, {k:v for k,v in vals.items() if k in
              ('stars_total','downloads_pypi_30d','downloads_npm_30d','dockerhub_pulls_total')})
"
```
**5 个全部相符才算 P0 通过。任一不符 → 定位采集器 bug 并修复，重跑本步。**

---

## Task 9: quickstart 清单

**Files:**
- Create: `config/quickstarts.yaml`, `src/aisel/sandbox/__init__.py`, `src/aisel/sandbox/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `aisel.config.RepoSpec`（Task 2）
- Produces: `aisel.sandbox.manifest.load(path) -> dict[str, Quickstart]`（键为 slug）；`Quickstart` dataclass 字段 `slug: str`、`image: str`、`setup: list[str]`、`smoke: str`、`needs_api_key: bool`、`timeout_s: int`
- `aisel.sandbox.manifest.validate_covers_top(quickstarts, specs) -> list[str]` 返回缺失的 Top-20 slug

> `smoke` 是从该 repo README 的 quickstart 段落抄下来的**最小可运行片段**，不是自创示例。填写时必须打开 README 逐条核对；`needs_api_key: true` 表示该 quickstart 依赖外部 LLM key，实跑时走 mock 端点（见 Task 10）。

- [ ] **Step 1: 写失败的测试 `tests/test_manifest.py`**

```python
import pytest

from aisel.config import RepoSpec
from aisel.sandbox.manifest import Quickstart, load, validate_covers_top

YAML = """
quickstarts:
  - slug: langchain-ai/langgraph
    image: python:3.12-slim
    setup:
      - pip install langgraph
    smoke: |
      python -c "from langgraph.graph import StateGraph; print('ok')"
    needs_api_key: false
    timeout_s: 600
"""


def test_load_parses_quickstart(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(YAML, encoding="utf-8")
    qs = load(p)
    q = qs["langchain-ai/langgraph"]
    assert isinstance(q, Quickstart)
    assert q.image == "python:3.12-slim"
    assert q.setup == ["pip install langgraph"]
    assert "StateGraph" in q.smoke
    assert q.timeout_s == 600


def test_missing_top_repo_is_reported(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(YAML, encoding="utf-8")
    qs = load(p)
    specs = [
        RepoSpec("langchain-ai", "langgraph", "u", None, None, None, True),
        RepoSpec("crewAIInc", "crewAI", "u", None, None, None, True),
        RepoSpec("some", "nontop", "u", None, None, None, False),
    ]
    assert validate_covers_top(qs, specs) == ["crewAIInc/crewAI"]


def test_timeout_must_be_positive(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(YAML.replace("timeout_s: 600", "timeout_s: 0"), encoding="utf-8")
    with pytest.raises(ValueError, match="timeout_s must be > 0"):
        load(p)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `src/aisel/sandbox/manifest.py`**

```python
"""Quickstart definitions — copied from each repo's README, never invented."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from aisel.config import RepoSpec


@dataclass(frozen=True)
class Quickstart:
    slug: str
    image: str
    setup: list[str]
    smoke: str
    needs_api_key: bool
    timeout_s: int


def load(path: str | Path) -> dict[str, Quickstart]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, Quickstart] = {}
    for entry in raw.get("quickstarts", []):
        timeout = int(entry.get("timeout_s", 600))
        if timeout <= 0:
            raise ValueError(f"timeout_s must be > 0 for {entry['slug']}")
        out[entry["slug"]] = Quickstart(
            slug=entry["slug"],
            image=entry["image"],
            setup=list(entry.get("setup", [])),
            smoke=entry["smoke"],
            needs_api_key=bool(entry.get("needs_api_key", False)),
            timeout_s=timeout,
        )
    return out


def validate_covers_top(quickstarts: dict[str, Quickstart],
                        specs: list[RepoSpec]) -> list[str]:
    tops = [f"{s.owner}/{s.name}" for s in specs if s.is_top]
    return [slug for slug in tops if slug not in quickstarts]
```

`src/aisel/sandbox/__init__.py` 内容为空。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 逐个 repo 填写 `config/quickstarts.yaml`**

对 Top 20 的每一个：打开其 GitHub README，找到 quickstart / getting-started 段落，抄出**最小安装命令与最小可运行片段**。禁止凭印象写。README 里没有可运行 quickstart 的，`smoke` 留空字符串并加注释 `# README has no runnable quickstart` —— 这本身就是一条判优信号，由 Task 10 记为 `doc_missing`。

- [ ] **Step 6: 校验覆盖 Top 20**

Run:
```bash
python -c "
from aisel.config import load_repos
from aisel.sandbox.manifest import load, validate_covers_top
missing = validate_covers_top(load('config/quickstarts.yaml'), load_repos('config/repos.yaml'))
print('missing:', missing); assert not missing
"
```
Expected: `missing: []`

- [ ] **Step 7: 提交**

```bash
git add config/quickstarts.yaml src/aisel/sandbox tests/test_manifest.py
git commit -m "feat: quickstart manifests for top 20 repos"
```

---

## Task 10: quickstart 执行器与失败分类

**Files:**
- Create: `src/aisel/sandbox/classify.py`, `src/aisel/sandbox/runner.py`
- Test: `tests/test_classify.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `aisel.sandbox.manifest.Quickstart`（Task 9）、`aisel.models.QuickstartRun`（Task 1）
- Produces:
  - `aisel.sandbox.classify.classify(exit_code: int, log: str, timed_out: bool) -> str | None` — 返回 `None`（成功）或 `install_error` / `missing_api_key` / `import_error` / `runtime_error` / `timeout` / `doc_missing` 之一
  - `aisel.sandbox.runner.run_one(quickstart, docker=subprocess_runner) -> RunResult`（dataclass：`status`、`failure_class`、`log_tail`）
  - `aisel.sandbox.runner.run_all(engine, quickstarts, specs, commit_shas) -> list[RunResult]`（写入 `runs` 表）

**规格 §9 P1a 关口**：20 条全部有明确结果，**不许有"未知"**——因此 `classify` 对任何非零退出都必须返回一个具体分类，兜底为 `runtime_error`。

- [ ] **Step 1: 写失败的测试 `tests/test_classify.py`**

```python
import pytest

from aisel.sandbox.classify import classify


def test_success_returns_none():
    assert classify(0, "ok\n", timed_out=False) is None


def test_timeout_wins_over_exit_code():
    assert classify(137, "anything", timed_out=True) == "timeout"


@pytest.mark.parametrize("log,expected", [
    ("ERROR: Could not find a version that satisfies the requirement foo", "install_error"),
    ("ERROR: pip's dependency resolver does not currently take", "install_error"),
    ("openai.AuthenticationError: No API key provided", "missing_api_key"),
    ("ValueError: OPENAI_API_KEY environment variable is not set", "missing_api_key"),
    ("ModuleNotFoundError: No module named 'langgraph.graph'", "import_error"),
    ("ImportError: cannot import name 'StateGraph'", "import_error"),
    ("Traceback ...\nTypeError: unsupported operand", "runtime_error"),
])
def test_log_patterns_map_to_classes(log, expected):
    assert classify(1, log, timed_out=False) == expected


def test_empty_smoke_is_doc_missing():
    assert classify(0, "", timed_out=False, smoke="") == "doc_missing"


def test_unrecognised_failure_falls_back_to_runtime_error():
    """No 'unknown' bucket is allowed — the P1a gate forbids it."""
    assert classify(1, "something entirely novel", timed_out=False) == "runtime_error"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `src/aisel/sandbox/classify.py`**

```python
"""Map a quickstart run outcome to exactly one failure class.

There is deliberately no 'unknown' bucket: the P1a gate requires every one of
the 20 runs to carry a definite result.
"""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("missing_api_key", re.compile(
        r"(api[_ ]?key|AuthenticationError|OPENAI_API_KEY|ANTHROPIC_API_KEY)",
        re.IGNORECASE)),
    ("install_error", re.compile(
        r"(Could not find a version|No matching distribution|"
        r"dependency resolver|pip install failed|npm ERR!|"
        r"error: subprocess-exited-with-error)", re.IGNORECASE)),
    ("import_error", re.compile(
        r"(ModuleNotFoundError|ImportError)")),
]

FALLBACK = "runtime_error"


def classify(exit_code: int, log: str, timed_out: bool,
             smoke: str | None = None) -> str | None:
    if smoke is not None and not smoke.strip():
        return "doc_missing"
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return None
    for name, pattern in PATTERNS:
        if pattern.search(log):
            return name
    return FALLBACK
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_classify.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 写失败的测试 `tests/test_runner.py`**

```python
import datetime as dt

from aisel.config import RepoSpec
from aisel.db import get_engine, init_db, session_scope
from aisel.models import QuickstartRun, Repo, UseCase
from aisel.sandbox.manifest import Quickstart
from aisel.sandbox.runner import RunResult, run_all, run_one

Q_OK = Quickstart("o/n", "python:3.12-slim", ["pip install x"],
                  "python -c \"print('ok')\"", False, 60)
Q_EMPTY = Quickstart("o/m", "python:3.12-slim", [], "", False, 60)


def test_run_one_success():
    def fake_docker(image, script, timeout_s):
        return 0, "ok\n", False
    r = run_one(Q_OK, docker=fake_docker)
    assert r == RunResult(slug="o/n", status="pass", failure_class=None, log_tail="ok\n")


def test_run_one_classifies_failure():
    def fake_docker(image, script, timeout_s):
        return 1, "ModuleNotFoundError: No module named 'x'", False
    r = run_one(Q_OK, docker=fake_docker)
    assert r.status == "fail"
    assert r.failure_class == "import_error"


def test_run_one_marks_empty_smoke_as_doc_missing_without_running():
    calls = []

    def fake_docker(image, script, timeout_s):
        calls.append(script)
        return 0, "", False

    r = run_one(Q_EMPTY, docker=fake_docker)
    assert r.status == "fail"
    assert r.failure_class == "doc_missing"
    assert calls == []  # never launched


def test_run_all_persists_one_row_per_quickstart(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        s.add(Repo(id=1, owner="o", name="n", use_case_id="u",
                   pypi_package=None, npm_package=None,
                   dockerhub_repo=None, is_top=True))

    specs = [RepoSpec("o", "n", "u", None, None, None, True)]
    results = run_all(engine, {"o/n": Q_OK}, specs,
                      commit_shas={"o/n": "abc123"},
                      docker=lambda i, s_, t: (0, "ok\n", False),
                      now=dt.datetime(2026, 8, 9, 12, 0, 0))

    assert [r.status for r in results] == ["pass"]
    with session_scope(engine) as s:
        row = s.query(QuickstartRun).one()
        assert row.repo_id == 1
        assert row.status == "pass"
        assert row.repo_commit == "abc123"
```

- [ ] **Step 6: 跑测试确认失败**

Run: `python -m pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.sandbox.runner'`

- [ ] **Step 7: 写 `src/aisel/sandbox/runner.py`**

```python
"""Execute quickstarts in Docker and persist the outcome.

The docker call is injected so the whole module is testable without a daemon —
required, because the dev machine has no Docker (see Global Constraints).
"""
from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import Engine

from aisel.config import RepoSpec
from aisel.db import session_scope
from aisel.models import QuickstartRun, Repo
from aisel.sandbox.classify import classify
from aisel.sandbox.manifest import Quickstart

LOG_TAIL_CHARS = 4000

DockerRunner = Callable[[str, str, int], tuple[int, str, bool]]


@dataclass(frozen=True)
class RunResult:
    slug: str
    status: str                 # pass | fail
    failure_class: str | None
    log_tail: str


def subprocess_runner(image: str, script: str, timeout_s: int) -> tuple[int, str, bool]:
    """Run `script` inside `image`. Returns (exit_code, combined_log, timed_out)."""
    cmd = ["docker", "run", "--rm", "--network", "bridge",
           "--memory", "4g", "--cpus", "2", image, "bash", "-lc", script]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + (exc.stderr or ""), True
    return proc.returncode, proc.stdout + proc.stderr, False


def run_one(q: Quickstart, docker: DockerRunner = subprocess_runner) -> RunResult:
    if not q.smoke.strip():
        return RunResult(q.slug, "fail", "doc_missing", "")

    script = "set -e\n" + "\n".join(q.setup) + "\n" + q.smoke
    exit_code, log, timed_out = docker(q.image, script, q.timeout_s)
    failure = classify(exit_code, log, timed_out, smoke=q.smoke)
    tail = log[-LOG_TAIL_CHARS:]
    return RunResult(q.slug, "pass" if failure is None else "fail", failure, tail)


def run_all(engine: Engine, quickstarts: dict[str, Quickstart],
            specs: list[RepoSpec], commit_shas: dict[str, str],
            docker: DockerRunner = subprocess_runner,
            now: dt.datetime | None = None) -> list[RunResult]:
    now = now or dt.datetime.now(dt.UTC).replace(tzinfo=None)

    with session_scope(engine) as s:
        ids = {f"{r.owner}/{r.name}": r.id for r in s.query(Repo).all()}

    results: list[RunResult] = []
    for spec in specs:
        slug = f"{spec.owner}/{spec.name}"
        if not spec.is_top or slug not in quickstarts:
            continue
        result = run_one(quickstarts[slug], docker=docker)
        results.append(result)
        with session_scope(engine) as s:
            s.add(QuickstartRun(
                repo_id=ids[slug], run_at=now, status=result.status,
                failure_class=result.failure_class, log_tail=result.log_tail,
                repo_commit=commit_shas.get(slug, ""),
            ))
    return results
```

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/test_runner.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 9: 提交**

```bash
git add src/aisel/sandbox/classify.py src/aisel/sandbox/runner.py tests/test_classify.py tests/test_runner.py
git commit -m "feat: quickstart runner with exhaustive failure classification"
```

---

## Task 11: 沙箱 workflow 与 P1a 关口

**Files:**
- Create: `.github/workflows/quickstart.yml`, `scripts/run_quickstarts.py`, `scripts/gate_p1a.py`
- Test: `tests/test_gate_p1a.py`

**Interfaces:**
- Consumes: `aisel.sandbox.runner`（Task 10）
- Produces: `scripts/gate_p1a.check(engine) -> list[str]` — 检查 20 个 Top repo 每个都有一条最新 `runs` 记录，且 `status=="fail"` 时 `failure_class` 非空

> `needs_api_key: true` 的 quickstart：workflow 注入 `OPENAI_API_KEY=sk-mock` 并把 `OPENAI_BASE_URL` 指向本地 mock。**MVP 不接真实 LLM key**——真实 key 会让"跑得通"混入配额与网络因素，测的就不是 repo 本身。这类 repo 若因此失败，分类为 `missing_api_key`，页面上如实展示为"需要外部 API key 才能跑通"。

- [ ] **Step 1: 写 `scripts/run_quickstarts.py`**

```python
"""Entry point for the quickstart workflow."""
from __future__ import annotations

import argparse
import os

import httpx

from aisel.collectors.base import request_json
from aisel.config import load_repos
from aisel.db import get_engine, init_db
from aisel.sandbox.manifest import load as load_quickstarts, validate_covers_top
from aisel.sandbox.runner import run_all


def head_shas(specs) -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    out: dict[str, str] = {}
    with httpx.Client(headers=headers, timeout=30) as c:
        for spec in specs:
            if not spec.is_top:
                continue
            slug = f"{spec.owner}/{spec.name}"
            data = request_json(c, "GET",
                                f"https://api.github.com/repos/{slug}/commits",
                                params={"per_page": 1})
            out[slug] = data[0]["sha"] if data else ""
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/repos.yaml")
    parser.add_argument("--quickstarts", default="config/quickstarts.yaml")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    specs = load_repos(args.config)
    quickstarts = load_quickstarts(args.quickstarts)
    missing = validate_covers_top(quickstarts, specs)
    if missing:
        print("missing quickstarts for:", missing)
        return 1

    engine = get_engine(args.db)
    init_db(engine)
    results = run_all(engine, quickstarts, specs, head_shas(specs))

    for r in results:
        print(f"{r.status:4}  {r.slug}  {r.failure_class or ''}")
    print(f"{sum(r.status == 'pass' for r in results)}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 写失败的测试 `tests/test_gate_p1a.py`**

```python
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aisel.db import get_engine, init_db, session_scope
from aisel.models import QuickstartRun, Repo, UseCase
import gate_p1a


def _seed(engine, n_top=2):
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        for i in range(1, n_top + 1):
            s.add(Repo(id=i, owner="o", name=f"n{i}", use_case_id="u",
                       pypi_package=None, npm_package=None,
                       dockerhub_repo=None, is_top=True))


def test_all_top_repos_with_definite_results_pass(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    now = dt.datetime(2026, 8, 9, 0, 0)
    with session_scope(engine) as s:
        s.add(QuickstartRun(repo_id=1, run_at=now, status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))
        s.add(QuickstartRun(repo_id=2, run_at=now, status="fail",
                            failure_class="install_error", log_tail="", repo_commit="b"))

    assert gate_p1a.check(engine) == []


def test_missing_run_is_reported(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    with session_scope(engine) as s:
        s.add(QuickstartRun(repo_id=1, run_at=dt.datetime(2026, 8, 9), status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))

    problems = gate_p1a.check(engine)
    assert len(problems) == 1 and "o/n2" in problems[0]


def test_fail_without_a_class_is_reported(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    _seed(engine)
    now = dt.datetime(2026, 8, 9)
    with session_scope(engine) as s:
        s.add(QuickstartRun(repo_id=1, run_at=now, status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))
        s.add(QuickstartRun(repo_id=2, run_at=now, status="fail",
                            failure_class=None, log_tail="", repo_commit="b"))

    problems = gate_p1a.check(engine)
    assert len(problems) == 1 and "no failure_class" in problems[0]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_gate_p1a.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate_p1a'`

- [ ] **Step 4: 写 `scripts/gate_p1a.py`**

```python
"""P1a gate: every Top-20 repo has a latest run, and every failure is classified."""
from __future__ import annotations

import argparse

from sqlalchemy import Engine

from aisel.db import get_engine, session_scope
from aisel.models import QuickstartRun, Repo


def check(engine: Engine) -> list[str]:
    problems: list[str] = []
    with session_scope(engine) as s:
        for repo in (s.query(Repo).filter(Repo.is_top.is_(True))
                      .order_by(Repo.owner, Repo.name).all()):
            latest = (s.query(QuickstartRun)
                       .filter(QuickstartRun.repo_id == repo.id)
                       .order_by(QuickstartRun.run_at.desc())
                       .first())
            slug = f"{repo.owner}/{repo.name}"
            if latest is None:
                problems.append(f"{slug}: no quickstart run recorded")
            elif latest.status == "fail" and not latest.failure_class:
                problems.append(f"{slug}: failed with no failure_class")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="P1a gate check")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    problems = check(get_engine(args.db))
    if problems:
        print(f"GATE P1a FAILED — {len(problems)} problem(s):")
        for p in problems:
            print("  " + p)
        return 1
    print("GATE P1a PASSED — all top repos have a definite result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_gate_p1a.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 6: 写 `.github/workflows/quickstart.yml`**

```yaml
name: quickstart

on:
  schedule:
    - cron: "40 4 * * 1"   # Mondays 04:40 UTC
  workflow_dispatch:

permissions:
  contents: write

jobs:
  quickstart:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Run quickstarts
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          AISEL_DB_URL: sqlite:///data/aisel.db
          OPENAI_API_KEY: sk-mock-not-a-real-key
        run: python scripts/run_quickstarts.py

      - name: Gate P1a
        env:
          AISEL_DB_URL: sqlite:///data/aisel.db
        run: python scripts/gate_p1a.py

      - name: Commit results
        if: always()
        run: |
          git config user.name  "aisel-bot"
          git config user.email "aisel-bot@users.noreply.github.com"
          git add data/aisel.db
          git diff --staged --quiet || git commit -m "chore: quickstart runs $(date -u +%F)"
          git push
```

- [ ] **Step 7: 手动触发并达成关口**

到 Actions 点 `Run workflow`。
Expected: `Gate P1a` 步骤输出 `GATE P1a PASSED — all top repos have a definite result`。
未通过时逐条修：缺 run → 补 `quickstarts.yaml`；`no failure_class` → 补 `classify.py` 的模式（但**兜底已保证不会出现**，若出现说明 classify 被绕过，查 runner）。

- [ ] **Step 8: 提交**

```bash
git add .github/workflows/quickstart.yml scripts/run_quickstarts.py scripts/gate_p1a.py tests/test_gate_p1a.py
git commit -m "ci: weekly quickstart runs with p1a gate"
```

---

## Task 12: 四轴评级与阈值标定

**Files:**
- Create: `src/aisel/scoring/__init__.py`, `src/aisel/scoring/axes.py`, `scripts/calibrate.py`
- Test: `tests/test_axes.py`

**Interfaces:**
- Consumes: `aisel.models.MetricDaily` / `QuickstartRun`（Task 1）
- Produces:
  - `aisel.scoring.axes.THRESHOLDS: dict[str, dict[str, float]] | None` — 各轴分级阈值，**初值必须是 `None`**，由 Task 12 Step 5 的标定结果填入。未标定时 `rate_all` 抛 `RuntimeError` 而不是静默出错
  - `aisel.scoring.axes.latest_metrics(engine, repo_id) -> dict[str, float]`
  - `aisel.scoring.axes.rate_all(metrics: dict[str, float], run_status: str | None) -> dict[str, str]` — 返回 `{"adoption": "strong|moderate|weak|unknown", "alive": ..., "responsive": ..., "runnable": "pass|fail|unknown"}`

> **阈值不能凭空写。** Step 5 先在真实数据上跑 `calibrate.py` 打印分布，用四分位数定档，再把数字写进 `THRESHOLDS`。测试里用注入的阈值，不依赖最终数值。

- [ ] **Step 1: 写失败的测试 `tests/test_axes.py`**

```python
import pytest

from aisel.scoring.axes import rate_all, rate_axis

TH = {
    "adoption_pypi":          {"strong": 100000.0, "moderate": 10000.0},
    "adoption_npm":           {"strong": 500000.0, "moderate": 50000.0},
    "adoption_docker":        {"strong": 1000000.0, "moderate": 100000.0},  # cumulative
    "alive_release":          {"strong": 30.0, "moderate": 120.0},  # days, lower better
    "alive_commits":          {"strong": 50.0, "moderate": 10.0},   # commits/90d, higher
    "alive_bus":              {"strong": 5.0, "moderate": 2.0},     # contributors, higher
    "responsive_latency":     {"strong": 24.0, "moderate": 168.0},  # hours, lower better
    "responsive_close_ratio": {"strong": 0.6, "moderate": 0.25},    # closed/opened, higher
}


def test_adoption_takes_the_strongest_channel_not_the_weakest():
    """Asymmetric with `alive` on purpose: alive is about failure modes, so any
    dead vital sign disqualifies; adoption is about evidence of use, and being
    huge on one channel is not diluted by being small on another."""
    m = {"downloads_pypi_30d": 5000.0,      # weak on its own band
         "downloads_npm_30d": 900000.0}     # strong on its own band
    assert rate_all(m, run_status=None, thresholds=TH)["adoption"] == "strong"


def test_each_channel_is_judged_against_its_own_band():
    """500k npm downloads is 'strong'; the same number of pypi downloads would
    also be strong — but the bands differ, so a shared band would misjudge one
    of them. Docker is cumulative and needs its own band most of all."""
    npm_only = {"downloads_npm_30d": 60000.0}    # above npm moderate, below strong
    pypi_only = {"downloads_pypi_30d": 60000.0}  # same number, pypi band -> moderate
    assert rate_all(npm_only, run_status=None, thresholds=TH)["adoption"] == "moderate"
    assert rate_all(pypi_only, run_status=None, thresholds=TH)["adoption"] == "moderate"


def test_docker_only_repos_still_get_an_adoption_rating():
    """Measured 2026-08-09: 8 of 40 roster repos publish only a Docker image,
    including nearly the whole vector-db stage. Ignoring the channel would leave
    that stage page with no primary pick at all."""
    m = {"dockerhub_pulls_total": 4200000.0}
    assert rate_all(m, run_status=None, thresholds=TH)["adoption"] == "strong"


def test_adoption_unknown_when_no_download_signal_exists():
    m = {"stars_total": 50000.0, "forks_total": 9000.0}
    assert rate_all(m, run_status=None, thresholds=TH)["adoption"] == "unknown"


def test_alive_is_weak_when_release_is_ancient():
    m = {"days_since_last_release": 400.0, "commits_90d": 0.0}
    assert rate_all(m, run_status=None, thresholds=TH)["alive"] == "weak"


def test_alive_takes_the_worst_vital_sign_not_the_best():
    """Spec §4.2: alive has three vital signs. A fresh release with almost no
    commits and a single maintainer is a release bot, not a healthy project —
    taking the best or the average would hide exactly that."""
    m = {"days_since_last_release": 5.0,   # strong
         "commits_90d": 2.0,               # weak
         "contributors_90d": 1.0}          # weak
    assert rate_all(m, run_status=None, thresholds=TH)["alive"] == "weak"


def test_alive_uses_only_the_vital_signs_that_are_present():
    m = {"days_since_last_release": 5.0}
    assert rate_all(m, run_status=None, thresholds=TH)["alive"] == "strong"


def test_alive_unknown_when_no_vital_sign_present():
    assert rate_all({}, run_status=None, thresholds=TH)["alive"] == "unknown"


def test_responsive_unknown_when_sentinel_no_sample():
    m = {"issue_first_response_p50_hours": -1.0}
    assert rate_all(m, run_status=None, thresholds=TH)["responsive"] == "unknown"


def test_fast_replies_cannot_hide_a_repo_that_never_closes_anything():
    """The failure this axis exists to catch: answers within the hour, but
    almost nothing ever gets resolved."""
    m = {"issue_first_response_p50_hours": 1.0,   # strong
         "issues_opened_90d": 200.0,
         "issues_closed_90d": 10.0}               # ratio 0.05 -> weak
    assert rate_all(m, run_status=None, thresholds=TH)["responsive"] == "weak"


def test_close_ratio_alone_rates_responsiveness_when_latency_has_no_sample():
    m = {"issue_first_response_p50_hours": -1.0,
         "issues_opened_90d": 100.0,
         "issues_closed_90d": 80.0}               # ratio 0.8 -> strong
    assert rate_all(m, run_status=None, thresholds=TH)["responsive"] == "strong"


def test_zero_opened_issues_contributes_no_close_ratio_band():
    """Dividing by zero opened issues is not a 0% close rate — it is no data."""
    m = {"issues_opened_90d": 0.0, "issues_closed_90d": 0.0}
    assert rate_all(m, run_status=None, thresholds=TH)["responsive"] == "unknown"


def test_runnable_mirrors_run_status():
    assert rate_all({}, run_status="pass", thresholds=TH)["runnable"] == "pass"
    assert rate_all({}, run_status=None, thresholds=TH)["runnable"] == "unknown"


def test_uncalibrated_thresholds_raise_instead_of_silently_misrating(monkeypatch):
    """Placeholder thresholds would rate every repo wrong and no test would see it."""
    import aisel.scoring.axes as axes_mod
    monkeypatch.setattr(axes_mod, "THRESHOLDS", None)
    with pytest.raises(RuntimeError, match="not calibrated"):
        rate_all({"downloads_pypi_30d": 1.0}, run_status="pass")


@pytest.mark.parametrize("value,lower_better,expected", [
    (200000.0, False, "strong"),
    (50000.0, False, "moderate"),
    (10.0, False, "weak"),
    (10.0, True, "strong"),
    (100.0, True, "moderate"),
    (900.0, True, "weak"),
])
def test_rate_axis_direction(value, lower_better, expected):
    band = {"strong": 100000.0, "moderate": 10000.0} if not lower_better \
        else {"strong": 30.0, "moderate": 120.0}
    assert rate_axis(value, band, lower_better=lower_better) == expected
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_axes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.scoring'`

- [ ] **Step 3: 写 `src/aisel/scoring/axes.py`**

```python
"""Raw metrics -> four independent axis ratings. No composite score, by design
(see spec §4.2): summing incommensurable quantities produces a number nobody
can trust or argue with.
"""
from __future__ import annotations

from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import MetricDaily, QuickstartRun

UNKNOWN = "unknown"
NO_SAMPLE = -1.0

# Calibrated against real data by scripts/calibrate.py (Task 12 Step 5).
# Deliberately None until then: placeholder zeros would silently rate every repo
# "strong" on higher-is-better axes and "weak" on lower-is-better ones, and the
# injected-threshold tests would never catch it. Fail loudly instead.
THRESHOLDS: dict[str, dict[str, float]] | None = None

# (metric, threshold band) per distribution channel. Each channel is banded
# separately because the units are not comparable: pypi/npm are 30-day install
# counts, dockerhub_pulls_total is cumulative since the image first existed.
# A band therefore means "high relative to peers on the same channel", which is
# a fair comparison; a shared band would not be.
DOWNLOAD_CHANNELS = (
    ("downloads_pypi_30d", "adoption_pypi"),
    ("downloads_npm_30d", "adoption_npm"),
    ("dockerhub_pulls_total", "adoption_docker"),
)

# Canonical band ordering. Task 14's verdict ranking imports this rather than
# defining its own copy — two orderings that could drift apart is a bug waiting.
BAND_RANK = {"unknown": 0, "weak": 1, "moderate": 2, "strong": 3}


def _worst(bands: list[str]) -> str:
    """A project is only as alive as its weakest vital sign.

    Recent releases with no commits and a single maintainer is a release bot,
    not a healthy project — averaging would hide exactly that.
    """
    present = [b for b in bands if b != UNKNOWN]
    if not present:
        return UNKNOWN
    return min(present, key=lambda b: BAND_RANK[b])


def _best(bands: list[str]) -> str:
    """Adoption takes the strongest channel, unlike `alive` which takes the
    weakest. The asymmetry is deliberate: `alive` is about failure modes, so any
    dead vital sign disqualifies; adoption is about evidence of use, and a
    library that is huge on PyPI is not less adopted for shipping no image.
    """
    present = [b for b in bands if b != UNKNOWN]
    if not present:
        return UNKNOWN
    return max(present, key=lambda b: BAND_RANK[b])


def rate_axis(value: float, band: dict[str, float], lower_better: bool) -> str:
    if lower_better:
        if value <= band["strong"]:
            return "strong"
        if value <= band["moderate"]:
            return "moderate"
        return "weak"
    if value >= band["strong"]:
        return "strong"
    if value >= band["moderate"]:
        return "moderate"
    return "weak"


def latest_metrics(engine: Engine, repo_id: int) -> dict[str, float]:
    with session_scope(engine) as s:
        latest_date = (s.query(MetricDaily.date)
                        .filter(MetricDaily.repo_id == repo_id)
                        .order_by(MetricDaily.date.desc()).first())
        if latest_date is None:
            return {}
        rows = (s.query(MetricDaily)
                 .filter(MetricDaily.repo_id == repo_id,
                         MetricDaily.date == latest_date[0]).all())
        return {r.metric: r.value for r in rows}


def latest_run_status(engine: Engine, repo_id: int) -> str | None:
    with session_scope(engine) as s:
        run = (s.query(QuickstartRun)
                .filter(QuickstartRun.repo_id == repo_id)
                .order_by(QuickstartRun.run_at.desc()).first())
        return run.status if run else None


def rate_all(metrics: dict[str, float], run_status: str | None,
             thresholds: dict[str, dict[str, float]] | None = None) -> dict[str, str]:
    th = thresholds if thresholds is not None else THRESHOLDS
    if th is None:
        raise RuntimeError(
            "axis thresholds are not calibrated — run scripts/calibrate.py and "
            "set THRESHOLDS in aisel/scoring/axes.py (plan Task 12 Step 5)")

    # Measured 2026-08-09: 8 of the 40 roster repos publish ONLY a Docker image —
    # pgvector, qdrant, milvus, weaviate and typesense among them, i.e. nearly the
    # entire vector-db stage. Banding only pypi/npm would leave that stage page
    # with no measurable adoption at all and therefore no primary pick.
    adoption = _best([
        rate_axis(metrics[metric], th[band], lower_better=False)
        for metric, band in DOWNLOAD_CHANNELS if metric in metrics
    ])

    # Spec §4.2: the "alive" axis has three vital signs, not one.
    alive_parts: list[str] = []
    if "days_since_last_release" in metrics:
        alive_parts.append(rate_axis(metrics["days_since_last_release"],
                                     th["alive_release"], lower_better=True))
    if "commits_90d" in metrics:
        alive_parts.append(rate_axis(metrics["commits_90d"],
                                     th["alive_commits"], lower_better=False))
    if "contributors_90d" in metrics:
        alive_parts.append(rate_axis(metrics["contributors_90d"],
                                     th["alive_bus"], lower_better=False))
    alive = _worst(alive_parts)

    # Spec §4.2: responsiveness is speed AND whether issues actually get closed.
    # Median latency alone rates a repo "strong" when it answers 20% of issues
    # within the hour and ignores the other 80% — measured on langgraph
    # 2026-08-09: 180 issues opened in 90 days, 36 of them never answered.
    #
    # Deliberate deviation: the spec's third signal, absolute unresolved-issue
    # growth, is not used. It is scale-dependent — 1000 opened/900 closed and
    # 10 opened/9 closed are equally healthy but score +100 vs +1 — so it would
    # systematically penalise high-traffic projects. The close ratio carries the
    # same information scale-invariantly.
    responsive_parts: list[str] = []
    latency = metrics.get("issue_first_response_p50_hours", NO_SAMPLE)
    if latency != NO_SAMPLE:
        responsive_parts.append(rate_axis(latency, th["responsive_latency"],
                                          lower_better=True))
    opened = metrics.get("issues_opened_90d", 0.0)
    if opened > 0:
        ratio = metrics.get("issues_closed_90d", 0.0) / opened
        responsive_parts.append(rate_axis(ratio, th["responsive_close_ratio"],
                                          lower_better=False))
    responsive = _worst(responsive_parts)

    return {
        "adoption": adoption,
        "alive": alive,
        "responsive": responsive,
        "runnable": run_status or UNKNOWN,
    }
```

`src/aisel/scoring/__init__.py` 内容为空。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_axes.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 写 `scripts/calibrate.py` 并用真实数据定阈值**

```python
"""Print the real distribution of each axis metric so thresholds are chosen
from data, not from imagination."""
from __future__ import annotations

import argparse
import statistics

from aisel.collectors.github_activity import NEVER_RELEASED
from aisel.db import get_engine, session_scope
from aisel.models import Repo
from aisel.scoring.axes import NO_SAMPLE, latest_metrics

# Sentinels mean "no measurement", not "a very large/small measurement".
# Feeding 9999.0 into a quantile would drag p75 to nonsense and silently
# produce thresholds nobody could defend.
SENTINELS = {NO_SAMPLE, NEVER_RELEASED}

AXES = {
    "adoption_pypi      (downloads_pypi_30d, higher better)": ("downloads_pypi_30d",),
    "adoption_npm       (downloads_npm_30d, higher better)": ("downloads_npm_30d",),
    "adoption_docker    (dockerhub_pulls_total, CUMULATIVE, higher better)":
        ("dockerhub_pulls_total",),
    "alive_release      (days_since_last_release, lower better)":
        ("days_since_last_release",),
    "alive_commits      (commits_90d, higher better)": ("commits_90d",),
    "alive_bus          (contributors_90d, higher better)": ("contributors_90d",),
    "responsive_latency (issue_first_response_p50_hours, lower better)":
        ("issue_first_response_p50_hours",),
}


def _close_ratio(m: dict[str, float]) -> float | None:
    """Zero opened issues is no data, not a 0% close rate."""
    opened = m.get("issues_opened_90d", 0.0)
    if opened <= 0:
        return None
    return m.get("issues_closed_90d", 0.0) / opened


DERIVED = {
    "responsive_close_ratio (closed/opened over 90d, higher better)": _close_ratio,
}


def _summarise(label: str, values: list[float], excluded: int) -> None:
    if not values:
        print(f"{label}: no data  (sentinel-only: {excluded})")
        return
    values.sort()
    q = statistics.quantiles(values, n=4)
    print(f"{label}\n  n={len(values)}  sentinel-excluded={excluded}  "
          f"min={values[0]:.3g}  p25={q[0]:.3g}  p50={q[1]:.3g}  "
          f"p75={q[2]:.3g}  max={values[-1]:.3g}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    engine = get_engine(args.db)

    with session_scope(engine) as s:
        repo_ids = [r.id for r in s.query(Repo).all()]

    snapshots = {rid: latest_metrics(engine, rid) for rid in repo_ids}

    for label, keys in AXES.items():
        values: list[float] = []
        excluded = 0
        for m in snapshots.values():
            raw = [m[k] for k in keys if k in m]
            usable = [v for v in raw if v not in SENTINELS]
            if raw and not usable:
                excluded += 1
            if usable:
                values.append(max(usable) if len(keys) > 1 else usable[0])
        _summarise(label, values, excluded)

    for label, fn in DERIVED.items():
        computed = [v for v in (fn(m) for m in snapshots.values()) if v is not None]
        _summarise(label, computed, len(snapshots) - len(computed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `AISEL_DB_URL=sqlite:///data/aisel.db python scripts/calibrate.py`

**定阈值规则（八个 band 一律照此，不允许逐个拍脑袋）：**
- 「越大越好」（`adoption_pypi`、`adoption_npm`、`adoption_docker`、`alive_commits`、`alive_bus`、`responsive_close_ratio`）：`strong = p75`，`moderate = p25`
- 「越小越好」（`alive_release`、`responsive_latency`）：`strong = p25`，`moderate = p75`

⚠️ 三个 adoption band 必须**各自**用自己那一列数据标定，不许共用。pypi/npm 是 30 天安装数、docker 是自镜像诞生以来的累计数——量纲不同。各自标定后，`strong` 的含义是「在同一渠道内相对同侪靠前」，这是公平比较；共用一档不是。

⚠️ `sentinel-excluded` 计数不为 0 时要看一眼：它表示有多少 repo 在这一轴上**根本没有测量值**（从未发过 release、90 天内无人回复 issue）。这些 repo 在该轴上会被判为 `unknown`，不是被判为差——这正是置信度分级要处理的情况，不要试图给它们编一个数。

把 `axes.py` 里的 `THRESHOLDS = None` 替换为算出的三轴字典，并在该常量上方用注释记下标定日期与当时的 n 值。替换后 `test_uncalibrated_thresholds_raise_instead_of_silently_misrating` 仍须通过（它用 monkeypatch 强制置 None，不依赖模块初值）。

- [ ] **Step 6: 提交**

```bash
git add src/aisel/scoring scripts/calibrate.py tests/test_axes.py
git commit -m "feat: four-axis rating with data-calibrated thresholds"
```

---

## Task 13: 置信度分级

**Files:**
- Create: `src/aisel/scoring/confidence.py`
- Test: `tests/test_confidence.py`

**Interfaces:**
- Consumes: `aisel.scoring.axes.rate_all` 的输出
- Produces: `aisel.scoring.confidence.grade(metrics: dict[str, float], ratings: dict[str, str]) -> str` → `"high" | "medium" | "low"`

**规格 §4.4**：
| 级别 | 条件 |
|---|---|
| high | 有真实使用量信号 + 活性 + issue 响应 三者齐全 |
| medium | 缺使用量信号，但活性与 issue 响应齐全，且 `forks_total >= 1000` |
| low | 其余 |

- [ ] **Step 1: 写失败的测试 `tests/test_confidence.py`**

```python
from aisel.scoring.confidence import grade

FULL = {"downloads_pypi_30d": 5000.0, "days_since_last_release": 10.0,
        "issue_first_response_p50_hours": 5.0, "forks_total": 2000.0}
RATED_OK = {"adoption": "strong", "alive": "strong",
            "responsive": "strong", "runnable": "pass"}


def test_all_three_signals_present_gives_high():
    assert grade(FULL, RATED_OK) == "high"


def test_no_download_signal_but_active_and_forked_gives_medium():
    m = dict(FULL); m.pop("downloads_pypi_30d")
    r = dict(RATED_OK); r["adoption"] = "unknown"
    assert grade(m, r) == "medium"


def test_no_download_signal_and_few_forks_gives_low():
    m = dict(FULL); m.pop("downloads_pypi_30d"); m["forks_total"] = 50.0
    r = dict(RATED_OK); r["adoption"] = "unknown"
    assert grade(m, r) == "low"


def test_missing_issue_response_drops_to_low():
    m = dict(FULL); m["issue_first_response_p50_hours"] = -1.0
    r = dict(RATED_OK); r["responsive"] = "unknown"
    assert grade(m, r) == "low"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_confidence.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `src/aisel/scoring/confidence.py`**

```python
"""Confidence grading (spec §4.4). Confidence must always be shown; a 'low'
entry may never be labelled a primary recommendation."""
from __future__ import annotations

MEDIUM_FORK_FLOOR = 1000.0


def grade(metrics: dict[str, float], ratings: dict[str, str]) -> str:
    has_adoption = ratings.get("adoption") != "unknown"
    has_alive = ratings.get("alive") != "unknown"
    has_responsive = ratings.get("responsive") != "unknown"

    if has_adoption and has_alive and has_responsive:
        return "high"
    if (has_alive and has_responsive
            and metrics.get("forks_total", 0.0) >= MEDIUM_FORK_FLOOR):
        return "medium"
    return "low"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_confidence.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 提交**

```bash
git add src/aisel/scoring/confidence.py tests/test_confidence.py
git commit -m "feat: confidence grading per spec 4.4"
```

---

## Task 14: verdict 生成与依据快照

**Files:**
- Create: `src/aisel/scoring/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `axes.rate_all` / `axes.latest_metrics` / `axes.latest_run_status`（Task 12）、`confidence.grade`（Task 13）
- Produces: `aisel.scoring.verdict.generate(engine, use_case_id, now=None) -> list[Verdict]`（写入 `verdicts` 表并返回）

**排序规则**（确定性，不含随机与手工插队）：按 `(strong 数量, adoption 档, alive 档, responsive 档)` 降序，同分按 slug 字典序。

**推荐等级规则**：
| 条件 | recommendation |
|---|---|
| `confidence == "low"` | `insufficient_data`（**规格硬约束：low 不得为 primary**） |
| rank 1 且 runnable == "pass" 且 无 weak 轴 | `primary` |
| `alive == "weak"` 或 `responsive == "weak"` | `avoid` |
| 其余 | `conditional` |

- [ ] **Step 1: 写失败的测试 `tests/test_verdict.py`**

```python
import datetime as dt

from aisel.db import get_engine, init_db, session_scope
from aisel.models import MetricDaily, QuickstartRun, Repo, UseCase, Verdict
from aisel.scoring import axes
from aisel.scoring.verdict import generate

TH = {"adoption_pypi":          {"strong": 100000.0, "moderate": 10000.0},
      "adoption_npm":           {"strong": 500000.0, "moderate": 50000.0},
      "adoption_docker":        {"strong": 1000000.0, "moderate": 100000.0},
      "alive_release":          {"strong": 30.0, "moderate": 120.0},
      "alive_commits":          {"strong": 50.0, "moderate": 10.0},
      "alive_bus":              {"strong": 5.0, "moderate": 2.0},
      "responsive_latency":     {"strong": 24.0, "moderate": 168.0},
      "responsive_close_ratio": {"strong": 0.6, "moderate": 0.25}}

D = dt.date(2026, 8, 9)
NOW = dt.datetime(2026, 8, 9, 12, 0)


def _repo(s, rid, name, is_top=True):
    s.add(Repo(id=rid, owner="o", name=name, use_case_id="u",
               pypi_package="p", npm_package=None, dockerhub_repo=None, is_top=is_top))


def _metrics(s, rid, downloads, release_days, latency, forks=5000.0):
    for metric, value in [("downloads_pypi_30d", downloads),
                          ("days_since_last_release", release_days),
                          ("issue_first_response_p50_hours", latency),
                          ("forks_total", forks)]:
        s.add(MetricDaily(repo_id=rid, date=D, metric=metric, value=value))


def _build(tmp_path, monkeypatch):
    monkeypatch.setattr(axes, "THRESHOLDS", TH)
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    return engine


def test_best_repo_becomes_primary_with_evidence_snapshot(tmp_path, monkeypatch):
    engine = _build(tmp_path, monkeypatch)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        _repo(s, 1, "great"); _repo(s, 2, "okay")
    with session_scope(engine) as s:
        _metrics(s, 1, 500000.0, 5.0, 3.0)
        _metrics(s, 2, 20000.0, 60.0, 100.0)
        s.add(QuickstartRun(repo_id=1, run_at=NOW, status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))
        s.add(QuickstartRun(repo_id=2, run_at=NOW, status="pass",
                            failure_class=None, log_tail="", repo_commit="b"))

    verdicts = generate(engine, "u", now=NOW)

    assert [v.repo_id for v in verdicts] == [1, 2]
    assert verdicts[0].rank == 1
    assert verdicts[0].recommendation == "primary"
    assert verdicts[0].confidence == "high"
    assert verdicts[0].evidence_snapshot["downloads_pypi_30d"] == 500000.0
    assert verdicts[0].evidence_snapshot["ratings"]["adoption"] == "strong"
    assert verdicts[1].recommendation == "conditional"


def test_low_confidence_can_never_be_primary(tmp_path, monkeypatch):
    """Spec hard constraint — enforced here, not left to the caller."""
    engine = _build(tmp_path, monkeypatch)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        s.add(Repo(id=1, owner="o", name="obscure", use_case_id="u",
                   pypi_package=None, npm_package=None,
                   dockerhub_repo=None, is_top=True))
    with session_scope(engine) as s:
        # no downloads, few forks -> low confidence
        s.add(MetricDaily(repo_id=1, date=D, metric="days_since_last_release", value=3.0))
        s.add(MetricDaily(repo_id=1, date=D, metric="issue_first_response_p50_hours", value=2.0))
        s.add(MetricDaily(repo_id=1, date=D, metric="forks_total", value=12.0))
        s.add(QuickstartRun(repo_id=1, run_at=NOW, status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))

    v = generate(engine, "u", now=NOW)[0]
    assert v.confidence == "low"
    assert v.recommendation == "insufficient_data"


def test_dying_project_is_marked_avoid(tmp_path, monkeypatch):
    engine = _build(tmp_path, monkeypatch)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        _repo(s, 1, "dying")
    with session_scope(engine) as s:
        _metrics(s, 1, 300000.0, 500.0, 3.0)   # popular but no release in 500 days
        s.add(QuickstartRun(repo_id=1, run_at=NOW, status="pass",
                            failure_class=None, log_tail="", repo_commit="a"))

    v = generate(engine, "u", now=NOW)[0]
    assert v.recommendation == "avoid"


def test_regenerating_replaces_previous_verdicts(tmp_path, monkeypatch):
    engine = _build(tmp_path, monkeypatch)
    with session_scope(engine) as s:
        s.add(UseCase(id="u", name="U", description=""))
        _repo(s, 1, "x")
    with session_scope(engine) as s:
        _metrics(s, 1, 500000.0, 5.0, 3.0)

    generate(engine, "u", now=NOW)
    generate(engine, "u", now=NOW)

    with session_scope(engine) as s:
        assert s.query(Verdict).count() == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.scoring.verdict'`

- [ ] **Step 3: 写 `src/aisel/scoring/verdict.py`**

```python
"""Turn ratings into ranked, confidence-tagged verdicts with a replayable
evidence snapshot (spec §6: a verdict that cannot be traced back to the data
it was generated from is a black box)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import Repo, Verdict
from aisel.scoring.axes import BAND_RANK, latest_metrics, latest_run_status, rate_all
from aisel.scoring.confidence import grade

AXES = ("adoption", "alive", "responsive")


def _sort_key(item: tuple[Repo, dict[str, str]]) -> tuple:
    repo, ratings = item
    strong = sum(ratings[a] == "strong" for a in AXES)
    return (-strong,
            -BAND_RANK[ratings["adoption"]],
            -BAND_RANK[ratings["alive"]],
            -BAND_RANK[ratings["responsive"]],
            f"{repo.owner}/{repo.name}")


def _recommend(rank: int, ratings: dict[str, str], confidence: str) -> str:
    if confidence == "low":
        return "insufficient_data"
    if ratings["alive"] == "weak" or ratings["responsive"] == "weak":
        return "avoid"
    if rank == 1 and ratings["runnable"] == "pass" and \
            not any(ratings[a] == "weak" for a in AXES):
        return "primary"
    return "conditional"


def _rationale(ratings: dict[str, str], metrics: dict[str, float]) -> str:
    parts = [f"{axis}: {ratings[axis]}" for axis in AXES]
    parts.append(f"quickstart: {ratings['runnable']}")
    if "downloads_pypi_30d" in metrics:
        parts.append(f"pypi 30d: {int(metrics['downloads_pypi_30d'])}")
    if "downloads_npm_30d" in metrics:
        parts.append(f"npm 30d: {int(metrics['downloads_npm_30d'])}")
    return "; ".join(parts)


def generate(engine: Engine, use_case_id: str,
             now: dt.datetime | None = None) -> list[Verdict]:
    now = now or dt.datetime.now(dt.UTC).replace(tzinfo=None)

    with session_scope(engine) as s:
        repos = s.query(Repo).filter(Repo.use_case_id == use_case_id).all()
        repo_ids = [(r.id, r.owner, r.name) for r in repos]

    scored = []
    for rid, owner, name in repo_ids:
        metrics = latest_metrics(engine, rid)
        ratings = rate_all(metrics, latest_run_status(engine, rid))
        stub = Repo(id=rid, owner=owner, name=name)
        scored.append(((stub, ratings), metrics))

    scored.sort(key=lambda pair: _sort_key(pair[0]))

    with session_scope(engine) as s:
        s.query(Verdict).filter(Verdict.use_case_id == use_case_id).delete()
        s.flush()
        out: list[Verdict] = []
        for rank, ((repo, ratings), metrics) in enumerate(scored, start=1):
            confidence = grade(metrics, ratings)
            row = Verdict(
                use_case_id=use_case_id,
                repo_id=repo.id,
                rank=rank,
                recommendation=_recommend(rank, ratings, confidence),
                condition=None,
                confidence=confidence,
                rationale=_rationale(ratings, metrics),
                evidence_snapshot={**metrics, "ratings": ratings},
                generated_at=now,
            )
            s.add(row)
            out.append(row)
        s.flush()
        for row in out:
            s.expunge(row)
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_verdict.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 提交**

```bash
git add src/aisel/scoring/verdict.py tests/test_verdict.py
git commit -m "feat: ranked verdicts with confidence and evidence snapshot"
```

---

## Task 15: 环节页渲染

**Files:**
- Create: `src/aisel/render/__init__.py`, `src/aisel/render/stage_page.py`, `scripts/build_pages.py`
- Test: `tests/test_stage_page.py`

**Interfaces:**
- Consumes: `aisel.models.Verdict`（Task 14）
- Produces: `aisel.render.stage_page.render(engine, use_case_id) -> str`（markdown）；`scripts/build_pages.py` 输出到 `out/stage-<id>.md`

> 盲测**不需要建站**。规格 §9 把建站放在 P1b 之后，正是为了避免在护城河被证实前投入前端。盲测发 markdown 渲染出的页面即可。

> ⚠️ **交接约束（Task 5 重审提出，不得遗忘）**：Task 5 采集了 `downloads_{pypi,npm}_days_30d` / `_days_prev30d`，**目前没有任何代码消费它们**。一旦本页（或任何地方）展示 30d-vs-prev30d 趋势，**必须先检查 `days_prev30d == 30`；不满 30 天就不许显示趋势**，改为标注「history too short」。
> 理由：不足 60 天历史的包，recent 窗口满、prev 窗口缺，平坦流量会渲染成暴涨。采集端已经把判断所需的信息交出来了，展示端不查就等于白采——而这恰恰是宪法第 2 条要防的那种「看起来合理、很好看、且是错的」数字。
> 当前版本的环节页**不展示趋势**，所以这条尚未被触发；加趋势时必须同时加这个守卫。

页面必须包含（缺一项即视为未完成）：
1. 环节名与一句话说明
2. **结论区**：primary / conditional / avoid / insufficient_data 分组呈现
3. 四轴表格，每行带 confidence 列
4. quickstart 实跑结果与失败原因
5. **数据窗口声明**：`Download figures are 30-day totals; trend window is 180 days (pypistats retention).`
6. 生成时间戳

- [ ] **Step 1: 写失败的测试 `tests/test_stage_page.py`**

```python
import datetime as dt

from aisel.db import get_engine, init_db, session_scope
from aisel.models import Repo, UseCase, Verdict
from aisel.render.stage_page import render

NOW = dt.datetime(2026, 8, 9, 12, 0)


def _setup(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with session_scope(engine) as s:
        s.add(UseCase(id="rag", name="RAG & Retrieval",
                      description="Turning your documents into answers."))
        s.add(Repo(id=1, owner="run-llama", name="llama_index", use_case_id="rag",
                   pypi_package="llama-index", npm_package=None,
                   dockerhub_repo=None, is_top=True))
        s.add(Repo(id=2, owner="stale", name="oldrag", use_case_id="rag",
                   pypi_package="oldrag", npm_package=None,
                   dockerhub_repo=None, is_top=True))
    with session_scope(engine) as s:
        s.add(Verdict(use_case_id="rag", repo_id=1, rank=1, recommendation="primary",
                      condition=None, confidence="high",
                      rationale="adoption: strong; alive: strong",
                      evidence_snapshot={"downloads_pypi_30d": 900000.0,
                                         "ratings": {"adoption": "strong",
                                                     "alive": "strong",
                                                     "responsive": "strong",
                                                     "runnable": "pass"}},
                      generated_at=NOW))
        s.add(Verdict(use_case_id="rag", repo_id=2, rank=2, recommendation="avoid",
                      condition=None, confidence="high",
                      rationale="alive: weak",
                      evidence_snapshot={"downloads_pypi_30d": 200.0,
                                         "ratings": {"adoption": "weak",
                                                     "alive": "weak",
                                                     "responsive": "unknown",
                                                     "runnable": "fail"}},
                      generated_at=NOW))
    return engine


def test_page_contains_all_required_sections(tmp_path):
    md = render(_setup(tmp_path), "rag")
    assert "# RAG & Retrieval" in md
    assert "Turning your documents into answers." in md
    assert "## Verdict" in md
    assert "run-llama/llama_index" in md
    assert "stale/oldrag" in md
    assert "Confidence" in md
    assert "trend window is 180 days" in md
    assert "2026-08-09" in md


def test_avoid_entries_are_visually_separated_from_primary(tmp_path):
    md = render(_setup(tmp_path), "rag")
    assert md.index("Primary") < md.index("Avoid")


def test_quickstart_column_carries_each_repos_own_run_result(tmp_path):
    md = render(_setup(tmp_path), "rag")
    # table row layout: | slug | adoption | alive | responsive | runnable | confidence |
    rows = {line.split("|")[1].strip(): line.split("|")[5].strip()
            for line in md.splitlines()
            if line.startswith("| ") and "/" in line}
    assert rows["run-llama/llama_index"] == "pass"
    assert rows["stale/oldrag"] == "fail"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stage_page.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aisel.render'`

- [ ] **Step 3: 写 `src/aisel/render/stage_page.py`**

```python
"""Render a stage page as markdown. Blind testing needs a page, not a website —
building the site is P2, deliberately after the P1b gate."""
from __future__ import annotations

from sqlalchemy import Engine

from aisel.db import session_scope
from aisel.models import Repo, UseCase, Verdict

GROUPS = [
    ("primary", "Primary pick"),
    ("conditional", "Conditional — pick if the condition matches"),
    ("avoid", "Avoid"),
    ("insufficient_data", "Insufficient data to judge"),
]

WINDOW_NOTE = (
    "_Download figures are 30-day totals; trend window is 180 days "
    "(pypistats retention). Quickstart results come from a clean container run._"
)


def render(engine: Engine, use_case_id: str) -> str:
    with session_scope(engine) as s:
        uc = s.get(UseCase, use_case_id)
        if uc is None:
            raise ValueError(f"unknown use case {use_case_id!r}")
        rows = (s.query(Verdict)
                 .filter(Verdict.use_case_id == use_case_id)
                 .order_by(Verdict.rank).all())
        slugs = {r.id: f"{r.owner}/{r.name}" for r in s.query(Repo).all()}
        data = [(slugs[v.repo_id], v.recommendation, v.confidence,
                 v.evidence_snapshot.get("ratings", {}), v.rationale,
                 v.generated_at) for v in rows]

    if not data:
        raise ValueError(f"no verdicts generated for {use_case_id!r}")

    generated_at = data[0][5]
    lines = [f"# {uc.name}", "", uc.description, "", "## Verdict", ""]

    for key, heading in GROUPS:
        members = [d for d in data if d[1] == key]
        if not members:
            continue
        lines += [f"### {heading}", ""]
        for slug, _, confidence, _, rationale, _ in members:
            lines.append(f"- **{slug}** — {rationale} _(confidence: {confidence})_")
        lines.append("")

    lines += ["## All candidates", "",
              "| Repo | Adoption | Alive | Responsive | Quickstart | Confidence |",
              "|---|---|---|---|---|---|"]
    for slug, _, confidence, ratings, _, _ in data:
        lines.append(
            f"| {slug} | {ratings.get('adoption', 'unknown')} "
            f"| {ratings.get('alive', 'unknown')} "
            f"| {ratings.get('responsive', 'unknown')} "
            f"| {ratings.get('runnable', 'unknown')} | {confidence} |")

    lines += ["", WINDOW_NOTE, "",
              f"_Generated {generated_at.date().isoformat()} (UTC)._"]
    return "\n".join(lines)
```

`src/aisel/render/__init__.py` 内容为空。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_stage_page.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 5: 写 `scripts/build_pages.py`**

```python
"""Generate verdicts for every use case and write the stage pages."""
from __future__ import annotations

import argparse
from pathlib import Path

from aisel.db import get_engine, session_scope
from aisel.models import UseCase
from aisel.render.stage_page import render
from aisel.scoring.verdict import generate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--out", default="out")
    args = parser.parse_args()

    engine = get_engine(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with session_scope(engine) as s:
        use_case_ids = [u.id for u in s.query(UseCase).order_by(UseCase.id).all()]

    for uc_id in use_case_ids:
        generate(engine, uc_id)
        path = out_dir / f"stage-{uc_id}.md"
        path.write_text(render(engine, uc_id), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 生成 5 张真实页面并逐页人工过一遍**

Run: `AISEL_DB_URL=sqlite:///data/aisel.db python scripts/build_pages.py`
Expected: `out/stage-agent-orchestration.md` 等 5 个文件。

逐页自查（这是给盲测者看的东西，不能带明显错误）：
- 结论读起来是否成句、有无自相矛盾
- 有无 `confidence: low` 却出现在 Primary 分组（**出现即 bug，回 Task 14 查**）
- 有无明显错到离谱的排序（例如一个人尽皆知的主流框架被排到最后）——若有，先查是不是采集或包名映射错了，**不要直接改排序规则去迎合直觉**

- [ ] **Step 7: 提交**

```bash
git add src/aisel/render scripts/build_pages.py tests/test_stage_page.py
git commit -m "feat: stage page markdown rendering and build script"
```

---

## Task 16: P1b 验证执行与关口

> ⚠️ **本任务待重写（2026-08-09 决定）。** 原设计的「盲测 5 个开发者」已废弃——冷启动招募 5 个英文开发者对单人创始人不可执行。规格 §1 已改为两段串行：**段 B 文献反证（自动化）→ 段 A 公开发帖**。下方内容是旧版，执行到本任务前必须按规格 §1 重写；`tally.py` 的判定逻辑、`protocol.md` 的内容、以及关口判据全部要换。**在重写前不要按下方步骤施工。**
>
> 重写时机定在 Task 15 完成之后——那时已能看到真实环节页长什么样，失败条件才写得具体。

### 旧版内容（作废，仅供改写时参考）

## Task 16-OLD: 盲测执行与 P1b 关口

**Files:**
- Create: `blindtest/protocol.md`, `blindtest/records/README.md`, `blindtest/tally.py`
- Test: `tests/test_tally.py`

**Interfaces:**
- Consumes: `out/stage-*.md`（Task 15）
- Produces: `blindtest.tally.summarise(records: list[dict]) -> Tally`（dataclass：`n`、`can_decide`、`conflicts`、`passed`）

**规格 §1 完工判据**：`n == 5` 且 `can_decide >= 4` 且 `conflicts == 0`。

- [ ] **Step 1: 写 `blindtest/protocol.md`**

```markdown
# Blind test protocol

Gate (spec §1): with 5 participants, PASS requires
`can_decide >= 4` **and** `conflicts == 0`.

## Recruiting

Requirement: has shipped or actively worked on an AI application in the last
6 months. Not "reads about AI" — has written the code.

| Channel | How |
|---|---|
| Reddit | r/LocalLLaMA, r/LangChain, r/MachineLearning — ask for 15 min of feedback |
| Discord | LangChain / LlamaIndex / vLLM community servers |
| GitHub | People who opened a merged PR or a substantive issue on a candidate repo in the last 6 months |
| X | Developers who have posted about shipping an agent or RAG system |

Match each participant to **one** stage page in their own area. Nobody
reviews five pages.

## Script — order matters, do not reorder

1. **Background, BEFORE showing anything.** "In the last 6 months, what have
   you used for <stage>? Why did you pick it?" Record verbatim. Showing the
   page first contaminates the answer.
2. **Hand over the page. Say nothing about it.** No framing, no explanation.
3. **Q1 — usability.** "If you had to pick a solution for this stage on a new
   project today, could you make the decision from this page? Yes or no."
4. **Q2 — correctness, open.** "Is there anything on this page that conflicts
   with your actual experience?"
5. **Do not defend, explain, or argue.** Record verbatim. The urge to explain
   is exactly what destroys the signal.

## Recording

One file per participant at `blindtest/records/<id>.yaml`:

```yaml
id: p1
stage: rag
background: "We use LlamaIndex, picked it because ..."
can_decide: true
conflicts: ""        # non-empty means a conflict was reported
notes: "..."
```
```

- [ ] **Step 2: 写失败的测试 `tests/test_tally.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blindtest"))

import tally


def _r(can_decide, conflicts=""):
    return {"id": "x", "stage": "rag", "background": "b",
            "can_decide": can_decide, "conflicts": conflicts}


def test_four_of_five_and_no_conflicts_passes():
    records = [_r(True)] * 4 + [_r(False)]
    result = tally.summarise(records)
    assert result.n == 5 and result.can_decide == 4 and result.conflicts == 0
    assert result.passed is True


def test_any_conflict_fails_even_with_five_yes():
    records = [_r(True)] * 4 + [_r(True, "LangGraph is listed as primary but it "
                                       "broke for us on streaming")]
    result = tally.summarise(records)
    assert result.can_decide == 5 and result.conflicts == 1
    assert result.passed is False


def test_three_of_five_fails():
    records = [_r(True)] * 3 + [_r(False)] * 2
    assert tally.summarise(records).passed is False


def test_fewer_than_five_participants_is_not_a_pass():
    assert tally.summarise([_r(True)] * 4).passed is False
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_tally.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tally'`

- [ ] **Step 4: 写 `blindtest/tally.py`**

```python
"""Tally blind test records against the P1b gate (spec §1)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml

REQUIRED_N = 5
REQUIRED_CAN_DECIDE = 4


@dataclass(frozen=True)
class Tally:
    n: int
    can_decide: int
    conflicts: int
    passed: bool


def summarise(records: list[dict]) -> Tally:
    n = len(records)
    can_decide = sum(1 for r in records if r.get("can_decide"))
    conflicts = sum(1 for r in records if (r.get("conflicts") or "").strip())
    passed = (n >= REQUIRED_N
              and can_decide >= REQUIRED_CAN_DECIDE
              and conflicts == 0)
    return Tally(n=n, can_decide=can_decide, conflicts=conflicts, passed=passed)


def load_records(directory: str | Path) -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(Path(directory).glob("*.yaml"))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", default="blindtest/records")
    args = parser.parse_args()

    result = summarise(load_records(args.records))
    print(f"participants: {result.n}")
    print(f"can decide  : {result.can_decide}/{REQUIRED_N} (need >= {REQUIRED_CAN_DECIDE})")
    print(f"conflicts   : {result.conflicts} (need 0)")
    print("GATE P1b PASSED" if result.passed else "GATE P1b FAILED")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`blindtest/records/README.md`:
```markdown
One YAML file per participant. See `../protocol.md` for the schema and the
question script. Do not edit a record after the session — if something was
recorded wrong, add a `correction:` field rather than rewriting the original.
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_tally.py -v`
Expected: every test in the file passes, zero failures, output pristine (no warnings). Do not chase a predicted count — the plan does not know how pytest will expand parametrised cases.

- [ ] **Step 6: 提交工具，然后执行盲测**

```bash
git add blindtest tests/test_tally.py
git commit -m "feat: blind test protocol and gate tally"
```

按 `blindtest/protocol.md` 招募 5 人并逐个执行，每人写一份 `blindtest/records/<id>.yaml`。

- [ ] **Step 7: 判定关口**

Run: `python blindtest/tally.py`

| 输出 | 下一步 |
|---|---|
| `GATE P1b PASSED` | 提交记录，本计划完成。另立 P2 建站计划。 |
| 失败且 `conflicts > 0` | **判优规则错。** 读冲突原文，定位是哪一轴的判断与现实不符，改 `axes.py` / `verdict.py`，重跑 Task 15 Step 6，重招 5 人重测。 |
| 失败且仅 `can_decide < 4` | **展示层问题。** 读 `notes` 找出缺什么信息，改 `stage_page.py`，重跑 Task 15 Step 6，重招 5 人重测。 |
| **两轮返工后仍失败** | ⛔ **停项目**（规格 §1）。写一份复盘记进 `docs/`，不要第三轮。 |

- [ ] **Step 8: 提交结果**

```bash
git add blindtest/records
git commit -m "test: p1b blind test records and gate result"
```

---

## 计划完成后

P1b 通过即本计划结束。**不要顺手开始建站** —— P2 另立计划，届时需要重新确认：域名、咨询定价、订阅定价、境外收款主体（规格 §13 未决事项）。
