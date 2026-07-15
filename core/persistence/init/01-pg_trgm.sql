-- Enable pg_trgm extension for trigram-based title similarity search
-- Used by ChangeTrackingRepository.resolve_target_document_id()
CREATE EXTENSION IF NOT EXISTS pg_trgm;
