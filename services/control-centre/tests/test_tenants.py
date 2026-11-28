"""control-centre's tenants: migrations, seeding, constraints, the internal endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from control_centre.models import Tenant
from control_centre.tenants import TenantFileError, seed
from govhub_shared.auth import TENANT_ADMIN
from govhub_shared.auth.testing import headers, service, user

ROOT = Path(__file__).parents[3]
DEMO = ROOT / "data/demo/tenants.toml"


def test_seed_demo_tenants_once(cc_db: Session) -> None:
    assert seed(cc_db, DEMO) == [
        "agency-sample-benefits", "dept-example-services", "office-fictional-permits",
    ]  # fmt: skip
    assert seed(cc_db, DEMO) == []  # idempotent
    assert all(t.synthetic for t in cc_db.query(Tenant))


def test_demo_tenants_match_the_fictional_inventory() -> None:
    import csv
    import tomllib

    ids = {t["id"] for t in tomllib.loads(DEMO.read_text("utf-8"))["tenants"]}
    with (ROOT / "data/inventory/systems.csv").open(encoding="utf-8") as fh:
        assert {r["Tenant"] for r in csv.DictReader(fh)} == ids


def test_residency_labels_are_constrained(cc_db: Session, tmp_path: Path) -> None:
    bad = tmp_path / "t.toml"
    bad.write_text('[[tenants]]\nid="x"\nname_en="X"\nname_fr="X"\nsynthetic=true\n'
                   'residency="anywhere"\n', "utf-8")  # fmt: skip
    with pytest.raises(TenantFileError, match="residency must be one of"):
        seed(cc_db, bad)
    # A real tenant can never carry the synthetic-only label.
    cc_db.add(Tenant(id="real", name_en="R", name_fr="R", synthetic=False,
                     residency="unrestricted-synthetic", created_by="t"))  # fmt: skip
    with pytest.raises(IntegrityError, match="tenants_synthetic_label"):
        cc_db.commit()


def test_internal_tenants_is_for_hub_services_only(ui: TestClient, cc_db: Session) -> None:
    seed(cc_db, DEMO)
    assert ui.get("/internal/tenants").status_code == 401
    admin = user("u-admin", tenant_admin=["office-fictional-permits"])
    assert TENANT_ADMIN in admin.tenant_roles["office-fictional-permits"]
    refused = ui.get("/internal/tenants", headers=headers(admin, "control-centre"))
    assert refused.status_code == 403
    wrong_aud = ui.get("/internal/tenants", headers=headers(service("rulebook"), "review-desk"))
    assert wrong_aud.status_code == 401
    ok = ui.get("/internal/tenants", headers=headers(service("rulebook"), "control-centre"))
    assert ok.status_code == 200
    assert [t["id"] for t in ok.json()] == [
        "agency-sample-benefits", "dept-example-services", "office-fictional-permits",
    ]  # fmt: skip
    assert ok.json()[0]["synthetic"] is True and ok.json()[0]["name"]["fr"]
