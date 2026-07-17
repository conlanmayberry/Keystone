from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Tables tagged with Phase 5's agent_id/project_name columns. Kept here
# (not per-model) since ensure_agent_project_columns is the one place that
# needs the list.
TAGGED_TABLES = ["tasks", "strategies", "memory_entries", "reviews"]
TAG_COLUMNS = ["agent_id", "project_name"]


class Base(DeclarativeBase):
    pass


def get_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    # Importing models registers them on Base.metadata before create_all.
    from megachud.models import approval, evaluation, event, memory_entry, reflection, task  # noqa: F401
    from megachud.models import strategy, experiment, promotion_request, curiosity, review  # noqa: F401
    from megachud.models import agent  # noqa: F401

    Base.metadata.create_all(engine)

    # create_all only creates tables that don't exist yet — indexes added
    # to a model after its table was first created (e.g. a dev DB from an
    # earlier phase) would otherwise never materialize. checkfirst makes
    # this an idempotent no-op for indexes that already exist.
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(engine, checkfirst=True)


def ensure_agent_project_columns(engine: Engine) -> None:
    """Base.metadata.create_all() only creates tables that don't exist yet
    — it never adds columns to tables that already exist. Dev DBs from
    Phases 1-4 already have populated tasks/strategies/memory_entries/
    reviews tables, so without this step those tables would stay out of
    sync with the ORM models the moment agent_id/project_name were added
    to them, and any query touching those columns would raise "no such
    column". SQLite supports additive ALTER TABLE ADD COLUMN; nullable
    TEXT columns need no default backfill. Idempotent — safe to call every
    startup, a no-op once the columns exist. Call this AFTER init_db(): a
    brand-new table is already created with every column by create_all(),
    so this only ever needs to patch tables that predate this migration.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in TAGGED_TABLES:
            if table not in existing_tables:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table)}
            for column in TAG_COLUMNS:
                if column not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} TEXT"))


def get_or_create_agent(session_factory: sessionmaker[Session], name: str) -> str:
    """SELECT by name; INSERT if missing; return id. Called once at
    create_app() startup with settings.agent_name (default "default"), so
    agent_id FKs always have something valid to point at.
    """
    from megachud.models.agent import Agent

    session = session_factory()
    try:
        agent = session.query(Agent).filter_by(name=name).first()
        if agent is None:
            agent = Agent(name=name)
            session.add(agent)
            session.commit()
        return agent.id
    finally:
        session.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
