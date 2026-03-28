#!/usr/bin/env python3.12
"""Fetch fresh Revolut transactions and Stripe charges, save to local JSON files."""

import json
import os
import subprocess
import time
import jwt
from datetime import datetime, timedelta

REVOLUT_DIR = '/Users/kevinharkin/flowstate/revolut'
CONFIG_PATH = os.path.expanduser("~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff/.config.json")

# Load credentials
with open(os.path.join(REVOLUT_DIR, 'credentials.json'), 'r') as f:
    revolut_creds = json.load(f)

with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

STRIPE_KEY = config['stripe_api_key']
CLIENT_ID = revolut_creds['client_id']
REFRESH_TOKEN = revolut_creds['refresh_token']
CERT_PATH = os.path.join(REVOLUT_DIR, 'certificate.pem')
KEY_PATH = os.path.join(REVOLUT_DIR, 'private.key')

# ============================================================
# REVOLUT - Refresh token and pull transactions
# ============================================================
def refresh_revolut_token():
    """Refresh Revolut access token using JWT client assertion."""
    now = int(time.time())
    payload = {
        'iss': 'flowstatesystems.ai',
        'sub': CLIENT_ID,
        'aud': 'https://revolut.com',
        'iat': now,
        'exp': now + 300,
    }
    with open(KEY_PATH, 'r') as f:
        private_key = f.read()

    assertion = jwt.encode(payload, private_key, algorithm='RS256')

    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        'https://b2b.revolut.com/api/1.0/auth/token',
        '--cert', CERT_PATH,
        '--key', KEY_PATH,
        '-d', f'grant_type=refresh_token&refresh_token={REFRESH_TOKEN}&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer&client_assertion={assertion}&client_id={CLIENT_ID}'
    ], capture_output=True, text=True)

    resp = json.loads(result.stdout)
    if 'access_token' not in resp:
        print(f"Token refresh failed: {resp}")
        raise Exception(f"Revolut token refresh failed: {resp}")

    # Save new tokens
    revolut_creds['access_token'] = resp['access_token']
    if 'refresh_token' in resp:
        revolut_creds['refresh_token'] = resp['refresh_token']

    with open(os.path.join(REVOLUT_DIR, 'credentials.json'), 'w') as f:
        json.dump(revolut_creds, f, indent=2)

    print(f"Revolut token refreshed successfully")
    return resp['access_token']


