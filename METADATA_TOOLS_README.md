# Metadata Discovery Tools

This document describes the SQLite metadata database and new discovery tools added to the Cook Islands Legislation RAG system.

## Overview

The system now uses a hybrid approach:
- **Pinecone**: Stores vector embeddings for semantic search
- **SQLite**: Stores metadata for fast filtering and discovery queries

This allows efficient metadata queries without consuming Pinecone quota or requiring expensive vector operations.

## SQLite Schema

### Tables

#### `documents`
Stores high-level information about each legislation act:
- `doc_id` (PRIMARY KEY) - Document identifier (e.g., "banking_act_1996")
- `act_name` - Human-readable name (e.g., "Banking Act 1996")
- `year` - Extracted year from act name
- `pdf_filename` - Original PDF filename
- `pdf_path` - Full path to PDF file
- `chunk_count` - Number of chunks in this document
- `file_hash` - SHA256 hash for change detection
- `last_processed` - Last ingestion timestamp

#### `chunks`
Stores metadata for each text chunk:
- `chunk_id` (PRIMARY KEY) - Unique chunk identifier
- `doc_id` (FOREIGN KEY) - Parent document
- `section_number` - Section number (e.g., "5", "13A")
- `section_title` - Section heading
- `section_id` - Unique section identifier
- `subsection_number` - Subsection identifier
- `element_type` - Type: 'section', 'subsection', 'paragraph', etc.
- `page_number` - PDF page number
- `heading_path` - Full hierarchical path
- `chunk_index` - Sequence number within document

#### `definitions` (Future Use)
Placeholder table for definitions database:
- `id` (PRIMARY KEY)
- `doc_id` (FOREIGN KEY)
- `term` - Defined term
- `definition_text` - The definition
- `section_id` - Where the definition appears

## New Discovery Tools

### 1. `list_all_acts_tool`

**Purpose**: Get complete list of all legislation acts

**Parameters**:
- `sort_by`: "name" (alphabetical) or "year" (newest first)
- `limit`: Maximum acts to return (default 100)

**Example Use Cases**:
- "What acts are in the database?"
- "List all legislation"
- "Show me the newest acts"

### 2. `search_acts_by_title_tool`

**Purpose**: Search for acts by keywords in their title (not semantic)

**Parameters**:
- `title_query`: Keywords to search for (case-insensitive)
- `year`: Optional year filter

**Example Use Cases**:
- "Find all banking acts"
- "Acts with 'education' in the title"
- "Show me tax-related legislation from 2020"

### 3. `filter_acts_by_year_tool`

**Purpose**: Filter acts by year or year range

**Parameters**:
- `year`: Specific year
- `year_from`: Start of range (inclusive)
- `year_to`: End of range (inclusive)

**Example Use Cases**:
- "Acts from 2020"
- "Legislation between 2015 and 2020"
- "All acts since 2018"

### 4. `get_act_metadata_tool`

**Purpose**: Get detailed information about a specific act

**Parameters**:
- `act_name_or_id`: Act name or document ID
- `include_sections`: Include list of all sections (default false)

**Example Use Cases**:
- "Tell me about the Banking Act 1996"
- "How many sections does the Electoral Act have?"
- "What's the structure of the Criminal Procedure Act?"

**Returns**:
- Document metadata (year, filename, chunk count)
- Optionally: List of all sections with titles

### 5. `find_definitions_tool`

**Purpose**: Find definition/interpretation sections across acts

**Parameters**:
- `act_filter`: Optional filter to specific act
- `top_k`: Number of definition sections to retrieve (default 5)

**Example Use Cases**:
- "What does 'beneficial owner' mean?"
- "Find definition sections"
- "What terms are defined in the Banking Act?"

**How It Works**:
- Searches for sections with titles containing "Interpretation", "Definitions", "Meaning"
- Uses semantic search to find definition-like content
- Filters results to only include definition sections

## Backfilling Metadata

### Initial Setup

To populate the SQLite database from existing PDFs:

