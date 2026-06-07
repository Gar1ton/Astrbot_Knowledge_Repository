# Zotero RAG Plugin Technical Design

## 1. Goal

This document summarizes the proposed architecture for adding a Zotero-linked PDF-to-Markdown, RAG, memory recall, and note write-back feature to a plugin.

The target workflow is:

1. Read Zotero metadata, collections, tags, notes, and PDF attachments.
2. Convert PDFs to clean Markdown.
3. Preserve page and chunk provenance.
4. Store normalized data in a local database and vector index.
5. Retrieve relevant chunks by item, collection, tag, or whole-library scope.
6. Let an LLM generate answers from retrieved evidence.
7. Save the answer and provenance in the plugin database.
8. Write human-readable notes back to Zotero.

Zotero remains the canonical literature manager. The plugin database acts as a Zotero-compatible mirror plus an AI/RAG processing layer.

## 2. Core Technical Stack

### Zotero

Zotero is the source of truth for:

- Libraries
- Collections
- Items
- Attachments
- Tags
- Notes
- Relations
- Annotations
- Metadata versions

The plugin should not directly modify Zotero's SQLite database.

### Zotero Local API

Use Zotero Local API for local access when Zotero Desktop is running.

Typical use:

- Read active local library.
- Resolve items and child attachments.
- Access local attachment information.
- Support local-first workflows.

Inspired by `54yyyu/zotero-mcp`, use local mode for fast local reads.

### Zotero Web API

Use Zotero Web API for stable write operations.

Typical use:

- Create notes.
- Update notes.
- Read cloud library metadata.
- Handle group libraries.
- Respect Zotero versioning.

Writing notes should use Web API or Zotero plugin APIs, not direct SQLite writes.

### Zotero SQLite Read-Only Access

Read `zotero.sqlite` only when local attachment paths or fast metadata mirroring are needed.

Do not write to `zotero.sqlite`.

Useful data from local SQLite:

- Item key
- Item type
- Parent-child relationship
- Attachment path
- Attachment content type
- Collections
- Tags
- Notes
- Zotero full-text cache references

### PyMuPDF4LLM

Use PyMuPDF4LLM for PDF-to-Markdown conversion.

Recommended mode:

```python
chunks = pymupdf4llm.to_markdown(
    pdf_path,
    page_chunks=True,
    page_separators=False,
)
```

Reason:

- Markdown stays clean.
- Page metadata is preserved outside the visible text.
- Better fit for downstream chunking and RAG provenance.

Avoid visible page markers like:

```text
--- end of page.page_number=12 ---
```

Store page data in metadata instead.

The cleaned Markdown artifact should not contain visible page numbers or page
boundary markers. Page numbers, offsets, citation metadata, and chunk metadata
should be stored in JSON/database records and linked back to the Markdown via
stable unique IDs.

### Database

Use a local relational or document database for normalized metadata and processing state.

Possible choices:

- SQLite for a simple local plugin.
- PostgreSQL if multi-device or server-side use is planned.
- DuckDB for analytical workloads.

The database should store both:

- Raw Zotero JSON for compatibility.
- Normalized tables for fast querying.

### Vector Store

Possible choices:

- ChromaDB
- LanceDB
- Qdrant
- pgvector

`zotero-mcp` uses ChromaDB, which proves feasibility. For a plugin, ChromaDB or LanceDB are reasonable local-first choices.

### Embeddings

Possible embedding providers:

- Local default model for privacy and low cost.
- OpenAI embeddings for higher quality.
- Gemini embeddings.
- Other local HuggingFace models.

Store embedding model name and version with each embedded chunk.

### LLM

The LLM should not operate directly on whole PDFs. It should operate on retrieved chunks with provenance.

The LLM output should include:

- Answer
- Source map
- Used chunk IDs
- Used item keys
- Page references

### Markdown to HTML

Store LLM answers internally as Markdown.

When writing back to Zotero notes, convert Markdown to simple HTML.

Use stable HTML tags:

```html
<h1>
<h2>
<p>
<ul>
<ol>
<li>
<blockquote>
<strong>
<em>
<code>
<pre>
<a>
```

Avoid complex custom HTML unless a Zotero plugin-specific renderer requires it.

## 3. Zotero-Compatible Logical Model

The plugin should clone Zotero's logical organization model, not Zotero's internal SQLite schema.

Recommended mirrored concepts:

- Library
- Collection
- Item
- Attachment
- Tag
- Relation
- Note
- Annotation

Recommended plugin-only concepts:

- Document
- Markdown artifact
- Page chunk
- Semantic chunk
- Embedding
- LLM answer
- Retrieval trace
- Sync log

## 4. Database Model

### libraries

```json
{
  "library_id": "123456",
  "library_type": "user",
  "name": "My Library",
  "raw_zotero_json": {}
}
```

