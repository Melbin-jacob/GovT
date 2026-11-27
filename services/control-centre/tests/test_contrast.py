"""WCAG 2.1 AA colour contrast of the stylesheet's colour pairs (axe checks the pages too)."""

from __future__ import annotations

import re
from importlib.resources import files

import pytest

CSS = files("control_centre").joinpath("static", "style.css").read_text("utf-8")
TOKENS = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", CSS))

# (foreground, background, minimum ratio): text needs 4.5:1, focus indicator 3:1.
PAIRS = [
    ("text", "background", 4.5),
    ("link", "background", 4.5),
    ("link-visited", "background", 4.5),
    ("muted", "background", 4.5),
    ("header-text", "header-bg", 4.5),
    ("banner-text", "banner-bg", 4.5),
    ("note-text", "note-bg", 4.5),
    ("error-text", "error-bg", 4.5),
    ("ok-text", "ok-bg", 4.5),
    ("badge-text", "badge-bg", 4.5),
    ("warn-text", "warn-bg", 4.5),
    ("text", "row-highlight", 4.5),
    ("link", "row-highlight", 4.5),
    ("muted", "row-highlight", 4.5),
    ("focus", "background", 3.0),
    ("#ffffff", "link", 4.5),  # button text
    ("#ffffff", "#1c2a39", 4.5),  # navigation bar
]


def _colour(name: str) -> str:
    return name if name.startswith("#") else TOKENS[name]


def _luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else float(((s + 0.055) / 1.055) ** 2.4)

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS)
def test_colour_pair_meets_wcag_aa(fg: str, bg: str, minimum: float) -> None:
    ratio = contrast(_colour(fg), _colour(bg))
    assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f}:1 < {minimum}:1"


def test_contrast_formula() -> None:
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0
