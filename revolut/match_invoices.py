#!/usr/bin/env python3.12
"""
Match expense transactions with invoice/receipt files on Google Drive.
Updates both Flowstate and Synergy sheets:
  - Writes expense log with 'Invoice Found' column below snapshot on 'Expense Breakdown' tab
  - Populates 'Invoices & Receipts' tab with index of all filed invoices + Drive links
  - Does NOT touch 'All Transactions' / 'All Invoices' tabs

Usage:
    python3.12 match_invoices.py                    # both
    python3.12 match_invoices.py --entity flowstate  # one only
    python3.12 match_invoices.py --entity synergy
"""
import pickle, os, re, argparse
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = "/Users/kevinharkin/flowstate/telegram-mcp/google_token.pickle"

with open(TOKEN_PATH, "rb") as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
    with open(TOKEN_PATH, 'wb') as f:
        pickle.dump(creds, f)

sheets = build('sheets', 'v4', credentials=creds)
drive = build('drive', 'v3', credentials=creds)

ENTITIES = {
    'flowstate': {
        'sheet_id': '1p1PRsots8UL_BmajWXTwouo3Gm43w1drA_QfZ37vjX0',
        'drive_folder': '1vX0zlVB0JZEOhLU5udr8ebM3cqXraAeb',
        'transactions_tab': 'All Transactions',
        'expense_tab': 'Expense Breakdown',
        'invoices_tab': 'Invoices & Receipts',
    },
    'synergy': {
        'sheet_id': '1TSd-Sa8DSv7iBEWfj0m1QLhDLdklpLTp0WWtAqjpKQI',
        'drive_folder': '1nhQAU85zlSal7v8CaxR-SIrRVyMPTg3l',
        'transactions_tab': 'All Invoices',
        'expense_tab': 'Expense Breakdown',
        'invoices_tab': 'Invoices & Receipts',
    },
}

# Vendor aliases: transaction description -> possible invoice sender names
VENDOR_ALIASES = {
    'anthropic': ['anthropic', 'anthropic pbc'],
    'pipeboard': ['pipeboard', 'pipeboard.co', 'pipeboard co ai mcp'],
    'manychat': ['manychat', 'manychat inc'],
    'google': ['google', 'google payments', 'google cloud', 'google workspace', 'the google workspace team'],
    'meta': ['meta', 'meta for business', 'facebook'],
    'apify': ['apify', 'apify billing'],
    'waterfront': ['waterfront', 'waterfront hall', 'noreplyemailwaterfrontcouk'],
    'argos': ['argos'],
    'slack': ['slack'],
    'godaddy': ['godaddy'],
    'midjourney': ['midjourney'],
    'appointwise': ['appointwise'],
    'stripe': ['stripe'],
    'apple': ['apple'],
    'amazon': ['amazon', 'amazon web services', 'aws'],
    'waghl': ['waghl'],
    'scoreapp': ['scoreapp'],
    'go power': ['go power', 'invoicing go power'],
    'glofox': ['glofox'],
    'firmus': ['firmus'],
    'james gibson': ['james gibson'],
    'captions': ['captions'],
    'transistor': ['transistor', 'transistorfm'],
    'opusclip': ['opusclip', 'opusclip inc', 'opus clip'],
    'predis': ['predis', 'predis.ai'],
    'addevent': ['addevent'],
    'flexx investments': ['flexx', 'flexxable', 'flexxable ltd'],
    'lead finesse': ['lead finesse'],
}

parser = argparse.ArgumentParser()
parser.add_argument('--entity', choices=['flowstate', 'synergy'])
args = parser.parse_args()
entities_to_process = [args.entity] if args.entity else list(ENTITIES.keys())


def get_drive_invoices(parent_folder_id):
    """Get all invoice files from Drive, organised by month subfolder."""
    invoices = []
    folders = drive.files().list(
        q=f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields='files(id, name)'
    ).execute().get('files', [])

    for folder in folders:
        files = drive.files().list(
            q=f"'{folder['id']}' in parents and trashed=false",
            fields='files(id, name, webViewLink)',
            pageSize=200
        ).execute().get('files', [])

        for f in files:
            name = f['name']
            date_match = re.match(r'(\d{4}-\d{2}-\d{2})', name)
            date_str = date_match.group(1) if date_match else None

            parts = name.split(' - ')
            sender = parts[1].strip() if len(parts) >= 2 else ''
            description = parts[2].strip() if len(parts) >= 3 else name

            invoices.append({
                'date': date_str,
                'sender': sender,
                'sender_lower': sender.lower().strip(),
                'description': description,
                'file_name': name,
                'file_id': f['id'],
                'link': f.get('webViewLink', ''),
                'month_folder': folder['name'],
            })

    return invoices