### collections

Collections are tree-like. Items can belong to multiple collections.

```json
{
  "collection_key": "COLL1234",
  "library_id": "123456",
  "name": "Value Ecology",
  "parent_collection_key": "PARENT123",
  "raw_zotero_json": {}
}
```

### collection_items

```json
{
  "collection_key": "COLL1234",
  "item_key": "ITEM1234"
}
```

### zotero_items

```json
{
  "item_key": "ITEM1234",
  "library_id": "123456",
  "item_type": "journalArticle",
  "version": 42,
  "deleted": false,
  "date_added": "2026-06-07T12:00:00Z",
  "date_modified": "2026-06-07T12:00:00Z",
  "raw_zotero_json": {}
}
```

### attachments

PDFs are child items in Zotero and should be stored separately.

```json
{
  "attachment_key": "PDF5678",
  "parent_item_key": "ITEM1234",
  "content_type": "application/pdf",
  "filename": "paper.pdf",
  "path": "storage:paper.pdf",
  "resolved_path": "C:/Users/.../Zotero/storage/PDF5678/paper.pdf",
  "link_mode": "imported_file",
  "md5": "...",
  "raw_zotero_json": {}
}
```

### tags

```json
{
  "item_key": "ITEM1234",
  "tag": "value ecology",
  "type": 0
}
```

### relations

```json
{
  "source_item_key": "ITEM1234",
  "relation_type": "dc:relation",
  "target_item_key": "ITEM5678"
}
```

### documents

Represents a processed attachment.

```json
{
  "document_id": "doc_ITEM1234_PDF5678",
  "zotero_item_key": "ITEM1234",
  "attachment_key": "PDF5678",
  "pdf_path": "C:/Users/.../paper.pdf",
  "pdf_hash": "...",
  "markdown_path": "...",
  "pages_json_path": "...",
  "converter": "pymupdf4llm",
  "converter_version": "1.27.2.3",
  "converted_at": "2026-06-07T12:00:00Z"
}
```

The `document_id` is the stable join key for all artifacts derived from the
same Zotero parent item and attachment. A recommended deterministic format is:

```text
document_id = <zotero_item_key>_<attachment_key>
```

Example:

```text
ITEM1234_PDF5678
```

The clean Markdown file should be associated with `document_id`, but should not
contain page numbers inline.

### page_chunks

Output from `page_chunks=True`.

```json
{
  "page_chunk_id": "ITEM1234_PDF5678_p012",
  "document_id": "doc_ITEM1234_PDF5678",
  "page": 12,
  "text": "...",
  "toc_items": [],
  "page_boxes": []
}
```

A recommended deterministic page chunk ID is:

```text
page_chunk_id = <document_id>_p<zero-padded-page-number>
```

Example:

```text
ITEM1234_PDF5678_p0012
```

Page metadata may also store offsets into the clean Markdown text if the
Markdown is assembled from page chunks:

```json
{
  "page_chunk_id": "ITEM1234_PDF5678_p0012",
  "document_id": "ITEM1234_PDF5678",
  "page": 12,
  "markdown_start_char": 18220,
  "markdown_end_char": 20640
}
```

### chunks

Final semantic chunks used for retrieval.

```json
{
  "chunk_id": "ITEM1234_0042",
  "document_id": "doc_ITEM1234_PDF5678",
  "zotero_item_key": "ITEM1234",
  "attachment_key": "PDF5678",
  "pages": [12, 13],
  "start_char": 18220,
  "end_char": 20640,
  "text": "...",
  "zotero_item_uri": "zotero://select/library/items/ITEM1234",
  "zotero_pdf_uri": "zotero://open-pdf/library/items/PDF5678?page=12"
}
```

A recommended deterministic semantic chunk ID is:

```text
chunk_id = <document_id>_c<zero-padded-chunk-number>
```

Example:

```text
ITEM1234_PDF5678_c0042
```

The chunk record is where page references become visible to the retrieval
system. The Markdown body remains clean, while chunk metadata carries:

- `zotero_item_key`
- `attachment_key`
- `document_id`
- `pages`
- `start_char`
- `end_char`
- Zotero item URI
- Zotero PDF page URI

This lets a retrieved chunk produce accurate citations and Zotero jump links
without polluting the Markdown source text.

## 4.1 Unique ID and Artifact Linking

All derived files and database records should be linked through one stable ID
chain.

Recommended ID hierarchy:

```text
zotero_item_key
  -> attachment_key
  -> document_id
  -> page_chunk_id
  -> chunk_id
  -> embedding_id
  -> retrieval_trace
  -> llm_answer
```

Recommended deterministic IDs:

