"""Obligation-word extraction: moved to ``govhub_shared.obligations`` so the assessment
engine checks drafted controls with the very same code."""

from __future__ import annotations

from govhub_shared.obligations import (
    NEGATED_TERMS,
    OBLIGATION_CODES,
    OBLIGATION_TERMS,
    RESTRICTION_TERMS,
    Lang,
    obligation_changed,
    obligation_codes,
    obligation_terms,
    primary_obligation,
)

__all__ = [
    "NEGATED_TERMS",
    "OBLIGATION_CODES",
    "OBLIGATION_TERMS",
    "RESTRICTION_TERMS",
    "Lang",
    "obligation_changed",
    "obligation_codes",
    "obligation_terms",
    "primary_obligation",
]
