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

python find_download_ids.py "$FAILED_JSON"

echo ""
echo "============================================================"
echo "Next steps:"
echo "  1. Review the ID mappings above"
echo "  2. Manually download using the correct IDs, or"
echo "  3. Update download_legislation.py with an ID mapping table"
echo "============================================================"