```text
document_id   = <zotero_item_key>_<attachment_key>
page_chunk_id = <document_id>_p<page>
chunk_id      = <document_id>_c<chunk_index>
embedding_id  = emb_<chunk_id>_<embedding_model_hash>
answer_id     = ans_<timestamp_or_uuid>
```

The plugin should preserve three separate but linked layers:

1. Clean content layer
   - Markdown body.
   - No visible page numbers.
   - No page separators.

2. Bibliographic metadata layer
   - Zotero raw JSON.
   - Normalized citation fields.
   - Collections, tags, relations.

3. Retrieval metadata layer
   - Page numbers.
   - Character offsets.
   - Chunk IDs.
   - Embedding IDs.
   - Zotero jump links.
   - Retrieval scores.

This structure allows the same Markdown document to be rechunked or re-embedded
without losing citation provenance.

### embeddings

```json
{
  "embedding_id": "emb_ITEM1234_0042",
  "chunk_id": "ITEM1234_0042",
  "vector_store": "chroma",
  "embedding_model": "text-embedding-3-small",
  "embedding_model_version": "...",
  "created_at": "2026-06-07T12:00:00Z"
}
```

### llm_answers

```json
{
  "answer_id": "ans_20260607_001",
  "scope_type": "collection",
  "scope_key": "COLL1234",
  "question": "...",
  "answer_markdown": "...",
  "answer_html": "...",
  "model": "gpt-5",
  "created_at": "2026-06-07T12:00:00Z",
  "zotero_note_key": "NOTE9999"
}
```

### retrieval_traces

```json
{
  "answer_id": "ans_20260607_001",
  "chunk_id": "ITEM1234_0042",
  "zotero_item_key": "ITEM1234",
  "attachment_key": "PDF5678",
  "pages": [12, 13],
  "score": 0.82,
  "rank": 1
}
```

### sync_log

```json
{
  "sync_id": "sync_001",
  "started_at": "2026-06-07T12:00:00Z",
  "finished_at": "2026-06-07T12:02:00Z",
  "library_id": "123456",
  "items_seen": 100,
  "items_updated": 7,
  "documents_reprocessed": 2,
  "errors": []
}
```

## 5. Scope Resolution Logic

The plugin should support four retrieval scopes:

- Item
- Collection
- Tag
- Whole library

### Item Scope

Retrieve chunks where:

```text
zotero_item_key = selected item key
```

### Collection Scope

Zotero collections are not exclusive folders. They are closer to playlists.

Resolution:

1. Get selected collection.
2. Optionally include descendant collections.
3. Get all item keys in those collections.
4. Retrieve chunks for those items.

### Tag Scope

Resolution:

1. Find item keys with the selected tag.
2. Retrieve chunks for those items.

### Whole Library Scope

Resolution:

1. Get all non-deleted items in a library.
2. Retrieve chunks for all indexed documents.

### Pseudocode

```python
def resolve_scope(scope_type, scope_key):
    if scope_type == "item":
        return [scope_key]

    if scope_type == "collection":
        collection_keys = get_collection_descendants(scope_key)
        return get_items_in_collections(collection_keys)

    if scope_type == "tag":
        return get_items_with_tag(scope_key)

    if scope_type == "library":
        return get_all_items_in_library(scope_key)
```

## 6. Processing Pipeline

### Initial Sync

```text
Zotero
  -> read libraries
  -> read collections
  -> read items
  -> read child attachments
  -> read tags
  -> read relations
  -> store raw JSON
  -> update normalized tables
```

### PDF Processing

```text
Attachment path
  -> verify PDF exists
  -> hash PDF
  -> PyMuPDF4LLM page_chunks=True
  -> save clean markdown
  -> save page metadata
  -> semantic chunking
  -> save chunks
  -> embed chunks
  -> write vector index
```

### Query Pipeline

```text
User question
  -> determine scope
  -> resolve scope to item keys
  -> vector search over chunks in scope
  -> optional rerank
  -> build prompt with chunk text and provenance
  -> LLM answer
  -> source map
  -> save answer and retrieval trace
  -> optionally write Zotero note
```

### Zotero Note Write-Back

```text
Answer Markdown
  -> convert to HTML
  -> add source links
  -> create Zotero note via Web API
  -> save returned note key
```

## 7. Zotero Note Strategy

### Single-Item Answer

If the answer is based on one item, create a child note attached to that item.

```json
{
  "itemType": "note",
  "parentItem": "ITEM1234",
  "note": "<h1>AI Reading Note</h1><p>...</p>",
  "tags": [
    { "tag": "ai-note" },
    { "tag": "rag-memory" }
  ]
}
```

### Collection Answer

If the answer is based on multiple items from a collection, create a standalone synthesis note and add it to the relevant collection if possible.

Recommended title:

