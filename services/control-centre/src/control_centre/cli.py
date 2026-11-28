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
    serve.add_argument("--migrate", action="store_true", help="Apply migrations first")
    serve.add_argument("--seed-tenants", metavar="FILE", help="Create missing tenants first")
    sub.add_parser("check-strings", help="EN/FR UI strings have the same keys")
    sub.add_parser("migrate", help="Apply database migrations (advisory lock)")
    seed_cmd = sub.add_parser("seed-tenants", help="Create the tenants of a TOML file (if missing)")
    seed_cmd.add_argument("file", help="e.g. data/demo/tenants.toml")
    args = parser.parse_args(argv)
    if args.command == "migrate" or (args.command == "serve" and args.migrate):
        from control_centre.migrate import upgrade

        upgrade()
        if args.command == "migrate":
            return 0
    seed_file = getattr(args, "seed_tenants", None) or getattr(args, "file", None)
    if args.command == "seed-tenants" or (args.command == "serve" and seed_file):
        from pathlib import Path

        from sqlalchemy.orm import sessionmaker

        from control_centre.db import get_engine
        from control_centre.tenants import seed

        with sessionmaker(bind=get_engine())() as session:
            added = seed(session, Path(str(seed_file)))
        print(f"tenants added: {', '.join(added) or 'none (all present)'}")
        if args.command == "seed-tenants":
            return 0
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
