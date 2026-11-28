"""Set the tenant of rows stored before Milestone 7 (row-level security hides rows with no
tenant). Runs as the database owner: assessments and results documents are immutable, so
their trigger is switched off for this one update; every other column stays as it was."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from assessment_engine.access import SystemDirectory

TABLES = (
    "evidence_documents", "evidence_passages", "system_facts", "assessments",
    "assessment_results_documents",
)  # fmt: skip
IMMUTABLE = ("assessments", "assessment_results_documents")


def backfill(owner_url: str, systems: SystemDirectory) -> dict[str, int]:
    engine = create_engine(owner_url)
    counts: dict[str, int] = {}
    try:
        with engine.begin() as conn:
            for table in TABLES:
                ids = conn.scalars(
                    text(f"SELECT DISTINCT system_id FROM {table} WHERE tenant IS NULL")  # noqa: S608
                ).all()
                if table in IMMUTABLE:
                    conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
                done = 0
                for system_id in ids:
                    tenant = systems.tenant_of(system_id)
                    if tenant is None:
                        continue
                    done += conn.execute(
                        text(f"UPDATE {table} SET tenant = :t "  # noqa: S608 - fixed table names
                             "WHERE system_id = :s AND tenant IS NULL"),
                        {"t": tenant, "s": system_id},
                    ).rowcount  # fmt: skip
                if table in IMMUTABLE:
                    conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
                counts[table] = done
    finally:
        engine.dispose()
    return counts
