"""Script to find correct download IDs from web pages."""
import asyncio
from playwright.async_api import async_playwright
import re
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

FAILED_ACTS = [
    ("LOCI.PA87", "PESTICIDES ACT 1987"),
    ("LOCI.STCLA", "SHORT TERM CROP LEASES ACT 1966"),
    ("LOCI.WANDA", "WANDERING ANIMALS ACT 1976"),
    ("LOCI.TLA", "TRANSPORT LICENSING ACT 1967"),
]

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

async def main():
    print("Finding correct download IDs for failed acts...\n")
    print("="*60)

    results = {}
    for legal_id, act_name in FAILED_ACTS:
        real_id = await find_download_id(legal_id, act_name)
        if real_id:
            results[legal_id] = real_id

    print("\n" + "="*60)
    print("\nResults:")
    for old_id, new_id in results.items():
        print(f"  {old_id} -> {new_id}")

if __name__ == "__main__":
    asyncio.run(main())