```text
[AI Synthesis] Value Ecology - 2026-06-07 - Question title
```

Recommended tags:

```text
ai-synthesis
rag-memory
collection:Value Ecology
```

### Whole-Library Answer

Create a standalone note in a dedicated collection, for example:

```text
AI Research Notes
```

## 8. Source Links in Zotero Notes

Use Zotero URI links inside note HTML.

### Link to Zotero Item

```html
<a href="zotero://select/library/items/ITEM1234">Li 2025</a>
```

### Link to PDF Page

Use the attachment key, not the parent item key.

```html
<a href="zotero://open-pdf/library/items/PDF5678?page=12">Li 2025, p.12</a>
```

### Example Source Section

```html
<h2>Sources</h2>
<ul>
  <li>
    <a href="zotero://open-pdf/library/items/PDF5678?page=12">
      Li 2025, p.12
    </a>
  </li>
  <li>
    <a href="zotero://open-pdf/library/items/PDF9999?page=23">
      Massumi 2018, p.23
    </a>
  </li>
</ul>
```

## 9. Sync Strategy

Use Zotero as canonical upstream data.

Track:

- Zotero item key
- Zotero item version
- `dateModified`
- deleted/trash state
- attachment key
- attachment hash
- converter version
- chunker version
- embedding model version

### Update Rules

```text
If Zotero item version changed:
  update raw_zotero_json
  update normalized metadata

If attachment hash changed:
  reconvert PDF
  regenerate Markdown
  regenerate page metadata
  rechunk
  re-embed

If item deleted or trashed:
  mark inactive
  do not immediately hard-delete local artifacts

If embedding model changed:
  re-embed chunks

If chunking config changed:
  rechunk and re-embed
```

## 10. Relationship to zotero-mcp

`54yyyu/zotero-mcp` demonstrates that the Zotero integration layer is feasible.

Useful design references:

- `pyzotero` for Zotero API access.
- Local/Web/Hybrid mode.
- Local API serialization lock.
- Local SQLite read-only attachment path resolution.
- Web API note creation and update.
- ChromaDB-based semantic search.
- CLI and MCP tool separation.

Recommended differences for this plugin:

- Use PyMuPDF4LLM instead of generic full-text extraction for PDF Markdown.
- Use page and chunk metadata as first-class entities.
- Store full retrieval provenance.
- Treat Zotero notes as an output channel, not the primary database.
- Support collection/tag/library scoped retrieval explicitly.

## 11. Implementation Milestones

### Phase 1: Zotero Mirror

- Configure Zotero local/API credentials.
- Read items, collections, tags, attachments.
- Store raw Zotero JSON.
- Build normalized mirror tables.
- Resolve local PDF attachment paths.

### Phase 2: PDF to Markdown

- Integrate PyMuPDF4LLM.
- Convert PDFs to clean Markdown.
- Save page metadata.
- Add PDF hash and converter version tracking.

### Phase 3: Chunking and Embeddings

- Build page-aware chunker.
- Preserve pages, offsets, item key, attachment key.
- Create vector index.
- Support incremental reindexing.

### Phase 4: Scoped Retrieval

- Implement item scope.
- Implement collection scope with descendants.
- Implement tag scope.
- Implement whole-library scope.
- Add reranking if needed.

### Phase 5: LLM Answer Memory

- Save prompts, answers, retrieved chunks, scores, model info.
- Generate Markdown answer.
- Generate HTML answer for Zotero.
- Preserve full provenance.

### Phase 6: Zotero Note Write-Back

- Create child note for single-item answers.
- Create standalone synthesis note for collection/library answers.
- Add source links using Zotero URI scheme.
- Save Zotero note key in local database.

## 12. Design Principles

1. Zotero remains the canonical literature library.
2. The plugin database mirrors Zotero logic, not Zotero SQLite schema.
3. `zotero.sqlite` is read-only.
4. Zotero Web API or plugin API handles writes.
5. Markdown should stay clean.
6. Page numbers belong in metadata.
7. Every chunk must preserve provenance.
8. Every LLM answer must preserve retrieval trace.
9. Zotero notes are human-readable outputs, not the only source of truth.
10. Multi-document answers should become synthesis notes, not arbitrary child notes under one cited paper.

## 13. Minimal End-to-End Example

```text
User asks:
  "How does this collection define ecological value?"

Scope:
  collection = Value Ecology

Pipeline:
  resolve collection -> item keys
  retrieve top chunks
  generate answer
  save answer and retrieval trace
  create Zotero standalone synthesis note

Zotero note contains:
  answer
  source list
  links to exact PDF pages

Database contains:
  full answer
  exact chunks used
  scores
  model
  prompt
  Zotero note key
```

This architecture keeps Zotero clean and usable while adding a reproducible AI memory layer on top.
