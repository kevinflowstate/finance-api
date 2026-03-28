#!/bin/bash
# Build and deploy the finance API to Railway.
# Copies scripts into build context, deploys, then cleans up.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REVOLUT_DIR="$HOME/flowstate/revolut"

echo "=== Preparing build context ==="

# Copy scripts into build context (not committed to git)
mkdir -p "$SCRIPT_DIR/revolut"
for f in fetch_data.py synergy_fetch_data.py build_finance_sheet.py synergy_build_finance_sheet.py scan_invoices.py match_invoices.py; do
    cp "$REVOLUT_DIR/$f" "$SCRIPT_DIR/revolut/"
    echo "  Copied $f"
done

echo ""
echo "=== Deploying to Railway ==="
cd "$SCRIPT_DIR"
railway up --detach

echo ""
echo "=== Cleaning build context ==="
rm -rf "$SCRIPT_DIR/revolut"

echo ""
echo "=== Done ==="
echo "After deploy completes, run push_data.sh to upload data files."
