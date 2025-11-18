"""Standalone script to download all Cook Islands legislation PDFs."""
import asyncio
import httpx
import os
import re
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('legislation_download.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Fix Windows console encoding for Unicode characters
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Configuration
LEGISLATION_DIR = "data/legislation"
API_BASE = "https://cookislandslaws.gov.ck/api"
RETRIEVE_ALL_ACTS_URL = f"{API_BASE}/retrieve_all_act"
DOWNLOAD_PDF_URL = f"{API_BASE}/download_pdf_consolidated_law"

# Rate limiting with exponential backoff
INITIAL_DELAY = 1  # seconds - 1s -> 5s -> 30s -> 1min progression
MAX_DELAY = 60  # seconds - up to 1 minute
MAX_RETRIES = 3


def sanitize_filename(name: str, legal_id: str) -> str:
    """Convert act name to safe filename."""
    # Use legal_id as base for unique identification
    base = legal_id.replace('LOCI.', '').lower()

    # Clean up the act name for readability
    clean_name = re.sub(r'[^\w\s-]', '', name.lower())
    clean_name = re.sub(r'[-\s]+', '_', clean_name)
    clean_name = clean_name.strip('_')

    # Combine: legalid_actname.pdf
    return f"{base}_{clean_name}.pdf"


async def get_all_acts(session: httpx.AsyncClient) -> List[Dict[str, str]]:
    """Retrieve list of all acts from the API."""
    print(f"Fetching legislation list from API...")

    try:
        response = await session.get(RETRIEVE_ALL_ACTS_URL)
        response.raise_for_status()
        acts = response.json()
        print(f"✓ Retrieved {len(acts)} acts from API")
        return acts
    except Exception as e:
        print(f"✗ Failed to retrieve acts list: {e}")
        return []


async def download_pdf_with_retry(
    session: httpx.AsyncClient,
    legal_id: str,
    filename: str,
    retry_count: int = 0
) -> Optional[str]:
    """Download PDF with exponential backoff retry."""
    output_path = os.path.join(LEGISLATION_DIR, filename)

    # Skip if already exists
    if os.path.exists(output_path):
        return output_path

    download_url = f"{DOWNLOAD_PDF_URL}/{legal_id}"

    try:
        response = await session.get(download_url)
        response.raise_for_status()

        # Check if response is JSON (API returns base64-encoded PDF in JSON)
        content_type = response.headers.get('content-type', '').lower()

        if 'json' in content_type:
            # Decode JSON response
            import base64
            import json

            data = response.json()
            if 'pdf_file' in data:
                # Decode base64 PDF
                pdf_content = base64.b64decode(data['pdf_file'])
            else:
                print(f"    ⚠ JSON response but no 'pdf_file' field")
                return None
        else:
            # Direct PDF response
            pdf_content = response.content

        # Verify it's actually a PDF
        if not pdf_content.startswith(b'%PDF'):
            print(f"    ⚠ Downloaded file doesn't appear to be a PDF")
            return None

        # Save PDF
        with open(output_path, 'wb') as f:
            f.write(pdf_content)

        file_size = len(response.content)
        print(f"    ✓ Downloaded {file_size:,} bytes")
        return output_path

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"    ✗ PDF not found (404)")
            return None
        elif e.response.status_code == 429:  # Rate limited
            if retry_count < MAX_RETRIES:
                delay = min(INITIAL_DELAY * (2 ** retry_count), MAX_DELAY)
                print(f"    ⚠ Rate limited, retrying in {delay}s...")
                await asyncio.sleep(delay)
                return await download_pdf_with_retry(session, legal_id, filename, retry_count + 1)
            else:
                print(f"    ✗ Max retries exceeded")
                return None
        else:
            print(f"    ✗ HTTP error: {e.response.status_code}")
            return None
    except Exception as e:
        print(f"    ✗ Failed: {e}")
        return None


