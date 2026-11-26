"""Extract numbered clauses from a saved web page (HTML) or a plain-text file.

Both formats reduce to a sequence of blocks (headings and paragraphs), then the same
rules apply:

- a paragraph that starts with a clause number (``6.2.1`` or ``6.2.1.``) starts a clause;
- an unnumbered paragraph after a clause is appended to it (e.g. a nested bullet);
- a heading ends the current clause and becomes the heading of the clauses that follow.

Text format: UTF-8; paragraphs separated by blank lines; lines starting with ``#`` are
headings. HTML: when the page has a ``<main>`` element only its content is used; scripts,
styles, navigation, headers and footers are always skipped.

No network access: the input is a local file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal

from rulebook.sources.normalize import clean_original

_CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(\S.*)$", re.DOTALL)
_BROKEN_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)+\.?(?=\S)")

BLOCK_TAGS = frozenset(
    {
        "p",
        "li",
        "dt",
        "dd",
        "td",
        "th",
        "caption",
        "blockquote",
        "div",
        "section",
        "article",
        "main",
        "ul",
        "ol",
        "dl",
        "table",
        "tr",
        "figcaption",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "head",
        "nav",
        "header",
        "footer",
        "noscript",
        "template",
        "aside",
        "form",
        "button",
    }
)
VOID_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link", "wbr"})


@dataclass(frozen=True)
class Block:
    kind: Literal["heading", "paragraph"]
    text: str
    in_main: bool = True


@dataclass
class ParsedClause:
    number: str
    text: str
    heading: str | None


@dataclass
class ParseResult:
    clauses: list[ParsedClause] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _BlockCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._buffer: list[str] = []
        self._kind: Literal["heading", "paragraph"] = "paragraph"
        self._skip_depth = 0
        self._main_depth = 0
        self._heading_depth = 0
        self.saw_main = False

    def _flush(self) -> None:
        text = clean_original("".join(self._buffer))
        self._buffer = []
        if text:
            kind: Literal["heading", "paragraph"] = (
                "heading" if self._heading_depth else "paragraph"
            )
            self.blocks.append(Block(kind, text, self._main_depth > 0))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            if tag == "br":
                self._buffer.append(" ")
            return
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS or tag in HEADING_TAGS:
            self._flush()
        if tag == "main":
            self._main_depth += 1
            self.saw_main = True
        if tag in HEADING_TAGS:
            self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS or tag in HEADING_TAGS:
            self._flush()
        if tag in HEADING_TAGS:
            self._heading_depth = max(0, self._heading_depth - 1)
        if tag == "main":
            self._main_depth = max(0, self._main_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def html_blocks(html: str) -> list[Block]:
    collector = _BlockCollector()
    collector.feed(html)
    collector.close()
    if collector.saw_main:
        return [b for b in collector.blocks if b.in_main]
    return collector.blocks


def text_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            cleaned = clean_original(" ".join(paragraph))
            if cleaned:
                blocks.append(Block("paragraph", cleaned))
            paragraph.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading = clean_original(stripped.lstrip("#"))
            if heading:
                blocks.append(Block("heading", heading))
        elif not stripped:
            flush()
        else:
            paragraph.append(stripped)
    flush()
    return blocks


def _number_key(number: str) -> tuple[int, ...]:
    return tuple(int(p) for p in number.split("."))


def extract_clauses(blocks: list[Block]) -> ParseResult:
    result = ParseResult()
    heading: str | None = None
    current: ParsedClause | None = None
    for block in blocks:
        if block.kind == "heading":
            heading, current = block.text, None
            continue
        match = _CLAUSE_RE.match(block.text)
        if match:
            current = ParsedClause(match.group(1), clean_original(match.group(2)), heading)
            if result.clauses and _number_key(current.number) <= _number_key(
                result.clauses[-1].number
            ):
                result.warnings.append(
                    f"clause {current.number} follows {result.clauses[-1].number}: "
                    "numbers are not increasing"
                )
            result.clauses.append(current)
        elif _BROKEN_NUMBER_RE.match(block.text):
            result.warnings.append(
                f"paragraph looks like a numbered clause but was not parsed: {block.text[:60]!r}"
            )
        elif current is not None:
            current.text = f"{current.text} {block.text}"
    return result


def parse_file_text(content: str, kind: Literal["html", "txt"]) -> ParseResult:
    blocks = html_blocks(content) if kind == "html" else text_blocks(content)
    return extract_clauses(blocks)
