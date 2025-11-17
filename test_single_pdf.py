"""Test ingestion with a single PDF (Banking Act)."""
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

async def main():
    """Test ingestion with Banking Act."""
    logger.info("Testing ingestion with Banking Act 2011...")

    # Find the Banking Act PDF
    pdf_path = "data/legislation/ba_banking_act_2011.pdf"

    if not Path(pdf_path).exists():
        logger.error(f"PDF not found: {pdf_path}")
        return

    # Run ingestion
    logger.info(f"Processing: {pdf_path}")
    chunks = await ingest_pdf(
        pdf_path=pdf_path,
        act_name="Banking Act 2011",
        force_reprocess=True
    )

    logger.info("="*80)
    logger.info("TEST COMPLETE")
    logger.info("="*80)
    logger.info(f"PDF:            {pdf_path}")
    logger.info(f"Chunks created: {chunks}")
    logger.info("="*80)

    # Test a search
    if chunks > 0:
        logger.info("\nTesting RAG search...")
        from app.rag.indexer import store

        # First embed the query
        query_vec = await store.embed_texts(["What are the requirements for banking licenses?"])
        results = store.search(query_vec[0], k=3)

        logger.info(f"\nSearch results: {len(results)} chunks found")
        for i, chunk_dict in enumerate(results, 1):
            logger.info(f"\n[{i}] Score: {chunk_dict.get('score', 0):.4f}")
            logger.info(f"Act: {chunk_dict.get('act_name', 'Unknown')}")
            logger.info(f"Section: {chunk_dict.get('hierarchy', 'N/A')}")
            logger.info(f"Content preview: {chunk_dict.get('content', '')[:200]}...")

if __name__ == "__main__":
    asyncio.run(main())
