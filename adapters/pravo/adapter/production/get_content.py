"""ProductionGetContentHandler — production get_content via pravo.gov.ru API."""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseGetContentHandler
from core.errors import SourceUnavailableError
from core.observability.logger import get_logger

logger = get_logger(__name__)


class ProductionGetContentHandler(BaseGetContentHandler):
    """Get full document text using the real pravo.gov.ru API.

    Downloads PDF from API and runs OCR to extract text.
    """

    async def get_content(self, document_id: str) -> str:
        """Get full document text in production mode.

        Args:
            document_id: Document identifier.

        Returns:
            Full document text.

        Raises:
            NotFoundError: Document not found.
            SourceUnavailableError: PDF unavailable or OCR not configured.
        """
        adapter = self._adapter
        with adapter.tracer.trace(
            "pravo.get_content",
            source_id=adapter.source_id,
            mode="stub",
            document_id=document_id,
        ) as span:
            span.set_input({"document_id": document_id})

            # Production: download PDF -> OCR
            publish_id = adapter._extract_publish_id(document_id)
            ocr = adapter._get_ocr_provider()
            if ocr is None:
                error_msg = (
                    f"No OCR provider configured — cannot extract content "
                    f"for document '{document_id}'"
                )
                span.set_error(SourceUnavailableError(error_msg))
                raise SourceUnavailableError(error_msg)

            try:
                pdf_bytes = await adapter._pravo_client.download_pdf(publish_id)
                text = await ocr.extract_text(pdf_bytes, document_id)
                span.set_output({"found": True, "content_length": len(text)})
                return text
            except SourceUnavailableError:
                circuit_state = adapter._pravo_client.circuit_state
                error_msg = (
                    f"Failed to get content for document '{document_id}' (circuit: {circuit_state})"
                )
                span.set_error(SourceUnavailableError(error_msg))
                raise SourceUnavailableError(error_msg) from None
            except Exception as exc:
                span.set_error(exc)
                raise SourceUnavailableError(
                    f"Unexpected error getting content for '{document_id}': {exc}"
                ) from exc


__all__ = [
    "ProductionGetContentHandler",
]
