"""``data/config/assessment.toml`` (PLACEHOLDER thresholds until the organization sets them)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AssessmentConfig:
    threshold: float = 0.70
    threshold_status: str = "PLACEHOLDER"
    by_language: dict[str, float] = field(default_factory=dict)
    passages: int = 5
    min_quote_chars: int = 15
    prompt_version: str = "assess-v1"
    drafting_threshold: float = 0.70
    drafting_prompt_version: str = "draft-v1"

    def threshold_for(self, lang: str) -> float:
        return self.by_language.get(lang, self.threshold)


def load_config(path: Path) -> AssessmentConfig:
    if not path.is_file():
        return AssessmentConfig()
    data = tomllib.loads(path.read_text("utf-8"))
    confidence = data.get("confidence", {})
    return AssessmentConfig(
        threshold=float(confidence.get("threshold", 0.70)),
        threshold_status=str(confidence.get("status", "PLACEHOLDER")),
        by_language={k: float(v) for k, v in confidence.get("by_language", {}).items()},
        passages=int(data.get("retrieval", {}).get("passages", 5)),
        min_quote_chars=int(data.get("retrieval", {}).get("min_quote_chars", 15)),
        prompt_version=str(data.get("prompt", {}).get("version", "assess-v1")),
        drafting_threshold=float(data.get("drafting", {}).get("threshold", 0.70)),
        drafting_prompt_version=str(data.get("drafting", {}).get("prompt_version", "draft-v1")),
    )
