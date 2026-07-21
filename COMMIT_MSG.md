Refactored rubric-to-topic semantic matching pipeline

- Each chunk independently searches for rubrics (topic_ids) via cosine similarity
- Auto topic resolution in search with combined ranking (queryxchunk + queryxtopic x chunkxtopic)
- Removed lazy-init of chunker/embedder from pipeline functions
- New DemoDocProvider for reading pre-downloaded OCR texts from fixtures
- Renamed topic_id to topic_ids across all layers
- Removed topic param from API and SearchContext
- Tests updated for all changes, fixed conftest region_id fixture ON CONFLICT