async def download_all_legislation(limit: Optional[int] = None):
    """Download all legislation PDFs with rate limiting."""
    # Create output directory
    os.makedirs(LEGISLATION_DIR, exist_ok=True)

    print(f"\n{'='*60}")
    print("Cook Islands Legislation Downloader")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as session:
        # Get list of all acts
        acts = await get_all_acts(session)

        if not acts:
            print("\n✗ No acts retrieved. Exiting.")
            return

        # Apply limit if specified
        total_acts = len(acts)
        if limit:
            acts = acts[:limit]
            print(f"\nℹ Limiting download to first {limit} of {total_acts} acts\n")
        else:
            print(f"\nℹ Preparing to download {total_acts} acts\n")

        # Download PDFs
        downloaded = []
        failed = []
        skipped = []

        start_time = datetime.now()
        last_status_time = start_time

        logger.info(f"Starting download of {len(acts)} acts...")

        for i, act in enumerate(acts, 1):
            act_id = act.get('ActId', 'unknown')
            year = act.get('Year', 'unknown')
            act_name = act.get('ActName', 'unknown')
            legal_id = act.get('LegalId', '')

            if not legal_id:
                print(f"[{i}/{len(acts)}] ⚠ {act_name} - No LegalId, skipping")
                skipped.append(act_name)
                continue

            # Create filename
            filename = sanitize_filename(act_name, legal_id)

            # Check if already exists
            output_path = os.path.join(LEGISLATION_DIR, filename)
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"[{i}/{len(acts)}] ⊙ {act_name} ({year})")
                print(f"    Already exists ({file_size:,} bytes)")
                skipped.append(filename)
                continue

            # Download
            print(f"[{i}/{len(acts)}] ↓ {act_name} ({year})")
            print(f"    Legal ID: {legal_id}")

            result = await download_pdf_with_retry(session, legal_id, filename)

            if result:
                downloaded.append({
                    'path': result,
                    'act_name': act_name,
                    'year': year,
                    'legal_id': legal_id
                })
            else:
                failed.append({
                    'act_name': act_name,
                    'legal_id': legal_id
                })

            # Progress logging every 10 acts
            current_time = datetime.now()
            if i % 10 == 0 or i == len(acts):
                elapsed = (current_time - start_time).total_seconds()
                rate = i / elapsed if elapsed > 0 else 0
                remaining = len(acts) - i
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60

                logger.info(f"Progress: {i}/{len(acts)} ({i/len(acts)*100:.1f}%) - "
                           f"Downloaded: {len(downloaded)}, Skipped: {len(skipped)}, Failed: {len(failed)} - "
                           f"ETA: {eta_minutes:.1f} min")

            # Rate limiting - be nice to the server
            if i < len(acts):  # Don't delay after last item
                await asyncio.sleep(INITIAL_DELAY)

        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print(f"\n{'='*60}")
        print("Download Summary")
        print(f"{'='*60}")
        print(f"Total acts:     {len(acts)}")
        print(f"Downloaded:     {len(downloaded)} ✓")
        print(f"Skipped:        {len(skipped)} ⊙")
        print(f"Failed:         {len(failed)} ✗")
        print(f"Duration:       {duration:.1f} seconds")
        print(f"Output dir:     {os.path.abspath(LEGISLATION_DIR)}")
        print(f"{'='*60}\n")

        if failed:
            print("Failed downloads:")
            for item in failed:
                print(f"  - {item['act_name']} ({item['legal_id']})")
            print()

            # Output JSON for piping to find_download_ids.py
            print("JSON format (for find_download_ids.py):")
            print(json.dumps(failed, indent=2))
            print()


def main():
    """Entry point."""
    import sys

    # Check for limit argument
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            print(f"Using limit: {limit}")
        except ValueError:
            print(f"Invalid limit: {sys.argv[1]}")
            print("Usage: python download_legislation.py [limit]")
            sys.exit(1)

    asyncio.run(download_all_legislation(limit=limit))


if __name__ == "__main__":
    main()
