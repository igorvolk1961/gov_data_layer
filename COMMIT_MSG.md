fix: исправлен баг с параметром source_id в get_document_detail + новый скрипт document_detail_pipeline

- Исправлен баг: get_document_detail принимает составной ID формата source_id-publish_id
  (как возвращает search), парсит publish_id и ищет через get_document_by_publish_id
- Добавлена фильтрация citations по поисковому запросу (query, context, max_citation_length)
- Добавлен метод get_document_uuid в DocumentRepository
- Исправлен вызов get_toc → get_sections
- Новый скрипт scripts/document_detail_pipeline.py для проверки эндпоинта
- Обновлены REST и MCP endpoint с новыми параметрами
- Обновлены тесты (все 536 проходят, mypy чисто)
