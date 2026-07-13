"""Shared stub data for PravoAdapter stub handlers.

Contains the fixed documents and factory function used by all stub-mode
handlers (search, get, ingest, list_topics, get_content).

This module is internal to the stub/ subpackage and should not be
imported from outside.
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.pravo.adapter.constants import _DOCUMENT_URL_TEMPLATE, _SOURCE_URL
from core.models.models import (
    LegalStatus,
    OfficialDocument,
    Source,
)

# Fixed publish_id values for stub mode
_STUB_PUBLISH_IDS_INITIAL = [
    "0001202012230060",  # Order of the Ministry of Labor dated 29.09.2020 No. 668n
    "0001202206200030",  # Order of the Ministry of Labor dated 21.03.2022 No. 154n
    "0001202212190143",  # Resolution of the Government of the Russian Federation dated 16.12.2022 No. 2330
]

_STUB_PUBLISH_IDS_NEW = [
    "0001202607060006",  # Order of the Ministry of Labor dated 03.06.2026 No. 238n
    "0001202606090026",  # Order of the Ministry of Labor dated 08.05.2026 No. 200n
]


def _build_stub_documents() -> dict[str, OfficialDocument]:
    """Create fixed documents for stub mode.

    Returns:
        Dictionary {document_id: OfficialDocument}.
    """
    now = datetime.now(timezone.utc)
    source = Source(
        id="pravo",
        name="Official Internet Portal of Legal Information",
        url=_SOURCE_URL,
    )

    docs: dict[str, OfficialDocument] = {}

    # Document 1: Order of the Ministry of Labor dated 29.09.2020 No. 668n
    doc1 = OfficialDocument(
        id="pravo-0001202012230060",
        title="On approval of the Procedure for providing workers with personal protective equipment",
        source=source,
        url=_DOCUMENT_URL_TEMPLATE.format(publish_id="0001202012230060"),
        summary="Order of the Ministry of Labor and Social Protection of the Russian Federation "
        "dated 29.09.2020 No. 668n "
        '"On approval of the Procedure for providing workers with personal protective equipment"',
        jurisdiction="federal",
        organization=["Ministry of Labor of Russia"],
        topic=["labor law", "occupational safety"],
        document_number="668n",
        document_type="Order",
        publish_id="0001202012230060",
        publish_date=datetime(2020, 12, 23, tzinfo=timezone.utc),
        valid_from=datetime(2020, 9, 29, tzinfo=timezone.utc),
        ingest_date=now,
        legal_status=LegalStatus.ACTIVE,
        meta={"pdf_pages": 0},
    )
    docs[doc1.id] = doc1

    # Document 2: Order of the Ministry of Labor dated 21.03.2022 No. 154n
    doc2 = OfficialDocument(
        id="pravo-0001202206200030",
        title="On approval of the Rules on occupational safety when working at height",
        source=source,
        url=_DOCUMENT_URL_TEMPLATE.format(publish_id="0001202206200030"),
        summary="Order of the Ministry of Labor and Social Protection of the Russian Federation "
        "dated 21.03.2022 No. 154n "
        '"On approval of the Rules on occupational safety when working at height"',
        jurisdiction="federal",
        organization=["Ministry of Labor of Russia"],
        topic=["labor law", "occupational safety"],
        document_number="154n",
        document_type="Order",
        publish_id="0001202206200030",
        publish_date=datetime(2022, 6, 20, tzinfo=timezone.utc),
        valid_from=datetime(2022, 3, 21, tzinfo=timezone.utc),
        ingest_date=now,
        legal_status=LegalStatus.ACTIVE,
        meta={"pdf_pages": 0},
    )
    docs[doc2.id] = doc2

    # Document 3: Resolution of the Government of the Russian Federation dated 16.12.2022 No. 2330
    doc3 = OfficialDocument(
        id="pravo-0001202212190143",
        title="On the procedure for conducting mandatory medical examinations of workers",
        source=source,
        url=_DOCUMENT_URL_TEMPLATE.format(publish_id="0001202212190143"),
        summary="Resolution of the Government of the Russian Federation dated 16.12.2022 No. 2330 "
        '"On the procedure for conducting mandatory medical examinations of workers"',
        jurisdiction="federal",
        organization=["Government of the Russian Federation"],
        topic=["labor law", "occupational safety", "medicine"],
        document_number="2330",
        document_type="Resolution",
        publish_id="0001202212190143",
        publish_date=datetime(2022, 12, 19, tzinfo=timezone.utc),
        valid_from=datetime(2022, 12, 16, tzinfo=timezone.utc),
        ingest_date=now,
        legal_status=LegalStatus.ACTIVE,
        meta={"pdf_pages": 0},
    )
    docs[doc3.id] = doc3

    return docs


__all__ = [
    "_STUB_PUBLISH_IDS_INITIAL",
    "_STUB_PUBLISH_IDS_NEW",
    "_build_stub_documents",
]
