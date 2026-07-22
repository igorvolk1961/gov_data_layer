# Pipeline Sequence Diagrams

> Три диаграммы последовательностей для ключевых пайплайнов:
> 1. **Ingest Pipeline** — загрузка данных из источника в индекс
> 2. **Search Pipeline (Metadata Routing)** — поиск документов с фильтрацией
> 3. **Document Detail Pipeline** — получение полной карточки документа

---

## 1. Ingest Pipeline

Загрузка документа из источника → OCR → чанкинг → эмбеддинг → сохранение в Qdrant + PostgreSQL.

```mermaid
sequenceDiagram
    participant Script as scripts/<br/>fixtures_ingest_pipeline.py
    participant Adapter as PravoAdapter (stub)
    participant OCR as DemoDocProvider
    participant PG as PostgreSQL
    participant Chunker as DocStructSplitter
    participant Embedder as Embedder
    participant Qdrant as Qdrant (vectors + payload)

    Script->>Adapter: get(document_id)
    Note over Adapter: Fetch metadata from stub<br/>(title, organization,<br/>document_type, etc.)
    Adapter-->>Script: OfficialDocument
    Script->>Adapter: get_content(document_id)
    Adapter->>OCR: get_text(pdf_path)
    OCR-->>Adapter: OCR text
    Adapter-->>Script: text (str)

    Script->>PG: save_document(doc)
    Note over PG: INSERT INTO document<br/>UNIQUE(source_id, external_id)
    PG-->>Script: doc_uuid (UUID)

    Script->>PG: resolve jurisdiction + region<br/>from organization
    Note over PG: get_or_create_organization<br/>→ jurisdiction_id, region_id
    PG-->>Script: region_id (str | None)

    Script->>Chunker: parse_hierarchy(text)
    Note over Chunker: spaCy NLP → sections<br/>with title, heading, level
    Chunker-->>Script: sections (list)

    Script->>Chunker: generate_chunks(sections)
    Note over Chunker: Split sections into chunks<br/>with section_path
    Chunker-->>Script: chunks + TOC

    Script->>PG: save_section_hierarchy(doc_uuid, TOC)
    Note over PG: INSERT INTO document_section<br/>self-referencing via parent_id
    PG-->>Script: section_uuids (list)

    Script->>Embedder: embed_batch(chunks)
    Note over Embedder: sentence-transformers<br/>→ vector per chunk
    Embedder-->>Script: vectors

    Script->>Qdrant: upsert(collection, points)
    Note over Qdrant: Payload: document_id, doc_uuid,<br/>region_id, topic_ids,<br/>section_path, data_freshness
    Qdrant-->>Script: OK

    Script->>Embedder: embed(topic_names)
    Note over Embedder: Encode each topic name<br/>→ topic vector
    Embedder-->>Script: topic_vectors

    Script->>Qdrant: search(topic_collection, topic_vectors)
    Note over Qdrant: Find closest topics to chunks<br/>→ topic_ids + scores
    Qdrant-->>Script: topic_matches

    Script->>Qdrant: upsert_topic_links(points)
    Note over Qdrant: Update chunk payload<br/>topic_ids, topic_scores
    Qdrant-->>Script: OK

    Note over Script: Pipeline complete
```

### Ключевые моменты инжеста

| Шаг | Что происходит | Заполняется в payload Qdrant |
|-----|---------------|------------------------------|
| Fetch metadata | Получение title, organization, document_type | `document_id`, `doc_uuid` |
| Resolve region | Определение `region_id` из организации | `region_id` |
| Generate chunks | Структурный чанкинг с section_path | `section_path`, `section_uuids` |
| Embed chunks | Векторизация текста чанков | `embedding` |
| Link topics | Косинусная близость чанк↔рубрика | `topic_ids`, `topic_scores` |
| Set legal_status | `ACTIVE` (stub) / из JSON API (production) | `legal_status` |

---

## 2. Search Pipeline (Metadata Routing)

