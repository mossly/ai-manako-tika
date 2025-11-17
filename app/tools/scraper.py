"""Cook Islands legislation scraper using official API."""
import os
import asyncio
from typing import List, Dict, Optional
from pathlib import Path
from loguru import logger
import re
from datetime import datetime

import httpx


LEGISLATION_DIR = os.getenv('LEGISLATION_DIR', 'data/legislation')
os.makedirs(LEGISLATION_DIR, exist_ok=True)

# Cook Islands Laws API endpoints
API_BASE = "https://cookislandslaws.gov.ck/api"
RETRIEVE_ALL_ACTS_URL = f"{API_BASE}/retrieve_all_act"
DOWNLOAD_PDF_URL = f"{API_BASE}/download_pdf_consolidated_law"


class LegislationScraper:
    """Scraper for Cook Islands legislation using official API."""

    def __init__(self):
        self.session: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.session = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()

    def _sanitize_filename(self, name: str, legal_id: str) -> str:
        """Convert act name to safe filename.

        Args:
            name: Act name
            legal_id: Legal ID (e.g., LOCI.NTB)

        Returns:
            Sanitized filename
        """
        # Use legal_id as base for unique identification
        base = legal_id.replace('LOCI.', '').lower()

        # Clean up the act name for readability
        clean_name = re.sub(r'[^\w\s-]', '', name.lower())
        clean_name = re.sub(r'[-\s]+', '_', clean_name)
        clean_name = clean_name.strip('_')

        # Combine: legalid_actname.pdf (e.g., ntb_nuclear_test_ban_act_2007.pdf)
        return f"{base}_{clean_name}.pdf"

    async def get_all_acts(self) -> List[Dict[str, str]]:
        """Retrieve list of all acts from the API.

        Returns:
            List of dicts with keys: ActId, Year, ActName, LegalId
        """
        logger.info(f"Fetching all acts from: {RETRIEVE_ALL_ACTS_URL}")

        try:
            response = await self.session.get(RETRIEVE_ALL_ACTS_URL)
            response.raise_for_status()

            acts = response.json()
            logger.info(f"Retrieved {len(acts)} acts from API")

            return acts

        except Exception as e:
            logger.exception(f"Failed to retrieve acts list: {e}")
            return []

    async def download_pdf(self, legal_id: str, filename: str) -> Optional[str]:
        """Download PDF for a specific act.

        Args:
            legal_id: Legal ID (e.g., LOCI.NTB)
            filename: Output filename

        Returns:
            Path to downloaded file, or None if failed
        """
        output_path = os.path.join(LEGISLATION_DIR, filename)

        # Skip if already exists
        if os.path.exists(output_path):
            logger.debug(f"PDF already exists, skipping: {filename}")
            return output_path

        # Construct download URL
        download_url = f"{DOWNLOAD_PDF_URL}/{legal_id}"

        try:
            logger.info(f"Downloading: {legal_id} -> {filename}")
            response = await self.session.get(download_url)
            response.raise_for_status()

            # Verify it's actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and not response.content.startswith(b'%PDF'):
                logger.warning(f"Downloaded file for {legal_id} doesn't appear to be a PDF (Content-Type: {content_type})")
                return None

            # Save PDF
            with open(output_path, 'wb') as f:
                f.write(response.content)

            file_size = len(response.content)
            logger.info(f"Downloaded: {filename} ({file_size:,} bytes)")
            return output_path

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"PDF not found for {legal_id}: {download_url}")
            else:
                logger.error(f"HTTP error downloading {legal_id}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.exception(f"Failed to download {legal_id}: {e}")
            return None

    async def scrape_all(self, limit: Optional[int] = None) -> Dict[str, any]:
        """Download all legislation PDFs from the API.

        Args:
            limit: Optional limit on number of PDFs to download (for testing)

        Returns:
            Dict with statistics: timestamp, total_acts, downloaded, failed, skipped
        """
        logger.info("Starting legislation download from Cook Islands API...")

        # Get list of all acts
        acts = await self.get_all_acts()

        if not acts:
            logger.error("No acts retrieved from API")
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'total_acts': 0,
                'downloaded': 0,
                'failed': 0,
                'skipped': 0,
                'downloaded_paths': []
            }

        # Apply limit if specified
        if limit:
            logger.info(f"Limiting download to first {limit} acts")
            acts = acts[:limit]

        # Download PDFs
        downloaded = []
        failed = []
        skipped = []

        for i, act in enumerate(acts, 1):
            act_id = act.get('ActId', 'unknown')
            year = act.get('Year', 'unknown')
            act_name = act.get('ActName', 'unknown')
            legal_id = act.get('LegalId', '')

            if not legal_id:
                logger.warning(f"Act {act_id} ({act_name}) has no LegalId, skipping")
                skipped.append(act_name)
                continue

            # Create filename
            filename = self._sanitize_filename(act_name, legal_id)

            # Check if already exists
            output_path = os.path.join(LEGISLATION_DIR, filename)
            if os.path.exists(output_path):
                logger.debug(f"[{i}/{len(acts)}] Skipping existing: {filename}")
                skipped.append(output_path)
                continue

            # Download
            logger.info(f"[{i}/{len(acts)}] Processing: {act_name} ({year}) - {legal_id}")
            result = await self.download_pdf(legal_id, filename)

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

            # Rate limiting - be nice to the server
            await asyncio.sleep(0.5)

        stats = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_acts': len(acts),
            'downloaded': len(downloaded),
            'failed': len(failed),
            'skipped': len(skipped),
            'downloaded_paths': [d['path'] for d in downloaded],
            'downloaded_details': downloaded,
            'failed_details': failed
        }

        logger.info(f"Scrape complete:")
        logger.info(f"  Total acts: {stats['total_acts']}")
        logger.info(f"  Downloaded: {stats['downloaded']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info(f"  Skipped: {stats['skipped']}")

        return stats


# Convenience function
async def scrape_legislation(limit: Optional[int] = None) -> Dict[str, any]:
    """Download all Cook Islands legislation PDFs.

    Args:
        limit: Optional limit on number of PDFs to download

    Returns:
        Statistics dict
    """
    async with LegislationScraper() as scraper:
        return await scraper.scrape_all(limit=limit)
