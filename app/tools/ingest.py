"""Legislation ingestion pipeline: PDF → Markdown → Chunks → Embeddings."""
import os
from typing import List, Optional
from pathlib import Path
from loguru import logger

from ..rag.indexer import store, Chunk
from ..rag.chunking import from_legislation_markdown, from_plaintext
from ..config import legislation_config
from .pdf_processor import process_pdf_to_markdown, save_markdown


MARKDOWN_DIR = os.getenv('MARKDOWN_DIR', '/data/markdown')
os.makedirs(MARKDOWN_DIR, exist_ok=True)


async def ingest_pdf(pdf_path: str, act_name: Optional[str] = None, force_reprocess: bool = False) -> int:
    """Ingest a single PDF legislation document.

    Args:
        pdf_path: Path to PDF file
        act_name: Human-readable act name (if None, derived from filename)
        force_reprocess: Force reprocessing even if already ingested

    Returns:
        Number of chunks ingested
    """
    # Derive identifiers
    pdf_filename = Path(pdf_path).stem
    doc_id = pdf_filename.replace(' ', '_').lower()

    if act_name is None:
        # Convert filename to readable act name
        # E.g., "banking_act_1996" → "Banking Act 1996"
        act_name = pdf_filename.replace('_', ' ').title()

    logger.info(f"Ingesting PDF: {pdf_path}")
    logger.info(f"  doc_id: {doc_id}")
    logger.info(f"  act_name: {act_name}")

    # Process PDF to markdown
    markdown_text, file_hash, page_map = await process_pdf_to_markdown(pdf_path)

    # Check if we need to reprocess
    if not force_reprocess and not legislation_config.document_needs_processing(doc_id, file_hash):
        logger.info(f"Document {doc_id} unchanged (hash match), skipping ingestion")
        return 0

    # Save markdown for inspection
    markdown_path = os.path.join(MARKDOWN_DIR, f"{doc_id}.md")
    save_markdown(markdown_text, markdown_path)

    # Get PDF filename for linking
    pdf_filename = Path(pdf_path).name

    # Chunk the markdown
    logger.info("Chunking legislation markdown...")
    chunk_dicts = from_legislation_markdown(
        doc_id=doc_id,
        act_name=act_name,
        markdown_text=markdown_text,
        page_map=page_map,
        metadata={
            'file_hash': file_hash,
            'pdf_path': pdf_path,
            'pdf_filename': pdf_filename,
            'markdown_path': markdown_path
        }
    )

    if not chunk_dicts:
        logger.warning(f"No chunks created from {pdf_path}, trying plaintext fallback")
        chunk_dicts = from_plaintext(
            doc_id=doc_id,
            act_name=act_name,
            text=markdown_text,
            page_map=page_map,
            metadata={'file_hash': file_hash, 'pdf_path': pdf_path, 'pdf_filename': pdf_filename}
        )

    if not chunk_dicts:
        logger.error(f"Failed to create any chunks from {pdf_path}")
        return 0

    # Convert to Chunk objects
    chunks = [Chunk(**c) for c in chunk_dicts]

    # Ingest into RAG store (creates embeddings)
    logger.info(f"Ingesting {len(chunks)} chunks into RAG store...")
    await store.ingest_chunks(chunks)

    # Update config
    legislation_config.set_document(doc_id, {
        'file_hash': file_hash,
        'act_name': act_name,
        'pdf_path': pdf_path,
        'markdown_path': markdown_path,
        'chunks': len(chunks),
        'last_processed': __import__('datetime').datetime.utcnow().isoformat()
    })

    logger.info(f"Ingestion complete: {doc_id} ({len(chunks)} chunks)")
    return len(chunks)


async def ingest_all_pdfs(legislation_dir: Optional[str] = None, force_reprocess: bool = False) -> dict:
    """Ingest all PDFs in the legislation directory.

    Args:
        legislation_dir: Directory containing PDF files (default: /data/legislation)
        force_reprocess: Force reprocessing even if already ingested

    Returns:
        Dict with statistics: total_pdfs, processed, skipped, total_chunks
    """
    if legislation_dir is None:
        legislation_dir = os.getenv('LEGISLATION_DIR', '/data/legislation')

    logger.info(f"Ingesting all PDFs from: {legislation_dir}")

    pdf_files = list(Path(legislation_dir).glob('*.pdf'))
    logger.info(f"Found {len(pdf_files)} PDF files")

    total_chunks = 0
    processed = 0
    skipped = 0

    for pdf_path in pdf_files:
        try:
            chunks = await ingest_pdf(str(pdf_path), force_reprocess=force_reprocess)
            if chunks > 0:
                processed += 1
                total_chunks += chunks
            else:
                skipped += 1
        except Exception as e:
            logger.exception(f"Failed to ingest {pdf_path}: {e}")
            skipped += 1

    stats = {
        'total_pdfs': len(pdf_files),
        'processed': processed,
        'skipped': skipped,
        'total_chunks': total_chunks
    }

    logger.info(f"Batch ingestion complete: {stats}")
    return stats


async def ingest_from_url(url: str, act_name: str) -> int:
    """Download and ingest legislation PDF from URL.

    Args:
        url: URL to PDF file
        act_name: Human-readable act name

    Returns:
        Number of chunks ingested
    """
    import httpx
    from tempfile import NamedTemporaryFile

    logger.info(f"Downloading PDF from URL: {url}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()

        # Save to temp file
        with NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

    try:
        # Ingest from temp file
        chunks = await ingest_pdf(tmp_path, act_name=act_name, force_reprocess=True)
        return chunks
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
