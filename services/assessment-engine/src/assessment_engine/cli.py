"""Command-line entry point: ``assessment-engine <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assessment-engine", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8005)
    serve.add_argument("--migrate", action="store_true", help="Apply migrations first")
    sub.add_parser("migrate", help="Apply database migrations")
    args = parser.parse_args(argv)
    if args.command == "migrate" or (args.command == "serve" and args.migrate):
        from assessment_engine.migrate import upgrade

        upgrade()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("assessment_engine.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
