"""Text normalization for matching: moved to ``govhub_shared.text`` so the assessment
engine's exact-quote check uses the very same rules as the clause diff."""

from __future__ import annotations

from govhub_shared.text import clean_original, match_tokens, normalize_for_match, sha256_text

__all__ = ["clean_original", "match_tokens", "normalize_for_match", "sha256_text"]
