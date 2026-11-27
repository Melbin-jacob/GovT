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


def _suggest(args: argparse.Namespace) -> int:
    from rulebook.golden import GoldenImportError, read_groups, read_rows
    from rulebook.sources.model import SourceDocument
    from rulebook.sources.suggest import suggest, to_csv

    golden = Path(args.golden)
    name = golden.name.removesuffix(".csv")
    try:
        rows, _ = read_rows(golden, read_groups(golden.with_name(f"{name}.groups.csv")))
    except GoldenImportError as exc:
        print(exc, file=sys.stderr)
        return 2
    source = SourceDocument.model_validate_json(Path(args.source).read_text(encoding="utf-8"))
    text = to_csv(suggest(rows, source, lang=args.lang, top=args.top, with_text=args.with_text))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(rows)} checks -> {args.out}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


def _inventory_json(args: argparse.Namespace) -> int:
    from rulebook.inventory import InventoryError, parse_inventory_csv

    path = Path(args.csv)
    try:
        inventory = parse_inventory_csv(path.read_text(encoding="utf-8"), source=path.name)
    except InventoryError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(inventory.model_dump_json(indent=2))
    print(f"{len(inventory.systems)} systems, hash {inventory.content_hash()}", file=sys.stderr)
    return 0


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
    golden.add_argument("--version", help="Semantic version (default: VERSION in settings)")
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
    sug = sub.add_parser(
        "suggest-source-clauses",
        help="Propose source clauses for each golden-set check (review CSV; nothing applied)",
    )
    sug.add_argument("golden", help="Golden-set CSV")
    sug.add_argument("--source", required=True, help="Full source-document JSON (with text)")
    sug.add_argument("--lang", choices=["en", "fr"], default="en")
    sug.add_argument("--top", type=int, default=3)
    sug.add_argument(
        "--with-text",
        action="store_true",
        help="Include clause text excerpts (keep the output out of git for official text)",
    )
    sug.add_argument("--out", help="Write here (default: stdout)")

    invj = sub.add_parser(
        "inventory-json", help="Validate an inventory CSV and print the PUT /inventory payload"
    )
    invj.add_argument("csv")

    args = parser.parse_args(argv)
    if args.command == "inventory-json":
        return _inventory_json(args)
    if args.command == "suggest-source-clauses":
        return _suggest(args)
    if args.command == "import-source":
        return _import_source(args)
    if args.command == "source-schema":
        from rulebook.sources.model import json_schema

        print(json_schema(), end="")
        return 0
    if args.command == "check-source-date":
        from rulebook.source_date_check import discover
        from rulebook.source_date_check import main as check_main

        repo = Path(args.repo)
        sets = [g for g in discover(repo) if not args.name or g.name in args.name]
        return check_main(repo, args.base or None, args.head, sets)
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
