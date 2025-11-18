# Sync and Verify Legislation Index

This guide helps you verify what's indexed in Pinecone, sync all PDFs with optimizations, and rebuild the metadata database.

## Scripts Overview

1. **verify_indexed_pdfs.py** - Check what's currently indexed vs. filesystem
2. **sync_all_pdfs.py** - Re-run ingestion with optimizations (minimal writes)
3. **rebuild_metadata.py** - Rebuild SQLite metadata database from Pinecone

## Usage

### Step 1: Verify Current State

Check which PDFs are indexed and which are missing:

```bash
sudo docker exec ai-manako-tika python verify_indexed_pdfs.py
```

This will show:
- Documents in both Pinecone and filesystem
- Documents only in Pinecone (duplicates or removed PDFs)
- Documents only in filesystem (not yet indexed)

### Step 2: Sync All PDFs (with Optimizations)

Run the optimized sync to ensure all PDFs are up-to-date:

```bash
sudo docker exec ai-manako-tika python sync_all_pdfs.py
```

**What this does:**
- ✅ Checks file hash before processing (skips unchanged PDFs)
- ✅ Uses batch fingerprint checking (99% fewer Pinecone reads)
- ✅ Only writes chunks that are new or changed
- ✅ Batches writes at 200 vectors per operation (50% fewer writes)

**Expected behavior:**
- If PDFs haven't changed: All will be skipped (0 writes)
- If PDFs are new/changed: Only those chunks will be written

### Step 3: Rebuild Metadata Database

Build the SQLite metadata database from Pinecone:

```bash
sudo docker exec ai-manako-tika python rebuild_metadata.py
```

This will:
- Query all vectors from Pinecone
- Extract document and chunk metadata
- Populate the SQLite database with accurate counts
- Enable better tracking and statistics

## Checking Results

After running, you can check the status:

```bash
# Check Pinecone stats
sudo docker exec ai-manako-tika python check_pinecone_stats.py

# Query metadata database
sqlite3 data/metadata.db "SELECT COUNT(*) as docs, SUM(chunk_count) as chunks FROM documents;"

# List all documents
sqlite3 data/metadata.db "SELECT act_name, chunk_count FROM documents ORDER BY chunk_count DESC LIMIT 20;"
```

## Expected Resource Usage

With the optimizations:

**First run (all new PDFs):**
- 271 PDFs × 150 chunks/PDF = ~40,650 chunks
- Writes needed: ~40,650 / 200 = ~203 write operations
- Well within your 800,000 WU limit!

**Subsequent runs (unchanged PDFs):**
- Writes needed: 0 (all skipped)
- Reads needed: 1-2 batch operations total

## Monitoring Progress

Watch logs in real-time:

```bash
sudo docker logs -f ai-manako-tika
```

## Troubleshooting

**Database locked errors:**
- Stop the app: `sudo docker compose down`
- Run the script
- Start the app: `sudo docker compose up -d`

**Out of memory:**
- The scripts process in batches, but if issues occur, reduce batch sizes
- Edit the scripts and change `batch_size` values

**Pinecone quota exceeded:**
- Check current usage: Run `check_pinecone_stats.py`
- The optimizations should prevent this!

## Notes

- All scripts use the optimized batch operations
- Safe to run multiple times (idempotent)
- Will not create duplicates
- Fingerprint checking ensures only changed content is reprocessed
