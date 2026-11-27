"""Command-line entry point: ``review-desk <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def _log_command(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from sqlalchemy.orm import sessionmaker

    from review_desk import decision_log
    from review_desk.db import get_engine

    if args.command == "verify-log" and args.file:
        entries = decision_log.file_entries(
            Path(args.file).read_text(encoding="utf-8").splitlines()
        )
        result = decision_log.verify_entries(
            entries, expect_seq=args.expect_seq, expect_head=args.expect_head
        )
        print(json.dumps(result.as_dict(), indent=2))
        return 0 if result.ok else 1
    with sessionmaker(bind=get_engine())() as session:
        if args.command == "verify-log":
            result = decision_log.verify_db(
                session, expect_seq=args.expect_seq, expect_head=args.expect_head
            )
            print(json.dumps(result.as_dict(), indent=2))
            return 0 if result.ok else 1
        if args.command == "checkpoint":
            print(json.dumps(decision_log.checkpoint(session), indent=2))
            return 0
        lines = "\n".join(decision_log.export_lines(session)) + "\n"
        if args.out:
            Path(args.out).write_text(lines, encoding="utf-8")
        else:
            print(lines, end="")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review-desk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--migrate", action="store_true", help="Apply migrations first")
    sub.add_parser("migrate", help="Apply database migrations")
    verify = sub.add_parser(
        "verify-log", help="Verify the hash-chained decision log (database or exported file)"
    )
    verify.add_argument("--file", help="Exported JSON Lines file (default: the database)")
    verify.add_argument("--expect-seq", type=int, help="Checkpoint sequence number")
    verify.add_argument("--expect-head", help="Checkpoint head hash")
    export = sub.add_parser("export-log", help="Export the decision log as JSON Lines")
    export.add_argument("--out", help="Output file (default: stdout)")
    sub.add_parser("checkpoint", help="Print the current head (seq, hash) of the log")
    args = parser.parse_args(argv)
    if args.command in ("verify-log", "export-log", "checkpoint"):
        return _log_command(args)
    if args.command == "migrate" or (args.command == "serve" and args.migrate):
        from review_desk.migrate import upgrade

        upgrade()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("review_desk.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
