#!/usr/bin/env python3.12
"""
Scan Gmail for invoices/receipts, download attachments, convert HTML to PDF,
organise into Accounts folder on Google Drive by entity (Synergy/Flowstate) and month.

Scans BOTH Flowstate and Synergy Gmail accounts.
Runs incrementally - only processes emails newer than the last scan.

Usage:
    python3.12 scan_invoices.py              # scan both accounts
    python3.12 scan_invoices.py --account synergy    # scan Synergy only
    python3.12 scan_invoices.py --account flowstate  # scan Flowstate only
"""
import pickle, os, base64, re, subprocess, tempfile, json, argparse, sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from collections import defaultdict
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

ACCOUNTS = {
    'flowstate': {
        'token': "/Users/kevinharkin/flowstate/telegram-mcp/google_token.pickle",
        'default_entity': 'flowstate',
    },
    'flowstatesystems': {
        'token': "/Users/kevinharkin/flowstate/revolut/google_token_flowstatesystems.pickle",
        'default_entity': 'flowstate',
    },
    'synergy': {
        'token': "/Users/kevinharkin/flowstate/revolut/google_token_synergy.pickle",
        'default_entity': 'synergy',
    },
}
STATE_PATH = "/Users/kevinharkin/flowstate/revolut/invoice_scan_state.json"

parser = argparse.ArgumentParser()
parser.add_argument('--account', choices=['flowstate', 'flowstatesystems', 'synergy'], help='Scan only this account')
args = parser.parse_args()

accounts_to_scan = [args.account] if args.account else list(ACCOUNTS.keys())

def load_creds(token_path):
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    return creds

# Use Flowstate creds for Drive (where files are uploaded)
flowstate_creds = load_creds(ACCOUNTS['flowstate']['token'])
drive = build('drive', 'v3', credentials=flowstate_creds)

def extract_pdf_text(path):
    try:
        result = subprocess.run(['/opt/homebrew/bin/pdftotext', path, '-'], capture_output=True, text=True, timeout=10)
        return result.stdout
    except:
        return ''

def html_to_pdf(html_content, output_path):
    tmp_html = tempfile.mktemp(suffix='.html')
    with open(tmp_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f'file://{tmp_html}')
            page.pdf(path=output_path, format='A4', print_background=True)
            browser.close()
        os.remove(tmp_html)
        return True
    except Exception as e:
        os.remove(tmp_html)
        print(f"  PDF conversion error: {e}")
        return False

# Load last scan state
last_scan = None
processed_ids = set()
if os.path.exists(STATE_PATH):
    with open(STATE_PATH, 'r') as f:
        state = json.load(f)
        last_scan = state.get('last_scan')
        processed_ids = set(state.get('processed_ids', []))

# Entity detection: Synergy Gmail defaults to Synergy, Flowstate Gmail defaults to Flowstate.
# Override list: vendors in Synergy Gmail whose invoices belong to Flowstate (domain/SaaS billed to Flowstate).
FLOWSTATE_VENDORS_IN_SYNERGY = ['godaddy', 'waghl', 'jag digital', 'slack', 'pipeboard', 'midjourney', 'addevent', 'manus', 'flexxable', 'thrivecart']
# Vendors that are always Synergy regardless of which Gmail they appear in
SYNERGY_SENDERS = ['captions', 'mirage', 'lovable', 'meta for business', 'facebook', 'glofox', 'go power', 'firmus', 'james gibson', 'scoreapp']

EXCLUDE_PATTERNS = [
    'share request', 'shared with you', 'folder shared', 'document shared',
    'security alert', 'password has been changed', 'unlock your',
    'action required', 'action needed', 'review your', 'verify your',
    'welcome to', 'finish setting up', 'you have access',
    'join the meta', 'sorry that we missed', 'customer portal login',
    'roles of your page', 'credit balance remaining', 'tell us more',
    'referral', 'refer you get', 'earn 500', '7 days left',
    'growth forum', 'unlock', 'complete your billing setup',
    'credential secu', 'critical problem', 'storage is',
    'invite', 'invited to join',
    'pending expenses', 'weekly summary', 'weekly expenses',
    'pro team', 'important  aws invoice e-mail',
    'payment from', 'you received a payment', 'successful payment',
    'new payment', 'payment received from', 'payout',
]

