#!/bin/bash
# Upload data files to the running Railway service's /data volume.
# Run this AFTER first deploy to populate the persistent volume.
#
# Usage: ./upload_data.sh <RAILWAY_SERVICE_URL>
# Example: ./upload_data.sh https://finance-api-production-xxxx.up.railway.app

set -e

SERVICE_URL="${1:?Usage: ./upload_data.sh <RAILWAY_SERVICE_URL>}"
REVOLUT_DIR="$HOME/flowstate/revolut"
GDRIVE_CONFIG="$HOME/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff/.config.json"
GOOGLE_TOKEN="$HOME/flowstate/telegram-mcp/google_token.pickle"

echo "=== Uploading data files to $SERVICE_URL ==="

# This script prepares a tar archive of all data files needed on the server.
# Upload via a temporary endpoint or Railway CLI.

DATA_BUNDLE="/tmp/finance-data-bundle"
rm -rf "$DATA_BUNDLE"
mkdir -p "$DATA_BUNDLE"

echo "Copying files..."

# Config
cp "$GDRIVE_CONFIG" "$DATA_BUNDLE/config.json"

# Google tokens
cp "$GOOGLE_TOKEN" "$DATA_BUNDLE/google_token.pickle"
cp "$REVOLUT_DIR/google_token_flowstatesystems.pickle" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/google_token_synergy.pickle" "$DATA_BUNDLE/"

# Revolut certs - Flowstate
cp "$REVOLUT_DIR/certificate.pem" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/private.key" "$DATA_BUNDLE/"

# Revolut certs - Synergy
cp "$REVOLUT_DIR/synergy_public.pem" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/synergy_private.pem" "$DATA_BUNDLE/"

# Revolut credentials
cp "$REVOLUT_DIR/credentials.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/synergy_credentials.json" "$DATA_BUNDLE/"

# Data files
cp "$REVOLUT_DIR/transactions_raw.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/synergy_transactions_raw.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/stripe_charges.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/stripe_customer_map.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/synergy_stripe_charges.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/synergy_stripe_customer_map.json" "$DATA_BUNDLE/"
cp "$REVOLUT_DIR/invoice_scan_state.json" "$DATA_BUNDLE/"

echo ""
echo "Files prepared in $DATA_BUNDLE:"
ls -lh "$DATA_BUNDLE/"

echo ""
echo "Creating tar archive..."
cd /tmp
tar czf finance-data-bundle.tar.gz -C finance-data-bundle .

echo ""
echo "Archive: /tmp/finance-data-bundle.tar.gz ($(du -h /tmp/finance-data-bundle.tar.gz | cut -f1))"
echo ""
echo "=== NEXT STEPS ==="
echo "Railway doesn't support direct file upload to volumes."
echo "Use 'railway shell' to connect to the container, then:"
echo "  1. railway shell"
echo "  2. Inside the shell: cd /data"
echo "  3. From another terminal: railway cp /tmp/finance-data-bundle.tar.gz :/tmp/"
echo "  4. Inside the shell: cd /data && tar xzf /tmp/finance-data-bundle.tar.gz"
echo ""
echo "Or use the /upload endpoint (next version) to upload files via HTTP."
