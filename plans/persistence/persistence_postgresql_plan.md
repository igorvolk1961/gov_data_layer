# PostgreSQL Persistence Layer — Plan

## 1. Overview

Currently, canonical models (`OfficialDocument`, `TocNode`, etc.) are stored only in Redis cache. In production, they must persist in PostgreSQL. This plan covers the **first phase**: creating the relational schema via Liquibase and implementing the repository layer.

**Key architectural rule:** The relational DB knows nothing about Qdrant chunks. Qdrant chunks reference relational DB records (documents and sections) via their IDs.

---

## 2. Database Schema Design

### 2.0 Data Source Table

A `data_source` table stores information about each source adapter (e.g. "pravo", "rss", "stub"). All reference tables and the `document` table reference this table via `source_id` FK.

```mermaid
erDiagram
    data_source {
        uuid id PK
        string source_id UK "adapter source id, e.g. 'pravo', 'rss', 'stub'"
        string name "human-readable name, e.g. 'Право РФ'"
        string url "base URL of the source"
        string jurisdiction "nullable, e.g. 'federal'"
        timestamp created_at
    }
```

### 2.1 Reference Tables (справочники)

All reference data from source adapters (document types, organizations, etc.) is stored in reference tables to normalize the schema.

**Important:** The field set in reference tables is limited to what the pravo.gov.ru API actually provides. See [API field audit](#api-field-audit) below.

**Note on ID types:** The pravo.gov.ru API returns all identifiers as **strings** containing GUIDs in `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` format (e.g. `"fd5a8766-f6fd-4ac2-8fd9-66f414d314ac"`). These are stored in `external_id` columns as `VARCHAR(36)`. The internal `id` PK in our tables uses native PostgreSQL `UUID` type.

**All reference tables have a `source_id` FK referencing `data_source.id`** — справочные данные привязаны к источнику, из которого они получены.

```mermaid
erDiagram
    document_type {
        uuid id PK
        uuid source_id FK "FK -> data_source.id"
        string external_id UK "GUID string from API /api/DocumentTypes, e.g. fd5a8766-..."
        string name "e.g. 'Приказ', 'Постановление'"
        int weight "sort weight from API, nullable"
        timestamp created_at
    }

    organization {
        uuid id PK
        uuid source_id FK "FK -> data_source.id"
        string external_id UK "GUID string from API /api/SignatoryAuthorities"
        string name "e.g. 'Правительство РФ'"
        int weight "sort weight from API, nullable"
        timestamp created_at
    }

    jurisdiction {
        uuid id PK
        uuid source_id FK "FK -> data_source.id"
        string code UK "e.g. 'federal', 'regional'"
        string name "e.g. 'Федеральная'"
        timestamp created_at
    }

    region {
        uuid id PK
        uuid source_id FK "FK -> data_source.id"
        string code UK "e.g. 'moscow-oblast'"
        string name "e.g. 'Московская область'"
        timestamp created_at
    }

    topic {
        uuid id PK
        uuid source_id FK "FK -> data_source.id"
        string code UK
        string name
        uuid parent_id FK "self-ref, nullable for root"
        string description
        timestamp created_at
    }
```

### 2.2 Document Tables

```mermaid
erDiagram
    document {
        uuid id PK
        string external_id UK "source-specific ID, e.g. pravo-123"
        string title
        string url
        string summary "nullable"
        uuid jurisdiction_id FK "nullable"
        uuid region_id FK "nullable"
        uuid document_type_id FK "nullable"
        string document_number "nullable, e.g. '668н'"
        string publish_id "nullable, e.g. '0001202012230060'"
        timestamp ingest_date
        timestamp valid_from "nullable"
        timestamp valid_to "nullable"
        timestamp publish_date "nullable"
        string legal_status "enum: active|revoked|modified|unknown"
        uuid source_id FK "FK -> data_source.id"
        jsonb meta "source-specific attributes"
        timestamp created_at
        timestamp updated_at
    }

    document_section {
        uuid id PK
        uuid document_id FK "many-to-one"
        string external_id "section ID within source"
        string title
        uuid parent_id FK "self-ref, nullable for root"
        int level "0 = root"
        int sort_order
        boolean is_deleted "default false"
        uuid deleted_by_document_id FK "nullable, ссылка на документ-основание удаления"
        timestamp delete_effective_date "nullable, если отличается от даты документа-основания"
        boolean is_modified "default false"
        timestamp modified_effective_date "nullable"
        timestamp created_at
        timestamp updated_at
    }

    document_organization {
        uuid document_id FK
        uuid organization_id FK
    }

    document_topic {
        uuid document_id FK
        uuid topic_id FK
    }

    document ||--o{ document_section : "has"
    document_section ||--o| document_section : "parent"
    document ||--o{ document_organization : "has"
    organization ||--o{ document_organization : "referenced in"
    document ||--o{ document_topic : "has"
    topic ||--o{ document_topic : "referenced in"
    document ||--o{ document_section : "deleted_by"
```

### 2.3 Change Tracking Tables

```mermaid
erDiagram
    document_section_modification {
        uuid section_id FK "изменённый раздел"
        uuid modifying_document_id FK "документ, на основании которого внесено изменение"
        timestamp effective_date "nullable, если отличается от даты документа"
    }

    document_revocation {
        uuid revoking_document_id FK "отменяющий документ"
        uuid revoked_document_id FK "отменяемый документ"
        timestamp effective_date "nullable, если отличается от даты отменяющего документа"
    }

    document_section_modification ||--o| document_section : "section"
    document_section_modification ||--o| document : "modifying_document"
    document_revocation ||--o| document : "revoking"
    document_revocation ||--o| document : "revoked"
```

### 2.4 Topic Rubricator Table (Hierarchical)

The rubric table is a hierarchical (self-referencing) category tree for classifying documents. It is initially empty and will be populated later.

```mermaid
erDiagram
    rubric {
        uuid id PK
        string code UK "rubric code"
        string name "rubric name"
        uuid parent_id FK "self-ref, nullable for root nodes"
        string description "nullable"
        int sort_order "ordering within same parent"
        timestamp created_at
    }

    document_rubric {
        uuid document_id FK "FK -> document.id"
        uuid rubric_id FK "FK -> rubric.id"
    }

    rubric ||--o| rubric : "parent"
    document ||--o{ document_rubric : "has"
    rubric ||--o{ document_rubric : "classified in"
```

---

## 3. Liquibase Migration Structure

```
core/persistence/
├── __init__.py
├── db_client.py              # Database connection management (asyncpg)
├── repository/
│   ├── __init__.py
│   ├── document_repo.py      # Document CRUD
│   ├── section_repo.py       # DocumentSection CRUD
│   ├── reference_repo.py     # Reference tables CRUD
│   └── change_tracking_repo.py # Modification & revocation tracking
└── migrations/
    ├── changelog-root.xml     # Root changelog
    ├── v001/
    │   ├── changelog.xml
    │   ├── 000_create_data_source.sql
    │   ├── 001_create_reference_tables.sql
    │   ├── 002_create_document_tables.sql
    │   ├── 003_create_document_relations.sql
    │   ├── 004_create_change_tracking.sql
    │   ├── 005_create_rubric_table.sql
    │   └── 006_create_document_rubric.sql
    └── v002/                  # Future migrations
```

---

## 4. Implementation Steps

### Step 1: Add Dependencies

Add to [`pyproject.toml`](pyproject.toml):
- `asyncpg>=0.29.0` — async PostgreSQL driver
- `liquibase` — not a Python dep, but a CLI tool; add to Dockerfile and CI

### Step 2: Create Liquibase Migrations

Create the migration directory structure under [`core/persistence/migrations/`](core/persistence/).

**Files to create:**
1. [`core/persistence/migrations/changelog-root.xml`](core/persistence/migrations/changelog-root.xml) — root changelog referencing all version changelogs
2. [`core/persistence/migrations/v001/changelog.xml`](core/persistence/migrations/v001/changelog.xml) — v001 changelog
3. [`core/persistence/migrations/v001/000_create_data_source.sql`](core/persistence/migrations/v001/000_create_data_source.sql) — `data_source` table (must be first, all other tables reference it)
4. [`core/persistence/migrations/v001/001_create_reference_tables.sql`](core/persistence/migrations/v001/001_create_reference_tables.sql) — `document_type`, `organization`, `jurisdiction`, `region`, `topic` (all with `source_id` FK)
5. [`core/persistence/migrations/v001/002_create_document_tables.sql`](core/persistence/migrations/v001/002_create_document_tables.sql) — `document` (with `source_id` FK), `document_section`
6. [`core/persistence/migrations/v001/003_create_document_relations.sql`](core/persistence/migrations/v001/003_create_document_relations.sql) — `document_organization`, `document_topic` (M:N junction tables)
7. [`core/persistence/migrations/v001/004_create_change_tracking.sql`](core/persistence/migrations/v001/004_create_change_tracking.sql) — `document_section_modification`, `document_revocation`
8. [`core/persistence/migrations/v001/005_create_rubric_table.sql`](core/persistence/migrations/v001/005_create_rubric_table.sql) — `rubric` (hierarchical, empty for now)
9. [`core/persistence/migrations/v001/006_create_document_rubric.sql`](core/persistence/migrations/v001/006_create_document_rubric.sql) — `document_rubric` (M:N junction table)

### Step 3: Create Database Client

Create [`core/persistence/db_client.py`](core/persistence/db_client.py):
- `DatabaseClient` class wrapping `asyncpg` connection pool
- Lazy connection (similar to [`CacheClient`](core/cache/__init__.py) pattern)
- Graceful degradation when DB is unavailable
- Connection string from config (`database.url` in [`config.example.yaml`](config.example.yaml))

### Step 4: Create Repository Layer

Create repository classes under [`core/persistence/repository/`](core/persistence/repository/):

1. **`reference_repo.py`** — CRUD for reference tables:
   - `get_or_create_document_type(code, name)`
   - `get_or_create_organization(code, name)`
   - `get_or_create_jurisdiction(code, name)`
   - `get_or_create_region(code, name)`
   - `get_or_create_topic(code, name, parent_id)`

2. **`document_repo.py`** — Document CRUD:
   - `upsert_document(OfficialDocument) -> uuid`
   - `get_document_by_external_id(external_id) -> OfficialDocument | None`
   - `get_document_by_id(uuid) -> OfficialDocument | None`
   - `search_documents(query, filters) -> list[OfficialDocument]`

3. **`section_repo.py`** — DocumentSection CRUD:
   - `upsert_sections(document_id, sections: list[TocNode])`
   - `get_sections(document_id) -> list[TocNode]`
   - `mark_section_deleted(section_id, deleted_by_document_id, effective_date)`
   - `mark_section_modified(section_id, modifying_document_id, effective_date)`

4. **`change_tracking_repo.py`** — Change tracking:
   - `add_section_modification(section_id, modifying_document_id, effective_date)`
   - `add_document_revocation(revoking_document_id, revoked_document_id, effective_date)`
   - `get_modifications_for_section(section_id)`
   - `get_revocations_for_document(document_id)`

### Step 5: Integrate with ODLService

Modify [`core/odl_service.py`](core/odl_service.py) to:
- Accept `DatabaseClient` in constructor (optional, for graceful degradation)
- After adapter returns `OfficialDocument`, persist it via repository
- On `get_document_detail()`, check DB first, then adapter (with cache fallback)

### Step 6: Update Docker Compose

The `metadata-db` service already exists in [`docker-compose.yml`](docker-compose.yml). Add Liquibase init container:

```yaml
liquibase:
  image: liquibase/liquibase:4.28
  container_name: odl-liquibase
  command: >
    --url=jdbc:postgresql://metadata-db:5432/odl_metadata
    --username=odl
    --password=odl
    --changeLogFile=/liquibase/changelog/changelog-root.xml
    update
  volumes:
    - ./core/persistence/migrations:/liquibase/changelog
  depends_on:
    metadata-db:
      condition: service_healthy
```

### Step 7: Update Configuration

Update [`config.example.yaml`](config.example.yaml) — the `database.url` already points to PostgreSQL. Ensure it's correct:

```yaml
database:
  url: "postgresql://odl:odl@localhost:5432/odl_metadata"
```

### Step 8: Add Tests

Create test files:
- [`tests/unit/test_db_client.py`](tests/unit/test_db_client.py) — unit tests for DatabaseClient
- [`tests/unit/test_document_repo.py`](tests/unit/test_document_repo.py) — unit tests for document repository
- [`tests/integration/test_persistence.py`](tests/integration/test_persistence.py) — integration tests with real PostgreSQL

---

## 5. API Field Audit

This section verifies that reference table fields can actually be populated from the pravo.gov.ru API.

### 5.1 API Endpoints and Available Fields

| API Endpoint | Returns | Fields Available |
|---|---|---|
| `/api/DocumentTypes` | List of document types | `id` (GUID), `name`, `weight` |
| `/api/SignatoryAuthorities` | List of adopting authorities | `id` (GUID), `name`, `weight` |
| `/api/Categories` | Categories of adopting authorities | `id` (GUID), `name`, `code` |
| `/api/PublicBlocks` | Publication blocks hierarchy | `id`, `shortName`, `name`, `menuName`, `code`, `description`, `weight`, `isBlocked`, `parentId`, `hasChildren`, `isAgenciesOfStateAuthorities`, `imageId`, `categories`, `section`, `items` |
| `/api/Documents` / `/api/Document` | Document list / detail | `id`, `eoNumber`, `publishDateShort`, `viewDate`, `complexName`, `title`, `jdRegNumber`, `jdRegDate`, `pagesCount`, `pdfFileLength`, `zipFileLength`, `name`, `number`, `documentDate`, `signatoryAuthorityId`, `documentTypeId`, `hasSvg`, nested `documentType` (id, name, weight), nested `signatoryAuthorities` (id, name, weight, isMain) |

### 5.2 Reference Table → API Field Mapping

| Reference Table | Populated From | Fields Mapped | Notes |
|---|---|---|---|
| `document_type` | `/api/DocumentTypes` | `external_id` ← `id` (GUID), `name` ← `name`, `weight` ← `weight` | API has NO `code` or `description` fields |
| `organization` | `/api/SignatoryAuthorities` | `external_id` ← `id` (GUID), `name` ← `name`, `weight` ← `weight` | API has NO `code` or `description` fields |
| `jurisdiction` | Canonical model `Source.jurisdiction` | `code` ← string like "federal", `name` ← human-readable | NOT from pravo API directly |
| `region` | Canonical model `OfficialDocument.region` | `code` ← normalized region code, `name` ← region name | NOT from pravo API directly |
| `topic` | Canonical model `OfficialDocument.topic` | `code` ← topic code, `name` ← topic name, `parent_id` ← hierarchy | NOT from pravo API directly |

### 5.3 Key Findings

1. **`document_type` and `organization` tables do NOT need `code` or `description` columns** — the API only provides `id` (GUID), `name`, and `weight`. The `external_id` column stores the GUID from the API, which serves as the natural key for lookups.

2. **`jurisdiction`, `region`, and `topic` are NOT sourced from pravo API** — they come from the canonical model fields (`Source.jurisdiction`, `OfficialDocument.region`, `OfficialDocument.topic`), which may be populated by other adapters (RSS, stub) or set manually.

3. **The `PravoParser` already uses lookup caches** (`_authority_cache`, `_doc_type_cache`) to resolve GUIDs to names. The reference tables will serve as the persistent version of these caches.

### 5.4 Corrected Reference Table Definitions

#### `document_type`

| Column | Type | Constraints | Source | Notes |
|--------|------|-------------|--------|-------|
| id | UUID | PK, DEFAULT gen_random_uuid() | auto | |
| external_id | VARCHAR(255) | UNIQUE, NOT NULL | API `id` (GUID) | Natural key for lookups |
| name | VARCHAR(255) | NOT NULL | API `name` | e.g. "Постановление" |
| weight | INTEGER | | API `weight` | Sort weight, nullable |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | auto | |

#### `organization`

| Column | Type | Constraints | Source | Notes |
|--------|------|-------------|--------|-------|
| id | UUID | PK, DEFAULT gen_random_uuid() | auto | |
| external_id | VARCHAR(255) | UNIQUE, NOT NULL | API `id` (GUID) | Natural key for lookups |
| name | VARCHAR(255) | NOT NULL | API `name` | e.g. "Правительство РФ" |
| weight | INTEGER | | API `weight` | Sort weight, nullable |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | auto | |

#### `jurisdiction`, `region`, `topic`

These tables remain as originally designed (with `code` and `name`), since they are populated from canonical model fields, not directly from the pravo API.

---

## 6. Detailed Table Definitions

### 6.1 `document` table

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, DEFAULT gen_random_uuid() | |
| external_id | VARCHAR(255) | UNIQUE, NOT NULL | Source-specific ID |
| title | TEXT | NOT NULL | |
| url | TEXT | NOT NULL | |
| summary | TEXT | | |
| jurisdiction_id | UUID | FK -> jurisdiction.id | |
| region_id | UUID | FK -> region.id | |
| document_type_id | UUID | FK -> document_type.id | |
| document_number | VARCHAR(100) | | |
| publish_id | VARCHAR(100) | | |
| ingest_date | TIMESTAMPTZ | NOT NULL | |
| valid_from | TIMESTAMPTZ | | |
| valid_to | TIMESTAMPTZ | | |
| publish_date | TIMESTAMPTZ | | |
| legal_status | VARCHAR(20) | NOT NULL, DEFAULT 'unknown' | Enum: active, revoked, modified, unknown |
| source_id | UUID | FK -> data_source.id, NOT NULL | |
| meta | JSONB | DEFAULT '{}' | |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

### 6.2 `document_section` table

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, DEFAULT gen_random_uuid() | |
| document_id | UUID | FK -> document.id, NOT NULL | |
| external_id | VARCHAR(255) | NOT NULL | Section ID within source |
| title | TEXT | NOT NULL | |
| parent_id | UUID | FK -> document_section.id | Nullable for root |
| level | INTEGER | NOT NULL, DEFAULT 0 | |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 | |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT false | |
| deleted_by_document_id | UUID | FK -> document.id | |
| delete_effective_date | TIMESTAMPTZ | | |
| is_modified | BOOLEAN | NOT NULL, DEFAULT false | |
| modified_effective_date | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

### 6.3 `document_section_modification` (M:N)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| section_id | UUID | FK -> document_section.id, NOT NULL | |
| modifying_document_id | UUID | FK -> document.id, NOT NULL | |
| effective_date | TIMESTAMPTZ | | If different from document's valid_from |
| PRIMARY KEY | | (section_id, modifying_document_id) | |

### 6.4 `document_revocation` (1:M)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| revoking_document_id | UUID | FK -> document.id, NOT NULL | |
| revoked_document_id | UUID | FK -> document.id, NOT NULL | |
| effective_date | TIMESTAMPTZ | | If different from revoking document's valid_from |
| PRIMARY KEY | | (revoking_document_id, revoked_document_id) | |

---

## 6. Todo List

```markdown
[x] Analyze existing project structure and canonical models
[ ] Add asyncpg dependency to pyproject.toml
[ ] Create core/persistence/ package structure
[ ] Create Liquibase migration files (v001)
    [ ] 001_create_reference_tables.sql
    [ ] 002_create_document_tables.sql
    [ ] 003_create_document_relations.sql
    [ ] 004_create_change_tracking.sql
    [ ] 005_create_rubric_table.sql
    [ ] changelog-root.xml and v001/changelog.xml
[ ] Implement DatabaseClient (asyncpg wrapper with graceful degradation)
[ ] Implement ReferenceRepository
[ ] Implement DocumentRepository
[ ] Implement SectionRepository
[ ] Implement ChangeTrackingRepository
[ ] Integrate repositories with ODLService
[ ] Update docker-compose.yml with Liquibase init container
[ ] Update config.example.yaml database URL
[ ] Add unit tests for DatabaseClient
[ ] Add unit tests for repositories
[ ] Add integration tests for persistence layer
```
