"""Verify which PDFs are indexed in Pinecone vs. what's in the directory."""
import os
import sys
from pathlib import Path
from collections import defaultdict
from pinecone import Pinecone

# Configuration
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY', '')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'cook-islands-legislation')
LEGISLATION_DIR = os.getenv('LEGISLATION_DIR', '/data/legislation')

if not PINECONE_API_KEY:
    print("Error: PINECONE_API_KEY not set")
    sys.exit(1)

print("=== Verifying Indexed PDFs ===")
print()

# Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

# Get all PDFs in directory
pdf_files = list(Path(LEGISLATION_DIR).glob('*.pdf'))
pdf_names = {f.stem for f in pdf_files}

print(f"PDFs in directory: {len(pdf_names)}")
print()

# Query Pinecone for unique doc_ids
# We'll do this by querying a sample and extracting doc_ids from metadata
print("Querying Pinecone for indexed documents...")

# Get stats first
stats = index.describe_index_stats()
total_vectors = stats.get('total_vector_count', 0)
print(f"Total vectors in Pinecone: {total_vectors:,}")
print()

# Fetch a sample of vectors to get doc_ids
# Since we can't query all metadata directly, we'll fetch vectors in batches
# and collect unique doc_ids

# Strategy: Use list_paginated to get all vector IDs, then fetch metadata in batches
print("Fetching vector metadata to identify documents...")
print("(This may take a moment...)")

doc_chunks = defaultdict(int)
doc_names = defaultdict(str)

# Fetch vectors in batches using query with dummy vector
# This is a workaround since Pinecone doesn't have a direct "list all metadata" API
dummy_vec = [0.0] * 3072

try:
    # Query for a large number to get samples
    # We'll do multiple queries to cover the space
    sample_size = 10000
    results = index.query(
        vector=dummy_vec,
        top_k=min(sample_size, total_vectors),
        include_metadata=True
    )

    for match in results.get('matches', []):
        metadata = match.get('metadata', {})
        doc_id = metadata.get('doc_id', '')
        act_name = metadata.get('act_name', '')

        if doc_id:
            doc_chunks[doc_id] += 1
            if not doc_names[doc_id]:
                doc_names[doc_id] = act_name

    print(f"Sampled {len(results.get('matches', []))} vectors")
    print(f"Found {len(doc_chunks)} unique documents in sample")
    print()

except Exception as e:
    print(f"Error querying Pinecone: {e}")
    print("Trying alternative approach...")

    # Alternative: Parse chunk IDs (they contain doc_id prefix)
    # Chunk IDs are formatted like: doc_id::chunk_identifier
    print("Attempting to extract doc_ids from vector IDs...")

    # We can't easily list all IDs without fetching, so this is limited
    print("Note: Limited to sample data only")
    print()

# Compare with PDF directory
print("=== Comparison ===")
print()

indexed_docs = set(doc_chunks.keys())
pdf_doc_ids = {name.replace(' ', '_').lower() for name in pdf_names}

# Find matches and differences
in_both = indexed_docs & pdf_doc_ids
only_indexed = indexed_docs - pdf_doc_ids
only_filesystem = pdf_doc_ids - indexed_docs

print(f"Documents in both Pinecone and filesystem: {len(in_both)}")
print(f"Documents only in Pinecone: {len(only_indexed)}")
print(f"Documents only in filesystem (not indexed): {len(only_filesystem)}")
print()

if only_indexed:
    print("Documents in Pinecone but not in filesystem:")
    for doc_id in sorted(only_indexed)[:20]:
        act_name = doc_names.get(doc_id, 'Unknown')
        chunks = doc_chunks.get(doc_id, 0)
        print(f"  - {doc_id} ({act_name}) - {chunks} chunks")
    if len(only_indexed) > 20:
        print(f"  ... and {len(only_indexed) - 20} more")
    print()

if only_filesystem:
    print("PDFs not yet indexed (or not found in sample):")
    for doc_id in sorted(only_filesystem)[:20]:
        print(f"  - {doc_id}")
    if len(only_filesystem) > 20:
        print(f"  ... and {len(only_filesystem) - 20} more")
    print()

if in_both:
    print("Sample of successfully indexed documents:")
    for doc_id in sorted(in_both)[:10]:
        act_name = doc_names.get(doc_id, 'Unknown')
        chunks = doc_chunks.get(doc_id, 0)
        print(f"  - {doc_id} ({act_name}) - {chunks} chunks")
    print()

print("=== Statistics ===")
if doc_chunks:
    avg_chunks = sum(doc_chunks.values()) / len(doc_chunks)
    max_chunks = max(doc_chunks.values())
    min_chunks = min(doc_chunks.values())

    print(f"Average chunks per document: {avg_chunks:.1f}")
    print(f"Min chunks: {min_chunks}")
    print(f"Max chunks: {max_chunks}")
    print()

print("Note: This analysis is based on a sample of vectors.")
print("For complete accuracy, all vectors would need to be fetched.")
