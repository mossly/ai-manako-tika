"""Test script for downloading Cook Islands legislation."""
import asyncio
import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from app.tools.scraper import scrape_legislation

async def main():
    print("Testing legislation scraper with limit of 3 acts...")
    stats = await scrape_legislation(limit=3)
    print("\nResults:")
    print(f"  Total acts found: {stats['total_acts']}")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Skipped: {stats['skipped']}")

    if stats['downloaded_details']:
        print("\nDownloaded files:")
        for detail in stats['downloaded_details']:
            print(f"  - {detail['act_name']} ({detail['year']})")
            print(f"    Path: {detail['path']}")

if __name__ == "__main__":
    asyncio.run(main())