Поиск документов по текстовому запросу с фильтрацией по метаданным. Ключевая особенность: **адаптеры источников не участвуют** — поиск идёт напрямую через Qdrant.

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant API as MCP / REST API
    participant Cache as Redis (cache-aside)
    participant Service as ODLService
    participant Embedder as Embedder
    participant RegionResolver as RegionResolver
    participant Qdrant as Qdrant (vectors + payload)
    participant PG as PostgreSQL
    participant Reranker as TopicAwareReranker

    Agent->>API: search_documents(query, context)
    Note over API: query: "пособия гражданам<br/>имеющим детей"<br/>context: {region, organization}

    API->>Service: search_documents(query, context)

    Service->>Cache: get(cache_key)
    alt Cache HIT
        Cache-->>Service: cached SearchResponse
        Service-->>API: SearchResponse
        API-->>Agent: results
        Note over Agent: Hot path: < 50ms
    else Cache MISS
        Cache-->>Service: None

        Service->>RegionResolver: resolve(context.region)
        Note over RegionResolver: Trigram search in PostgreSQL<br/>→ region_id + confidence
        RegionResolver-->>Service: region_id, confidence

        Service->>Embedder: embed(query)
        Note over Embedder: sentence-transformers<br/>→ query vector
        Embedder-->>Service: query_vector

        Service->>Qdrant: search(query_vector, filters, limit=50)
        Note over Qdrant: Payload filters:<br/>- region_id (if set)<br/>- topic_ids (if relevant)<br/>- legal_status != NOT_ACTIVE<br/>- not_actual_since > now()
        Qdrant-->>Service: chunks + scores

        Service->>Qdrant: search_topics(query_vector)
        Note over Qdrant: Find top-3 topics<br/>closest to query
        Qdrant-->>Service: topic_matches

        Service->>Reranker: rerank(query_vector, chunks, topic_matches)
        Note over Reranker: Combine retrieval score + topic score<br/>→ reranked list
        Reranker-->>Service: reranked_chunks

        Service->>PG: get_document_meta(publish_ids)
        Note over PG: Fetch title, url, source_name,<br/>organization, document_number
        PG-->>Service: doc_metadata

        Service->>Service: assemble SearchResponse
        Note over Service: Group chunks by document_id<br/>Build citations, section_path,<br/>ConfidenceSignals

        Service->>Cache: set(cache_key, response, TTL=5min)
        Service-->>API: SearchResponse
        API-->>Agent: results + provenance
        Note over Agent: retrieval_relevance<br/>topic_relevance<br/>last_verified_at
    end
```

### Flow поиска

```
Query → Embedder → Qdrant (vector search + payload filter)
                                       ↓
                              TopicAwareReranker
                                       ↓
                              PostgreSQL enrichment
                                       ↓
                              Cache → Response
```

### Payload-фильтры в Qdrant

| Поле | Фильтр | Назначение |
|------|--------|------------|
| `region_id` | Равенство (если указан в контексте) | Поиск только по нужному региону |
| `topic_ids` | Пересечение (если рубрики релевантны) | Поиск в тематической области |
| `legal_status` | `!= NOT_ACTIVE` | Исключить отменённые документы |
| `not_actual_since` | `IS NULL OR > now()` | Исключить устаревшие разделы |

---

## 3. Document Detail Pipeline

Получение полной карточки документа с цитатами по `source_id`.

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant API as MCP / REST API
    participant Cache as Redis (cache-aside)
    participant Service as ODLService
    participant Embedder as Embedder
    participant Qdrant as Qdrant
    participant PG as PostgreSQL

    Agent->>API: get_document_detail(source_id)
    Note over API: source_id = "pravo-0001202012230060"

    API->>Service: get_document_detail(source_id,<br/>query=None,<br/>max_citation_length=2000)

    Service->>Cache: get(cache_key)
    alt Cache HIT
        Cache-->>Service: cached DocumentDetail
        Service-->>API: DocumentDetail
        API-->>Agent: detail
    else Cache MISS
        Cache-->>Service: None

        Service->>PG: get_document_by_publish_id(publish_id)
        Note over PG: Parse source_id → publish_id<br/>SELECT from document table
        PG-->>Service: doc_meta (OfficialDocument)

        alt Document not found
            Service-->>API: NotFoundError
            API-->>Agent: NOT_FOUND error
        end

        Service->>Qdrant: search(document_id, limit=50)
        Note over Qdrant: Find all chunks belonging<br/>to this document_id
        Qdrant-->>Service: chunks + scores

        alt Optional: filter by query
            Service->>Embedder: embed(query) [if query provided]
            Embedder-->>Service: query_vector
            Service->>Service: filter_chunks_by_query(chunks, query_vector)
            Note over Service: Re-rank chunks by relevance to query<br/>→ top N most relevant
        end

        Service->>Service: _merge_chunks_to_citations(chunks)
        Note over Service: Group chunks by section_path<br/>Merge overlapping chunks<br/>→ one Citation per section<br/>Truncate to max_citation_length

        Service->>Service: assemble DocumentDetail
        Note over Service: Merge doc_meta + citations<br/>→ flat metadata + citations

        Service->>Cache: set(cache_key, detail, TTL=1h)
        Service-->>API: DocumentDetail
        API-->>Agent: detail + citations
        Note over Agent: id, title, url,<br/>legal_status, citations<br/>each with section path
    end
```

### Сборка цитат

Процесс в `_merge_chunks_to_citations()`:

1. Чанки группируются по `section_path`
2. Внутри каждой группы — сортировка по `section_chunk_index`
3. Перекрывающиеся чанки объединяются
4. Одна `Citation` на раздел с `section` (путь от корня)
5. Общая длина цитат ≤ `max_citation_length`

---

## Сводка TTL кэширования

| Метод | TTL | Ключ |
|-------|-----|------|
| `search_documents` | 5 минут | `odl:search:{sha256(query+ctx)}` |
| `get_document_detail` | 1 час | `odl:detail:{source_id}` |
| `list_topics` | 1 час | `odl:topics:{parent_id}:{query}` |
| `get_toc` | 1 час | `odl:toc:{doc_id}:{parent_id}:{query}` |
| Region resolution | 24 часа | `region:{region_name}` |