def fetch_revolut_transactions(access_token):
    """Pull all Revolut transactions."""
    # Get transactions from 3 months ago (full history already saved locally)
    from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%dT00:00:00.000Z')
    to_date = datetime.now(tz=__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    all_transactions = []
    count = 1000

    # First page
    result = subprocess.run([
        'curl', '-s',
        f'https://b2b.revolut.com/api/1.0/transactions?from={from_date}&to={to_date}&count={count}',
        '--cert', CERT_PATH,
        '--key', KEY_PATH,
        '-H', f'Authorization: Bearer {access_token}'
    ], capture_output=True, text=True)

    transactions = json.loads(result.stdout)
    if isinstance(transactions, dict) and 'message' in transactions:
        print(f"Revolut API error: {transactions}")
        raise Exception(f"Revolut API error: {transactions}")

    all_transactions.extend(transactions)
    print(f"Fetched {len(transactions)} Revolut transactions (page 1)")

    # Paginate if we got a full page
    while len(transactions) == count:
        last_created = transactions[-1].get('created_at', '')
        result = subprocess.run([
            'curl', '-s',
            f'https://b2b.revolut.com/api/1.0/transactions?from={from_date}&to={last_created}&count={count}',
            '--cert', CERT_PATH,
            '--key', KEY_PATH,
            '-H', f'Authorization: Bearer {access_token}'
        ], capture_output=True, text=True)
        transactions = json.loads(result.stdout)
        if isinstance(transactions, list) and len(transactions) > 0:
            all_transactions.extend(transactions[1:])  # Skip first (overlap)
            print(f"Fetched {len(transactions)} more transactions")
        else:
            break

    # Merge with existing data (keep older transactions, update/add newer ones)
    output_path = os.path.join(REVOLUT_DIR, 'transactions_raw.json')
    existing = []
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            existing = json.load(f)

    # Deduplicate by transaction ID
    seen_ids = {t['id'] for t in all_transactions if 'id' in t}
    merged = all_transactions[:]
    for t in existing:
        if t.get('id') not in seen_ids:
            merged.append(t)
            seen_ids.add(t.get('id'))

    # Sort by created_at descending (newest first, same as Revolut API)
    merged.sort(key=lambda t: t.get('created_at', ''), reverse=True)

    with open(output_path, 'w') as f:
        json.dump(merged, f, indent=2)

    print(f"Saved {len(merged)} Revolut transactions to {output_path} ({len(all_transactions)} fetched, {len(merged) - len(all_transactions)} from history)")
    return len(merged)


# ============================================================
# STRIPE - Pull charges and customer map
# ============================================================
def fetch_stripe_charges():
    """Pull Stripe charges incrementally - only new ones since last fetch."""
    output_path = os.path.join(REVOLUT_DIR, 'stripe_charges.json')

    # Load existing charges to find the most recent one
    existing = []
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            existing = json.load(f)

    created_after = None
    if existing:
        latest_ts = max(c.get('created', 0) for c in existing)
        if latest_ts > 0:
            created_after = latest_ts
            print(f"Incremental fetch: only charges after {datetime.fromtimestamp(latest_ts).strftime('%d %b %Y')}")

    all_new_charges = []
    has_more = True
    starting_after = None
    page = 0

    while has_more:
        page += 1
        url = 'https://api.stripe.com/v1/charges?limit=100'
        if starting_after:
            url += f'&starting_after={starting_after}'
        if created_after:
            url += f'&created[gt]={created_after}'

        result = subprocess.run([
            'curl', '-s', url,
            '-u', f'{STRIPE_KEY}:'
        ], capture_output=True, text=True)

        resp = json.loads(result.stdout)
        charges = resp.get('data', [])
        all_new_charges.extend(charges)
        has_more = resp.get('has_more', False)

        if charges:
            starting_after = charges[-1]['id']

        print(f"Fetched {len(charges)} Stripe charges (page {page})")

    # Merge new with existing, deduplicate by ID
    if existing and all_new_charges:
        existing_ids = {c['id'] for c in existing}
        for c in all_new_charges:
            if c['id'] not in existing_ids:
                existing.append(c)
        all_charges = existing
        print(f"Merged {len(all_new_charges)} new with {len(existing) - len(all_new_charges)} existing")
    elif all_new_charges:
        all_charges = all_new_charges
    else:
        all_charges = existing
        print("No new charges found")

    with open(output_path, 'w') as f:
        json.dump(all_charges, f, indent=2)

    print(f"Saved {len(all_charges)} Stripe charges total")

    # Build customer map for charges missing billing names
    customer_ids = set()
    for charge in all_charges:
        cust_id = charge.get('customer')
        billing_name = charge.get('billing_details', {}).get('name', '')
        if cust_id and not billing_name:
            customer_ids.add(cust_id)

    # Load existing map
    map_path = os.path.join(REVOLUT_DIR, 'stripe_customer_map.json')
    if os.path.exists(map_path):
        with open(map_path, 'r') as f:
            customer_map = json.load(f)
    else:
        customer_map = {}

    # Fetch any new customers
    new_customers = customer_ids - set(customer_map.keys())
    for i, cust_id in enumerate(new_customers):
        result = subprocess.run([
            'curl', '-s',
            f'https://api.stripe.com/v1/customers/{cust_id}',
            '-u', f'{STRIPE_KEY}:'
        ], capture_output=True, text=True)
        cust = json.loads(result.stdout)
        customer_map[cust_id] = {
            'name': cust.get('name', ''),
            'email': cust.get('email', '')
        }
        if (i + 1) % 10 == 0:
            print(f"Resolved {i + 1}/{len(new_customers)} new Stripe customers")

    with open(map_path, 'w') as f:
        json.dump(customer_map, f, indent=2)

    if new_customers:
        print(f"Resolved {len(new_customers)} new Stripe customers")

    return len(all_charges)


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    print(f"=== Finance Data Fetch - {datetime.now().strftime('%d %b %Y %H:%M')} ===\n")

    # Revolut
    try:
        token = refresh_revolut_token()
        rev_count = fetch_revolut_transactions(token)
    except Exception as e:
        print(f"Revolut fetch failed: {e}")
        rev_count = 0

    # Stripe
    try:
        stripe_count = fetch_stripe_charges()
    except Exception as e:
        print(f"Stripe fetch failed: {e}")
        stripe_count = 0

    print(f"\n=== Done. Revolut: {rev_count} txns, Stripe: {stripe_count} charges ===")
