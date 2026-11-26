from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def minimal_catalog() -> dict[str, Any]:
    return {
        "catalog": {
            "uuid": "8f1c2e3a-0000-4000-8000-000000000010",
            "metadata": {
                "title": "Test catalog",
                "last-modified": "2026-11-26T00:00:00+00:00",
                "version": "1.0.0",
                "oscal-version": "1.1.3",
            },
            "groups": [
                {
                    "id": "dadm-6.1",
                    "title": "Algorithmic Impact Assessment",
                    "controls": [
                        {
                            "id": "DADM-6.1.1-A",
                            "title": "DADM-6.1.1-A",
                            "props": [
                                {"name": "label", "value": "6.1.1"},
                                {
                                    "name": "check-type",
                                    "ns": "https://egcsgroup.com/ns/oscal",
                                    "value": "Rule-based",
                                },
                            ],
                            "parts": [
                                {
                                    "id": "DADM-6.1.1-A_smt",
                                    "name": "statement",
                                    "prose": "Une évaluation a été réalisée.",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }
