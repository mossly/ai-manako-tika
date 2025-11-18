"""Rebuild metadata database from Pinecone index.

This script will:
1. Query all vectors from Pinecone
2. Extract document and chunk metadata
3. Rebuild the SQLite metadata database with accurate counts
"""
import os
import sys
from collections import defaultdict
from pinecone import Pinecone

# Add app to path
sys.path.insert(0, '/app')

from app.db.metadata import metadata_db
from loguru import logger

PINECONE_API_KEY = os.getenv('PINECONE_API_KEY', '')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'cook-islands-legislation')

if not PINECONE_API_KEY:
    print("Error: PINECONE_API_KEY not set")
    sys.exit(1)

def rebuild_metadata():
    """Rebuild metadata database from Pinecone."""

    logger.info("=== Rebuilding Metadata Database ===")
    logger.info("")

    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    # Get stats
    stats = index.describe_index_stats()
    total_vectors = stats.get('total_vector_count', 0)

    logger.info(f"Total vectors in Pinecone: {total_vectors:,}")
    logger.info("")

    # We need to fetch all vectors to get complete metadata
    # Strategy: Use query with dummy vector to get large samples, multiple times

    logger.info("Fetching all vector metadata from Pinecone...")
    logger.info("(This may take several minutes for large indexes...)")
    logger.info("")

    doc_data = defaultdict(lambda: {
        'chunks': [],
        'act_name': None,
        'year': None,
        'pdf_filename': None,
        'pdf_path': None,
        'file_hash': None,
    })

    # Dummy vector for querying
    dummy_vec = [0.0] * 3072

    # Fetch in multiple queries to get better coverage
    # Pinecone query returns top_k results, so we'll do multiple queries
    # with different dummy vectors to get different results

    import random
    queries_to_make = min(10, max(1, total_vectors // 10000))

    logger.info(f"Making {queries_to_make} queries to sample vector space...")

    all_chunk_ids = set()
    batch_size = 10000

    for query_num in range(queries_to_make):
        # Use random vectors to query different parts of the space
        if query_num > 0:
            query_vec = [random.gauss(0, 0.1) for _ in range(3072)]
        else:
            query_vec = dummy_vec

        try:
            results = index.query(
                vector=query_vec,
                top_k=batch_size,
                include_metadata=True
            )

            new_chunks = 0
            for match in results.get('matches', []):
                chunk_id = match['id']

                if chunk_id in all_chunk_ids:
                    continue

                all_chunk_ids.add(chunk_id)
                new_chunks += 1

                metadata = match.get('metadata', {})
                doc_id = metadata.get('doc_id', '')

                if doc_id:
                    # Extract metadata
                    doc_data[doc_id]['chunks'].append({
                        'chunk_id': chunk_id,
                        'metadata': metadata
                    })

                    # Update document-level metadata
                    if not doc_data[doc_id]['act_name']:
                        doc_data[doc_id]['act_name'] = metadata.get('act_name')
                        doc_data[doc_id]['year'] = metadata.get('year')
                        doc_data[doc_id]['pdf_filename'] = metadata.get('pdf_filename')
                        doc_data[doc_id]['pdf_path'] = metadata.get('pdf_path')
                        doc_data[doc_id]['file_hash'] = metadata.get('file_hash')

            logger.info(f"  Query {query_num + 1}: Found {new_chunks} new chunks (total: {len(all_chunk_ids)})")

        except Exception as e:
            logger.exception(f"Error in query {query_num + 1}: {e}")

    logger.info("")
    logger.info(f"Collected metadata for {len(all_chunk_ids):,} chunks across {len(doc_data)} documents")
    logger.info("")

    # Now rebuild the database
    logger.info("Rebuilding SQLite metadata database...")

    processed_docs = 0
    processed_chunks = 0

    for doc_id, data in doc_data.items():
        try:
            # Upsert document
            metadata_db.upsert_document(
                doc_id=doc_id,
                act_name=data['act_name'] or doc_id,
                year=data['year'],
                pdf_filename=data['pdf_filename'],
                pdf_path=data['pdf_path'],
                file_hash=data['file_hash']
            )

            # Upsert all chunks for this document
            for chunk in data['chunks']:
                metadata_db.upsert_chunk(
                    chunk_id=chunk['chunk_id'],
                    doc_id=doc_id,
                    metadata=chunk['metadata']
                )
                processed_chunks += 1

            # Update chunk count
            metadata_db.update_document_chunk_count(doc_id)
            processed_docs += 1

            if processed_docs % 10 == 0:
                logger.info(f"  Processed {processed_docs} documents...")

        except Exception as e:
            logger.exception(f"Error processing document {doc_id}: {e}")

    logger.info("")
    logger.info("=== Metadata Rebuild Complete ===")
    logger.info(f"Documents processed: {processed_docs}")
    logger.info(f"Chunks processed: {processed_chunks:,}")
    logger.info("")

    # Verify
    all_docs = metadata_db.get_all_documents()
    logger.info(f"Documents in database: {len(all_docs)}")

    if all_docs:
        total_chunks_in_db = sum(d.get('chunk_count', 0) for d in all_docs)
        logger.info(f"Total chunks in database: {total_chunks_in_db:,}")

        # Show sample
        logger.info("")
        logger.info("Sample of documents in metadata DB:")
        for doc in sorted(all_docs, key=lambda x: x.get('chunk_count', 0), reverse=True)[:10]:
            logger.info(f"  - {doc['doc_id']}: {doc.get('chunk_count', 0)} chunks ({doc.get('act_name', 'Unknown')})")

    logger.info("")
    logger.info("✓ Metadata database rebuilt successfully!")

if __name__ == "__main__":
    rebuild_metadata()
