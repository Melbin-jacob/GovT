#!/usr/bin/env python3
"""Generate the recorded replies of a SCRIPTED FAKE model for the synthetic demo cases.

No real model is involved: each reply below is written by hand to exercise the engine.
For injection cases the fake model *obeys* the injected instruction (worst case), so the
harness and CI show whether the engine's safeguards block it. Replies are keyed by the
exact request, so re-run this script after changing the prompt, retrieval or the cases;
`--check` fails if the committed recordings are stale.

    uv run python scripts/make_synthetic_recordings.py [--check]
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from assessment_engine import harness
from assessment_engine.controls import FileControls
from assessment_engine.passages import injection_flags
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import (
    ChatRequest,
    ChatResponse,
    RecordedGateway,
    TokenLogprob,
)

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data/accuracy/synthetic-demo/cases.csv"
RECORDINGS = ROOT / "data/accuracy/synthetic-demo/recordings"
MODEL = "scripted-fake-v1"

REPLIES = ROOT / "data/accuracy/synthetic-demo/scripted-replies.toml"
Answer = tuple[str, str | None, float, float, str, str]


def _answer(entry: dict[str, Any]) -> Answer:
    return (
        str(entry["verdict"]),
        entry.get("quote"),
        float(entry["self_confidence"]),
        float(entry["token_confidence"]),
        str(entry["reasoning_en"]),
        str(entry["reasoning_fr"]),
    )


_DATA = tomllib.loads(REPLIES.read_text("utf-8"))
SCRIPT: dict[str, Answer] = {cid: _answer(e) for cid, e in _DATA.items()}
HONEST: dict[str, Answer] = {cid: _answer(e["honest"]) for cid, e in _DATA.items() if "honest" in e}


class ScriptedFake:
    """Obeys an injected instruction only if it is actually in the request (worst case)."""

    def __init__(self) -> None:
        self.case = ""

    def chat(self, request: ChatRequest) -> ChatResponse:
        user = request.messages[-1].content
        answer = SCRIPT[self.case]
        if self.case in HONEST and not injection_flags(user):
            answer = HONEST[self.case]
        verdict, quote, self_conf, tok_conf, en, fr = answer
        passage_id = None
        if quote is not None:
            blocks = user.split("<<<EVIDENCE ")[1:]
            for block in blocks:
                pid = block.split("id=", 1)[1].split(">>>", 1)[0]
                body = block.split(">>>", 1)[1].split("<<<END", 1)[0]
                typographic = quote.replace(
                    "'", chr(0x2019)
                )  # evidence uses typographic apostrophes
                if typographic[:30] in body or quote[:30] in body:
                    passage_id = pid
                    break
        reply = {
            "verdict": verdict,
            "confidence": self_conf,
            "cited_passage_id": passage_id,
            "cited_quote": quote or "",
            "reasoning_en": en,
            "reasoning_fr": fr,
        }
        content = json.dumps(reply, ensure_ascii=False)
        head, tail = content.split(f'"{verdict}"', 1)
        tokens = [
            TokenLogprob(token=head + '"', logprob=0.0),
            TokenLogprob(token=verdict, logprob=math.log(tok_conf)),
            TokenLogprob(token='"' + tail, logprob=0.0),
        ]
        return ChatResponse(
            content=content,
            model_id=MODEL,
            logprobs=tokens,
            prompt_tokens=len(user) // 4,
            completion_tokens=len(content) // 4,
            latency_seconds=0.0,
        )


def generate(directory: Path) -> list[str]:
    if directory.exists():
        shutil.rmtree(directory)
    fake = ScriptedFake()
    recorder = RecordedGateway(directory, MODEL, mode="record", inner=fake)
    config = load_config(ROOT / "data/config/assessment.toml")
    source = FileControls(ROOT / "data/demo/catalogs")
    done = []
    for case in harness.load_cases(CASES):
        if case.case_id not in SCRIPT:
            continue
        fake.case = case.case_id
        harness.run_case(
            case, gateway=recorder, source=source, rules_dir=ROOT / "data/rules", config=config
        )
        done.append(case.case_id)
    return done


def main(argv: list[str]) -> int:
    if "--check" in argv:
        with tempfile.TemporaryDirectory() as tmp:
            generate(Path(tmp) / "r")
            fresh = {p.name: p.read_text("utf-8") for p in (Path(tmp) / "r").glob("*.json")}
        current = {p.name: p.read_text("utf-8") for p in RECORDINGS.glob("*.json")}
        if fresh != current:
            print("recordings are stale: run uv run python scripts/make_synthetic_recordings.py")
            return 1
        print(f"{len(current)} recordings are current")
        return 0
    done = generate(RECORDINGS)
    print(f"wrote {len(list(RECORDINGS.glob('*.json')))} recordings for {len(done)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
