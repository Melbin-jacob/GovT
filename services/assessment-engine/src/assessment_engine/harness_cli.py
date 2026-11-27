"""``assessment-engine accuracy ...`` commands."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from assessment_engine import draft_harness, gate, harness
from assessment_engine.controls import FileControls
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import NullGateway, RecordedGateway, gateway_from_env


def golden_set_status(path: Path) -> str:
    if not path.is_file():
        return "DRAFT GOLDEN SET"
    return str(tomllib.loads(path.read_text("utf-8")).get("golden_set", "DRAFT GOLDEN SET"))


def _gate(args: argparse.Namespace) -> int:
    run = json.loads(Path(args.run).read_text("utf-8"))
    path = Path(args.baseline)
    current = json.loads(path.read_text("utf-8")) if path.is_file() else None
    if args.accuracy_command == "baseline":
        baseline = gate.baseline_from(run, args.scores)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(gate.new_baseline_file(current, baseline), indent=1) + "\n", "utf-8"
        )
        print(f"baseline set from {args.run} ({baseline['golden_set_status']}) in {path}")
        return 0
    result = gate.check(run, current, args.scores)
    print(json.dumps(result, indent=1))
    print("RELEASE GATE: " + ("PASSED" if result["passed"] else "FAILED"))
    return 0 if result["passed"] else 1


def _draft_run(args: argparse.Namespace) -> int:
    gateway = gateway_from_env()
    if isinstance(gateway, NullGateway):
        print("No model: set MODEL_GATEWAY_URL (live) or MODEL_GATEWAY_RECORDINGS (replay).")
        return 2
    cases_path = Path(args.cases)
    cases = draft_harness.load_cases(cases_path)
    folder = Path(args.batches) if args.batches else cases_path.parent / "batches"
    batches = {p.stem: draft_harness.load_batch(p) for p in sorted(folder.glob("*.json"))}
    config = load_config(Path(args.config))
    proposals = draft_harness.run(cases, batches, gateway, config)
    model_ids = sorted({p.model_id for p in proposals if p.model_id})
    info = harness.RunInfo(
        model_id=", ".join(model_ids) or "none",
        prompt_version=config.drafting_prompt_version,
        gateway="recorded replies" if isinstance(gateway, RecordedGateway) else "live server",
        hardware=args.hardware,
        golden_set_status=golden_set_status(Path(args.status_file)),
        cases_file=str(cases_path),
        cases_sha256=harness.sha256_file(cases_path),
    )
    run = draft_harness.report(cases, proposals, info)
    return _write(run, draft_harness.markdown(run), info, cases_path, "drafting", args)


def _write(
    run: dict[str, Any], summary: str, info: harness.RunInfo, cases_path: Path, kind: str,
    args: argparse.Namespace,
) -> int:  # fmt: skip
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{info.model_id}-{info.prompt_version}")
    folder = cases_path.parent.name
    stem = f"{info.started[:10]}-{slug}-{folder}" + ("" if kind in folder else f"-{kind}")
    (out / f"{stem}.json").write_text(json.dumps(run, indent=1) + "\n", "utf-8")
    (out / f"{stem}.md").write_text(summary, "utf-8")
    print(summary)
    print(f"Run written to {out / stem}.json")
    if args.write_latest:
        Path(args.write_latest).write_text(json.dumps(run, indent=1) + "\n", "utf-8")
    return 0


def accuracy(args: argparse.Namespace) -> int:
    if args.accuracy_command in ("gate", "baseline"):
        return _gate(args)
    if args.accuracy_command == "draft-run":
        return _draft_run(args)
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
    if args.write_latest:
        Path(args.write_latest).write_text(json.dumps(run, indent=1) + "\n", "utf-8")
    return 0
