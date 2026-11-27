"""Demo: policy change -> AI drafts -> people approve in the UI -> catalog 1.1.0 -> impact.

Runs against the live stack after the other demos (``make demo-drafts``); it publishes a
new catalog version, so it is skipped unless ``E2E_DRAFTS=1``. Synthetic data only: the
fictional Directive on Example Widgets, drafted by the scripted fake model (recorded
replies served over HTTP, no real model).

Steps: plan and draft in the UI; a reviewer corrects three drafts (a wrong "no change",
a wrong obligation, a French draft the engine left to a person); a governance officer who
edited a draft is refused when approving it (two-person rule, reason shown); approvals;
an invalid SOURCE_DATE is refused before publishing; publish 1.1.0; the impact report of
1.0.0 -> 1.1.0 in English and French. Then API checks: the approval log verifies, the
change set applied to a copy of the golden set re-imports to exactly the stored 1.1.0,
and the source date advanced. Writes evidence to ``E2E_OUTPUT/drafts/``.
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from e2e_support import OUT, Recorder
from playwright.sync_api import Locator, Page, expect

from rulebook.cli import main as rulebook_cli

ROOT = Path(__file__).resolve().parents[3]
RULEBOOK = os.environ.get("RULEBOOK_URL", "http://127.0.0.1:8000").rstrip("/")
DRAFTS_OUT = OUT / "drafts"

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_DRAFTS") != "1",
    reason="publishes a catalog version: run with `make demo-drafts` after the other demos",
)


def item(page: Page, control: str) -> Locator:
    return page.locator("section.draft-item").filter(
        has=page.locator("h2", has_text=f" {control} ")
    )


def act_as(page: Page, person: str) -> None:
    page.select_option("#actor", person)
    page.get_by_role("button", name="Change person").or_(
        page.get_by_role("button", name="Changer de personne")
    ).click()
    expect(page.locator("#actor")).to_have_value(person)


def edit(page: Page, control: str, statement: str, obligation: str | None = None) -> None:
    section = item(page, control)
    section.locator("summary").click()
    section.locator("textarea").fill(statement)
    if obligation:
        section.locator("select[name=obligation]").select_option(obligation)
    section.locator("form[action$='/edit'] button").click()
    expect(page.locator("#notice")).to_be_visible()


def approve(page: Page, control: str) -> None:
    section = item(page, control)
    section.locator("input[name=both_languages]").check()
    section.locator("form[action$='/approve'] button").click()


def test_policy_change_to_new_catalog_version(rec: Recorder) -> None:
    page = rec.page
    DRAFTS_OUT.mkdir(parents=True, exist_ok=True)
    golden_before = tomllib.loads(
        (ROOT / "data/demo/golden/example-widgets.settings.toml").read_text("utf-8")
    )

    # 1. Plan and draft (rulebook plans with plain code; the engine asks the fake model).
    page.goto("/en/drafts")
    act_as(page, "demo-officer-01")
    rec.capture("drafts-list-en")
    page.get_by_role("button", name="Plan and draft").click()
    expect(page.locator("#notice")).to_contain_text("the model's drafts have arrived")
    batch_url = page.url.split("?")[0]
    batch_id = batch_url.rsplit("/", 1)[1]
    expect(page.locator("section.draft-item")).to_have_count(10)
    expect(item(page, "WID-6.1.2")).to_contain_text("Obligation differs from the clause")
    expect(item(page, "WID-6.3.1")).to_contain_text("The model proposes no change of wording.")
    rec.capture("drafts-batch-en")
    page.goto(f"/fr/drafts/{batch_id}")
    expect(item(page, "WID-6.4.2").locator("[data-draft-status]")).to_have_attribute(
        "data-draft-status", "needs-human"
    )
    expect(item(page, "WID-6.4.2")).to_contain_text("la confiance du modèle est inférieure")
    rec.capture("drafts-batch-fr")

    # 2. A reviewer corrects the drafts a person must look at (synthetic wording).
    act_as(page, "demo-reviewer-01")
    edit(page, "WID-6.4.2", "Les ministères font rapport chaque année, pour l'exercice "
         "financier, sur les widgets en service.")  # fmt: skip
    page.goto(f"/en/drafts/{batch_id}")
    edit(page, "WID-6.3.1", "Every calibration is logged, and the calibration log is kept "
         "for two years.")  # fmt: skip
    edit(page, "WID-6.1.2", "The register records the owner, location, model and firmware "
         "version of each widget.", obligation="must")  # fmt: skip
    # The reviewer cannot approve: only a governance officer can.
    approve(page, "WID-6.2.2")
    expect(page.locator("#error")).to_contain_text("Your role cannot do this")

    # 3. Two-person rule: an officer who last edited a draft cannot approve it.
    act_as(page, "demo-officer-01")
    edit(page, "WID-C002", "The widget risk assessment is updated whenever the purpose of "
         "the widget changes.")  # fmt: skip
    expect(item(page, "WID-C002")).to_contain_text("another governance officer must approve")
    approve(page, "WID-C002")
    expect(page.locator("#error")).to_contain_text("Two-person rule: you last edited this draft")
    rec.capture("drafts-two-person-rule-en")

    # 4. Approvals: officer 01 everything except WID-C002, officer 02 that one.
    for control in ("WID-6.1.2", "WID-6.2.1", "WID-6.2.2", "WID-6.2.3", "WID-6.4.1",
                    "WID-6.4.2", "WID-6.3.1", "WID-6.3.2", "WID-C001"):  # fmt: skip
        approve(page, control)
        expect(item(page, control)).to_have_attribute("data-status", "approved")
    act_as(page, "demo-officer-02")
    approve(page, "WID-C002")
    expect(item(page, "WID-C002")).to_contain_text("Approved by demo-officer-02")

    # 5. SOURCE_DATE: the default passes the guard; an earlier date is refused here.
    date_input = page.locator("#source-date")
    expect(date_input).to_have_value("2026-11-29")
    expect(date_input).to_have_attribute("min", "2026-11-29")
    date_input.evaluate("el => el.removeAttribute('min')")  # what a stale browser could send
    date_input.fill("2026-11-28")
    page.get_by_role("button", name="Publish version 1.1.0").click()
    expect(page.locator("#error")).to_contain_text("the SOURCE_DATE guard would refuse it")
    assert httpx.get(f"{RULEBOOK}/drafts/batches/{batch_id}").json()["status"] == "open"
    rec.capture("drafts-ready-to-publish-en")
    page.locator("#source-date").fill("2026-11-29")
    page.get_by_role("button", name="Publish version 1.1.0").click()
    expect(page.locator("[data-published]")).to_have_attribute("data-published", "1.1.0")
    rec.capture("drafts-published-en")

    # 6. The impact report generated from the new version, in English and in French.
    page.get_by_role("link", name="See the impact report for version 1.1.0").first.click()
    expect(page.locator("[data-trigger=catalog]")).to_be_visible()
    rec.capture("impact-catalog-change-en")
    page.goto("/fr/impact?catalog_from=1.0.0&catalog_to=1.1.0")
    expect(page.locator("main")).to_contain_text("Contrôle nouveau dans la version 1.1.0")
    rec.capture("impact-catalog-change-fr")

    _api_checks(batch_id, golden_before)


def _get(path: str, **params: Any) -> Any:
    resp = httpx.get(f"{RULEBOOK}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json() if "json" in resp.headers.get("content-type", "") else resp.text


def _save(name: str, data: Any) -> None:
    text = data if isinstance(data, str) else json.dumps(data, indent=1, ensure_ascii=False)
    (DRAFTS_OUT / name).write_text(text + ("" if text.endswith("\n") else "\n"), "utf-8")


def _api_checks(batch_id: str, golden_before: dict[str, Any]) -> None:
    verify = _get("/drafts/log/verify")
    assert verify["ok"], verify
    batch = _get(f"/drafts/batches/{batch_id}")
    assert batch["status"] == "published" and batch["new_version"] == "1.1.0"
    diff = _get("/catalogs/example-widgets/diff", **{"from": "1.0.0", "to": "1.1.0"})
    assert diff["added"] == ["WID-C001", "WID-C002"] and diff["retired"] == ["WID-6.3.2"]
    report = httpx.post(
        f"{RULEBOOK}/impact-reports",
        json={"catalog": "example-widgets", "catalog_change": {"from": "1.0.0", "to": "1.1.0"},
              "as_of": "2026-12-01", "lang": "en"},
        timeout=30,
    ).json()  # fmt: skip
    affected = {c["id"]: c for c in report["affected_controls"]}
    assert sorted(affected) == ["WID-6.1.2", "WID-6.2.1", "WID-6.3.1", "WID-6.4.2",
                                "WID-C001", "WID-C002"]  # fmt: skip
    assert affected["WID-6.2.1"]["obligation_change"] is True
    assert report["triggers"]["catalog"]["not_reassessed"] == [
        "WID-6.1.1", "WID-6.2.2", "WID-6.2.3", "WID-6.4.1"
    ]  # fmt: skip
    # The golden set stays the record: the change set re-imports to the stored 1.1.0.
    change_set = _get(f"/drafts/batches/{batch_id}/change-set")
    shutil.rmtree(DRAFTS_OUT / "demo", ignore_errors=True)
    for folder in ("golden", "sources"):  # the settings point to ../sources
        shutil.copytree(ROOT / "data/demo" / folder, DRAFTS_OUT / "demo" / folder)
    work = DRAFTS_OUT / "demo" / "golden"
    (DRAFTS_OUT / "change-set.json").write_text(json.dumps(change_set, indent=1), "utf-8")
    status = rulebook_cli(
        ["apply-drafts", str(DRAFTS_OUT / "change-set.json"),
         "--csv", str(work / "example-widgets.csv"), "--out-dir", str(work / "catalogs")]
    )  # fmt: skip
    assert status == 0
    for lang in ("en", "fr"):
        stored = _get("/catalogs/example-widgets/versions/1.1.0", lang=lang)
        built = json.loads((work / "catalogs" / f"example-widgets.{lang}.json").read_text("utf-8"))
        assert built == stored, f"{lang}: the golden set does not re-import to the stored 1.1.0"
        _save(f"catalog-1.1.0.{lang}.json", stored)
    after = tomllib.loads((work / "example-widgets.settings.toml").read_text("utf-8"))
    assert after["SOURCE_DATE"] > golden_before["SOURCE_DATE"], "the SOURCE_DATE guard"
    approved = next(i for i in batch["items"] if i["target_control"] == "WID-6.1.2")
    log = _get("/drafts/log/export")
    entries = [json.loads(line) for line in log.splitlines() if line]
    record = next(
        {**e, "record": json.loads(e["record"])} for e in entries
        if json.loads(e["record"]).get("action") == "approved"
        and json.loads(e["record"]).get("item") == approved["id"]
    )  # fmt: skip
    _save("batch.json", batch)
    _save("catalog-diff-1.0.0-1.1.0.en.json", diff)
    _save("impact-report-1.1.0.en.json", report)
    _save("approval-log.jsonl", log)
    _save(
        "approved-item-WID-6.1.2.json",
        {
            "item": approved,
            "approval_log_record": record,
            "provenance_props": _props(stored_en(), "WID-6.1.2"),
        },
    )
    _save("approval-log-verify.json", verify)
    decided = [(i["target_control"] or i["proposed_id"], i["kind"], i["decided_by"],
                i["last_edited_by"] or "-") for i in batch["items"]]  # fmt: skip
    lines = [
        "## Rulebook drafts demo (synthetic data, scripted fake model)",
        "",
        f"Batch `{batch_id}`: example-widgets 1.0.0, source change 2023-01-01 -> 2025-01-01, "
        f"published as **{batch['new_version']}**; approval log verified.",
        "",
        "| Control | Kind | Approved by | Last edited by |",
        "|---|---|---|---|",
        *[f"| {c} | {k} | {d} | {e} |" for c, k, d, e in decided],
        "",
        f"Catalog diff 1.0.0 -> 1.1.0: {diff['summary']}.",
        f"Impact report `{report['report_id']}`: reassess {sorted(affected)} "
        f"(obligation change: WID-6.2.1); not reassessed (renumbering or record-keeping "
        f"only): {report['triggers']['catalog']['not_reassessed']}.",
        "The change set applied to a copy of the golden set re-imports to exactly the stored "
        f"1.1.0; SOURCE_DATE {golden_before['SOURCE_DATE']} -> {after['SOURCE_DATE']}.",
    ]
    _save("summary.md", "\n".join(lines))


def stored_en() -> dict[str, Any]:
    data: dict[str, Any] = _get("/catalogs/example-widgets/versions/1.1.0", lang="en")
    return data


def _props(doc: dict[str, Any], control_id: str) -> list[dict[str, Any]]:
    for group in doc["catalog"].get("groups", []):
        for control in group.get("controls", []):
            if control["id"] == control_id:
                return list(control.get("props", []))
    return []