def categorise_sender(sender):
    s = sender.lower()
    if 'meta' in s: return 'Ad Spend (Meta)'
    if any(x in s for x in ['lovable', 'captions', 'mirage', 'nocap', 'google', 'apify', 'manychat', 'slack', 'pipeboard', 'gamma', 'highlevel', 'gohighlevel', 'leadconnector']): return 'Software / SaaS'
    if 'anthropic' in s: return 'AI / Software'
    if 'argos' in s: return 'Equipment / Hardware'
    if 'waterfront' in s: return 'Events / Entertainment'
    return 'Other'

# Search queries
QUERIES = [
    'subject:(invoice OR receipt OR statement) has:attachment',
    'from:meta subject:"ads receipt"',
    'from:argos subject:("order" OR "collecting")',
    'from:google subject:(billing OR "payment received" OR subscription)',
    'from:manychat subject:(invoice OR receipt OR subscription OR "trial ends")',
    'from:apify subject:(subscription OR invoice OR receipt)',
    'from:waterfront subject:order',
    'from:stripe subject:(invoice OR "your receipt" OR subscription) -subject:"payment from" -subject:"you received"',
    'from:apple subject:(receipt OR invoice)',
    'from:amazon subject:("your order" OR "invoice" OR "payment")',
    'from:glofox subject:(invoice OR receipt OR payment)',
    'from:electric subject:(bill OR statement OR invoice)',
    'from:firmus subject:(bill OR statement OR invoice)',
    'from:godaddy subject:(receipt OR invoice OR renewal OR order)',
    'from:slack subject:(receipt OR invoice OR payment)',
    'from:midjourney subject:(receipt OR invoice OR payment OR subscription)',
    'from:appointwise subject:(receipt OR invoice OR payment)',
    'from:pipeboard subject:(receipt OR invoice OR payment)',
    'from:anthropic subject:(receipt OR invoice)',
    'from:addevent subject:(receipt OR invoice OR payment)',
    'from:predis subject:(receipt OR invoice OR payment)',
    'from:feedback@slack.com subject:(renewed OR receipt OR invoice)',
    'from:thrivecart subject:invoice',
    'from:flexxable subject:invoice',
    'from:gohighlevel subject:(receipt OR invoice)',
    'from:highlevel subject:(receipt OR invoice)',
    'from:leadconnector subject:(receipt OR invoice)',
]

all_msg_ids = set()
all_messages = []  # tuples of (msg, account_name)

for acct_name in accounts_to_scan:
    acct = ACCOUNTS[acct_name]
    acct_creds = load_creds(acct['token'])
    acct_gmail = build('gmail', 'v1', credentials=acct_creds)

    queries = list(QUERIES)
    acct_last_scan = last_scan.get(acct_name) if isinstance(last_scan, dict) else last_scan
    if acct_last_scan:
        queries = [q + f" after:{acct_last_scan}" for q in queries]

    acct_count = 0
    for q in queries:
        page_token = None
        while True:
            results = acct_gmail.users().messages().list(userId='me', q=q, maxResults=100, pageToken=page_token).execute()
            for msg in results.get('messages', []):
                combo_id = f"{acct_name}:{msg['id']}"
                if combo_id not in all_msg_ids and combo_id not in processed_ids:
                    all_msg_ids.add(combo_id)
                    all_messages.append((msg, acct_name, acct_gmail))
                    acct_count += 1
            page_token = results.get('nextPageToken')
            if not page_token:
                break
    print(f"[{acct_name}] Found {acct_count} new emails")

print(f"Total: {len(all_messages)} new emails to process")

