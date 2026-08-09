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
