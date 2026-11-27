"""Command-line entry point: ``control-centre <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control-centre", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8004)
    sub.add_parser("check-strings", help="EN/FR UI strings have the same keys")
    args = parser.parse_args(argv)
    if args.command == "check-strings":
        from control_centre.i18n import check_parity

        problems = check_parity()
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    import uvicorn

    uvicorn.run("control_centre.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
