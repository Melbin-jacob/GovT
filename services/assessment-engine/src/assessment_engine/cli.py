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
    fake = sub.add_parser("fake-model", help="Scripted fake model server (demo and CI only)")
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=int, default=8090)
    acc = sub.add_parser("accuracy", help="Accuracy harness (Appendix B)")
    acc_sub = acc.add_subparsers(dest="accuracy_command", required=True)
    run = acc_sub.add_parser("run", help="Run labelled cases through the engine")
    run.add_argument("--cases", required=True, help="Case CSV (see docs/accuracy-cases.md)")
    run.add_argument("--out", default="data/accuracy/runs", help="Directory for the run files")
    run.add_argument("--hardware", default="not described", help="e.g. '8 vCPU, 32 GB RAM'")
    run.add_argument("--status-file", default="data/accuracy/status.toml")
    run.add_argument("--catalogs", nargs="+", default=["data/catalogs", "data/demo/catalogs"])
    run.add_argument("--rules", default="data/rules")
    run.add_argument("--config", default="data/config/assessment.toml")
    run.add_argument("--write-latest", help="Also write the run JSON to this path")
    for name, text in (
        ("gate", "Fail if any measure is below the baseline in either language"),
        ("baseline", "Make a run the new baseline (previous ones are kept as history)"),
    ):
        cmd = acc_sub.add_parser(name, help=text)
        cmd.add_argument("--run", required=True, help="Run JSON from 'accuracy run'")
        cmd.add_argument("--baseline", default="data/accuracy/baseline.json")
        cmd.add_argument(
            "--scores",
            default="human",
            choices=["human", "synthetic-demo"],
            help="Which scores (human for releases; synthetic-demo in CI)",
        )
    args = parser.parse_args(argv)
    if args.command == "accuracy":
        from assessment_engine.harness_cli import accuracy

        return accuracy(args)
    if args.command == "fake-model":
        import uvicorn

        uvicorn.run("assessment_engine.fake_model:app", host=args.host, port=args.port)
        return 0
    if args.command == "migrate" or (args.command == "serve" and args.migrate):
        from assessment_engine.migrate import upgrade

        upgrade()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("assessment_engine.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
