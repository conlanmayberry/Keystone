"""Dev entrypoint: `python -m megachud.cli serve` starts the dashboard."""

import sys

import uvicorn

from megachud.config import Settings


def serve() -> None:
    settings = Settings.load()
    uvicorn.run(
        "megachud.api.app:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
        reload=False,
    )


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        print("usage: python -m megachud.cli serve")
        raise SystemExit(1)
    serve()


if __name__ == "__main__":
    main()
