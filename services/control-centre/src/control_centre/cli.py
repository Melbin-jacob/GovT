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
    fr = sub.add_parser("fr-strings", help="Write the French strings list with provenance")
    fr.add_argument("path", help="e.g. docs/fr-ui-strings.md")
    fr.add_argument("--check", action="store_true", help="Fail if the file is not current")
    args = parser.parse_args(argv)
    if args.command == "fr-strings":
        from pathlib import Path

        from control_centre.i18n import fr_strings_markdown

        text = fr_strings_markdown()
        target = Path(args.path)
        if args.check:
            current = target.read_text("utf-8") if target.is_file() else ""
            if current != text:
                print(f"{target} is stale: run `control-centre fr-strings {target}`")
                return 1
            print(f"{target} is current")
            return 0
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
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
