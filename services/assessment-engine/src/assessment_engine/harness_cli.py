"""``assessment-engine accuracy ...`` commands."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

from assessment_engine import harness
from assessment_engine.controls import FileControls
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import NullGateway, RecordedGateway, gateway_from_env


def golden_set_status(path: Path) -> str:
    if not path.is_file():
        return "DRAFT GOLDEN SET"
    return str(tomllib.loads(path.read_text("utf-8")).get("golden_set", "DRAFT GOLDEN SET"))


def accuracy(args: argparse.Namespace) -> int:
    if args.accuracy_command != "run":
        return 2
    gateway = gateway_from_env()
    if isinstance(gateway, NullGateway):
        print("No model: set MODEL_GATEWAY_URL (live) or MODEL_GATEWAY_RECORDINGS (replay).")
        return 2
    cases_path = Path(args.cases)
    cases = harness.load_cases(cases_path)
    config = load_config(Path(args.config))
    source = FileControls(*[Path(d) for d in args.catalogs])
    results = [
        harness.run_case(
            case, gateway=gateway, source=source, rules_dir=Path(args.rules), config=config
        )
        for case in cases
    ]
    model_ids = sorted({r.model_id for r in results if r.model_id})
    info = harness.RunInfo(
        model_id=", ".join(model_ids) or "none",
        prompt_version=config.prompt_version,
        gateway="recorded replies" if isinstance(gateway, RecordedGateway) else "live server",
        hardware=args.hardware,
        golden_set_status=golden_set_status(Path(args.status_file)),
        cases_file=str(cases_path),
        cases_sha256=harness.sha256_file(cases_path),
    )
    run = harness.report(results, info)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{info.model_id}-{info.prompt_version}")
    stem = f"{info.started[:10]}-{slug}-{cases_path.parent.name}"
    (out / f"{stem}.json").write_text(json.dumps(run, indent=1) + "\n", "utf-8")
    summary = harness.markdown(run)
    (out / f"{stem}.md").write_text(summary, "utf-8")
    print(summary)
    print(f"Run written to {out / stem}.json")
    return 0
