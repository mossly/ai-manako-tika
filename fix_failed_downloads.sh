#!/bin/bash
# Helper script to fix failed legislation downloads
# This can be run inside the Docker container

set -e

echo "============================================================"
echo "Fix Failed Downloads - Workflow"
echo "============================================================"
echo ""

# Step 1: Run the download script and capture output
echo "Step 1: Running download_legislation.py to identify failures..."
echo ""

python download_legislation.py > /tmp/download_output.txt 2>&1

# Show summary
tail -30 /tmp/download_output.txt

# Step 2: Extract failed acts JSON
echo ""
echo "Step 2: Extracting failed acts..."
echo ""

# Extract JSON between "JSON format" and next empty line
FAILED_JSON=$(sed -n '/JSON format/,/^$/p' /tmp/download_output.txt | grep -A 1000 '^\[' | sed '/^$/q')

if [ -z "$FAILED_JSON" ]; then
    echo "✓ No failures detected! All downloads successful."
    exit 0
fi

echo "Found failures. Saving to /tmp/failed_acts.json"
echo "$FAILED_JSON" > /tmp/failed_acts.json

# Step 3: Find correct download IDs
echo ""
echo "Step 3: Finding correct download IDs using Playwright..."
echo ""

python find_download_ids.py "$FAILED_JSON" > /tmp/find_ids_output.txt 2>&1

# Show output
cat /tmp/find_ids_output.txt

# Step 4: Extract corrected IDs and retry
echo ""
echo "Step 4: Retrying downloads with corrected IDs..."
echo ""

# Extract comma-separated list from output
CORRECTED_IDS=$(grep -A 1 "python download_legislation.py --retry" /tmp/find_ids_output.txt | tail -1 | sed 's/.*--retry //')

if [ -n "$CORRECTED_IDS" ]; then
    echo "Retrying with: $CORRECTED_IDS"
    echo ""
    python download_legislation.py --retry "$CORRECTED_IDS"
else
    echo "✗ No corrected IDs found. Manual intervention required."
fi

echo ""
echo "============================================================"
echo "Complete! Check the summary above for final status."
echo "============================================================"
