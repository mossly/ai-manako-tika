"""Backfill SQLite metadata database from existing PDFs.

This script processes all PDFs in the legislation directory and populates
the SQLite metadata database WITHOUT touching Pinecone. Safe to run while
Pinecone ingestion is happening on another system.
"""
import os
import asyncio
import hashlib
from pathlib import Path
from loguru import logger

# Add app to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from app.db.metadata import metadata_db
from app.utils.extract_year import extract_year_from_act_name
from app.rag.chunking import from_legislation_markdown
from app.tools.pdf_processor import process_pdf_to_markdown


def get_file_hash(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


async def backfill_from_pdfs(legislation_dir: str = None, limit: int = None):
    """Backfill metadata database from PDFs.

    Args:
        legislation_dir: Directory containing PDF files (default: from env)
        limit: Optional limit on number of PDFs to process (for testing)
    """
    if not legislation_dir:
        legislation_dir = os.getenv('LEGISLATION_DIR', 'data/legislation')

    legislation_path = Path(legislation_dir)
    if not legislation_path.exists():
        logger.error(f"Legislation directory not found: {legislation_dir}")
        return

    # Find all PDFs
    pdf_files = sorted(legislation_path.glob('*.pdf'))
    logger.info(f"Found {len(pdf_files)} PDF files in {legislation_dir}")

    if limit:
        pdf_files = pdf_files[:limit]
        logger.info(f"Limited to first {limit} PDFs")

    processed = 0
    skipped = 0
    errors = 0

    for pdf_path in pdf_files:
        try:
            logger.info(f"Processing: {pdf_path.name}")

            # Calculate file hash
            file_hash = get_file_hash(str(pdf_path))

            # Extract act name from filename
            # Format: "banking_act_1996.pdf" -> "Banking Act 1996"
            act_name_guess = pdf_path.stem.replace('_', ' ').title()

            # Process PDF to markdown
            markdown_text, extracted_act_name = await process_pdf_to_markdown(
                str(pdf_path),
                act_name=None  # Let it auto-extract
            )

            # Use extracted name if available, otherwise use filename-based guess
            act_name = extracted_act_name or act_name_guess

            # Extract year
            year = extract_year_from_act_name(act_name)

            # Generate doc_id (consistent with Pinecone naming)
            doc_id = pdf_path.stem.lower().replace(' ', '_')

            # Insert document
            metadata_db.upsert_document(
                doc_id=doc_id,
                act_name=act_name,
                year=year,
                pdf_filename=pdf_path.name,
                pdf_path=str(pdf_path),
                file_hash=file_hash
            )
            logger.info(f"  → Document: {act_name} (year: {year})")

            # Chunk the markdown
            chunks_data = from_legislation_markdown(
                doc_id=doc_id,
                act_name=act_name,
                markdown_text=markdown_text,
                metadata={
                    'pdf_path': str(pdf_path),
                    'pdf_filename': pdf_path.name,
                    'file_hash': file_hash
                }
            )

            # Insert chunks
            for chunk in chunks_data:
                metadata_db.upsert_chunk(
                    chunk_id=chunk['id'],
                    doc_id=doc_id,
                    metadata=chunk['meta']
                )

            # Update chunk count
            metadata_db.update_document_chunk_count(doc_id)

            logger.info(f"  → Inserted {len(chunks_data)} chunks")
            processed += 1

        except Exception as e:
            logger.exception(f"Error processing {pdf_path.name}: {e}")
            errors += 1
            continue

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Backfill Summary:")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Skipped: {skipped}")
    logger.info(f"  Errors: {errors}")
    logger.info(f"{'='*60}\n")

    # Print database stats
    stats = metadata_db.get_stats()
    logger.info(f"Database Statistics:")
    logger.info(f"  Total Documents: {stats['total_documents']}")
    logger.info(f"  Total Chunks: {stats['total_chunks']}")
    logger.info(f"  Year Range: {stats['earliest_year']} - {stats['latest_year']}")
    logger.info(f"\nActs by Year:")
    for year_stat in stats['acts_by_year']:
        logger.info(f"    {year_stat['year']}: {year_stat['count']} acts")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Backfill metadata database from PDFs')
    parser.add_argument('--dir', help='Legislation directory (default: data/legislation)')
    parser.add_argument('--limit', type=int, help='Limit number of PDFs to process')
    args = parser.parse_args()

    asyncio.run(backfill_from_pdfs(legislation_dir=args.dir, limit=args.limit))
