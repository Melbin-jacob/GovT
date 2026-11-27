"""Optional golden-set columns (Milestone 6): Obligation, Status, Group, provenance."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from test_golden_import import FIXED, GOLDEN, GROUPS, SETTINGS, _by_id, _csv_rows

from rulebook.golden import GoldenImportError, import_golden
from rulebook.obligation_column import propose

REPO = Path(__file__).resolve().parents[3]
EXTRA = ["Obligation", "Status", "Group", "Drafted by", "Approved by", "Approval record"]


def variant(tmp_path: Path, edit: dict[str, dict[str, str]], groups_extra: str = "") -> Path:
    header, rows = _csv_rows()
    for row in rows:
        row.update({c: "" for c in EXTRA})
        row.update(edit.get(row["Check ID"], {}))
    path = tmp_path / "dadm-section6.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header + EXTRA, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    groups = GROUPS.read_text("utf-8")
    if groups_extra:
        lines = groups.rstrip("\n").split("\n")
        lines[0] += ',"Group ID"'
        lines = [lines[0]] + [ln + ',""' for ln in lines[1:]] + [groups_extra]
        groups = "\n".join(lines) + "\n"
    (tmp_path / "dadm-section6.groups.csv").write_text(groups, "utf-8")
    shutil.copy(SETTINGS, tmp_path / "dadm-section6.settings.toml")
    return path


def props(control: object, name: str) -> list[str]:
    return [p.value for p in control.props if p.name == name]  # type: ignore[attr-defined]


def test_blank_columns_change_nothing(tmp_path: Path) -> None:
    plain = import_golden(GOLDEN, tmp_path / "a", source_date=FIXED, write=False)
    extended = import_golden(variant(tmp_path, {}), tmp_path / "b", source_date=FIXED, write=False)
    assert plain.catalogs["en"]["catalog"]["groups"] == extended.catalogs["en"]["catalog"]["groups"]


def test_obligation_status_group_and_provenance_become_props(tmp_path: Path) -> None:
    edits = {
        "DADM-6.1.1-A": {"Obligation": "must"},
        "DADM-6.1.1-B": {"Status": "withdrawn"},
        "DADM-6.2.1": {
            "Group": "6.2@2025-06-24",
            "Drafted by": "model qwen3-8b, prompt draft-v1 (batch 7)",
            "Approved by": "governance-officer-02",
            "Approval record": "seq 3 sha256:abc",
        },
    }
    group = '"6.2@2025-06-24","New section","Nouvelle section","no","test","dadm-G01"'
    result = import_golden(variant(tmp_path, edits, group), tmp_path, source_date=FIXED)
    for lang in ("en", "fr"):
        controls = _by_id(result.catalogs[lang])
        assert props(controls["DADM-6.1.1-A"], "obligation") == ["must"]
        assert props(controls["DADM-6.1.1-B"], "status") == ["withdrawn"]
        drafted = controls["DADM-6.2.1"]
        assert drafted.group_id == "dadm-G01"
        assert props(drafted, "drafted-by") == ["model qwen3-8b, prompt draft-v1 (batch 7)"]
        assert props(drafted, "approved-by") == ["governance-officer-02"]
        assert props(drafted, "approval-record") == ["seq 3 sha256:abc"]
        assert props(drafted, "review-status") == ["draft"]  # approval is not review
    ids = [g["id"] for g in result.catalogs["en"]["catalog"]["groups"]]
    assert ids[-1] == "dadm-G01" and ids.index("dadm-6.2") < ids.index("dadm-G01")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"Obligation": "mandatory"}, "Obligation 'mandatory' is not one of"),
        ({"Status": "retired"}, "Status 'retired' is not one of"),
        ({"Group": "9.9"}, "section 9.9 has no entry in the groups file"),
    ],
)
def test_bad_values_fail_the_import(tmp_path: Path, edit: dict[str, str], message: str) -> None:
    with pytest.raises(GoldenImportError, match=message):
        import_golden(variant(tmp_path, {"DADM-6.1.1-A": edit}), tmp_path, write=False)


def test_propose_obligations_fills_only_blank_linked_rows() -> None:
    text, proposals = propose(
        REPO / "data/demo/golden/example-widgets.csv",
        REPO / "data/demo/sources/example-widgets.2023-01-01.en.json",
    )
    # The committed demo CSV is already filled: only rows without an obligation word in
    # their clause are reported again, and they stay blank.
    assert {p.check_id: p.code for p in proposals} == {"WID-6.4.1": None, "WID-6.4.2": None}
    assert text == (REPO / "data/demo/golden/example-widgets.csv").read_text("utf-8")


def test_propose_obligations_from_clause_text(tmp_path: Path) -> None:
    source = REPO / "data/demo/golden/example-widgets.csv"
    with source.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = [f for f in (reader.fieldnames or []) if f != "Obligation"]
    for row in rows:
        row.pop("Obligation", None)
    rows[3]["Source clauses"] = ""  # unlinked: stays blank, never guessed
    blank = tmp_path / "widgets.csv"
    with blank.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    _, proposals = propose(blank, REPO / "data/demo/sources/example-widgets.2023-01-01.en.json")
    codes = {p.check_id: p.code for p in proposals}
    assert codes["WID-6.1.1"] == "must" and codes["WID-6.2.1"] == "should"
    assert codes["WID-6.3.2"] == "may" and codes["WID-6.4.1"] is None
    assert rows[3]["Check ID"] not in codes