def get_vendor_key(text):
    """Map a transaction description or invoice sender to a canonical vendor key."""
    text_lower = text.lower().strip()
    for key, aliases in VENDOR_ALIASES.items():
        for alias in aliases:
            if alias in text_lower or text_lower in alias:
                return key
    return text_lower


def match_transaction_to_invoice(txn_date, txn_desc, txn_amount_abs, invoices):
    """Try to match a transaction to an invoice file using vendor aliases + date proximity."""
    if not txn_date:
        return None

    try:
        txn_dt = datetime.strptime(txn_date, '%Y-%m-%d')
    except ValueError:
        return None

    txn_vendor = get_vendor_key(txn_desc)
    txn_month = txn_dt.strftime('%Y-%m')

    best_match = None
    best_date_diff = 999

    for inv in invoices:
        if not inv['date']:
            continue

        # Vendor must match via alias system
        inv_vendor = get_vendor_key(inv['sender'])
        if txn_vendor != inv_vendor:
            continue

        try:
            inv_dt = datetime.strptime(inv['date'], '%Y-%m-%d')
        except ValueError:
            continue

        date_diff = abs((txn_dt - inv_dt).days)

        # Same month = match (SaaS billing dates vary but receipts come same month)
        inv_month = inv_dt.strftime('%Y-%m')
        if txn_month != inv_month and date_diff > 10:
            continue

        # Prefer closest date match
        if date_diff < best_date_diff:
            best_date_diff = date_diff
            best_match = inv

    return best_match


def ensure_tab(sheet_id, tab_name):
    """Create tab if it doesn't exist."""
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing = [s['properties']['title'] for s in meta['sheets']]
    if tab_name not in existing:
        sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={
            'requests': [{'addSheet': {'properties': {'title': tab_name}}}]
        }).execute()
        print(f"  Created '{tab_name}' tab")


