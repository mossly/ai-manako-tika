"""Index only the PDFs that are missing from the metadata database."""
import os
import sys
import asyncio
from pathlib import Path

# Add app to path
sys.path.insert(0, '/app')

from app.tools.ingest import ingest_pdf
from app.db.metadata import metadata_db
from loguru import logger

LEGISLATION_DIR = os.getenv('LEGISLATION_DIR', '/data/legislation')

async def index_missing():
    """Index only PDFs not in metadata database."""

    logger.info("=== Indexing Missing PDFs ===")
    logger.info("")

    # Get all PDFs
    pdf_files = sorted(Path(LEGISLATION_DIR).glob('*.pdf'))
    logger.info(f"Total PDFs in directory: {len(pdf_files)}")

    # Get indexed docs from metadata DB
    indexed = metadata_db.get_all_documents()
    indexed_ids = {doc['doc_id'] for doc in indexed}
    logger.info(f"Already indexed: {len(indexed_ids)}")
    logger.info("")

    # Find missing PDFs
    missing = []
    for pdf in pdf_files:
        doc_id = pdf.stem.replace(' ', '_').lower()
        if doc_id not in indexed_ids:
            missing.append(pdf)

    if not missing:
        logger.info("✓ All PDFs are already indexed!")
        return

    logger.info(f"Found {len(missing)} missing PDFs to index:")
    for pdf in missing:
        logger.info(f"  - {pdf.name}")
    logger.info("")

    # Index each missing PDF with force_reprocess=True
    stats = {
        'total': len(missing),
        'processed': 0,
        'errors': 0,
        'total_chunks': 0,
    }

    for i, pdf_path in enumerate(missing, 1):
        pdf_name = pdf_path.stem
        logger.info(f"[{i}/{len(missing)}] Processing: {pdf_name}")

        try:
            # Force reprocess to ensure it gets indexed
            chunks_ingested = await ingest_pdf(
                str(pdf_path),
                act_name=None,  # Will derive from filename
                force_reprocess=True  # Force processing even if hash matches
            )

            if chunks_ingested > 0:
                stats['processed'] += 1
                stats['total_chunks'] += chunks_ingested
                logger.info(f"  ✓ Ingested {chunks_ingested} chunks")
            else:
                logger.warning(f"  ⚠ No chunks created (may have failed)")

        except Exception as e:
            stats['errors'] += 1
            logger.exception(f"  ✗ Error processing {pdf_name}: {e}")

        logger.info("")

    # Print summary
    logger.info("=== Indexing Complete ===")
    logger.info(f"Total missing PDFs: {stats['total']}")
    logger.info(f"Successfully processed: {stats['processed']}")
    logger.info(f"Errors: {stats['errors']}")
    logger.info(f"Total chunks ingested: {stats['total_chunks']}")
    logger.info("")

    if stats['errors'] == 0:
        logger.info("✓ All missing PDFs successfully indexed!")
    else:
        logger.warning(f"⚠ {stats['errors']} PDFs had errors - check logs above")

    return stats

if __name__ == "__main__":
    asyncio.run(index_missing())
