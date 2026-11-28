"""Shared test helpers for the assessment engine."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"
# Every table, truncated before each test (a test checks the list is complete).
TABLES: tuple[str, ...] = (
    "evidence_documents",
    "evidence_passages",
    "system_facts",
    "assessments",
    "assessment_results_documents",
)


def minimal_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a text layer (Helvetica), built by hand for tests."""
    text = (
        "BT /F1 11 Tf 50 750 Td 14 TL "
        + " ".join(
            "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") ' "
            for ln in lines
        )
        + "ET"
    )
    stream = text.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def docx_bytes(paragraphs: list[str]) -> bytes:
    import io

    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class ScriptedGateway:
    """Test double: returns scripted replies in order and keeps the requests."""

    def __init__(self, *contents: str, model_id: str = "scripted-test-model") -> None:
        self.contents = list(contents)
        self.model_id = model_id
        self.requests: list[object] = []

    def chat(self, request: object) -> object:
        from govhub_shared.model_gateway import ChatResponse, GatewayError

        self.requests.append(request)
        if not self.contents:
            raise GatewayError("no more scripted replies")
        return ChatResponse(content=self.contents.pop(0), model_id=self.model_id)


def reply(
    verdict: str,
    *,
    passage: str | None = "P1",
    quote: str = "",
    confidence: float = 0.9,
) -> str:
    import json

    return json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "cited_passage_id": passage,
            "cited_quote": quote,
            "reasoning_en": "The notice is given online only.",
            "reasoning_fr": "L'avis est donné en ligne seulement.",
        }
    )


class CsvSystems:
    """The fictional inventory's system -> tenant (tests; production asks the rulebook)."""

    def __init__(self, path: Path) -> None:
        import csv

        with path.open(encoding="utf-8") as fh:
            self.tenants = {r["System ID"]: r["Tenant"] for r in csv.DictReader(fh)}

    def tenant_of(self, system_id: str) -> str | None:
        return self.tenants.get(system_id)


TEST_SYSTEMS = CsvSystems(REPO / "data/inventory/systems.csv")
DEMO_TENANTS = sorted(set(TEST_SYSTEMS.tenants.values()))