```bash
python backfill_metadata.py
```

**Options**:
- `--dir` - Specify legislation directory (default: data/legislation)
- `--limit` - Limit number of PDFs to process (for testing)

**Example**:
```bash
# Process all PDFs
python backfill_metadata.py

# Process only first 10 PDFs (testing)
python backfill_metadata.py --limit 10

# Use custom directory
python backfill_metadata.py --dir /path/to/pdfs
```

**Important**: The backfill script does NOT touch Pinecone. It's safe to run while Pinecone ingestion is happening on another system.

### What The Backfill Does

1. Finds all PDFs in legislation directory
2. Processes each PDF through chunking pipeline
3. Extracts metadata (act name, year, sections)
4. Populates SQLite database
5. Calculates chunk counts per document

## Dual-Write System

For **future ingestion** (after backfill), the system automatically writes to both:

1. **Pinecone**: Embeddings + minimal metadata (for vector search)
2. **SQLite**: Full metadata (for discovery queries)

This happens atomically in `app/rag/indexer.py`:
- Pinecone upsert (existing behavior)
- SQLite upsert (new - non-fatal if fails)

## Year Extraction

Years are automatically extracted from act names using regex patterns:

**Supported Formats**:
- "Banking Act 1996" → 1996
- "Banking Act (Amendment) 2005" → 2005
- "Electoral Act 2004-05" → 2004
- "Criminal Procedure (Reform and Modernisation) Act 2023" → 2023

See `app/utils/extract_year.py` for implementation.

## Database Location

Default: `/data/metadata.db`

Override with environment variable:
```bash
METADATA_DB_PATH=/custom/path/metadata.db
```

## Querying Directly

You can query the SQLite database directly for analytics:

```bash
sqlite3 /data/metadata.db

# Count acts by year
SELECT year, COUNT(*) as count
FROM documents
WHERE year IS NOT NULL
GROUP BY year
ORDER BY year DESC;

# Acts without year extraction
SELECT act_name FROM documents WHERE year IS NULL;

# Most chunked documents
SELECT act_name, chunk_count
FROM documents
ORDER BY chunk_count DESC
LIMIT 10;
```

## Future Enhancements

### Definitions Database (Roadmap)

Planned feature to extract and index all defined terms:

1. Identify definition sections (done via `find_definitions_tool`)
2. Parse definitions using NLP/regex
3. Extract term → definition mappings
4. Store in `definitions` table
5. Create new tool: `lookup_definition_tool`

**Benefits**:
- Quick term lookups across all acts
- Cross-reference where terms are defined
- Identify terminology conflicts across legislation

## Performance

**SQLite Queries**: Sub-millisecond for most operations
**Backfill Speed**: ~30-60 seconds per PDF (depends on size)
**Storage**: ~1-5MB for typical legislation corpus

## Troubleshooting

### Database Locked

If you get "database is locked" errors:
- SQLite uses file-based locking
- Don't run multiple backfills simultaneously
- Check for stale `.db-lock` files

### Missing Years

If acts show `year: null`:
- Check act name format in `documents` table
- Update year extraction regex in `app/utils/extract_year.py`
- Re-run backfill

### Metadata Out of Sync

If SQLite and Pinecone don't match:
- Delete `/data/metadata.db`
- Re-run `python backfill_metadata.py`
- Future ingests will stay in sync

## API Examples

**List all acts**:
```bash
curl http://localhost:8080/stats
```

**Query SQLite directly** (in Python):
```python
from app.db.metadata import metadata_db

# Get all acts
acts = metadata_db.get_all_documents(sort_by='year', limit=50)

# Search by title
banking_acts = metadata_db.search_by_title('banking')

# Filter by year range
recent = metadata_db.filter_by_year(year_from=2020, year_to=2023)

# Get stats
stats = metadata_db.get_stats()
print(f"Total: {stats['total_documents']} acts")
print(f"Range: {stats['earliest_year']} - {stats['latest_year']}")
```
