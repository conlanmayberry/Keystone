"""Dev convenience: create all tables at the configured db_path."""

from megachud.config import Settings
from megachud.db import get_engine, init_db


def main() -> None:
    settings = Settings.load()
    engine = get_engine(settings.db_path)
    init_db(engine)
    print(f"Initialized database at {settings.db_path}")


if __name__ == "__main__":
    main()
