#!/usr/bin/env python3.12
"""Fetch fresh Revolut transactions (and Stripe charges when key available) for Synergy."""

import json
import os
import subprocess
import time
import jwt
from datetime import datetime, timedelta

REVOLUT_DIR = '/Users/kevinharkin/flowstate/revolut'
CONFIG_PATH = os.path.expanduser("~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff/.config.json")

# Load Synergy Revolut credentials
with open(os.path.join(REVOLUT_DIR, 'synergy_credentials.json'), 'r') as f:
    revolut_creds = json.load(f)

with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

SYNERGY_STRIPE_KEY = config.get('synergy_stripe_api_key', '')
CLIENT_ID = revolut_creds['client_id']
REFRESH_TOKEN = revolut_creds['refresh_token']
CERT_PATH = os.path.join(REVOLUT_DIR, 'synergy_public.pem')
KEY_PATH = os.path.join(REVOLUT_DIR, 'synergy_private.pem')

# ============================================================
# REVOLUT - Refresh token and pull transactions
# ============================================================
def refresh_revolut_token():
    """Refresh Synergy Revolut access token using JWT client assertion."""
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
        raise Exception(f"Synergy Revolut token refresh failed: {resp}")

    revolut_creds['access_token'] = resp['access_token']
    if 'refresh_token' in resp:
        revolut_creds['refresh_token'] = resp['refresh_token']

    with open(os.path.join(REVOLUT_DIR, 'synergy_credentials.json'), 'w') as f:
        json.dump(revolut_creds, f, indent=2)

    print(f"Synergy Revolut token refreshed successfully")
    return resp['access_token']


def fetch_revolut_transactions(access_token):
    """Pull all Synergy Revolut transactions."""
    from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%dT00:00:00.000Z')
    to_date = datetime.now(tz=__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    all_transactions = []
    count = 1000

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
    print(f"Fetched {len(transactions)} Synergy Revolut transactions (page 1)")

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
            all_transactions.extend(transactions[1:])
            print(f"Fetched {len(transactions)} more transactions")
        else:
            break

    # Merge with existing data
    output_path = os.path.join(REVOLUT_DIR, 'synergy_transactions_raw.json')
    existing = []
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            existing = json.load(f)

    seen_ids = {t['id'] for t in all_transactions if 'id' in t}
    merged = all_transactions[:]
    for t in existing:
        if t.get('id') not in seen_ids:
            merged.append(t)
            seen_ids.add(t.get('id'))

    merged.sort(key=lambda t: t.get('created_at', ''), reverse=True)

    with open(output_path, 'w') as f:
        json.dump(merged, f, indent=2)

    print(f"Saved {len(merged)} Synergy Revolut transactions ({len(all_transactions)} fetched, {len(merged) - len(all_transactions)} from history)")
    return len(merged)


# ============================================================
# STRIPE - Pull charges (when key is available)
# ============================================================
def fetch_stripe_charges():
    """Pull Synergy Stripe charges incrementally - only new ones since last fetch."""
    if not SYNERGY_STRIPE_KEY:
        print("No Synergy Stripe key configured - skipping Stripe fetch")
        return 0

    output_path = os.path.join(REVOLUT_DIR, 'synergy_stripe_charges.json')

    # Load existing charges to find the most recent one
    existing = []
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            existing = json.load(f)

    # Find the most recent charge timestamp for incremental fetch
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
            'curl', '-s', '--globoff', url,
            '-u', f'{SYNERGY_STRIPE_KEY}:'
        ], capture_output=True, text=True)

        resp = json.loads(result.stdout)
        charges = resp.get('data', [])
        all_new_charges.extend(charges)
        has_more = resp.get('has_more', False)

        if charges:
            starting_after = charges[-1]['id']

        print(f"Fetched {len(charges)} Synergy Stripe charges (page {page})")

    # Merge new with existing, deduplicate by ID
    if existing and all_new_charges:
        existing_ids = {c['id'] for c in existing}
        for c in all_new_charges:
            if c['id'] not in existing_ids:
                existing.append(c)
        all_charges = existing
        print(f"Merged {len(all_new_charges)} new charges with {len(existing) - len(all_new_charges)} existing")
    elif all_new_charges:
        all_charges = all_new_charges
    else:
        all_charges = existing
        print("No new charges found")

    with open(output_path, 'w') as f:
        json.dump(all_charges, f, indent=2)

    print(f"Saved {len(all_charges)} Synergy Stripe charges total")

    # Build customer map
    customer_ids = set()
    for charge in all_charges:
        cust_id = charge.get('customer')
        billing_name = charge.get('billing_details', {}).get('name', '')
        if cust_id and not billing_name:
            customer_ids.add(cust_id)

    map_path = os.path.join(REVOLUT_DIR, 'synergy_stripe_customer_map.json')
    if os.path.exists(map_path):
        with open(map_path, 'r') as f:
            customer_map = json.load(f)
    else:
        customer_map = {}

    new_customers = customer_ids - set(customer_map.keys())
    for i, cust_id in enumerate(new_customers):
        result = subprocess.run([
            'curl', '-s',
            f'https://api.stripe.com/v1/customers/{cust_id}',
            '-u', f'{SYNERGY_STRIPE_KEY}:'
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
    print(f"=== Synergy Finance Data Fetch - {datetime.now().strftime('%d %b %Y %H:%M')} ===\n")

    # Revolut
    try:
        token = refresh_revolut_token()
        rev_count = fetch_revolut_transactions(token)
    except Exception as e:
        print(f"Synergy Revolut fetch failed: {e}")
        rev_count = 0

    # Stripe
    try:
        stripe_count = fetch_stripe_charges()
    except Exception as e:
        print(f"Synergy Stripe fetch failed: {e}")
        stripe_count = 0

    print(f"\n=== Done. Synergy Revolut: {rev_count} txns, Stripe: {stripe_count} charges ===")
