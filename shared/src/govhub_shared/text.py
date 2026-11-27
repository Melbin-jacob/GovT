"""Text normalization for *matching only* (shared by the rulebook clause diff and the
assessment engine's quote check). Original text is always kept unchanged.

Treated as equal: no-break and narrow no-break spaces vs ordinary spaces; guillemets and
curly double quotes vs straight double quotes; typographic apostrophes (right/left single
quotation marks, modifier apostrophe) vs the straight apostrophe; typographic dashes vs
hyphen-minus; ligatures (oe, ae, and the fi/fl family via NFKC); spacing inside guillemets
and before French high punctuation (: ; ! ?); and letter case. Accents are kept: they
change meaning in French. The exact code points are listed in ``_CHAR_MAP``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Code points, not literal characters: these are invisible or look alike in source.
_CHAR_MAP: dict[int, str] = {
    0x00A0: " ",  # NO-BREAK SPACE
    0x202F: " ",  # NARROW NO-BREAK SPACE (French « » and : ; ! ?)
    0x2007: " ",  # FIGURE SPACE
    0x2009: " ",  # THIN SPACE
    0x2019: "'",  # RIGHT SINGLE QUOTATION MARK (typographic apostrophe)
    0x2018: "'",  # LEFT SINGLE QUOTATION MARK
    0x02BC: "'",  # MODIFIER LETTER APOSTROPHE
    0x2032: "'",  # PRIME
    0x00AB: '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet)
    0x00BB: '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet)
    0x201C: '"',  # LEFT DOUBLE QUOTATION MARK
    0x201D: '"',  # RIGHT DOUBLE QUOTATION MARK
    0x201E: '"',  # DOUBLE LOW-9 QUOTATION MARK
    0x2010: "-",  # HYPHEN
    0x2011: "-",  # NON-BREAKING HYPHEN
    0x2012: "-",  # FIGURE DASH
    0x2013: "-",  # EN DASH
    0x2014: "-",  # EM DASH
    0x0153: "oe",  # LATIN SMALL LIGATURE OE (NFKC keeps it)
    0x0152: "OE",  # LATIN CAPITAL LIGATURE OE
    0x00E6: "ae",  # LATIN SMALL LETTER AE
    0x00C6: "AE",  # LATIN CAPITAL LETTER AE
}
_SPACE_RE = re.compile(r"\s+")
_QUOTE_INNER_SPACE_RE = re.compile(r'"\s*([^"]*?)\s*"')
_HIGH_PUNCT_SPACE_RE = re.compile(r"\s+([:;!?])")
_WORD_RE = re.compile(r"\w+")


def normalize_for_match(text: str) -> str:
    """Canonical form used to compare clause text. Never shown to users."""
    text = unicodedata.normalize("NFKC", text)  # also expands ﬁ, ﬂ, ﬀ ... ligatures
    text = text.translate(_CHAR_MAP)
    text = _SPACE_RE.sub(" ", text).strip()
    text = _QUOTE_INNER_SPACE_RE.sub(r'"\1"', text)
    text = _HIGH_PUNCT_SPACE_RE.sub(r"\1", text)
    return text.casefold()


def match_tokens(text: str) -> list[str]:
    """Word tokens of the normalized text (punctuation and apostrophes split words)."""
    return _WORD_RE.findall(normalize_for_match(text))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_original(text: str) -> str:
    """Whitespace tidy-up applied to extracted text before storage.

    Collapses runs of ordinary whitespace (from HTML indentation and line wrapping) but
    keeps every no-break space, apostrophe and quote exactly as published.
    """
    return re.sub(r"[ \t\r\n\f\v]+", " ", text).strip()
