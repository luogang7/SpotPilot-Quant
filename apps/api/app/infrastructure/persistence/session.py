from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


MYSQL_CONNECT_ARGS = {
    "connect_timeout": 3,
    "read_timeout": 5,
    "write_timeout": 5,
    "init_command": "SET SESSION lock_wait_timeout=5",
}


def create_mysql_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.mysql_dsn,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=5,
        future=True,
        connect_args=MYSQL_CONNECT_ARGS,
    )


def create_mysql_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_mysql_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
