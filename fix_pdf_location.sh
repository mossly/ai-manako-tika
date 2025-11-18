#!/bin/bash
# Fix: Move PDFs from /app/data/legislation to /data/legislation

echo "Checking for misplaced PDFs..."

APP_DIR="/app/data/legislation"
DATA_DIR="/data/legislation"

# Count files in both locations
APP_COUNT=$(ls -1 $APP_DIR/*.pdf 2>/dev/null | wc -l)
DATA_COUNT=$(ls -1 $DATA_DIR/*.pdf 2>/dev/null | wc -l)

echo "PDFs in $APP_DIR: $APP_COUNT"
echo "PDFs in $DATA_DIR: $DATA_COUNT"

if [ $APP_COUNT -gt 0 ]; then
    echo ""
    echo "Moving $APP_COUNT PDFs to mounted volume..."
    mv $APP_DIR/*.pdf $DATA_DIR/ 2>/dev/null

    NEW_COUNT=$(ls -1 $DATA_DIR/*.pdf 2>/dev/null | wc -l)
    echo "✓ Complete! PDFs in $DATA_DIR: $NEW_COUNT"
else
    echo "✓ No files to move"
fi
