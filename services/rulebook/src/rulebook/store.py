"""Catalog storage rules: immutable versions, ID freeze, EN/FR parity, retire-not-delete."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared import OSCAL_NS
from govhub_shared.oscal import (
    OscalValidationError,
    content_hash,
    iter_controls,
    normalize,
    stable_uuid,
    validate,
)
from rulebook.diff import STATUS_PROP, WITHDRAWN, CatalogDiff, diff_catalogs
from rulebook.models import Catalog, CatalogControl, CatalogVersion
from rulebook.semver import SemVer

Lang = Literal["en", "fr"]
LANGS: tuple[Lang, ...] = ("en", "fr")


class StoreError(Exception):
    """Base class; ``status`` is the HTTP status the API maps it to."""

    status = 400

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class InvalidCatalogError(StoreError):
    status = 422


class NotFoundError(StoreError):
    status = 404


class ConflictError(StoreError):
    status = 409


@dataclass
class StoredVersion:
    name: str
    version: str
    lang: Lang
    uuid: str
    content_hash: str
    controls: int
    withdrawn: int
    created: bool
    warnings: list[str] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------------------


def _hub_meta_prop(doc: Mapping[str, Any], name: str) -> str | None:
    for prop in doc["catalog"]["metadata"].get("props", []):
        if prop.get("name") == name and prop.get("ns") == OSCAL_NS:
            return cast(str, prop["value"])
    return None


def _status(control: Mapping[str, Any]) -> str:
    for prop in control.get("props", []):
        if prop.get("name") == STATUS_PROP and prop.get("ns") is None:
            return WITHDRAWN if prop.get("value") == WITHDRAWN else "active"
    return "active"


def _raw_controls(doc: Mapping[str, Any]) -> list[tuple[dict[str, Any], str | None]]:
    out: list[tuple[dict[str, Any], str | None]] = []

    def walk(container: Mapping[str, Any], group_id: str | None) -> None:
        for control in container.get("controls", []):
            out.append((control, group_id))
            walk(control, group_id)
        for group in container.get("groups", []):
            walk(group, group.get("id"))

    walk(doc["catalog"], None)
    return out


def find_control(doc: Mapping[str, Any], control_id: str) -> dict[str, Any] | None:
    for control, _group in _raw_controls(doc):
        if control["id"] == control_id:
            return control
    return None


def _get_catalog(session: Session, name: str) -> Catalog:
    catalog = session.scalar(select(Catalog).where(Catalog.name == name))
    if catalog is None:
        raise NotFoundError(f"catalog {name!r} not found")
    return catalog


def _versions(session: Session, catalog: Catalog, lang: str) -> list[CatalogVersion]:
    return list(
        session.scalars(
            select(CatalogVersion)
            .where(CatalogVersion.catalog_id == catalog.id, CatalogVersion.lang == lang)
            .order_by(CatalogVersion.major, CatalogVersion.minor, CatalogVersion.patch)
        )
    )


def latest_version(session: Session, name: str, lang: str) -> str:
    """The newest stored version of a catalog in one language."""
    rows = _versions(session, _get_catalog(session, name), lang)
    if not rows:
        raise NotFoundError(f"{name} has no {lang} version")
    return rows[-1].version


def get_version(session: Session, name: str, version: str, lang: str) -> CatalogVersion:
    catalog = _get_catalog(session, name)
    row = session.scalar(
        select(CatalogVersion).where(
            CatalogVersion.catalog_id == catalog.id,
            CatalogVersion.version == version,
            CatalogVersion.lang == lang,
        )
    )
    if row is None:
        raise NotFoundError(f"{name} version {version} ({lang}) not found")
    return row


# --- import ----------------------------------------------------------------------------


def _resolve_identity(
    doc: Mapping[str, Any], name: str | None, lang: str | None
) -> tuple[str, Lang, SemVer]:
    errors: list[str] = []
    doc_name, doc_lang = _hub_meta_prop(doc, "catalog-name"), _hub_meta_prop(doc, "language")
    if name and doc_name and name != doc_name:
        errors.append(f"name {name!r} disagrees with metadata catalog-name {doc_name!r}")
    if lang and doc_lang and lang != doc_lang:
        errors.append(f"lang {lang!r} disagrees with metadata language {doc_lang!r}")
    final_name, final_lang = name or doc_name, lang or doc_lang
    if not final_name:
        errors.append("catalog name missing: pass ?name= or a hub catalog-name metadata prop")
    if final_lang not in LANGS:
        errors.append("language must be 'en' or 'fr': pass ?lang= or a hub language prop")
    raw_version = doc["catalog"]["metadata"]["version"]
    try:
        semver = SemVer.parse(raw_version)
    except ValueError as exc:
        errors.append(str(exc))
        semver = SemVer(0, 0, 0)
    if errors:
        raise InvalidCatalogError("catalog identity is invalid", errors)
    return cast(str, final_name), cast(Lang, final_lang), semver


def _freeze_checks(
    previous: Mapping[str, Any], new: Mapping[str, Any], previous_version: str
) -> tuple[list[str], list[str]]:
    """Errors and warnings from comparing a new version with its predecessor."""
    errors: list[str] = []
    warnings: list[str] = []
    old = {c.id: c for c in iter_controls(previous)}
    cur = {c.id: c for c in iter_controls(new)}
    for cid in old:
        if cid not in cur:
            errors.append(
                f"{cid} exists in {previous_version} but is missing: control IDs are frozen; "
                "use retire-control instead of deleting"
            )
    for cid, control in cur.items():
        before = old.get(cid)
        if before is None:
            continue
        old_label, new_label = before.prop("label"), control.prop("label")
        if old_label != new_label:
            warnings.append(
                f"{cid}: ID reused for a different clause label "
                f"({old_label!r} in {previous_version} -> {new_label!r}); "
                "IDs are frozen, so a renumbered clause should normally get a new ID"
            )
        if before.prop(STATUS_PROP) == WITHDRAWN and control.prop(STATUS_PROP) != WITHDRAWN:
            warnings.append(f"{cid}: withdrawn in {previous_version} but active again")
    return errors, warnings


def _parity_checks(
    session: Session, catalog: Catalog, version: str, lang: Lang, doc: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    other_lang: Lang = "fr" if lang == "en" else "en"
    other = session.scalar(
        select(CatalogVersion).where(
            CatalogVersion.catalog_id == catalog.id,
            CatalogVersion.version == version,
            CatalogVersion.lang == other_lang,
        )
    )
    if other is None:
        return [], []
    mine = {c.id: c.prop(STATUS_PROP) for c in iter_controls(doc)}
    theirs = {c.id: c.prop(STATUS_PROP) for c in iter_controls(other.document)}
    errors = []
    if set(mine) != set(theirs):
        errors.append(
            f"EN/FR parity: control IDs differ from the {other_lang} catalog at {version}: "
            f"only here {sorted(set(mine) - set(theirs))}, "
            f"only in {other_lang} {sorted(set(theirs) - set(mine))}"
        )
    warnings = [
        f"{cid}: status differs from the {other_lang} catalog at {version}"
        for cid in sorted(set(mine) & set(theirs))
        if mine[cid] != theirs[cid]
    ]
    return errors, warnings


def store_catalog(
    session: Session,
    document: Mapping[str, Any],
    *,
    name: str | None = None,
    lang: str | None = None,
    created_by: str = "anonymous",
    derived_from: str | None = None,
) -> StoredVersion:
    """Validate and store one catalog version. Stored versions are never modified."""
    try:
        validate(document, "catalog")
        doc = normalize(document, "catalog")
    except OscalValidationError as exc:
        raise InvalidCatalogError(
            "catalog does not validate against OSCAL 1.1.3", exc.errors
        ) from exc
    except (ValueError, TypeError) as exc:
        raise InvalidCatalogError("catalog could not be parsed", [str(exc)]) from exc

    final_name, final_lang, semver = _resolve_identity(doc, name, lang)
    version = str(semver)
    digest = content_hash(doc, "catalog")

    catalog = session.scalar(select(Catalog).where(Catalog.name == final_name))
    if catalog is None:
        catalog = Catalog(name=final_name)
        session.add(catalog)
        session.flush()

    existing_versions = _versions(session, catalog, final_lang)
    for row in existing_versions:
        if row.version == version:
            if row.content_hash == digest:
                return _stored(row, final_name, created=False)
            raise ConflictError(
                f"{final_name} {version} ({final_lang}) already exists with different content; "
                "stored versions are immutable, publish a new version instead"
            )
    errors: list[str] = []
    warnings: list[str] = []
    if existing_versions:
        latest = existing_versions[-1]
        if SemVer(latest.major, latest.minor, latest.patch) > semver:
            raise ConflictError(
                f"{version} is older than the latest stored version {latest.version} "
                f"of {final_name} ({final_lang}); versions must increase"
            )
        e, w = _freeze_checks(latest.document, doc, latest.version)
        errors += e
        warnings += w
    e, w = _parity_checks(session, catalog, version, final_lang, doc)
    errors += e
    warnings += w
    if errors:
        raise InvalidCatalogError("catalog violates rulebook rules", errors)

    row = CatalogVersion(
        catalog=catalog,
        version=version,
        major=semver.major,
        minor=semver.minor,
        patch=semver.patch,
        lang=final_lang,
        document=doc,
        content_hash=digest,
        doc_uuid=doc["catalog"]["uuid"],
        created_by=created_by,
        derived_from=derived_from,
    )
    session.add(row)
    session.flush()
    for position, (control, group_id) in enumerate(_raw_controls(doc)):
        label = next(
            (
                p["value"]
                for p in control.get("props", [])
                if p["name"] == "label" and "ns" not in p
            ),
            None,
        )
        session.add(
            CatalogControl(
                version_id=row.id,
                control_id=control["id"],
                group_id=group_id,
                label=label,
                status=_status(control),
                position=position,
            )
        )
    session.flush()
    return _stored(row, final_name, created=True, warnings=warnings)


def _stored(
    row: CatalogVersion, name: str, *, created: bool, warnings: list[str] | None = None
) -> StoredVersion:
    controls = _raw_controls(row.document)
    return StoredVersion(
        name=name,
        version=row.version,
        lang=cast(Lang, row.lang),
        uuid=row.doc_uuid,
        content_hash=row.content_hash,
        controls=len(controls),
        withdrawn=sum(_status(c) == WITHDRAWN for c, _ in controls),
        created=created,
        warnings=warnings or [],
    )


# --- queries ---------------------------------------------------------------------------


def list_catalogs(session: Session) -> list[dict[str, Any]]:
    result = []
    for catalog in session.scalars(select(Catalog).order_by(Catalog.name)):
        by_version: dict[str, dict[str, Any]] = {}
        rows = sorted(catalog.versions, key=lambda r: (r.major, r.minor, r.patch, r.lang))
        for row in rows:
            entry = by_version.setdefault(
                row.version, {"version": row.version, "langs": [], "derived_from": None}
            )
            entry["langs"].append(row.lang)
            entry["derived_from"] = entry["derived_from"] or row.derived_from
        versions = list(by_version.values())
        result.append(
            {
                "name": catalog.name,
                "latest": versions[-1]["version"] if versions else None,
                "versions": versions,
            }
        )
    return result


def get_control(
    session: Session,
    control_id: str,
    *,
    version: str | None,
    catalog_name: str | None,
    lang: str,
) -> dict[str, Any]:
    query = (
        select(CatalogControl, CatalogVersion, Catalog)
        .join(CatalogVersion, CatalogControl.version_id == CatalogVersion.id)
        .join(Catalog, CatalogVersion.catalog_id == Catalog.id)
        .where(CatalogControl.control_id == control_id, CatalogVersion.lang == lang)
    )
    if version is not None:
        query = query.where(CatalogVersion.version == version)
    if catalog_name is not None:
        query = query.where(Catalog.name == catalog_name)
    rows = session.execute(query).all()
    if not rows:
        raise NotFoundError(
            f"control {control_id} not found ({lang}, version={version or 'latest'})"
        )
    catalogs = {cat.name for _, _, cat in rows}
    if len(catalogs) > 1:
        raise ConflictError(
            f"control {control_id} exists in several catalogs {sorted(catalogs)}; pass ?catalog="
        )
    ctrl, ver, cat = max(rows, key=lambda r: (r[1].major, r[1].minor, r[1].patch))
    control = find_control(ver.document, control_id)
    return {
        "catalog": cat.name,
        "version": ver.version,
        "lang": ver.lang,
        "group": ctrl.group_id,
        "status": ctrl.status,
        "control": control,
    }


def diff_versions(
    session: Session, name: str, from_version: str, to_version: str, lang: str
) -> CatalogDiff:
    if lang not in LANGS:
        raise InvalidCatalogError("lang must be 'en' or 'fr'")
    before = get_version(session, name, from_version, lang)
    after = get_version(session, name, to_version, lang)
    return diff_catalogs(
        before.document,
        after.document,
        catalog=name,
        lang=lang,
        from_version=from_version,
        to_version=to_version,
    )


# --- retire ----------------------------------------------------------------------------


def _withdrawn_copy(
    document: Mapping[str, Any], control_id: str, new_version: str, now: datetime
) -> dict[str, Any]:
    doc = copy.deepcopy(dict(document))
    control = find_control(doc, control_id)
    assert control is not None  # noqa: S101 - checked by the caller
    props = [
        p for p in control.get("props", []) if not (p["name"] == STATUS_PROP and "ns" not in p)
    ]
    props.append({"name": STATUS_PROP, "value": WITHDRAWN})
    control["props"] = props
    metadata = doc["catalog"]["metadata"]
    metadata["version"] = new_version
    metadata["last-modified"] = now.isoformat()
    normalized = normalize(doc, "catalog")
    normalized["catalog"]["uuid"] = stable_uuid(
        "oscal-catalog", content_hash(normalized, "catalog")
    )
    return normalized


def retire_control(
    session: Session,
    name: str,
    version: str,
    control_id: str,
    *,
    created_by: str = "anonymous",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create the next minor version, in every language present, with the control withdrawn."""
    catalog = _get_catalog(session, name)
    sources: dict[Lang, CatalogVersion] = {}
    for lang in LANGS:
        rows = _versions(session, catalog, lang)
        match = next((r for r in rows if r.version == version), None)
        if match is None:
            continue
        if rows[-1].version != version:
            raise ConflictError(
                f"{version} is not the latest {lang} version ({rows[-1].version}); "
                "retire from the latest version"
            )
        sources[lang] = match
    if not sources:
        raise NotFoundError(f"{name} version {version} not found")

    for lang, row in sources.items():
        control = find_control(row.document, control_id)
        if control is None:
            raise NotFoundError(f"control {control_id} not found in {name} {version} ({lang})")
        if _status(control) == WITHDRAWN:
            raise ConflictError(f"control {control_id} is already withdrawn in {version} ({lang})")

    new_version = str(SemVer.parse(version).next_minor())
    stamp = (now or datetime.now(UTC)).replace(microsecond=0)
    stored = [
        store_catalog(
            session,
            _withdrawn_copy(row.document, control_id, new_version, stamp),
            name=name,
            lang=lang,
            created_by=created_by,
            derived_from=f"retire {control_id} from {version}",
        )
        for lang, row in sources.items()
    ]
    return {
        "catalog": name,
        "from_version": version,
        "version": new_version,
        "control_id": control_id,
        "langs": [s.lang for s in stored],
        "warnings": [w for s in stored for w in s.warnings],
    }
