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


def _resolve_profile(args: argparse.Namespace) -> int:
    import json

    from govhub_shared.oscal import ProfileResolutionError, dump_json, resolve_profile
    from rulebook.profiles import file_loader

    path = Path(args.profile)
    try:
        result = resolve_profile(
            json.loads(path.read_text(encoding="utf-8")),
            file_loader(path.parent),
            source_href=path.name,
        )
    except ProfileResolutionError as exc:
        print(exc, file=sys.stderr)
        return 2
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.ids:
        print("\n".join(result.control_ids))
    elif args.out:
        Path(args.out).write_text(dump_json(result.catalog), encoding="utf-8")
        print(f"{len(result.control_ids)} controls -> {args.out}", file=sys.stderr)
    else:
        print(dump_json(result.catalog), end="")
    return 0


def _import_source(args: argparse.Namespace) -> int:
    import json
    from datetime import date

    from rulebook.sources.importer import SourceImportError, import_source_file

    status = 0
    for name in args.files:
        path = Path(name)
        try:
            doc, summary = import_source_file(
                path,
                registry_path=Path(args.registry),
                retrieved=date.fromisoformat(args.retrieved) if args.retrieved else None,
                write=not args.check and not args.stdout,
            )
        except (SourceImportError, OSError, ValueError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            status = 2
            continue
        if args.stdout:
            print(doc.to_json(), end="")
            continue
        if args.check:
            meta = Path(summary["metadata"])
            if not meta.is_file() or meta.read_text("utf-8") != doc.metadata_only().to_json():
                print(f"{meta}: out of date (re-run without --check)", file=sys.stderr)
                status = max(status, 1)
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the rulebook API")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--migrate", action="store_true", help="Apply database migrations before serving"
    )
    sub.add_parser("migrate", help="Apply database migrations (alembic upgrade head)")

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

    resolve = sub.add_parser(
        "resolve-profile", help="Resolve an OSCAL profile (local files only) to a flat catalog"
    )
    resolve.add_argument("profile", help="Path to the profile JSON")
    resolve.add_argument("--out", help="Write the resolved catalog here instead of stdout")
    resolve.add_argument("--ids", action="store_true", help="Print only the control IDs")

    guard = sub.add_parser(
        "check-source-date",
        help="Fail if a commit changed a golden-set CSV without advancing SOURCE_DATE",
    )
    guard.add_argument("--base", help="Exclusive base revision (default: whole history)")
    guard.add_argument("--head", default="HEAD")
    guard.add_argument("--repo", default=".")
    guard.add_argument("--name", action="append", help="Golden-set name (default: all)")

    src = sub.add_parser(
        "import-source",
        help="Extract clauses from a local copy of a policy instrument (no network)",
    )
    src.add_argument("files", nargs="+", help="<instrument>.<YYYY-MM-DD>.<en|fr>.<html|txt>")
    src.add_argument("--registry", default="data/sources/instruments.toml")
    src.add_argument("--retrieved", help="Date the page was saved (YYYY-MM-DD)")
    src.add_argument(
        "--stdout", action="store_true", help="Print the full document instead of writing files"
    )
    src.add_argument(
        "--check", action="store_true", help="Write nothing; exit 1 if *.meta.json is stale"
    )
    sub.add_parser("source-schema", help="Print the source-document JSON Schema")

    args = parser.parse_args(argv)
    if args.command == "import-source":
        return _import_source(args)
    if args.command == "source-schema":
        from rulebook.sources.model import json_schema

        print(json_schema(), end="")
        return 0
    if args.command == "check-source-date":
        from rulebook.source_date_check import GOLDEN_DIR
        from rulebook.source_date_check import main as check_main

        repo = Path(args.repo)
        names = args.name or sorted(
            p.name.removesuffix(".settings.toml")
            for p in (repo / GOLDEN_DIR).glob("*.settings.toml")
        )
        return check_main(repo, args.base or None, args.head, names)
    if args.command == "resolve-profile":
        return _resolve_profile(args)
    if args.command == "import-golden":
        return _import_golden(args)
    if args.command == "migrate" or (args.command == "serve" and args.migrate):
        from rulebook.migrate import upgrade

        upgrade()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("rulebook.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
