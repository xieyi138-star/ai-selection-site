"""Engine / session helpers. SQLite now, Postgres at P2 via AISEL_DB_URL."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from aisel.models import Base

DEFAULT_URL = "sqlite:///aisel.db"


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or os.environ.get("AISEL_DB_URL", DEFAULT_URL))


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
