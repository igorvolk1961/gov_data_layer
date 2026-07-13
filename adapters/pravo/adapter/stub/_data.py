"""Shared stub data for PravoAdapter stub handlers.

Contains the fixed publish_id lists used by stub-mode handlers
(get, ingest) to know which documents to fetch from the real API.

This module is internal to the stub/ subpackage and should not be
imported from outside.
"""

from __future__ import annotations

# Fixed publish_id values for stub mode — initial load
_STUB_PUBLISH_IDS_INITIAL: list[str] = [
    "0001202012230060",  # Order of the Ministry of Labor dated 29.09.2020 No. 668n
    "0001202206200030",  # Order of the Ministry of Labor dated 21.03.2022 No. 154n
    "0001202212190143",  # Resolution of the Government of the Russian Federation dated 16.12.2022 No. 2330
]

# Fixed publish_id values for stub mode — new/updated documents
_STUB_PUBLISH_IDS_NEW: list[str] = [
    "0001202607060006",  # Order of the Ministry of Labor dated 03.06.2026 No. 238n
    "0001202606090026",  # Order of the Ministry of Labor dated 08.05.2026 No. 200n
]


__all__ = [
    "_STUB_PUBLISH_IDS_INITIAL",
    "_STUB_PUBLISH_IDS_NEW",
]
