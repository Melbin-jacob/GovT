"""Human approval of drafted control changes, and publishing the new catalog version.

- Edit: a reviewer or governance officer writes or corrects a language's draft (and may
  change a proposed ID, which must never have been used). Needs-human drafts must be
  edited before approval.
- Approve / reject: governance officer only. **Two-person rule:** whoever last edited a
  draft cannot approve it. English and French must agree on check type and obligation.
- Publish: once every item is approved or rejected, the approved changes become a new
  immutable minor version, built from golden-set rows by the importer's own code. Its
  SOURCE_DATE defaults to the later of the new source version's effective date and the
  previous SOURCE_DATE plus one day; any date not later than the previous one is refused
  (the SOURCE_DATE guard would refuse it too). The version carries the approval-log head;
  the log head also goes to a checkpoint file outside the database.

Every action is a record in the hash-chained approval log. Approval does not make a
control "reviewed": that stays the annotators' agreed wording.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from rulebook import approval_log, catalog_rows, drafts, store
from rulebook.golden import LANGS
from rulebook.identity import APPROVER_ROLE, EDITOR_ROLES, Actor
from rulebook.models import DraftBatch, DraftItem
from rulebook.parity import require_parity
from rulebook.sources import store as source_store

_TOKEN = re.compile(r"^[^\W\d][\w.\-]*$")
READY_STATES = ("drafted", "edited", "ready")


class ApprovalError(ValueError):
    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _log(
    session: Session,
    batch: DraftBatch,
    item: DraftItem | None,
    action: str,
    actor: Actor,
    **details: Any,
) -> Any:
    return approval_log.append(
        session,
        {
            "action": action,
            "batch": batch.id,
            "item": item.id if item else None,
            "by": actor.id,
            "role": actor.role,
            "timestamp": datetime.now(UTC).isoformat(),
            **details,
        },
        batch_id=batch.id,
        item_id=item.id if item else None,
    )


def _open(batch: DraftBatch, item: DraftItem | None = None) -> None:
    if batch.status != "open":
        raise ApprovalError(409, f"batch is {batch.status}", "batch-closed")
    if item is not None and item.status in ("approved", "rejected"):
        raise ApprovalError(409, f"item is already {item.status}", "item-decided")


def edit(
    session: Session,
    batch: DraftBatch,
    item: DraftItem,
    actor: Actor,
    languages: dict[str, dict[str, Any]],
    proposed_id: str | None = None,
) -> DraftItem:
    if actor.role not in EDITOR_ROLES:
        raise ApprovalError(403, "only reviewers and governance officers edit drafts", "role")
    _open(batch, item)
    if item.kind not in ("edit", "new") and languages:
        raise ApprovalError(409, f"{item.kind} items have no wording to edit", "no-wording")
    if proposed_id is not None and proposed_id != item.proposed_id:
        if item.kind != "new":
            raise ApprovalError(409, "only new controls get a proposed ID", "not-new")
        used, _ = drafts._all_ids(session, batch.catalog)
        if not _TOKEN.match(proposed_id) or proposed_id in used:
            raise ApprovalError(
                422, f"{proposed_id} is not a valid ID or has been used before", "id-used"
            )
        item.proposed_id = proposed_id
    new = dict(item.drafts)
    for lang, fields in languages.items():
        if lang not in LANGS:
            raise ApprovalError(422, f"unknown language {lang}", "lang")
        previous = new.get(lang, {})
        suggestion = (
            previous.get("statement")
            if previous.get("source") == "model"
            else previous.get("model_suggestion")
        )
        new[lang] = {
            **previous,
            **fields,
            "status": "edited",
            "source": "person",
            "edited_by": actor.id,
            "model_suggestion": suggestion,
        }
    item.drafts = new
    item.last_edited_by = actor.id
    if all(new.get(la, {}).get("status") in READY_STATES for la in LANGS):
        item.status = "ready"
    _log(session, batch, item, "edited", actor, languages=languages, proposed_id=item.proposed_id)
    return item


def _check_ready(item: DraftItem) -> None:
    if item.status != "ready":
        raise ApprovalError(409, "the item is not ready: both languages need a draft", "not-ready")
    if item.kind not in ("edit", "new"):
        return
    en, fr = item.drafts["en"], item.drafts["fr"]
    for lang, d in (("en", en), ("fr", fr)):
        if d.get("status") not in ("drafted", "edited"):
            raise ApprovalError(409, f"the {lang} draft needs a person to write it", "needs-human")
        if not d.get("no_change") and not d.get("statement"):
            raise ApprovalError(409, f"the {lang} draft has no statement", "no-statement")
    if bool(en.get("no_change")) != bool(fr.get("no_change")):
        raise ApprovalError(422, "English and French disagree on 'no change'", "languages-differ")
    for name in ("obligation", "check_type"):
        if en.get(name) != fr.get(name):
            raise ApprovalError(
                422, f"English and French drafts give a different {name}", "languages-differ"
            )
    if item.kind == "new" and not en.get("check_type"):
        raise ApprovalError(422, "a new control needs a check type", "no-check-type")


def decide(
    session: Session, batch: DraftBatch, item: DraftItem, actor: Actor, action: str, reason: str
) -> DraftItem:
    if actor.role != APPROVER_ROLE:
        raise ApprovalError(403, "only a governance officer approves or rejects drafts", "role")
    _open(batch, item)
    if action == "approve":
        if item.last_edited_by and item.last_edited_by == actor.id:
            raise ApprovalError(
                409,
                f"two-person rule: {actor.id} last edited this draft and cannot also approve it",
                "two-person-rule",
            )
        _check_ready(item)
        item.status = "approved"
    elif action == "reject":
        if not reason.strip():
            raise ApprovalError(422, "a rejection needs a reason", "reason")
        item.status = "rejected"
    else:
        raise ApprovalError(422, f"unknown action {action}", "action")
    item.decided_by = actor.id
    record = _log(
        session,
        batch,
        item,
        f"{action}d",
        actor,
        reason=reason,
        drafts=item.drafts if action == "approve" else None,
    )
    item.drafts = {**item.drafts, "_decision": {"seq": record.seq, "hash": record.record_hash}}
    return item


def source_date_bounds(session: Session, batch: DraftBatch) -> dict[str, str]:
    """Previous SOURCE_DATE (exclusive minimum) and the default for the new version."""
    base = store.get_version(session, batch.catalog, batch.base_version, "en").document
    previous = datetime.fromisoformat(base["catalog"]["metadata"]["last-modified"])
    effective = datetime.combine(date.fromisoformat(batch.to_version), time(), UTC)
    next_day = datetime.combine(previous.date() + timedelta(days=1), time(), UTC)
    default = max(effective, next_day)
    return {
        "previous": previous.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "default": default.isoformat().replace("+00:00", "Z"),
    }


def check_source_date(session: Session, batch: DraftBatch, value: str) -> datetime:
    try:
        chosen = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalError(422, f"{value!r} is not an ISO 8601 date-time", "source-date") from exc
    if chosen.tzinfo is None:
        raise ApprovalError(422, "the source date needs a time zone (e.g. Z)", "source-date")
    previous = datetime.fromisoformat(source_date_bounds(session, batch)["previous"])
    if chosen <= previous:
        raise ApprovalError(
            422,
            f"the source date must be later than the previous one ({previous.isoformat()}); "
            "the SOURCE_DATE guard refuses any other",
            "source-date",
        )
    return chosen.astimezone(UTC).replace(microsecond=0)


def _drafted_by(item: DraftItem) -> str:
    if item.kind in ("reference", "retire"):
        return "rulebook clause diff (plain code)"
    parts = []
    for lang in LANGS:
        d = item.drafts[lang]
        model = d.get("model_id")
        text = (
            f"{lang}: model {model}, prompt {d.get('prompt_version')}"
            if model
            else f"{lang}: person"
        )
        if d.get("source") == "person":
            text += f", edited by {d.get('edited_by')}"
        parts.append(text)
    return "; ".join(parts)


def change_set(
    session: Session, batch: DraftBatch, source_date: datetime, head: str
) -> dict[str, Any]:
    items = [i for i in drafts.items_of(session, batch.id) if i.status == "approved"]
    used_groups = {i.group_key for i in items if i.kind == "new"}
    hashes = {}
    for lang in LANGS:
        doc = source_store.get_source(session, batch.instrument, batch.to_version, lang)
        if doc.file is not None:
            hashes[lang] = doc.file.sha256
    changes = []
    for item in items:
        en, fr = item.drafts["en"], item.drafts["fr"]
        decision = item.drafts.get("_decision", {})
        change: dict[str, Any] = {
            "kind": item.kind,
            "control_id": item.target_control or item.proposed_id,
            "source_clauses": item.new_clauses,
            "drafted_by": _drafted_by(item),
            "approved_by": item.decided_by,
            "approval_record": f"approval-log seq {decision.get('seq')} {decision.get('hash')}",
        }
        if item.kind in ("edit", "new"):
            change.update(
                no_change=bool(en.get("no_change")),
                statement={"en": en.get("statement"), "fr": fr.get("statement")},
                guidance={"en": en.get("guidance"), "fr": fr.get("guidance")},
                objective={"en": en.get("objective"), "fr": fr.get("objective")},
                check_type=en.get("check_type"),
                obligation=en.get("obligation"),
            )
        if item.kind == "new":
            group = item.group_key or ""
            change["group"] = batch.plan["new_groups"].get(group, {}).get("key") or _section(
                session, batch, group
            )
            change["clause"] = item.new_clauses[0]
        changes.append(change)
    return {
        "format": catalog_rows.FORMAT,
        "catalog": batch.catalog,
        "batch": batch.id,
        "base_version": batch.base_version,
        "new_version": batch.plan["proposed_version"],
        "source_date": source_date.isoformat().replace("+00:00", "Z"),
        "source_instrument": batch.instrument,
        "source_version": batch.to_version,
        "source_hashes": hashes,
        "approval_log_head": head,
        "new_groups": {g: v for g, v in batch.plan["new_groups"].items() if g in used_groups},
        "changes": changes,
    }


def _section(session: Session, batch: DraftBatch, group_id: str) -> str:
    base = store.get_version(session, batch.catalog, batch.base_version, "en").document
    for group in base["catalog"]["groups"]:
        if group["id"] == group_id:
            return str(next(p["value"] for p in group.get("props", []) if p["name"] == "label"))
    raise ApprovalError(409, f"unknown group {group_id}", "group")


def publish(
    session: Session, batch: DraftBatch, actor: Actor, source_date: str, checkpoint_file: str
) -> dict[str, Any]:
    if actor.role != APPROVER_ROLE:
        raise ApprovalError(403, "only a governance officer publishes a version", "role")
    _open(batch)
    items = drafts.items_of(session, batch.id)
    undecided = [i.seq for i in items if i.status not in ("approved", "rejected")]
    if undecided:
        raise ApprovalError(409, f"items {undecided} are not approved or rejected yet", "undecided")
    chosen = check_source_date(session, batch, source_date)
    last = approval_log.entries(session)[-1]
    head = f"seq {last.seq} {last.record_hash}"
    changes = change_set(session, batch, chosen, head)
    docs = {
        lang: store.get_version(session, batch.catalog, batch.base_version, lang).document
        for lang in LANGS
    }
    rows, groups, settings, source_name = catalog_rows.rows_from_catalogs(docs)
    rows, groups, settings = catalog_rows.apply_change_set(rows, groups, settings, changes)
    numbers = {
        c.number
        for c in source_store.get_source(session, batch.instrument, batch.to_version, "en").clauses
    }
    # Every active control must link to what the clause diff maps it to: a link to a number
    # that no longer exists, or that now names another clause, is stale.
    expected = batch.plan.get("new_links", {})
    stale = sorted(
        f"{r.check_id} ({', '.join(r.source_clauses)})"
        for r in rows
        if r.status != "withdrawn"
        and r.source_clauses
        and (
            any(n not in numbers for n in r.source_clauses)
            or (r.check_id in expected and sorted(r.source_clauses) != sorted(expected[r.check_id]))
        )
    )
    if stale:
        raise ApprovalError(
            409,
            f"links to clauses that are not in {batch.to_version}: {stale}; approve their "
            "clause-reference updates or retire them",
            "stale-links",
        )
    built = catalog_rows.build(rows, groups, settings, batch.catalog, source_name)
    require_parity(built["en"], built["fr"])
    stored = {
        lang: store.store_catalog(
            session, built[lang], created_by=actor.id, derived_from=f"draft batch {batch.id}"
        )
        for lang in LANGS
    }
    batch.status = "published"
    batch.new_version = changes["new_version"]
    record = _log(
        session,
        batch,
        None,
        "published",
        actor,
        version=changes["new_version"],
        source_date=changes["source_date"],
        content_hashes={lang: stored[lang].content_hash for lang in LANGS},
        approval_log_head=head,
    )
    checkpoint = approval_log.write_checkpoint(checkpoint_file, record)
    return {
        "catalog": batch.catalog,
        "version": changes["new_version"],
        "source_date": changes["source_date"],
        "approval_log_head": head,
        "published_record": {"seq": record.seq, "hash": record.record_hash},
        "checkpoint": checkpoint,
        "change_set": changes,
    }
