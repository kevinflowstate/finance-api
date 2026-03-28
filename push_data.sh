#!/bin/bash
# Push all data files to the Finance API's /data volume via HTTP upload.
# Run this after first deploy to populate the persistent volume.
#
# Usage: ./push_data.sh <SERVICE_URL> <API_KEY>
# Example: ./push_data.sh https://finance-api-xxx.up.railway.app my-secret-key

set -e

SERVICE_URL="${1:?Usage: ./push_data.sh <SERVICE_URL> <API_KEY>}"
API_KEY="${2:?Usage: ./push_data.sh <SERVICE_URL> <API_KEY>}"

REVOLUT_DIR="$HOME/flowstate/revolut"
GDRIVE="$HOME/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff"
GOOGLE_TOKEN="$HOME/flowstate/telegram-mcp/google_token.pickle"

upload() {
    local filepath="$1"
    local filename="$2"
    echo -n "  $filename ... "
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "x-api-key: $API_KEY" \
        -F "file=@$filepath" \
        "$SERVICE_URL/data/upload?filename=$filename")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "OK"
    else
        echo "FAILED (HTTP $HTTP_CODE)"
    fi
}

echo "=== Pushing data files to $SERVICE_URL ==="
echo ""

# Config
upload "$GDRIVE/.config.json" "config.json"

# Google tokens
upload "$GOOGLE_TOKEN" "google_token.pickle"
upload "$REVOLUT_DIR/google_token_flowstatesystems.pickle" "google_token_flowstatesystems.pickle"
upload "$REVOLUT_DIR/google_token_synergy.pickle" "google_token_synergy.pickle"

# Revolut certs - Flowstate
upload "$REVOLUT_DIR/certificate.pem" "certificate.pem"
upload "$REVOLUT_DIR/private.key" "private.key"

# Revolut certs - Synergy
upload "$REVOLUT_DIR/synergy_public.pem" "synergy_public.pem"
upload "$REVOLUT_DIR/synergy_private.pem" "synergy_private.pem"

# Revolut credentials
upload "$REVOLUT_DIR/credentials.json" "credentials.json"
upload "$REVOLUT_DIR/synergy_credentials.json" "synergy_credentials.json"

# Data files
upload "$REVOLUT_DIR/transactions_raw.json" "transactions_raw.json"
upload "$REVOLUT_DIR/synergy_transactions_raw.json" "synergy_transactions_raw.json"
upload "$REVOLUT_DIR/stripe_charges.json" "stripe_charges.json"
upload "$REVOLUT_DIR/stripe_customer_map.json" "stripe_customer_map.json"
upload "$REVOLUT_DIR/synergy_stripe_charges.json" "synergy_stripe_charges.json"
upload "$REVOLUT_DIR/synergy_stripe_customer_map.json" "synergy_stripe_customer_map.json"
upload "$REVOLUT_DIR/invoice_scan_state.json" "invoice_scan_state.json"

echo ""
echo "=== Verifying ==="
curl -s -H "x-api-key: $API_KEY" "$SERVICE_URL/data/list" | python3 -m json.tool

echo ""
echo "=== Done ==="
