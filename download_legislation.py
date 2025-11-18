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


async def download_specific_ids(legal_ids: List[str]):
    """Download specific acts by Legal IDs (for retrying failures with corrected IDs)."""
    os.makedirs(LEGISLATION_DIR, exist_ok=True)

    print(f"\n{'='*60}")
    print("Retry Failed Downloads with Corrected IDs")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as session:
        # Get full act list to lookup metadata
        all_acts = await get_all_acts(session)
        acts_by_id = {act.get('LegalId', ''): act for act in all_acts}

        downloaded = []
        failed = []
        start_time = datetime.now()

        for i, legal_id in enumerate(legal_ids, 1):
            # Try to find act metadata (might not match if using corrected ID)
            act = acts_by_id.get(legal_id, {})
            act_name = act.get('ActName', 'Unknown Act')
            year = act.get('Year', 'unknown')

            # Create filename - use Legal ID if no metadata found
            if act:
                filename = sanitize_filename(act_name, legal_id)
            else:
                # Fallback: use legal_id as filename
                filename = f"{legal_id.replace('LOCI.', '').lower()}.pdf"

            print(f"[{i}/{len(legal_ids)}] ↓ {act_name} ({year})")
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

            # Rate limiting
            if i < len(legal_ids):
                await asyncio.sleep(INITIAL_DELAY)

        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print(f"\n{'='*60}")
        print("Retry Summary")
        print(f"{'='*60}")
        print(f"Attempted:      {len(legal_ids)}")
        print(f"Downloaded:     {len(downloaded)} ✓")
        print(f"Failed:         {len(failed)} ✗")
        print(f"Duration:       {duration:.1f} seconds")
        print(f"Output dir:     {os.path.abspath(LEGISLATION_DIR)}")
        print(f"{'='*60}\n")

        if failed:
            print("Still failed:")
            for item in failed:
                print(f"  - {item['act_name']} ({item['legal_id']})")
            print()


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
    """Entry point.

    Usage:
        python download_legislation.py              # Download all
        python download_legislation.py 50           # Download first 50
        python download_legislation.py --retry LOCI.STCLA66,LOCI.WANDAM,...
        python download_legislation.py --retry-json '[{"old":"LOCI.STCLA","new":"LOCI.STCLA66"},...]'
    """
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Download Cook Islands legislation PDFs')
    parser.add_argument('limit', nargs='?', type=int, default=None,
                       help='Limit number of acts to download')
    parser.add_argument('--retry', type=str,
                       help='Comma-separated Legal IDs to retry (e.g., LOCI.STCLA66,LOCI.WANDAM)')
    parser.add_argument('--retry-json', type=str,
                       help='JSON array of ID mappings from find_download_ids.py')

    args = parser.parse_args()

    # Handle retry with ID mappings
    if args.retry_json:
        try:
            import json
            mappings = json.loads(args.retry_json)
            retry_ids = [m['new'] for m in mappings if 'new' in m]
            print(f"Retrying {len(retry_ids)} failed downloads with corrected IDs...")
            asyncio.run(download_specific_ids(retry_ids))
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}")
            sys.exit(1)
    elif args.retry:
        retry_ids = [id.strip() for id in args.retry.split(',')]
        print(f"Retrying {len(retry_ids)} specific Legal IDs...")
        asyncio.run(download_specific_ids(retry_ids))
    else:
        asyncio.run(download_all_legislation(limit=args.limit))


if __name__ == "__main__":
    main()
