from __future__ import annotations

from rulebook.sources.parse import parse_file_text

PAGE = """<!DOCTYPE html><html><head><title>t</title><style>p{}</style></head><body>
<header><p>6.9.9 Not part of the directive (site header).</p></header>
<nav><ul><li>6.8.8 Menu item</li></ul></nav>
<main>
<h2>6. Requirements</h2>
<h3>6.1 First</h3>
<ol>
  <li><strong>6.1.1</strong> First&nbsp;clause with an entity.</li>
  <li>6.1.2. Second clause,<br>wrapped
      over lines.
    <ul><li>A nested bullet that belongs to 6.1.2.</li></ul>
  </li>
  <li>6.1.3Missing space after the number.</li>
</ol>
<h3>6.2 Second</h3>
<p>Introductory paragraph without a number.</p>
<p>6.2.1 Clause in a paragraph.</p>
<p>6.1.9 Out of order.</p>
<script>var x = "6.7.7 not text";</script>
</main>
<footer><p>6.9.8 Footer.</p></footer>
</body></html>"""


def test_html_clauses_headings_and_continuations() -> None:
    result = parse_file_text(PAGE, "html")
    numbers = [c.number for c in result.clauses]
    assert numbers == ["6.1.1", "6.1.2", "6.2.1", "6.1.9"]
    first, second = result.clauses[0], result.clauses[1]
    assert first.text == "First clause with an entity."  # &nbsp; kept as U+00A0
    assert first.heading == "6.1 First"
    assert second.text == (
        "Second clause, wrapped over lines. A nested bullet that belongs to 6.1.2."
    )
    assert result.clauses[2].heading == "6.2 Second"


def test_html_warnings() -> None:
    warnings = parse_file_text(PAGE, "html").warnings
    assert any("6.1.3Missing" in w for w in warnings)
    assert any("6.1.9 follows 6.2.1" in w for w in warnings)


def test_html_without_main_uses_whole_body_but_skips_chrome() -> None:
    page = "<body><nav>6.1.1 menu</nav><p>6.1.1 Real clause.</p><footer>6.1.2 f</footer></body>"
    result = parse_file_text(page, "html")
    assert [(c.number, c.text) for c in result.clauses] == [("6.1.1", "Real clause.")]


def test_text_format() -> None:
    text = """# 6.1 Heading

6.1.1 A clause
over two lines.

A continuation paragraph.

# 6.2 Next heading
Orphan paragraph after a heading is ignored.

6.2.1 Another clause.
"""
    result = parse_file_text(text, "txt")
    assert [(c.number, c.text, c.heading) for c in result.clauses] == [
        ("6.1.1", "A clause over two lines. A continuation paragraph.", "6.1 Heading"),
        ("6.2.1", "Another clause.", "6.2 Next heading"),
    ]
    assert result.warnings == []
