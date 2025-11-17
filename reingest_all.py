"""Re-ingest all PDFs with new subsection-based chunking strategy."""
import asyncio
import sys
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.tools.ingest import ingest_all_pdfs

async def main():
    logger.info("Starting re-ingestion of all PDFs with new chunking strategy")
    logger.info("=" * 80)

    # Force reprocess all PDFs (use relative path for Windows)
    legislation_dir = "data/legislation"
    stats = await ingest_all_pdfs(legislation_dir=legislation_dir, force_reprocess=True)

    logger.info("=" * 80)
    logger.info("Re-ingestion complete!")
    logger.info(f"Statistics: {stats}")
    logger.success(f"✅ Processed: {stats['processed']} PDFs")
    logger.success(f"✅ Total chunks: {stats['total_chunks']}")
    if stats.get('skipped'):
        logger.warning(f"⚠️  Skipped: {stats['skipped']} PDFs")

if __name__ == "__main__":
    asyncio.run(main())
