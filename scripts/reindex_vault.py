"""Dev CLI: reindex vault/ markdown notes back into the DB. Human edits made
directly in Obsidian win over what's currently stored.
"""

from megachud.config import Settings
from megachud.db import get_engine, init_db, make_session_factory
from megachud.obsidian.reindex import reindex_vault


def main() -> None:
    settings = Settings.load()
    engine = get_engine(settings.db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    report = reindex_vault(settings.vault_root, session_factory, settings.memory.vector_dim)
    print(f"created={report.created} updated={report.updated} skipped={report.skipped}")
    for error in report.errors:
        print(f"  error: {error}")


if __name__ == "__main__":
    main()
