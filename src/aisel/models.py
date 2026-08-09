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
