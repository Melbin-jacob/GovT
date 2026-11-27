"""The source-document format (``govhub-source-document/1``).

A *full* document carries clause text and lives only in ``data/sources/raw/`` and in a
deployment's database. A *metadata-only* document (``text`` and ``heading`` omitted) is
what gets committed: instrument, version, language, file hash, clause numbers and hashes.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT: Literal["govhub-source-document/1"] = "govhub-source-document/1"
CLAUSE_NUMBER_PATTERN = r"^\d+(\.\d+)+$"


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(description="File name the document was extracted from")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: str = Field(pattern=CLAUSE_NUMBER_PATTERN, description="Clause number, e.g. 6.2.1")
    section: str = Field(description="First two levels of the number, e.g. 6.2")
    heading: str | None = Field(
        default=None, description="Nearest preceding heading (full documents only)"
    )
    text: str | None = Field(default=None, description="Official clause text, as published")
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of `text`")
    match_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the normalized text (typography-insensitive)",
    )


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["govhub-source-document/1"] = FORMAT
    content: Literal["full", "metadata-only"]
    instrument: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    effective_date: date
    lang: Literal["en", "fr"]
    source_url: str
    retrieved: date | None = None
    synthetic: bool
    file: SourceFile
    clauses: list[Clause]
    warnings: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> SourceDocument:
        numbers = [c.number for c in self.clauses]
        if len(numbers) != len(set(numbers)):
            dupes = sorted({n for n in numbers if numbers.count(n) > 1})
            raise ValueError(f"duplicate clause numbers: {dupes}")
        has_text = [c.text is not None for c in self.clauses]
        if self.content == "full" and not all(has_text):
            raise ValueError("a full document needs text for every clause")
        if self.content == "metadata-only" and (
            any(has_text) or any(c.heading for c in self.clauses)
        ):
            raise ValueError("a metadata-only document must not contain clause text or headings")
        return self

    @property
    def version(self) -> str:
        return self.effective_date.isoformat()

    def metadata_only(self) -> SourceDocument:
        return self.model_copy(
            update={
                "content": "metadata-only",
                "clauses": [
                    c.model_copy(update={"text": None, "heading": None}) for c in self.clauses
                ],
            }
        )

    def to_json(self) -> str:
        """Stable serialization (field order fixed by the model, UTF-8, trailing newline)."""
        data = self.model_dump(mode="json", exclude_none=True)
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    def clause(self, number: str) -> Clause | None:
        return next((c for c in self.clauses if c.number == number), None)


def json_schema() -> str:
    schema = SourceDocument.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://egcsgroup.com/ns/govhub/source-document-1.schema.json"
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
