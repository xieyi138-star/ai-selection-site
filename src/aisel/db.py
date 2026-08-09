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
