"""Rule-based checks: plain code against a system's recorded facts. No model involved.

Rules live in ``data/rules/<catalog>.rules.toml`` (unverified drafts until the annotators
confirm them; see the header of those files for the logic). Evaluation is three-valued:
a missing fact makes the check *unable to determine*, never a guess.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from assessment_engine import messages as msg


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    value: Any
    source: str = ""


@dataclass
class RuleSet:
    catalog: str
    status: str
    facts: dict[str, dict[str, str]]
    rules: dict[str, dict[str, Any]]
    path: str


@dataclass
class RuleOutcome:
    control_id: str
    verdict: str
    confidence: float | None
    rationale: dict[str, str]
    facts_used: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    rule_status: str = "unverified-draft"

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "method": "rule",
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "facts_used": self.facts_used,
            "missing_facts": self.missing,
            "rule_status": self.rule_status,
        }


def load_rules(rules_dir: Path, catalog: str) -> RuleSet | None:
    path = rules_dir / f"{catalog}.rules.toml"
    if not path.is_file():
        return None
    data = tomllib.loads(path.read_text("utf-8"))
    rules = {str(r["control"]): r for r in data.get("rule", [])}
    return RuleSet(
        catalog=str(data["meta"]["catalog"]),
        status=str(data["meta"].get("status", "unverified-draft")),
        facts=data.get("facts", {}),
        rules=rules,
        path=str(path),
    )


def referenced_facts(condition: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(condition, dict):
        if "fact" in condition:
            out.add(str(condition["fact"]))
        if "within_days_fact" in condition:
            out.add(str(condition["within_days_fact"]))
        for key in ("before",):
            out.update(str(x) for x in condition.get(key, []))
        for key in ("all", "any"):
            for sub in condition.get(key, []):
                out |= referenced_facts(sub)
        if "not" in condition:
            out |= referenced_facts(condition["not"])
    return out


class _MissingFactError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name


def _date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RuleError(f"fact {name} is not a date (YYYY-MM-DD): {value!r}") from exc


def evaluate(condition: dict[str, Any], facts: dict[str, Fact], as_of: date) -> bool | None:
    """True, False, or None when a needed fact is missing."""
    used: set[str] = set()
    try:
        return _eval(condition, facts, as_of, used)
    except _MissingFactError:
        return None


def _get(facts: dict[str, Fact], name: str, used: set[str]) -> Any:
    fact = facts.get(name)
    if fact is None or fact.value is None:
        raise _MissingFactError(name)
    used.add(name)
    return fact.value


def _eval(c: dict[str, Any], facts: dict[str, Fact], as_of: date, used: set[str]) -> bool:
    if "all" in c:
        results = [_eval(x, facts, as_of, used) for x in c["all"]]
        return all(results)
    if "any" in c:
        results = []
        missing: _MissingFactError | None = None
        for x in c["any"]:
            try:
                results.append(_eval(x, facts, as_of, used))
            except _MissingFactError as exc:
                missing = exc
        if any(results):
            return True
        if missing is not None:
            raise missing
        return False
    if "not" in c:
        return not _eval(c["not"], facts, as_of, used)
    if "before" in c:
        a, b = c["before"]
        return _date(_get(facts, a, used), a) <= _date(_get(facts, b, used), b)
    name = str(c["fact"])
    value = _get(facts, name, used)
    if "equals" in c:
        return bool(value == c["equals"])
    if "is_true" in c:
        return bool(value is True) == bool(c["is_true"])
    if "exists" in c:
        return True
    if "at_least" in c:
        return float(value) >= float(c["at_least"])
    if "at_most" in c:
        return float(value) <= float(c["at_most"])
    if "within_days" in c:
        return as_of - _date(value, name) <= timedelta(days=int(c["within_days"]))
    if "within_days_fact" in c:
        days = int(_get(facts, str(c["within_days_fact"]), used))
        return as_of - _date(value, name) <= timedelta(days=days)
    raise RuleError(f"unknown condition {sorted(c)}")


def _facts_text(ruleset: RuleSet, names: list[str], facts: dict[str, Fact], lang: str) -> str:
    parts = []
    for name in names:
        label = ruleset.facts.get(name, {}).get(lang, name)
        fact = facts[name]
        values = {"label": label, "value": msg.value(fact.value, lang)}
        if fact.source:
            parts.append(msg.render("fact", lang, **values, source=fact.source))
        else:
            parts.append(msg.render("fact.no-source", lang, **values))
    return msg.join(parts, lang)


def assess_rule(
    ruleset: RuleSet | None, control_id: str, facts: dict[str, Fact], as_of: date
) -> RuleOutcome:
    rule = ruleset.rules.get(control_id) if ruleset else None
    if ruleset is None or rule is None:
        text = {lang: msg.render("rule.no-rule", lang) for lang in msg.LANGS}
        return RuleOutcome(control_id, "unable-to-determine", None, text)
    status = ruleset.status
    if rule.get("rollup"):
        text = {lang: msg.render("rule.rollup", lang, rule=rule[lang]) for lang in msg.LANGS}
        return RuleOutcome(control_id, "unable-to-determine", None, text, rule_status=status)
    names: set[str] = set()
    for key in ("applies_when", "met", "partial"):
        names |= referenced_facts(rule.get(key))
    present = sorted(n for n in names if n in facts and facts[n].value is not None)
    used = {n: facts[n].value for n in present}

    def outcome(verdict: str, key: str, confidence: float | None) -> RuleOutcome:
        missing = sorted(names - set(present)) if key == "rule.missing" else []
        text = {
            lang: msg.render(
                key,
                lang,
                rule=rule[lang],
                facts=_facts_text(ruleset, present, facts, lang),
                missing=msg.join([ruleset.facts.get(m, {}).get(lang, m) for m in missing], lang),
            )
            for lang in msg.LANGS
        }
        return RuleOutcome(control_id, verdict, confidence, text, used, missing, status)

    applies = rule.get("applies_when")
    if applies is not None:
        result = evaluate(applies, facts, as_of)
        if result is None:
            return outcome("unable-to-determine", "rule.missing", None)
        if result is False:
            return outcome("not-applicable", "rule.not-applicable", 1.0)
    met = evaluate(rule["met"], facts, as_of)
    if met is True:
        return outcome("met", "rule.met", 1.0)
    if met is None:  # never guess between met and the rest
        return outcome("unable-to-determine", "rule.missing", None)
    if "partial" in rule:
        partial = evaluate(rule["partial"], facts, as_of)
        if partial is True:
            return outcome("partially-met", "rule.met", 1.0)
        if partial is None:
            return outcome("unable-to-determine", "rule.missing", None)
    return outcome("not-met", "rule.met", 1.0)
