"""Command-line entry point: ``rulebook <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the rulebook API")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    serve.add_argument("--port", type=int, default=8000)
    # TODO(milestone-1): `import-golden` subcommand (commit 4).
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("rulebook.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
