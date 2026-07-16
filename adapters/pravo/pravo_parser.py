"""PravoParser — парсер ответов API pravo.gov.ru в каноническую модель.

Маппинг полей API → каноническая модель OfficialDocument:

| Поле API              | Поле модели        | Примечание                          |
|-----------------------|--------------------|-------------------------------------|
| id (GUID)             | id                 | Префикс 'pravo-' + GUID             |
| eoNumber              | publish_id         | Номер электронного опубликования    |
| publishDateShort      | publish_date       | Дата публикации                     |
| complexName           | summary            | Составное название                  |
| title                 | title              | Заголовок                           |
| name                  | —                  | Дублирует complexName, не маппим    |
| number                | document_number    | Номер документа (НПА)               |
| documentDate          | valid_from         | Дата подписания                     |
| documentTypeId        | document_type      | Lookup имени вида через _doc_type_cache |
| signatoryAuthorityId  | organization       | Lookup имени органа через _authority_cache |
| pagesCount            | meta["pdf_pages"]  | Source-специфично                   |
| pdfFileLength         | meta["pdf_file_length"] | Source-специфично              |
| jdRegNumber           | meta["jd_reg_number"]  | Source-специфично              |
| jdRegDate             | meta["jd_reg_date"]    | Source-специфично              |
| zipFileLength         | meta["zip_file_length"] | Source-специфично              |
| hasSvg                | meta["has_svg"]         | Source-специфично              |
| viewDate              | meta["view_date"]       | Дата публикации в формате DD.MM.YYYY |
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.models import LegalStatus, OfficialDocument, Source

# Статический маппинг кодов блоков публикации pravo.gov.ru → юрисдикция.
# Коды взяты из документации API: /api/PublicBlocks, /api/BlockStatistics.
# Блок определяет уровень власти органа, опубликовавшего документ.
BLOCK_TO_JURISDICTION: dict[str, str] = {
    "president": "federal",
    "assembly": "federal",
    "government": "federal",
    "federal_authorities": "federal",
    "court": "federal",
    "subjects": "regional",
    "international": "international",
    "un_securitycouncil": "international",
}


class PravoParser:
    """Парсер ответов API pravo.gov.ru в каноническую модель OfficialDocument."""

    SOURCE_ID = "pravo"
    SOURCE_NAME = "Официальный интернет-портал правовой информации"
    SOURCE_URL = "http://publication.pravo.gov.ru"

    def __init__(self) -> None:
        # Кэш для lookup-данных (органы, типы документов).
        # TODO: Вызывать update_authority_cache() и update_doc_type_cache()
        # перед production-поиском, иначе document_type всегда None,
        # a organization содержит сырые GUID.
        self._authority_cache: dict[str, str] = {}
        self._doc_type_cache: dict[str, str] = {}
        # Юрисдикция, устанавливаемая перед циклом парсинга (через set_jurisdiction).
        # Если None — jurisdiction не будет заполнен в документе.
        self._jurisdiction: str | None = None

    def _make_document_id(self, raw_id: str) -> str:
        """Сформировать ID документа с префиксом источника.

        Args:
            raw_id: GUID из API.

        Returns:
            ID в формате 'pravo-<GUID>'.
        """
        return f"pravo-{raw_id}"

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Распарсить дату из API pravo.gov.ru.

        API возвращает даты в формате 'YYYY-MM-DDTHH:mm:ss' или 'YYYY-MM-DD'.

        Args:
            date_str: Строка с датой.

        Returns:
            datetime в UTC или None.
        """
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass
        # Попробуем YYYY-MM-DD
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _map_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Маппинг полей API pravo.gov.ru в поля канонической модели.

        Маппинг основан на документированной структуре ответов API:
        - /api/Document — расширенный набор полей документа
        - /api/Documents — результаты поиска (те же поля в items)

        Args:
            raw: Сырой JSON-ответ от API pravo.gov.ru.

        Returns:
            Словарь с полями для создания OfficialDocument.
        """
        raw_id = raw.get("id", "")
        doc_id = self._make_document_id(raw_id) if raw_id else ""

        # eoNumber — номер электронного опубликования → publish_id
        publish_id = raw.get("eoNumber")

        # Формируем URL документа
        url = f"{self.SOURCE_URL}/document/{publish_id}" if publish_id else ""

        # Парсим даты
        publish_date = self._parse_date(raw.get("publishDateShort"))
        valid_from = self._parse_date(raw.get("documentDate"))

        # documentTypeId — GUID вида документа
        doc_type_id: str | None = None
        doc_type_id_raw = raw.get("documentTypeId")
        if doc_type_id_raw:
            doc_type_id = str(doc_type_id_raw)

        # signatoryAuthorityId — GUID принявшего органа
        organization_id: str | None = None
        authority_id = raw.get("signatoryAuthorityId")
        if authority_id:
            organization_id = str(authority_id)

        # Source-специфичные атрибуты в meta
        meta: dict[str, Any] = {}
        for src_field, meta_key in [
            ("pagesCount", "pdf_pages"),
            ("pdfFileLength", "pdf_file_length"),
            ("jdRegNumber", "jd_reg_number"),
            ("jdRegDate", "jd_reg_date"),
            ("zipFileLength", "zip_file_length"),
            ("hasSvg", "has_svg"),
            ("viewDate", "view_date"),
        ]:
            if src_field in raw:
                meta[meta_key] = raw[src_field]

        return {
            "id": doc_id,
            "title": raw.get("title", ""),
            "source": Source(
                id=self.SOURCE_ID,
                name=self.SOURCE_NAME,
                url=self.SOURCE_URL,
            ),
            "url": url,
            "summary": raw.get("complexName") or raw.get("summary"),
            "document_number": raw.get("number"),
            "publish_id": publish_id,
            "publish_date": publish_date,
            "valid_from": valid_from,
            "organization_id": organization_id,
            "document_type_id": doc_type_id,
            "jurisdiction": self._jurisdiction,
            "meta": meta,
            "legal_status": LegalStatus.UNKNOWN,
        }

    def parse_document(self, raw: dict[str, Any]) -> OfficialDocument:
        """Парсинг JSON-ответа API в OfficialDocument.

        Args:
            raw: Сырой JSON-ответ от API pravo.gov.ru (get_document).

        Returns:
            Нормализованный документ в канонической модели.

        Raises:
            ValueError: Если не удалось извлечь обязательные поля.
        """
        mapped = self._map_fields(raw)

        if not mapped["id"]:
            raise ValueError("Missing required field 'id' in API response")
        if not mapped["title"]:
            raise ValueError("Missing required field 'title' in API response")

        return OfficialDocument(**mapped)

    def parse_search_result(self, raw: dict[str, Any]) -> OfficialDocument:
        """Парсинг элемента результата поиска в OfficialDocument.

        Результаты поиска (/api/Documents) содержат те же поля,
        что и get_document, поэтому используем тот же _map_fields.

        Args:
            raw: Элемент из результатов поиска.

        Returns:
            Нормализованный документ.
        """
        return self.parse_document(raw)

    def set_jurisdiction(self, jurisdiction: str | None) -> None:
        """Установить юрисдикцию для документов, которые будут распарсены.

        Вызывается перед циклом поиска/парсинга, когда известен блок
        публикации, из которого будут получены документы.

        Args:
            jurisdiction: Значение jurisdiction (например, 'federal', 'regional')
                         или None для сброса.
        """
        self._jurisdiction = jurisdiction

    def update_authority_cache(
        self,
        authorities: list[dict[str, Any]],
    ) -> None:
        """Обновить кэш органов власти.

        Args:
            authorities: Список органов власти от API /api/SignatoryAuthorities.
        """
        for auth in authorities:
            auth_id = auth.get("id")
            auth_name = auth.get("name")
            if auth_id and auth_name:
                self._authority_cache[str(auth_id)] = auth_name

    def update_doc_type_cache(
        self,
        doc_types: list[dict[str, Any]],
    ) -> None:
        """Обновить кэш видов документов.

        Args:
            doc_types: Список видов документов от API /api/DocumentTypes.
        """
        for dt in doc_types:
            dt_id = dt.get("id")
            dt_name = dt.get("name")
            if dt_id and dt_name:
                self._doc_type_cache[str(dt_id)] = dt_name


__all__ = [
    "BLOCK_TO_JURISDICTION",
    "PravoParser",
]
