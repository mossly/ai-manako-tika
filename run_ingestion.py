"""Run legislation ingestion pipeline."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.tools.ingest import ingest_pdf
from loguru import logger
from datetime import datetime

async def main():
    """Run the ingestion with progress logging."""
    logger.info("="*80)
    logger.info("COOK ISLANDS LEGISLATION INGESTION")
    logger.info("="*80)

    # Set legislation directory
    legislation_dir = Path("data/legislation")
    pdf_files = sorted(legislation_dir.glob('*.pdf'))

    logger.info(f"Found {len(pdf_files)} PDF files")
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")

    total_chunks = 0
    processed = 0
    skipped = 0
    failed = []

    start_time = datetime.now()

    for i, pdf_path in enumerate(pdf_files, 1):
        try:
            # Log progress every 10 PDFs
            if i % 10 == 0 or i == 1:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = i / elapsed if elapsed > 0 else 0
                remaining = len(pdf_files) - i
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60

                logger.info(f"Progress: {i}/{len(pdf_files)} ({i/len(pdf_files)*100:.1f}%) - "
                           f"Processed: {processed}, Skipped: {skipped}, Failed: {len(failed)} - "
                           f"ETA: {eta_minutes:.1f} min")

            # Process PDF
            chunks = await ingest_pdf(
                str(pdf_path),
                force_reprocess=False
            )

            if chunks > 0:
                processed += 1
                total_chunks += chunks
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"[{i}/{len(pdf_files)}] Failed: {pdf_path.name} - {e}")
            failed.append({
                'file': pdf_path.name,
                'error': str(e)
            })

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("")
    logger.info("="*80)
    logger.info("INGESTION COMPLETE")
    logger.info("="*80)
    logger.info(f"Total PDFs:     {len(pdf_files)}")
    logger.info(f"Processed:      {processed}")
    logger.info(f"Skipped:        {skipped}")
    logger.info(f"Failed:         {len(failed)}")
    logger.info(f"Total Chunks:   {total_chunks}")
    logger.info(f"Duration:       {duration/60:.1f} minutes")
    logger.info(f"Avg per PDF:    {duration/len(pdf_files):.1f} seconds")
    logger.info("="*80)

    if failed:
        logger.warning(f"\nFailed PDFs ({len(failed)}):")
        for item in failed:
            logger.warning(f"  - {item['file']}: {item['error']}")

    logger.info(f"\nCompleted at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(main())
