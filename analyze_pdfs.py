"""Analyze PDFs to determine text vs scanned content ratio."""
import sys
import os
from pathlib import Path
import PyPDF2
from collections import defaultdict

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

LEGISLATION_DIR = "data/legislation"

def analyze_pdf(pdf_path):
    """Analyze a single PDF to check if it has extractable text."""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)

            total_pages = len(reader.pages)
            total_chars = 0

            # Sample first 5 pages or all pages if less
            pages_to_check = min(5, total_pages)

            for i in range(pages_to_check):
                try:
                    text = reader.pages[i].extract_text()
                    total_chars += len(text.strip())
                except Exception as e:
                    # If extraction fails, likely scanned
                    pass

            # Calculate average chars per page
            avg_chars_per_page = total_chars / pages_to_check if pages_to_check > 0 else 0

            return {
                'path': pdf_path,
                'total_pages': total_pages,
                'chars_sampled': total_chars,
                'avg_chars_per_page': avg_chars_per_page,
                'has_text': avg_chars_per_page > 100,  # Threshold: 100 chars/page
                'file_size': os.path.getsize(pdf_path)
            }

    except Exception as e:
        return {
            'path': pdf_path,
            'error': str(e),
            'has_text': False,
            'file_size': os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
        }

def main():
    print("="*80)
    print("Cook Islands Legislation PDF Analysis")
    print("="*80)
    print()

    pdf_dir = Path(LEGISLATION_DIR)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))

    print(f"Found {len(pdf_files)} PDF files")
    print()

    results = {
        'text_pdfs': [],
        'scanned_pdfs': [],
        'errors': []
    }

    print("Analyzing PDFs...")
    print()

    for i, pdf_path in enumerate(pdf_files, 1):
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(pdf_files)} ({i/len(pdf_files)*100:.1f}%)")

        result = analyze_pdf(pdf_path)

        if 'error' in result:
            results['errors'].append(result)
        elif result['has_text']:
            results['text_pdfs'].append(result)
        else:
            results['scanned_pdfs'].append(result)

    print(f"  Progress: {len(pdf_files)}/{len(pdf_files)} (100.0%)")
    print()
    print("="*80)
    print("Analysis Complete")
    print("="*80)
    print()

    # Summary statistics
    total_text = len(results['text_pdfs'])
    total_scanned = len(results['scanned_pdfs'])
    total_errors = len(results['errors'])
    total = len(pdf_files)

    print(f"Total PDFs:         {total}")
    print(f"  Text-based:       {total_text} ({total_text/total*100:.1f}%)")
    print(f"  Scanned/Image:    {total_scanned} ({total_scanned/total*100:.1f}%)")
    print(f"  Errors:           {total_errors} ({total_errors/total*100:.1f}%)")
    print()

    # Size statistics
    total_size = sum(r['file_size'] for r in results['text_pdfs'] + results['scanned_pdfs'] + results['errors'])
    text_size = sum(r['file_size'] for r in results['text_pdfs'])
    scanned_size = sum(r['file_size'] for r in results['scanned_pdfs'])

    print(f"Total size:         {total_size/1024/1024:.1f} MB")
    print(f"  Text-based:       {text_size/1024/1024:.1f} MB ({text_size/total_size*100:.1f}%)")
    print(f"  Scanned/Image:    {scanned_size/1024/1024:.1f} MB ({scanned_size/total_size*100:.1f}%)")
    print()

    if results['scanned_pdfs']:
        print("="*80)
        print(f"Scanned PDFs requiring OCR ({len(results['scanned_pdfs'])} files):")
        print("="*80)
        print()

        # Sort by size (largest first)
        scanned_sorted = sorted(results['scanned_pdfs'], key=lambda x: x['file_size'], reverse=True)

        for r in scanned_sorted[:20]:  # Show top 20
            filename = Path(r['path']).name
            size_mb = r['file_size'] / 1024 / 1024
            print(f"  {filename:60} {size_mb:6.1f} MB, {r['total_pages']:3} pages")

        if len(scanned_sorted) > 20:
            print(f"\n  ... and {len(scanned_sorted) - 20} more")
        print()

    if results['errors']:
        print("="*80)
        print(f"PDFs with errors ({len(results['errors'])} files):")
        print("="*80)
        print()
        for r in results['errors']:
            filename = Path(r['path']).name
            print(f"  {filename:60} {r.get('error', 'Unknown error')}")
        print()

    # Save detailed results to file
    output_file = "pdf_analysis_results.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("Detailed PDF Analysis Results\n")
        f.write("="*80 + "\n\n")

        f.write(f"TEXT-BASED PDFs ({len(results['text_pdfs'])} files):\n")
        f.write("-"*80 + "\n")
        for r in sorted(results['text_pdfs'], key=lambda x: Path(x['path']).name):
            f.write(f"{Path(r['path']).name}\n")
            f.write(f"  Pages: {r['total_pages']}, Avg chars/page: {r['avg_chars_per_page']:.0f}\n")
        f.write("\n")

        f.write(f"SCANNED PDFs ({len(results['scanned_pdfs'])} files):\n")
        f.write("-"*80 + "\n")
        for r in sorted(results['scanned_pdfs'], key=lambda x: Path(x['path']).name):
            f.write(f"{Path(r['path']).name}\n")
            f.write(f"  Pages: {r['total_pages']}, Size: {r['file_size']/1024/1024:.1f} MB\n")
        f.write("\n")

    print(f"Detailed results saved to: {output_file}")
    print()

if __name__ == "__main__":
    main()
