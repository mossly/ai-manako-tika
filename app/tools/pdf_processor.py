"""PDF processing with OCR support via OpenRouter."""
import os
import hashlib
from typing import Optional, Tuple
from pathlib import Path
from loguru import logger
import base64
import json

# PDF processing libraries
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

# OpenRouter API client
import httpx


OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_OCR_MODEL', 'qwen/qwen-2-vl-7b-instruct')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of a file for change detection."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def is_text_based_pdf(pdf_path: str) -> bool:
    """Determine if a PDF contains extractable text (vs scanned images).

    Args:
        pdf_path: Path to PDF file

    Returns:
        True if PDF contains text, False if likely scanned images
    """
    if pypdf is None:
        logger.warning("pypdf not installed, assuming PDF is scanned")
        return False

    try:
        with open(pdf_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            # Check first 3 pages for text content
            pages_to_check = min(3, len(reader.pages))
            total_text = ""
            for i in range(pages_to_check):
                text = reader.pages[i].extract_text() or ""
                total_text += text

            # Heuristic: if we got more than 100 characters from first few pages, it's text-based
            has_text = len(total_text.strip()) > 100
            logger.info(f"PDF text check: {pdf_path} - extracted {len(total_text)} chars - is_text_based={has_text}")
            return has_text
    except Exception as e:
        logger.error(f"Failed to check PDF text content: {e}")
        return False


def extract_text_from_pdf(pdf_path: str) -> Tuple[str, dict]:
    """Extract text from text-based PDF using pypdf.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Tuple of (extracted text, page_map dict mapping character positions to page numbers)
    """
    if pypdf is None:
        raise RuntimeError("pypdf not installed. Install with: pip install pypdf")

    try:
        with open(pdf_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            text_parts = []
            page_map = {}  # Maps text position to page number

            logger.info(f"Extracting text from {len(reader.pages)} pages...")
            current_pos = 0

            for i, page in enumerate(reader.pages):
                page_num = i + 1  # 1-indexed page numbers
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

                # Track which page this text came from
                page_start = current_pos
                page_end = current_pos + len(page_text)
                page_map[page_num] = {'start': page_start, 'end': page_end}
                current_pos = page_end + 2  # +2 for the \n\n separator

                if (i + 1) % 10 == 0:
                    logger.debug(f"Extracted {i + 1}/{len(reader.pages)} pages")

            full_text = '\n\n'.join(text_parts)
            logger.info(f"Extracted {len(full_text)} characters from PDF with page mapping")
            return full_text, page_map
    except Exception as e:
        logger.exception(f"Failed to extract text from PDF: {pdf_path}")
        raise


async def ocr_pdf_with_openrouter(pdf_path: str, max_pages: Optional[int] = None) -> Tuple[str, dict]:
    """Perform OCR on scanned PDF using Qwen VL via OpenRouter.

    Args:
        pdf_path: Path to scanned PDF file
        max_pages: Optional limit on number of pages to process (for cost control)

    Returns:
        Tuple of (OCR text in markdown format, page_map dict)
    """
    if convert_from_path is None:
        raise RuntimeError("pdf2image not installed. Install with: pip install pdf2image pillow")

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set. Cannot perform OCR.")

    try:
        # Convert PDF pages to images
        logger.info(f"Converting PDF to images: {pdf_path}")
        images = convert_from_path(pdf_path, dpi=200)

        if max_pages:
            images = images[:max_pages]
            logger.info(f"Limiting to first {max_pages} pages for OCR")

        logger.info(f"Processing {len(images)} pages with OCR via OpenRouter...")

        all_page_texts = []
        page_map = {}
        current_pos = 0

        async with httpx.AsyncClient(timeout=60.0) as client:
            for page_num, image in enumerate(images, 1):
                logger.debug(f"OCR page {page_num}/{len(images)}")

                # Convert image to base64
                import io
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
                image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

                # Call OpenRouter API
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Extract all text from this legal document page in markdown format. Preserve section numbers, headings, and paragraph structure. Output only the extracted text, no commentary."
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{image_b64}"
                                        }
                                    }
                                ]
                            }
                        ],
                        "max_tokens": 2000,
                        "temperature": 0.1
                    }
                )

                if response.status_code != 200:
                    logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                    page_text = f"\n\n[OCR failed for page {page_num}]\n\n"
                else:
                    result = response.json()
                    page_text = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    page_text = f"\n\n--- Page {page_num} ---\n\n{page_text}"

                # Track page positions
                page_start = current_pos
                page_end = current_pos + len(page_text)
                page_map[page_num] = {'start': page_start, 'end': page_end}
                current_pos = page_end + 1  # +1 for \n separator

                all_page_texts.append(page_text)
                logger.debug(f"Page {page_num} OCR completed: {len(page_text)} chars")

        full_text = '\n'.join(all_page_texts)
        logger.info(f"OCR completed: {len(full_text)} characters from {len(images)} pages")
        return full_text, page_map

    except Exception as e:
        logger.exception(f"OCR failed for PDF: {pdf_path}")
        raise


async def process_pdf_to_markdown(pdf_path: str, force_ocr: bool = False) -> Tuple[str, str, dict]:
    """Process PDF to markdown, auto-detecting if OCR is needed.

    Args:
        pdf_path: Path to PDF file
        force_ocr: Force OCR even if text is extractable

    Returns:
        Tuple of (markdown_text, file_hash, page_map)
        page_map is dict mapping page numbers to character positions
    """
    file_hash = compute_file_hash(pdf_path)
    logger.info(f"Processing PDF: {pdf_path} (hash={file_hash[:12]}...)")

    # Determine processing method
    if force_ocr:
        logger.info("Forcing OCR (force_ocr=True)")
        markdown_text, page_map = await ocr_pdf_with_openrouter(pdf_path)
    elif is_text_based_pdf(pdf_path):
        logger.info("Extracting text from text-based PDF")
        markdown_text, page_map = extract_text_from_pdf(pdf_path)
    else:
        logger.info("Scanned PDF detected, using OCR")
        markdown_text, page_map = await ocr_pdf_with_openrouter(pdf_path)

    logger.info(f"PDF processing complete: {len(markdown_text)} chars, {len(page_map)} pages")
    return markdown_text, file_hash, page_map


def save_markdown(markdown_text: str, output_path: str):
    """Save markdown text to file.

    Args:
        markdown_text: Markdown content
        output_path: Path to output .md file
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_text)

    logger.info(f"Saved markdown: {output_path}")
