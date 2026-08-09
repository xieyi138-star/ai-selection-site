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
