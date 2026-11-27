"""Command-line entry point: ``connector-hub <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="connector-hub", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    mock = sub.add_parser(
        "mock-servicenow", help="Run the mock ServiceNow Table API (tests, CI, demo only)"
    )
    mock.add_argument("--host", default="127.0.0.1")
    mock.add_argument("--port", type=int, default=8003)
    mock.add_argument("--seed", default="data/demo/servicenow/seed.json")
    args = parser.parse_args(argv)
    if args.command == "mock-servicenow":
        import uvicorn

        from connector_hub.mock_servicenow import create_app

        uvicorn.run(create_app(args.seed), host=args.host, port=args.port)
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("connector_hub.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