if not all_messages:
    today = datetime.now().strftime('%Y/%m/%d')
    scan_dates = last_scan if isinstance(last_scan, dict) else {}
    for acct_name in accounts_to_scan:
        scan_dates[acct_name] = today
    with open(STATE_PATH, 'w') as f:
        json.dump({'last_scan': scan_dates, 'processed_ids': list(processed_ids)}, f)
    print("No new invoices found")
    exit(0)

# Find or create Accounts folder structure
def find_or_create_folder(name, parent_id=None):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    results = drive.files().list(q=q, fields="files(id)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    body = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        body['parents'] = [parent_id]
    return drive.files().create(body=body, fields='id').execute()['id']

accounts_id = find_or_create_folder('Accounts')
synergy_parent = find_or_create_folder('Synergy', accounts_id)
flowstate_parent = find_or_create_folder('Flowstate', accounts_id)

month_folders = {}
def get_or_create_month_folder(entity, year_month):
    key = (entity, year_month)
    if key in month_folders:
        return month_folders[key]
    dt = datetime.strptime(year_month, "%Y-%m")
    folder_name = dt.strftime("%Y-%m %B")
    parent = synergy_parent if entity == 'synergy' else flowstate_parent
    folder_id = find_or_create_folder(folder_name, parent)
    month_folders[key] = folder_id
    return folder_id

# Process emails
items = []
for i, (msg, acct_name, acct_gmail) in enumerate(all_messages):
    combo_id = f"{acct_name}:{msg['id']}"
    try:
        detail = acct_gmail.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = {h['name']: h['value'] for h in detail['payload']['headers']}

        subject = headers.get('Subject', 'no-subject')
        subj_lower = subject.lower()
        if any(pat in subj_lower for pat in EXCLUDE_PATTERNS):
            processed_ids.add(combo_id)
            continue

        date_str = headers.get('Date', '')
        try:
            dt = parsedate_to_datetime(date_str)
            year_month = dt.strftime("%Y-%m")
            date_prefix = dt.strftime("%Y-%m-%d")
        except:
            processed_ids.add(combo_id)
            continue

        from_addr = headers.get('From', 'unknown')
        sender = re.sub(r'<.*>', '', from_addr).strip().strip('"').strip()
        sender = re.sub(r'[^\w\s-]', '', sender).strip()[:30]

        is_invoice = 'invoice' in subj_lower
        amount_match = re.search(r'[\$\£\€][\d,.]+', subject)
        amount = amount_match.group(0) if amount_match else None

        from_lower = from_addr.lower()
        # Entity detection:
        # 1. Check if sender is a known Flowstate vendor (even if in Synergy Gmail)
        # 2. Synergy account defaults to Synergy, Flowstate account uses sender detection
        is_flowstate_vendor = any(v in from_lower for v in FLOWSTATE_VENDORS_IN_SYNERGY)
        if is_flowstate_vendor:
            is_synergy = False
        elif acct_name == 'synergy':
            is_synergy = True
        else:
            is_synergy = any(s in from_lower for s in SYNERGY_SENDERS)

        # Find attachments
        parts = []
        def get_parts(payload, _parts=parts):
            if 'parts' in payload:
                for p in payload['parts']:
                    get_parts(p, _parts)
            else:
                if payload.get('filename') and payload.get('body', {}).get('attachmentId'):
                    _parts.append(payload)
        parts = []
        get_parts(detail['payload'], parts)

        useful_exts = ['.pdf', '.png', '.jpg', '.jpeg', '.csv', '.xlsx', '.xls', '.doc', '.docx']
        useful_parts = [p for p in parts if os.path.splitext(p['filename'])[1].lower() in useful_exts]

        att_data = []
        for part in useful_parts:
            att = acct_gmail.users().messages().attachments().get(userId='me', messageId=msg['id'], id=part['body']['attachmentId']).execute()
            raw_data = base64.urlsafe_b64decode(att['data'])
            att_data.append({'filename': part['filename'], 'data': raw_data})

            if not is_synergy and part['filename'].lower().endswith('.pdf'):
                tmp = f"/tmp/entity_{msg['id']}.pdf"
                with open(tmp, 'wb') as f:
                    f.write(raw_data)
                pdf_text = extract_pdf_text(tmp).lower()
                os.remove(tmp)
                if 'synergy' in pdf_text:
                    is_synergy = True

        # For no-attachment emails, get HTML body for PDF conversion
        email_html = None
        if not att_data:
            def get_body(payload):
                if payload.get('body', {}).get('data'):
                    return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace'), payload.get('mimeType', '')
                if 'parts' in payload:
                    for p in payload['parts']:
                        result = get_body(p)
                        if result and 'html' in result[1]:
                            return result
                    for p in payload['parts']:
                        result = get_body(p)
                        if result:
                            return result
                return None
            body_result = get_body(detail['payload'])
            if body_result:
                email_html = body_result[0]
                if not is_synergy and 'synergy' in email_html.lower():
                    is_synergy = True

        entity = 'synergy' if is_synergy else 'flowstate'

        items.append({
            'year_month': year_month, 'date_prefix': date_prefix, 'sender': sender,
            'subject': subject, 'is_invoice': is_invoice, 'amount': amount,
            'att_data': att_data, 'email_html': email_html,
            'entity': entity, 'msg_id': msg['id'], 'combo_id': combo_id
        })

    except Exception as e:
        print(f"  Error on message {i} [{acct_name}]: {e}")

# Dedup
groups = defaultdict(list)
for item in items:
    key = (item['year_month'], item['sender'], item['amount'])
    groups[key].append(item)

keep = []
for key, group in groups.items():
    invoices = [g for g in group if g['is_invoice']]
    keep.append(invoices[0] if invoices else group[0])

# Upload
saved = 0
for item in keep:
    try:
        folder_id = get_or_create_month_folder(item['entity'], item['year_month'])

        # Check what already exists in this folder to avoid duplicates
        existing_files = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields='files(name)', pageSize=200
        ).execute().get('files', [])
        existing_names = {f['name'] for f in existing_files}

        if item['att_data']:
            for att in item['att_data']:
                clean_name = f"{item['date_prefix']} - {item['sender']} - {att['filename']}"
                if clean_name in existing_names:
                    continue
                tmp_path = f"/tmp/inv_{item['msg_id']}_{att['filename']}"
                with open(tmp_path, 'wb') as f:
                    f.write(att['data'])
                media = MediaFileUpload(tmp_path)
                drive.files().create(body={'name': clean_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()
                os.remove(tmp_path)
                saved += 1
        elif item['email_html']:
            subj_clean = re.sub(r'[^\w\s-]', '', item['subject'])[:50]
            pdf_name = f"{item['date_prefix']} - {item['sender']} - {subj_clean}.pdf"
            if pdf_name in existing_names:
                pass
            else:
                pdf_path = f"/tmp/inv_{item['msg_id']}.pdf"
                if html_to_pdf(item['email_html'], pdf_path):
                    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
                    drive.files().create(body={'name': pdf_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()
                os.remove(pdf_path)
                saved += 1

        processed_ids.add(item['combo_id'])
    except Exception as e:
        print(f"  Upload error: {e}")

# Also mark skipped items as processed
for item in items:
    processed_ids.add(item['combo_id'])

# Save state - per-account last_scan dates
today = datetime.now().strftime('%Y/%m/%d')
scan_dates = last_scan if isinstance(last_scan, dict) else {}
for acct_name in accounts_to_scan:
    scan_dates[acct_name] = today

with open(STATE_PATH, 'w') as f:
    json.dump({
        'last_scan': scan_dates,
        'processed_ids': list(processed_ids)[-4000:]  # Keep last 4000 (2 accounts)
    }, f)

print(f"Done: {saved} new files saved, {len(keep)} items processed")
