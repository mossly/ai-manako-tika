"""Re-run ingestion for all PDFs with optimizations enabled.

This script will:
1. Process all PDFs in the legislation directory
2. Use the new batch fingerprint checking to minimize Pinecone reads
3. Only write chunks that are new or changed
4. Update the metadata database
"""
import os
import sys
import asyncio
from pathlib import Path

# Add app to path
sys.path.insert(0, '/app')

from app.tools.ingest import ingest_pdf
from loguru import logger

LEGISLATION_DIR = os.getenv('LEGISLATION_DIR', '/data/legislation')

async def sync_all():
    """Sync all PDFs with Pinecone using optimized batch operations."""

    logger.info("=== Starting PDF Sync with Optimizations ===")
    logger.info(f"Legislation directory: {LEGISLATION_DIR}")
    logger.info("")

    # Get all PDFs
    pdf_files = sorted(Path(LEGISLATION_DIR).glob('*.pdf'))
    logger.info(f"Found {len(pdf_files)} PDF files")
    logger.info("")

    # Statistics
    stats = {
        'total': len(pdf_files),
        'processed': 0,
        'skipped': 0,
        'errors': 0,
        'total_chunks': 0,
        'new_chunks': 0,
    }

    # Process each PDF
    for i, pdf_path in enumerate(pdf_files, 1):
        pdf_name = pdf_path.stem
        logger.info(f"[{i}/{len(pdf_files)}] Processing: {pdf_name}")

        try:
            # Ingest PDF (will use optimizations automatically)
            # force_reprocess=False means it will check file hash first
            chunks_ingested = await ingest_pdf(
                str(pdf_path),
                act_name=None,  # Will derive from filename
                force_reprocess=False  # Use hash-based checking
            )

            if chunks_ingested > 0:
                stats['processed'] += 1
                stats['total_chunks'] += chunks_ingested
                logger.info(f"  ✓ Ingested {chunks_ingested} chunks")
            else:
                stats['skipped'] += 1
                logger.info(f"  ⊘ Skipped (unchanged)")

        except Exception as e:
            stats['errors'] += 1
            logger.exception(f"  ✗ Error processing {pdf_name}: {e}")

        logger.info("")

    # Print summary
    logger.info("=== Sync Complete ===")
    logger.info(f"Total PDFs: {stats['total']}")
    logger.info(f"Processed: {stats['processed']}")
    logger.info(f"Skipped (unchanged): {stats['skipped']}")
    logger.info(f"Errors: {stats['errors']}")
    logger.info(f"Total chunks ingested: {stats['total_chunks']}")
    logger.info("")

    if stats['processed'] == 0 and stats['errors'] == 0:
        logger.info("✓ All PDFs are already up-to-date!")
    elif stats['errors'] > 0:
        logger.warning(f"⚠ {stats['errors']} PDFs had errors - check logs above")
    else:
        logger.info(f"✓ Successfully updated {stats['processed']} PDFs")

    return stats

if __name__ == "__main__":
    asyncio.run(sync_all())
