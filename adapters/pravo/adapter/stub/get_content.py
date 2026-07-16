"""StubGetContentHandler — get full document text via PDF download + OCR.

In stub mode, metadata is fetched from the real API (via the stub get handler),
but the document text is obtained by downloading the actual PDF and running
Yandex Vision OCR — exactly like production mode. The only difference between
stub and production is the source of the document list (config file vs API query).
"""

from __future__ import annotations

from adapters.pravo.adapter.handlers import BaseGetContentHandler
from core.errors import SourceUnavailableError


class StubGetContentHandler(BaseGetContentHandler):
    """Get full document text using real PDF download + OCR.

    Downloads the PDF from pravo.gov.ru via the shared PravoClient and
    runs OCR (Yandex Vision) to extract the full text.
    """

    async def get_content(self, document_id: str) -> str:
        """Get full document text: download PDF + OCR.

        Args:
            document_id: Document identifier.

        Returns:
            Full document text (OCR result).

        Raises:
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
    "StubGetContentHandler",
]
