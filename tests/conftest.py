from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory


@pytest.fixture
def tmp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def test_settings(tmp_path, tmp_workspace, tmp_vault) -> Settings:
    return Settings(
        workspace_root=tmp_workspace,
        db_path=tmp_path / "test.db",
        vault_root=tmp_vault,
    )


@pytest.fixture
def db_session(tmp_path) -> Session:
    engine = get_engine(tmp_path / "test_session.db")
    init_db(engine)
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory(tmp_path):
    engine = get_engine(tmp_path / "test_engine.db")
    init_db(engine)
    return make_session_factory(engine)
