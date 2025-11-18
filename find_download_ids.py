"""Script to find correct download IDs from web pages.

This script reads failed downloads from download_legislation.py and attempts
to find the correct Legal IDs by scraping the actual download URLs.

Usage:
    python find_download_ids.py [failed_acts_list]

    If failed_acts_list is provided as JSON (from download_legislation.py output),
    it will use that. Otherwise, you can paste the failed items when prompted.
"""
import asyncio
from playwright.async_api import async_playwright
import re
import sys
import json

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def find_download_id(legal_id, act_name):
    """Navigate to the page and extract the download link."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        url = f"https://cookislandslaws.gov.ck/#/InternalConsolidatedLaws?legalId={legal_id}"
        print(f"\n{act_name}")
        print(f"  URL: {url}")

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for the download button to appear
            await page.wait_for_selector('text="Download"', timeout=10000)

            # Listen for network requests when clicking download
            download_url = None

            async def handle_request(request):
                nonlocal download_url
                if 'download_pdf_consolidated_law' in request.url:
                    download_url = request.url

            page.on('request', handle_request)

            # Click the download button
            await page.click('text="Download"')

            # Wait a bit for the request to be captured
            await asyncio.sleep(2)

            if download_url:
                # Extract the legal ID from the download URL
                match = re.search(r'/download_pdf_consolidated_law/([^/?]+)', download_url)
                if match:
                    real_id = match.group(1)
                    print(f"  ✓ Found ID: {real_id}")
                    return real_id
            else:
                print(f"  ✗ No download URL captured")

        except Exception as e:
            print(f"  ✗ Error: {e}")
        finally:
            await browser.close()

    return None

def parse_failed_acts(input_data=None):
    """Parse failed acts from various input formats."""
    failed_acts = []

    # If provided as argument (JSON list from download_legislation.py)
    if input_data:
        try:
            data = json.loads(input_data)
            for item in data:
                legal_id = item.get('legal_id', '')
                act_name = item.get('act_name', '')
                if legal_id and act_name:
                    failed_acts.append((legal_id, act_name))
            return failed_acts
        except json.JSONDecodeError:
            pass

    # Interactive mode - read from stdin
    print("Paste the failed downloads list (Ctrl+D when done):")
    print("Expected format: 'ACT NAME (LOCI.ID)' or JSON array")
    print("-" * 60)

    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
    except EOFError:
        pass

    full_input = '\n'.join(lines)

    # Try JSON format first
    try:
        data = json.loads(full_input)
        for item in data:
            legal_id = item.get('legal_id', '')
            act_name = item.get('act_name', '')
            if legal_id and act_name:
                failed_acts.append((legal_id, act_name))
        return failed_acts
    except json.JSONDecodeError:
        pass

    # Parse line-by-line format: "  - ACT NAME (LOCI.ID)"
    for line in lines:
        match = re.search(r'-\s*(.+?)\s*\((LOCI\.\w+)\)', line)
        if match:
            act_name = match.group(1).strip()
            legal_id = match.group(2).strip()
            failed_acts.append((legal_id, act_name))

    return failed_acts

async def main():
    print("Finding correct download IDs for failed acts...\n")
    print("="*60 + "\n")

    # Check if failed acts provided as command line argument
    failed_input = sys.argv[1] if len(sys.argv) > 1 else None

    failed_acts = parse_failed_acts(failed_input)

    if not failed_acts:
        print("✗ No failed acts found. Exiting.")
        return

    print(f"Found {len(failed_acts)} failed acts to process:\n")
    for legal_id, act_name in failed_acts:
        print(f"  - {act_name} ({legal_id})")

    print("\n" + "="*60)

    results = {}
    for legal_id, act_name in failed_acts:
        real_id = await find_download_id(legal_id, act_name)
        if real_id:
            results[legal_id] = real_id

    print("\n" + "="*60)
    print("\nResults:")
    if results:
        for old_id, new_id in results.items():
            print(f"  {old_id} -> {new_id}")
    else:
        print("  No successful mappings found.")

if __name__ == "__main__":
    asyncio.run(main())
