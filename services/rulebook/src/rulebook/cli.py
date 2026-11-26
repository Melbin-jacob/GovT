"""Command-line entry point: ``rulebook <command>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def _import_golden(args: argparse.Namespace) -> int:
    from rulebook.golden import GoldenImportError, format_summary, import_golden

    try:
        result = import_golden(
            Path(args.csv),
            Path(args.out_dir),
            name=args.name,
            version=args.version,
            groups_path=Path(args.groups) if args.groups else None,
            settings_path=Path(args.settings) if args.settings else None,
            write=not args.check,
        )
    except GoldenImportError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(format_summary(result))
    if args.check and any(result.changed.values()):
        stale = [str(result.paths[lang]) for lang, changed in result.changed.items() if changed]
        print(f"out of date (re-run without --check): {stale}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the rulebook API")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    serve.add_argument("--port", type=int, default=8000)

    golden = sub.add_parser(
        "import-golden", help="Import a golden-set CSV into EN and FR OSCAL catalogs"
    )
    golden.add_argument("csv", help="Path to the golden-set CSV")
    golden.add_argument("--out-dir", default="data/catalogs")
    golden.add_argument("--name", help="Catalog name (default: CSV file name without .csv)")
    golden.add_argument("--version", default="1.0.0", help="Semantic version (default 1.0.0)")
    golden.add_argument("--groups", help="Groups CSV (default: <name>.groups.csv beside the CSV)")
    golden.add_argument(
        "--settings", help="Settings TOML with SOURCE_DATE (default: <name>.settings.toml)"
    )
    golden.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 if the committed catalogs are out of date",
    )

    args = parser.parse_args(argv)
    if args.command == "import-golden":
        return _import_golden(args)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("rulebook.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
