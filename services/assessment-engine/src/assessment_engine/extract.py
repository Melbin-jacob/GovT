"""Text extraction from uploaded evidence: TXT/Markdown, HTML, PDF and DOCX.

Scanned PDFs (no text layer) yield no text: there is no OCR yet, and such evidence makes
the dependent checks *unable to determine* (the document is flagged "no-text").
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

Status = Literal["ok", "no-text", "unsupported", "error"]
_BLOCK = {
    "p", "div", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "br", "table", "ul", "ol", "dd", "dt", "blockquote", "pre",
}  # fmt: skip
SUPPORTED = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass
class Extracted:
    status: Status
    paragraphs: list[str]
    media_type: str
    detail: str = ""


class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    return [re.sub(r"[ \t\r\n\f\v]+", " ", b).strip() for b in blocks if b.strip()]


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def extract(filename: str, data: bytes) -> Extracted:
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    media = SUPPORTED.get(suffix)
    if media is None:
        return Extracted(
            "unsupported", [], "application/octet-stream", f"{suffix or 'no'} extension"
        )
    try:
        if suffix in (".txt", ".md"):
            paragraphs = _paragraphs(_decode(data))
        elif suffix in (".html", ".htm"):
            parser = _Html()
            parser.feed(_decode(data))
            paragraphs = _paragraphs("".join(parser.parts))
        elif suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            paragraphs = []
            for page in reader.pages:
                paragraphs += _paragraphs(page.extract_text() or "")
        else:
            from docx import Document

            doc = Document(io.BytesIO(data))
            texts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    texts.append(" | ".join(cell.text for cell in row.cells))
            paragraphs = [p for t in texts for p in _paragraphs(t)]
    except Exception as exc:
        return Extracted("error", [], media, exc.__class__.__name__)
    if not paragraphs:
        return Extracted("no-text", [], media, "no text layer (scanned?)")
    return Extracted("ok", paragraphs, media)
