"""The golden-set CSV with the published change set gives exactly the stored version."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from drafts_support import OFFICER
from fastapi.testclient import TestClient
from test_drafts_approval import approve_all, checkpoint_file, drafted_batch  # noqa: F401

from rulebook.apply_drafts import ApplyError, apply
from rulebook.cli import main
from rulebook.golden import import_golden

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "data" / "demo"


def published(client: TestClient) -> dict:  # type: ignore[type-arg]
    batch = drafted_batch(client)
    approve_all(client, batch)
    assert (
        client.post(f"/drafts/batches/{batch['id']}/publish", json={}, headers=OFFICER).status_code
        == 200
    )
    return client.get(f"/drafts/batches/{batch['id']}/change-set").json()  # type: ignore[no-any-return]


def golden_copy(tmp_path: Path) -> Path:
    golden = tmp_path / "golden"
    shutil.copytree(DEMO / "golden", golden)
    shutil.copytree(DEMO / "sources", tmp_path / "sources")  # SOURCE_META_DIR = ../sources
    return golden / "example-widgets.csv"


def test_csv_with_the_change_set_equals_the_stored_version(
    client: TestClient, tmp_path: Path
) -> None:
    change_set = published(client)
    csv_path = golden_copy(tmp_path)
    for path, text in apply(csv_path, change_set).items():
        path.write_text(text, encoding="utf-8")
    result = import_golden(csv_path, tmp_path / "catalogs")
    assert result.version == "1.1.0"
    for lang in ("en", "fr"):
        stored = client.get(
            "/catalogs/example-widgets/versions/1.1.0", params={"lang": lang}
        ).json()
        assert result.catalogs[lang] == stored, lang
    settings = (csv_path.parent / "example-widgets.settings.toml").read_text("utf-8")
    assert 'SOURCE_DATE = "2026-11-29T00:00:00Z"' in settings
    assert 'SOURCE_VERSION = "2025-01-01"' in settings and "APPROVAL_LOG_HEAD" in settings
    text = csv_path.read_text("utf-8")
    assert '"WID-C001","6.2.1"' in text and '"withdrawn"' in text
    assert "Firmware" not in text and "firmware version" in text


def test_cli_and_refusals(client: TestClient, tmp_path: Path) -> None:
    import json

    change_set = published(client)
    csv_path = golden_copy(tmp_path)
    cs = tmp_path / "change-set.json"
    cs.write_text(json.dumps(change_set), "utf-8")
    assert (
        main(["apply-drafts", str(cs), "--csv", str(csv_path), "--out-dir", str(tmp_path / "out")])
        == 0
    )
    assert (tmp_path / "out" / "example-widgets.en.json").is_file()
    with pytest.raises(ApplyError, match="WID-C001 already exists"):
        apply(csv_path, change_set)
