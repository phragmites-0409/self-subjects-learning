from collections.abc import Generator
from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.account_scope import account_id, active_data_dir
from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


_legacy_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
_account_sessions: dict[str, sessionmaker] = {}
_account_lock = Lock()


def SessionLocal() -> Session:
    """Resolve the SQLite database from the verified request's account scope."""
    owner = account_id()
    if owner is None:
        return _legacy_session()
    factory = _account_sessions.get(owner)
    if factory is None:
        with _account_lock:
            factory = _account_sessions.get(owner)
            if factory is None:
                directory = active_data_dir()
                for folder in ("db", "objects", "tmp", "logs", "backups"):
                    (directory / folder).mkdir(parents=True, exist_ok=True)
                account_engine = create_engine(
                    f"sqlite:///{(directory / 'db' / 'subjects-learning.sqlite3').resolve()}",
                    connect_args={"check_same_thread": False},
                    future=True,
                )
                event.listen(account_engine, "connect", _configure_sqlite)
                Base.metadata.create_all(bind=account_engine)
                factory = sessionmaker(bind=account_engine, autoflush=False, expire_on_commit=False, class_=Session)
                _account_sessions[owner] = factory
    return factory()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(*, include_legacy: bool = True) -> None:
    """Load all models; leave unassigned local data untouched in account mode."""
    from app.db import models
    from app.modules.learning import knowledge as knowledge_contents
    from app.modules.learning import models as learning_models  # noqa: F401
    from app.modules.notifications import Delivery  # noqa: F401
    from app.modules.papers.revisions import PaperRevision  # noqa: F401
    from app.modules.question_bank.service import QuestionSearch  # noqa: F401
    from app.modules.vocabulary import models as vocabulary_models  # noqa: F401

    if include_legacy:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        models.migrate_legacy_english_knowledge_nodes(engine)
        with SessionLocal() as db:
            knowledge_contents.migrate_contents(db)