def process_entity(entity_name):
    config = ENTITIES[entity_name]
    sheet_id = config['sheet_id']
    txn_tab = config['transactions_tab']
    expense_tab = config['expense_tab']
    inv_tab = config['invoices_tab']

    print(f"\n{'='*50}")
    print(f"Processing {entity_name.upper()}")
    print(f"{'='*50}")

    # 1. Get all Drive invoices (for Flowstate, also check Synergy folder as fallback)
    invoices = get_drive_invoices(config['drive_folder'])
    if entity_name == 'flowstate':
        synergy_invoices = get_drive_invoices(ENTITIES['synergy']['drive_folder'])
        invoices.extend(synergy_invoices)
    print(f"  {len(invoices)} invoice files on Drive (inc. cross-account)")

    # 2. Get all transactions
    result = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{txn_tab}'!A1:Z"
    ).execute()
    rows = result.get('values', [])
    if not rows:
        print(f"  No transactions found in '{txn_tab}'")
        return

    headers = rows[0]
    data_rows = rows[1:]

    # Remove 'Invoice Found' column from All Transactions if it was added previously
    if 'Invoice Found' in headers:
        inv_col = headers.index('Invoice Found')
        headers.pop(inv_col)
        for row in data_rows:
            if len(row) > inv_col:
                row.pop(inv_col)
        # Clear and rewrite without that column
        sheets.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range=f"'{txn_tab}'"
        ).execute()
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"'{txn_tab}'!A1",
            valueInputOption='RAW', body={'values': [headers] + data_rows}
        ).execute()
        print(f"  Removed 'Invoice Found' column from '{txn_tab}'")

    # Find column indices
    date_col = headers.index('Date') if 'Date' in headers else 0
    desc_col = headers.index('Description') if 'Description' in headers else (headers.index('Vendor') if 'Vendor' in headers else 1)
    amount_col = headers.index('Amount (GBP)') if 'Amount (GBP)' in headers else (headers.index('Amount') if 'Amount' in headers else 4)
    cat_col = headers.index('Category') if 'Category' in headers else None
    subcat_col = headers.index('Subcategory') if 'Subcategory' in headers else None
    type_col = headers.index('Type') if 'Type' in headers else None

    # 3. Extract expense-only rows
    expenses = []
    for row in data_rows:
        txn_cat = row[cat_col] if cat_col is not None and cat_col < len(row) else ''
        txn_type = row[type_col] if type_col is not None and type_col < len(row) else ''
        txn_amount = row[amount_col] if amount_col < len(row) else '0'

        is_income = txn_cat.lower() == 'income' or txn_type == 'topup'
        if is_income:
            continue

        try:
            amt = float(txn_amount)
        except ValueError:
            continue

        txn_date = row[date_col] if date_col < len(row) else ''
        txn_desc = row[desc_col] if desc_col < len(row) else ''
        txn_subcat = row[subcat_col] if subcat_col is not None and subcat_col < len(row) else ''
        category_display = txn_subcat or txn_cat

        # Categories that don't need invoices
        NO_RECEIPT_NEEDED = [
            'savings deposit', 'savings withdrawal', 'bank fees', 'transfer out',
            'company pro plan', 'depositing savings', 'withdrawing savings',
        ]
        desc_lower = txn_desc.lower()
        cat_lower = category_display.lower()
        no_receipt = any(nr in desc_lower or nr in cat_lower for nr in NO_RECEIPT_NEEDED)

        # Zero-amount auth holds don't need receipts either
        if amt == 0:
            no_receipt = True

        if no_receipt:
            inv_status = 'N/A'
            inv_link = ''
        else:
            match = match_transaction_to_invoice(txn_date, txn_desc, abs(amt), invoices)
            if match:
                inv_status = 'Yes'
                inv_link = match['link']
            else:
                inv_status = 'No'
                inv_link = ''

        expenses.append([txn_date, txn_desc, f"{amt:.2f}", category_display, inv_status, inv_link])

    matched = sum(1 for e in expenses if e[4] == 'Yes')
    unmatched = sum(1 for e in expenses if e[4] == 'No')
    print(f"  Expenses: {len(expenses)} | Matched: {matched} | Unmatched: {unmatched}")

    # 4. Read existing Expense Breakdown tab to find where snapshot ends
    existing = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{expense_tab}'!A1:Z"
    ).execute().get('values', [])

    # Find the last non-empty row of the existing snapshot
    last_content_row = 0
    for i, row in enumerate(existing):
        if any(cell.strip() for cell in row if cell):
            last_content_row = i + 1

    # Start the expense log 2 rows below the snapshot
    start_row = last_content_row + 3

    # 5. Sort expenses: No first (need chasing), Yes second, N/A last
    sort_order = {'No': 0, 'Yes': 1, 'N/A': 2}
    expenses.sort(key=lambda e: (sort_order.get(e[4], 3), e[0]))

    no_rows = [e for e in expenses if e[4] == 'No']
    yes_rows = [e for e in expenses if e[4] == 'Yes']
    na_rows = [e for e in expenses if e[4] == 'N/A']

    expense_block = [
        ['--- Expense Log (with Invoice Matching) ---'],
        [],
        [f'MISSING RECEIPT ({len(no_rows)})'],
        ['Date', 'Vendor', 'Amount (GBP)', 'Category', 'Invoice Found', 'Drive Link'],
    ] + no_rows + [
        [],
        [f'RECEIPT FOUND ({len(yes_rows)})'],
        ['Date', 'Vendor', 'Amount (GBP)', 'Category', 'Invoice Found', 'Drive Link'],
    ] + yes_rows + [
        [],
        [f'NO RECEIPT NEEDED ({len(na_rows)})'],
        ['Date', 'Vendor', 'Amount (GBP)', 'Category', 'Invoice Found', 'Drive Link'],
    ] + na_rows

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{expense_tab}'!A{start_row}",
        valueInputOption='RAW',
        body={'values': expense_block}
    ).execute()
    print(f"  Wrote {len(expenses)} expense rows to '{expense_tab}' starting at row {start_row}")

    # 6. Build and write Invoices & Receipts index
    ensure_tab(sheet_id, inv_tab)

    # Clear existing data first
    sheets.spreadsheets().values().clear(
        spreadsheetId=sheet_id, range=f"'{inv_tab}'"
    ).execute()

    inv_headers = ['Date', 'Vendor', 'Description', 'File Name', 'Drive Link', 'Month']
    inv_rows = [inv_headers]
    for inv in sorted(invoices, key=lambda x: x['date'] or ''):
        inv_rows.append([
            inv['date'] or '',
            inv['sender'],
            inv['description'],
            inv['file_name'],
            inv['link'],
            inv['month_folder'],
        ])

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{inv_tab}'!A1",
        valueInputOption='RAW',
        body={'values': inv_rows}
    ).execute()
    print(f"  Wrote {len(inv_rows)-1} entries to '{inv_tab}'")


for entity in entities_to_process:
    process_entity(entity)

print("\nDone.")
