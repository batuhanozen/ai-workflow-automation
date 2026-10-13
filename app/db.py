from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def build_database(url: str) -> tuple[Engine, sessionmaker[Session]]:
    database = make_url(url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
        **({"poolclass": StaticPool} if database in (None, "", ":memory:") else {}),
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine, sessionmaker(engine, expire_on_commit=False)
