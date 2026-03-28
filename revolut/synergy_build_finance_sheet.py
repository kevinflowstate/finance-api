#!/usr/bin/env python3.12
"""Build Synergy financial tracker Google Sheet from Revolut transactions (and Stripe when available)."""

import json
import pickle
import os
from datetime import datetime
from collections import defaultdict
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Load Google credentials
token_path = os.path.expanduser("~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff/google_token.pickle")
with open(token_path, 'rb') as f:
    creds = pickle.load(f)
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
    with open(token_path, 'wb') as f:
        pickle.dump(creds, f)

sheets_service = build('sheets', 'v4', credentials=creds)
drive_service = build('drive', 'v3', credentials=creds)

REVOLUT_DIR = '/Users/kevinharkin/flowstate/revolut'
CONFIG_PATH = os.path.expanduser("~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/My Drive/Flowstate/Claude's Stuff/.config.json")

# ============================================================
# REVOLUT DATA
# ============================================================
txn_path = os.path.join(REVOLUT_DIR, 'synergy_transactions_raw.json')
with open(txn_path, 'r') as f:
    transactions = json.load(f)

parsed = []
for t in transactions:
    if t['state'] != 'completed':
        continue
    for leg in t.get('legs', []):
        amount = leg.get('amount', 0)
        desc = leg.get('description', t.get('reference', ''))
        ref = t.get('reference', '')
        tx_type = t.get('type', '')
        date_str = t.get('completed_at', t.get('created_at', ''))

        try:
            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            continue

        desc_lower = (desc + ' ' + ref).lower()

        # Synergy-specific expense categorisation
        if 'depositing savings' in desc_lower or 'withdrawing savings' in desc_lower:
            category = 'Savings'
            subcategory = 'Savings Deposit' if amount < 0 else 'Savings Withdrawal'
        elif tx_type == 'topup':
            category = 'Income'
            if 'stripe' in desc_lower:
                subcategory = 'Member Payments (Stripe)'
            elif 'ontraport' in desc_lower:
                subcategory = 'Member Payments (Ontraport)'
            elif 'revolut' in desc_lower or 'top' in desc_lower:
                subcategory = 'Top Up / Transfer In'
            else:
                subcategory = 'Other Income'
        elif tx_type == 'transfer' and amount > 0:
            category = 'Income'
            subcategory = 'Transfer In'
        elif tx_type == 'transfer' and amount < 0:
            category = 'Expense'
            if 'sara' in desc_lower or 'harkin' in desc_lower:
                subcategory = 'Wages / Drawings'
            else:
                subcategory = 'Transfer Out'
        elif tx_type == 'card_payment':
            category = 'Expense'
            # Gym-specific categories
            if any(w in desc_lower for w in ['meta', 'facebook', 'facebk', 'fb.me']):
                subcategory = 'Ad Spend (Meta)'
            elif any(w in desc_lower for w in ['google', 'goog']):
                subcategory = 'Ad Spend (Google)'
            elif any(w in desc_lower for w in ['firmus', 'electric ireland', 'sse', 'energia', 'power ni', 'electric', 'gas']):
                subcategory = 'Utilities'
            elif any(w in desc_lower for w in ['rent', 'landlord', 'property', 'lease']):
                subcategory = 'Rent / Property'
            elif any(w in desc_lower for w in ['insurance', 'insure', 'aviva', 'axa', 'zurich']):
                subcategory = 'Insurance'
            elif any(w in desc_lower for w in ['glofox', 'teamup', 'gym management', 'booking']):
                subcategory = 'Gym Software'
            elif any(w in desc_lower for w in ['openai', 'anthropic', 'claude', 'cursor']):
                subcategory = 'AI / Software'
            elif any(w in desc_lower for w in ['zapier', 'n8n', 'manychat', 'gohighlevel', 'highlevel', 'appointwise', 'lovable', 'vercel', 'supabase', 'github', 'notion', 'slack', 'canva', 'figma', 'pipeboard', 'scoreapp', 'captions', 'mirage']):
                subcategory = 'Software / SaaS'
            elif any(w in desc_lower for w in ['gym equipment', 'technogym', 'life fitness', 'rogue', 'eleiko', 'hammer strength', 'concept2', 'assault', 'cable', 'dumbbell', 'barbell', 'plates', 'bench']):
                subcategory = 'Gym Equipment'
            elif any(w in desc_lower for w in ['cleaning', 'hygiene', 'sanitiser', 'towel', 'laundry']):
                subcategory = 'Cleaning / Hygiene'
            elif any(w in desc_lower for w in ['amazon', 'amzn', 'argos']):
                subcategory = 'Equipment / Supplies'
            elif any(w in desc_lower for w in ['uber', 'taxi', 'parking', 'fuel', 'petrol', 'diesel']):
                subcategory = 'Travel'
            elif any(w in desc_lower for w in ['food', 'restaurant', 'cafe', 'coffee', 'mcdonalds', 'costa', 'starbucks', 'greggs', 'subway', 'just eat', 'deliveroo']):
                subcategory = 'Food / Entertainment'
            elif any(w in desc_lower for w in ['go power', 'water']):
                subcategory = 'Utilities'
            else:
                subcategory = 'Other Expense'
        elif tx_type == 'charge':
            category = 'Expense'
            subcategory = 'Bank Fees / Charges'
        else:
            category = 'Income' if amount > 0 else 'Expense'
            subcategory = 'Other'

        parsed.append({
            'date': date,
            'date_str': date.strftime('%Y-%m-%d'),
            'month': date.strftime('%Y-%m'),
            'month_display': date.strftime('%b %Y'),
            'type': tx_type,
            'description': desc,
            'reference': ref,
            'amount': amount,
            'currency': leg.get('currency', 'GBP'),
            'balance': leg.get('balance', ''),
            'category': category,
            'subcategory': subcategory,
            'tx_id': t.get('id', '')
        })

parsed.sort(key=lambda x: x['date'])

# FY cutoff: Aug 2025 (same as Flowstate)
FY_CUTOFF = datetime(2025, 8, 1)

# ============================================================
# STRIPE DATA (optional - when key is available)
# ============================================================
stripe_charges = []
customer_map = {}
stripe_path = os.path.join(REVOLUT_DIR, 'synergy_stripe_charges.json')
customer_map_path = os.path.join(REVOLUT_DIR, 'synergy_stripe_customer_map.json')

if os.path.exists(stripe_path):
    with open(stripe_path, 'r') as f:
        stripe_charges = json.load(f)
if os.path.exists(customer_map_path):
    with open(customer_map_path, 'r') as f:
        customer_map = json.load(f)

has_stripe = len(stripe_charges) > 0

# Skip internal payments
SKIP_NAMES = {'kevin harkin', 'sara harkin', 'mr k harkin', 'uk standard', 'add new card: 3ds verification'}

def resolve_member(charge):
    name = (charge.get('billing_details', {}).get('name', '') or '').strip()
    cust_id = charge.get('customer', '')
    desc = charge.get('description', '') or ''

    if not name and cust_id in customer_map:
        name = customer_map[cust_id].get('name', '')
    if not name:
        name = desc

    name_lower = name.lower().strip()
    if name_lower in SKIP_NAMES:
        return None
    return name

# Parse Stripe into member revenue
member_revenue = defaultdict(lambda: {'total_gbp': 0, 'payments': 0, 'months': defaultdict(float)})
stripe_gross_by_month = defaultdict(float)
stripe_fees_by_month = defaultdict(float)
stripe_net_by_month = defaultdict(float)

for charge in stripe_charges:
    if charge.get('status') != 'succeeded':
        continue
    amount = charge['amount'] / 100
    currency = charge.get('currency', 'gbp')
    member = resolve_member(charge)
    if not member or currency != 'gbp':
        continue

    date = datetime.fromtimestamp(charge['created'])
    if date < FY_CUTOFF:
        continue
    month_display = date.strftime('%b %Y')

    member_revenue[member]['total_gbp'] += amount
    member_revenue[member]['payments'] += 1
    member_revenue[member]['months'][month_display] += amount

    stripe_gross_by_month[month_display] += amount

    # Stripe fee calculation
    card = charge.get('payment_method_details', {}).get('card', {})
    country = card.get('country', '')
    eea = ('GB', 'IE', 'DE', 'FR', 'ES', 'IT', 'NL', 'BE', 'AT', 'PT', 'FI', 'SE', 'DK', 'NO', 'PL', 'CZ', 'HU', 'RO', 'BG', 'HR', 'SK', 'SI', 'LT', 'LV', 'EE', 'CY', 'MT', 'LU', 'GR', '')
    fee = amount * 0.014 + 0.20 if country in eea else amount * 0.029 + 0.30
    stripe_fees_by_month[month_display] += fee

for month in stripe_gross_by_month:
    stripe_net_by_month[month] = stripe_gross_by_month[month] - stripe_fees_by_month.get(month, 0)

# ============================================================
# BUILD GOOGLE SHEET
# ============================================================
spreadsheet_id = '1TSd-Sa8DSv7iBEWfj0m1QLhDLdklpLTp0WWtAqjpKQI'
print(f"Updating Synergy spreadsheet: {spreadsheet_id}")

result = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
existing_titles = [s['properties']['title'] for s in result['sheets']]

# Required tabs
required_tabs = ['Monthly P&L', 'Expense Breakdown', 'All Transactions', 'Dashboard', 'Tax Position', 'Projection']
if has_stripe:
    required_tabs.append('Member Revenue')

add_requests = []
for tab in required_tabs:
    if tab not in existing_titles:
        add_requests.append({'addSheet': {'properties': {'title': tab}}})

if add_requests:
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': add_requests}
    ).execute()
    result = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

# Clear tabs we're writing to
for sheet in result['sheets']:
    title = sheet['properties']['title']
    if title in required_tabs:
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'!A:Z"
        ).execute()

# ============================================================
# TAB 1: Monthly P&L
# ============================================================
# Revenue: Stripe if available, otherwise Revolut income
months_data = defaultdict(lambda: {'gross': 0, 'fees': 0, 'net': 0, 'expenses': 0, 'savings': 0, 'transactions': 0})

for month in stripe_gross_by_month:
    month_date = datetime.strptime(month, '%b %Y')
    if month_date < FY_CUTOFF:
        continue
    months_data[month]['gross'] = stripe_gross_by_month[month]
    months_data[month]['fees'] = stripe_fees_by_month.get(month, 0)
    months_data[month]['net'] = stripe_net_by_month[month]

for tx in parsed:
    if tx['currency'] != 'GBP':
        continue
    if tx['date'].replace(tzinfo=None) < FY_CUTOFF:
        continue
    month = tx['month_display']
    months_data[month]['transactions'] += 1
    if tx['category'] == 'Savings':
        months_data[month]['savings'] += abs(tx['amount'])
    elif tx['category'] == 'Expense':
        months_data[month]['expenses'] += abs(tx['amount'])

# Add Revolut-only income (non-Stripe)
for tx in parsed:
    if tx['currency'] != 'GBP' or tx['category'] != 'Income':
        continue
    if tx['date'].replace(tzinfo=None) < FY_CUTOFF:
        continue
    if has_stripe and 'stripe' in (tx['description'] + ' ' + tx['reference']).lower():
        continue  # Skip Stripe payouts if we have Stripe data
    month = tx['month_display']
    months_data[month]['gross'] += tx['amount']
    months_data[month]['net'] += tx['amount']

# Build month order
month_order = []
seen = set()
for tx in parsed:
    m = tx['month_display']
    if m not in seen and tx['date'].replace(tzinfo=None) >= FY_CUTOFF:
        month_order.append(m)
        seen.add(m)
for m in sorted(stripe_gross_by_month.keys(), key=lambda x: datetime.strptime(x, '%b %Y')):
    if m not in seen and datetime.strptime(m, '%b %Y') >= FY_CUTOFF:
        month_order.append(m)
        seen.add(m)
month_order.sort(key=lambda x: datetime.strptime(x, '%b %Y'))

# Savings vault running balance
vault_movements = defaultdict(float)
for tx in parsed:
    if tx['currency'] != 'GBP':
        continue
    if tx['date'].replace(tzinfo=None) < FY_CUTOFF:
        continue
    desc_lower = (tx['description'] + ' ' + tx['reference']).lower()
    if 'depositing savings' in desc_lower:
        vault_movements[tx['month_display']] += abs(tx['amount'])
    elif 'withdrawing savings' in desc_lower:
        vault_movements[tx['month_display']] -= abs(tx['amount'])

pnl_rows = [['Month', 'Gross Revenue (GBP)', 'Stripe Fees (GBP)', 'Net Revenue (GBP)', 'Expenses (GBP)', 'Profit (GBP)', 'Margin %', 'Cumulative Revenue', 'Cumulative Profit', 'Savings Vault Balance (GBP)']]
cumulative_rev = 0
cumulative_profit = 0
vault_running = 0
for month in month_order:
    d = months_data[month]
    gross = round(d['gross'], 2)
    fees = round(d['fees'], 2)
    net = round(d['net'], 2)
    profit = net - d['expenses']
    margin = (profit / net * 100) if net > 0 else 0
    cumulative_rev += net
    cumulative_profit += profit
    vault_running += vault_movements.get(month, 0)
    pnl_rows.append([
        month, gross, fees, net, round(d['expenses'], 2), round(profit, 2),
        f"{margin:.1f}%", round(cumulative_rev, 2), round(cumulative_profit, 2), round(vault_running, 2),
    ])

total_gross = sum(months_data[m]['gross'] for m in month_order)
total_fees = sum(months_data[m]['fees'] for m in month_order)
total_income = sum(months_data[m]['net'] for m in month_order)
total_expenses = sum(months_data[m]['expenses'] for m in month_order)
total_profit = total_income - total_expenses
total_margin = (total_profit / total_income * 100) if total_income > 0 else 0
pnl_rows.append([])
pnl_rows.append([
    'TOTAL', round(total_gross, 2), round(total_fees, 2), round(total_income, 2),
    round(total_expenses, 2), round(total_profit, 2), f"{total_margin:.1f}%",
    round(cumulative_rev, 2), round(cumulative_profit, 2), round(vault_running, 2)
])

# ============================================================
# TAB 2: Expense Breakdown
# ============================================================
expense_cats = defaultdict(float)
for tx in parsed:
    if tx['category'] == 'Expense' and tx['currency'] == 'GBP' and tx['date'].replace(tzinfo=None) >= FY_CUTOFF:
        expense_cats[tx['subcategory']] += abs(tx['amount'])

expense_rows = [['Category', 'Total Spend (GBP)', '% of Total Expenses']]
total_exp = sum(expense_cats.values())
for cat in sorted(expense_cats.keys(), key=lambda x: expense_cats[x], reverse=True):
    pct = (expense_cats[cat] / total_exp * 100) if total_exp > 0 else 0
    expense_rows.append([cat, round(expense_cats[cat], 2), f"{pct:.1f}%"])
expense_rows.append([])
expense_rows.append(['TOTAL', round(total_exp, 2), '100.0%'])

# SaaS breakdown
expense_rows.append([])
expense_rows.append(['--- Software & SaaS Breakdown ---'])
expense_rows.append([])
expense_rows.append(['Service', 'Total Spend (GBP)', 'Category', 'Payments'])

saas_categories = ['Software / SaaS', 'AI / Software', 'Gym Software']
service_spend = defaultdict(lambda: {'total': 0, 'count': 0, 'category': ''})
for tx in parsed:
    if tx['category'] == 'Expense' and tx['subcategory'] in saas_categories and tx['currency'] == 'GBP' and tx['amount'] < 0 and tx['date'].replace(tzinfo=None) >= FY_CUTOFF:
        name = tx['description'].strip()
        service_spend[name]['total'] += abs(tx['amount'])
        service_spend[name]['count'] += 1
        service_spend[name]['category'] = tx['subcategory']

for service in sorted(service_spend.keys(), key=lambda x: service_spend[x]['total'], reverse=True):
    s = service_spend[service]
    expense_rows.append([service, round(s['total'], 2), s['category'], s['count']])

saas_total = sum(s['total'] for s in service_spend.values())
expense_rows.append([])
expense_rows.append(['TOTAL SOFTWARE', round(saas_total, 2), '', sum(s['count'] for s in service_spend.values())])

# Monthly expense breakdown
expense_rows.append([])
expense_rows.append(['--- Monthly Expense Breakdown ---'])
expense_rows.append([])
monthly_exp_header = ['Category'] + month_order
expense_rows.append(monthly_exp_header)

monthly_expense_data = defaultdict(lambda: defaultdict(float))
for tx in parsed:
    if tx['category'] == 'Expense' and tx['currency'] == 'GBP' and tx['date'].replace(tzinfo=None) >= FY_CUTOFF:
        monthly_expense_data[tx['subcategory']][tx['month_display']] += abs(tx['amount'])

for cat in sorted(expense_cats.keys(), key=lambda x: expense_cats[x], reverse=True):
    row = [cat]
    for month in month_order:
        val = monthly_expense_data[cat].get(month, 0)
        row.append(round(val, 2) if val > 0 else '')
    expense_rows.append(row)

# ============================================================
# TAB 3: All Transactions
# ============================================================
tx_rows = [['Date', 'Description', 'Reference', 'Type', 'Amount (GBP)', 'Category', 'Subcategory', 'Running Balance']]
for tx in parsed:
    if tx['currency'] != 'GBP':
        continue
    if tx['date'].replace(tzinfo=None) < FY_CUTOFF:
        continue
    tx_rows.append([
        tx['date_str'], tx['description'], tx['reference'], tx['type'],
        round(tx['amount'], 2), tx['category'], tx['subcategory'],
        tx['balance'] if tx['balance'] != '' else ''
    ])

# ============================================================
# TAB 4: Dashboard
# ============================================================
current_month = datetime.now().strftime('%b %Y')
cm = months_data.get(current_month, {'gross': 0, 'fees': 0, 'net': 0, 'expenses': 0})
last_month_display = None
for i, m in enumerate(month_order):
    if m == current_month and i > 0:
        last_month_display = month_order[i-1]
lm = months_data.get(last_month_display, {'gross': 0, 'fees': 0, 'net': 0, 'expenses': 0}) if last_month_display else {'gross': 0, 'fees': 0, 'net': 0, 'expenses': 0}

dashboard_rows = [
    ['SYNERGY FINANCIAL DASHBOARD'],
    [f'Last updated: {datetime.now().strftime("%d %b %Y %H:%M")}'],
    [],
    ['CURRENT MONTH', current_month],
    ['Gross Revenue', f"\u00a3{cm['gross']:,.2f}"],
    ['Stripe Fees', f"\u00a3{cm['fees']:,.2f}"],
    ['Net Revenue', f"\u00a3{cm['net']:,.2f}"],
    ['Expenses', f"\u00a3{cm['expenses']:,.2f}"],
    ['Profit', f"\u00a3{cm['net'] - cm['expenses']:,.2f}"],
    [],
    ['PREVIOUS MONTH', last_month_display or 'N/A'],
    ['Gross Revenue', f"\u00a3{lm['gross']:,.2f}"],
    ['Stripe Fees', f"\u00a3{lm['fees']:,.2f}"],
    ['Net Revenue', f"\u00a3{lm['net']:,.2f}"],
    ['Expenses', f"\u00a3{lm['expenses']:,.2f}"],
    ['Profit', f"\u00a3{lm['net'] - lm['expenses']:,.2f}"],
    [],
    ['ALL TIME TOTALS'],
    ['Total Gross Revenue', f"\u00a3{total_gross:,.2f}"],
    ['Total Stripe Fees', f"\u00a3{total_fees:,.2f}"],
    ['Total Net Revenue', f"\u00a3{total_income:,.2f}"],
    ['Total Expenses', f"\u00a3{total_expenses:,.2f}"],
    ['Total Profit', f"\u00a3{total_profit:,.2f}"],
    ['Profit Margin', f"{total_margin:.1f}%"],
    ['Current Balance (Main)', f"\u00a3{parsed[-1]['balance'] if parsed and parsed[-1].get('balance') else 'N/A'}"],
    ['Savings Vault', f"\u00a3{vault_running:,.2f}"],
    ['Total Cash Position', f"\u00a3{(float(parsed[-1]['balance']) if parsed and parsed[-1].get('balance') else 0) + vault_running:,.2f}"],
    [],
    ['TOP EXPENSE CATEGORIES'],
]

top_cats = sorted(expense_cats.items(), key=lambda x: x[1], reverse=True)[:5]
for cat, amount in top_cats:
    pct = (amount / total_exp * 100) if total_exp > 0 else 0
    dashboard_rows.append([cat, f"\u00a3{amount:,.2f}", f"{pct:.1f}%"])

dashboard_rows.append([])
dashboard_rows.append(['INSIGHTS'])
insights = []
if cm['net'] > lm['net'] and lm['net'] > 0:
    pct_increase = ((cm['net'] - lm['net']) / lm['net']) * 100
    insights.append(f"Revenue up {pct_increase:.0f}% vs last month")
if cm['expenses'] > lm['expenses'] and lm['expenses'] > 0:
    pct_increase = ((cm['expenses'] - lm['expenses']) / lm['expenses']) * 100
    if pct_increase > 20:
        insights.append(f"Expenses up {pct_increase:.0f}% vs last month - review spending")
if total_margin < 30:
    insights.append(f"Profit margin at {total_margin:.1f}% - consider reducing expenses or increasing prices")
if not insights:
    insights.append("Looking healthy - keep tracking month over month")
for insight in insights:
    dashboard_rows.append([insight])

# ============================================================
# TAB 5: Tax Position
# ============================================================
# Synergy FY: use same Aug-Jul as Flowstate (both UK Ltd)
FY_START_MONTH = 8
now = datetime.now()
if now.month >= FY_START_MONTH:
    fy_start = datetime(now.year, FY_START_MONTH, 1)
    fy_end = datetime(now.year + 1, FY_START_MONTH - 1, 31)
    fy_label = f"Aug {now.year} - Jul {now.year + 1}"
else:
    fy_start = datetime(now.year - 1, FY_START_MONTH, 1)
    fy_end = datetime(now.year, FY_START_MONTH - 1, 31)
    fy_label = f"Aug {now.year - 1} - Jul {now.year}"

fy_income = 0
fy_expenses = 0
fy_months_active = 0
for month in month_order:
    d = months_data[month]
    month_date = datetime.strptime(month, '%b %Y')
    if fy_start <= month_date.replace(day=1) <= fy_end:
        fy_income += d['net']
        fy_expenses += d['expenses']
        fy_months_active += 1

fy_profit = fy_income - fy_expenses

if fy_profit <= 50000:
    tax_rate = 0.19
    tax_band = 'Small Profits (19%)'
elif fy_profit <= 250000:
    tax_rate = 0.265
    tax_band = 'Marginal Relief (26.5% effective)'
else:
    tax_rate = 0.25
    tax_band = 'Main Rate (25%)'

corp_tax = fy_profit * tax_rate if fy_profit > 0 else 0
after_tax_profit = fy_profit - corp_tax
total_fy_months = 12
months_remaining = total_fy_months - fy_months_active

allowable_cats = ['Software / SaaS', 'AI / Software', 'Gym Software', 'Ad Spend (Meta)', 'Ad Spend (Google)',
                  'Travel', 'Equipment / Supplies', 'Gym Equipment', 'Bank Fees / Charges', 'Wages / Drawings',
                  'Utilities', 'Rent / Property', 'Insurance', 'Cleaning / Hygiene']

fy_allowable = 0
for tx in parsed:
    if tx['currency'] != 'GBP' or tx['category'] != 'Expense':
        continue
    month_date = tx['date'].replace(tzinfo=None)
    if fy_start <= month_date <= fy_end:
        if tx['subcategory'] in allowable_cats:
            fy_allowable += abs(tx['amount'])

tax_rows = [
    ['SYNERGY - CORPORATION TAX POSITION'],
    [f'Financial Year: {fy_label}'],
    [f'Updated: {now.strftime("%d %b %Y")}'],
    [],
    ['CURRENT FY SUMMARY'],
    ['Revenue (FY to date)', f"\u00a3{fy_income:,.2f}"],
    ['Expenses (FY to date)', f"\u00a3{fy_expenses:,.2f}"],
    ['Taxable Profit', f"\u00a3{fy_profit:,.2f}"],
    [],
    ['TAX CALCULATION'],
    ['Tax Band', tax_band],
    ['Estimated Corporation Tax', f"\u00a3{corp_tax:,.2f}"],
    ['After-Tax Profit', f"\u00a3{after_tax_profit:,.2f}"],
    [],
    ['TAX TIMELINE'],
    ['FY Months Elapsed', fy_months_active],
    ['FY Months Remaining', months_remaining],
    ['Tax Return Due', f"12 months after FY end (Jul {fy_end.year + 1})"],
    ['Tax Payment Due', f"9 months + 1 day after FY end (May {fy_end.year + 1})"],
    [],
    ['ALLOWABLE EXPENSES (tax-deductible)'],
    ['Total Allowable to Date', f"\u00a3{fy_allowable:,.2f}"],
    [],
    ['Category', 'Amount (GBP)', 'Tax-Deductible?'],
]

for cat in allowable_cats:
    cat_total = 0
    for tx in parsed:
        if tx['currency'] != 'GBP' or tx['category'] != 'Expense' or tx['subcategory'] != cat:
            continue
        month_date = tx['date'].replace(tzinfo=None)
        if fy_start <= month_date <= fy_end:
            cat_total += abs(tx['amount'])
    if cat_total > 0:
        tax_rows.append([cat, round(cat_total, 2), 'Yes'])

tax_rows.append([])
tax_rows.append(['QUARTERLY TAX PROVISION'])
tax_rows.append(['Set aside monthly', f"\u00a3{corp_tax / max(fy_months_active, 1):,.2f}"])
tax_rows.append(['Already owed (to date)', f"\u00a3{corp_tax:,.2f}"])

tax_rows.append([])
tax_rows.append(['NOTES'])
tax_rows.append(['- Small profits rate (19%) applies to profits under 50,000'])
tax_rows.append(['- Gym rent, utilities, equipment, insurance, cleaning are all allowable'])
tax_rows.append(['- Staff wages/drawings reduce taxable profit'])
tax_rows.append(['- Consider pension contributions before FY end to reduce tax liability'])

# ============================================================
# TAB 6: Projection
# ============================================================
recent_months = month_order[-3:] if len(month_order) >= 3 else month_order
avg_rev = sum(months_data[m]['net'] for m in recent_months) / len(recent_months) if recent_months else 0
avg_exp = sum(months_data[m]['expenses'] for m in recent_months) / len(recent_months) if recent_months else 0
avg_profit = avg_rev - avg_exp
avg_savings = sum(months_data[m]['savings'] for m in recent_months) / len(recent_months) if recent_months else 0

projected_fy_rev = fy_income + (avg_rev * months_remaining)
projected_fy_exp = fy_expenses + (avg_exp * months_remaining)
projected_fy_profit = projected_fy_rev - projected_fy_exp

if projected_fy_profit <= 50000:
    proj_tax_rate = 0.19
    proj_tax_band = 'Small Profits (19%)'
elif projected_fy_profit <= 250000:
    proj_tax_rate = 0.265
    proj_tax_band = 'Marginal Relief'
else:
    proj_tax_rate = 0.25
    proj_tax_band = 'Main Rate (25%)'

proj_tax = projected_fy_profit * proj_tax_rate if projected_fy_profit > 0 else 0

proj_rows = [
    ['SYNERGY - YEAR-END PROJECTION'],
    [f'Based on {len(recent_months)}-month average ({", ".join(recent_months)})'],
    [f'Projecting to end of FY: Jul {fy_end.year}'],
    [],
    ['MONTHLY AVERAGES (recent)'],
    ['Average Revenue', f"\u00a3{avg_rev:,.2f}"],
    ['Average Expenses', f"\u00a3{avg_exp:,.2f}"],
    ['Average Profit', f"\u00a3{avg_profit:,.2f}"],
    ['Average Saved to Vault', f"\u00a3{avg_savings:,.2f}"],
    [],
    ['PROJECTED FY TOTALS'],
    ['Projected Revenue', f"\u00a3{projected_fy_rev:,.2f}"],
    ['Projected Expenses', f"\u00a3{projected_fy_exp:,.2f}"],
    ['Projected Profit', f"\u00a3{projected_fy_profit:,.2f}"],
    ['Projected Tax Band', proj_tax_band],
    ['Projected Corp Tax', f"\u00a3{proj_tax:,.2f}"],
    ['Projected After-Tax Profit', f"\u00a3{projected_fy_profit - proj_tax:,.2f}"],
    [],
    ['GROWTH METRICS'],
]

if len(month_order) >= 2:
    recent_rev = months_data[month_order[-1]]['net']
    prev_rev = months_data[month_order[-2]]['net']
    if prev_rev > 0:
        mom_growth = ((recent_rev - prev_rev) / prev_rev) * 100
        proj_rows.append(['Month-over-Month Growth', f"{mom_growth:+.1f}%"])

if len(month_order) >= 4:
    recent_3 = sum(months_data[m]['net'] for m in month_order[-3:])
    prev_3 = sum(months_data[m]['net'] for m in month_order[-6:-3]) if len(month_order) >= 6 else sum(months_data[m]['net'] for m in month_order[:-3])
    if prev_3 > 0:
        qoq_growth = ((recent_3 - prev_3) / prev_3) * 100
        proj_rows.append(['Quarter-over-Quarter Growth', f"{qoq_growth:+.1f}%"])

proj_rows.append([])
proj_rows.append(['SAVINGS PROJECTION'])
proj_rows.append(['Current Vault', f"\u00a3{vault_running:,.2f}"])
proj_rows.append(['Projected Vault (FY end)', f"\u00a3{vault_running + (avg_savings * months_remaining):,.2f}"])

# ============================================================
# WRITE ALL TABS
# ============================================================
batch_data = [
    {'range': 'Monthly P&L!A1', 'values': pnl_rows},
    {'range': 'Expense Breakdown!A1', 'values': expense_rows},
    {'range': 'All Transactions!A1', 'values': tx_rows},
    {'range': 'Dashboard!A1', 'values': dashboard_rows},
    {'range': 'Tax Position!A1', 'values': tax_rows},
    {'range': 'Projection!A1', 'values': proj_rows},
]

# Optional member revenue tab
if has_stripe:
    member_rows = [['Member', 'Total Revenue (GBP)', 'Payments']]
    for member in sorted(member_revenue.keys(), key=lambda x: member_revenue[x]['total_gbp'], reverse=True):
        mr = member_revenue[member]
        if mr['total_gbp'] == 0:
            continue
        member_rows.append([member, round(mr['total_gbp'], 2), mr['payments']])
    total_member_rev = sum(mr['total_gbp'] for mr in member_revenue.values())
    member_rows.append([])
    member_rows.append(['TOTAL', round(total_member_rev, 2), sum(mr['payments'] for mr in member_revenue.values())])
    batch_data.append({'range': 'Member Revenue!A1', 'values': member_rows})

sheets_service.spreadsheets().values().batchUpdate(
    spreadsheetId=spreadsheet_id,
    body={'valueInputOption': 'RAW', 'data': batch_data}
).execute()

# Format tabs
requests = []
for sheet in result['sheets']:
    title = sheet['properties']['title']
    if title not in required_tabs:
        continue
    sheet_id = sheet['properties']['sheetId']
    requests.append({
        'repeatCell': {
            'range': {'sheetId': sheet_id, 'startRowIndex': 0, 'endRowIndex': 1},
            'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}},
            'fields': 'userEnteredFormat.textFormat.bold'
        }
    })
    requests.append({
        'updateSheetProperties': {
            'properties': {'sheetId': sheet_id, 'gridProperties': {'frozenRowCount': 1}},
            'fields': 'gridProperties.frozenRowCount'
        }
    })
    requests.append({
        'autoResizeDimensions': {
            'dimensions': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 15}
        }
    })

# Delete existing charts on our tabs
for sheet in result['sheets']:
    if sheet['properties']['title'] in required_tabs:
        for chart in sheet.get('charts', []):
            requests.append({'deleteEmbeddedObject': {'objectId': chart['chartId']}})

if requests:
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': requests}
    ).execute()

# Charts
pnl_sheet_id = None
for sheet in result['sheets']:
    if sheet['properties']['title'] == 'Monthly P&L':
        pnl_sheet_id = sheet['properties']['sheetId']
        break

if pnl_sheet_id and len(month_order) > 1:
    num_months = len(month_order)
    chart_requests = [
        {'addChart': {'chart': {
            'position': {'overlayPosition': {
                'anchorCell': {'sheetId': pnl_sheet_id, 'rowIndex': num_months + 5, 'columnIndex': 0},
                'widthPixels': 900, 'heightPixels': 450
            }},
            'spec': {
                'title': 'Monthly Revenue vs Expenses vs Profit',
                'basicChart': {
                    'chartType': 'COMBO', 'legendPosition': 'BOTTOM_LEGEND',
                    'axis': [{'position': 'BOTTOM_AXIS', 'title': 'Month'}, {'position': 'LEFT_AXIS', 'title': 'GBP'}],
                    'domains': [{'domain': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 0, 'endColumnIndex': 1}]}}}],
                    'series': [
                        {'series': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 3, 'endColumnIndex': 4}]}}, 'targetAxis': 'LEFT_AXIS', 'type': 'COLUMN', 'color': {'red': 0.26, 'green': 0.52, 'blue': 0.96}},
                        {'series': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 4, 'endColumnIndex': 5}]}}, 'targetAxis': 'LEFT_AXIS', 'type': 'COLUMN', 'color': {'red': 0.91, 'green': 0.3, 'blue': 0.24}},
                        {'series': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 5, 'endColumnIndex': 6}]}}, 'targetAxis': 'LEFT_AXIS', 'type': 'LINE', 'color': {'red': 0.2, 'green': 0.8, 'blue': 0.4}},
                    ],
                    'headerCount': 1,
                }
            }
        }}},
        {'addChart': {'chart': {
            'position': {'overlayPosition': {
                'anchorCell': {'sheetId': pnl_sheet_id, 'rowIndex': num_months + 5, 'columnIndex': 5},
                'widthPixels': 700, 'heightPixels': 450
            }},
            'spec': {
                'title': 'Cumulative Revenue & Profit Growth',
                'basicChart': {
                    'chartType': 'LINE', 'legendPosition': 'BOTTOM_LEGEND',
                    'axis': [{'position': 'BOTTOM_AXIS', 'title': 'Month'}, {'position': 'LEFT_AXIS', 'title': 'GBP (Cumulative)'}],
                    'domains': [{'domain': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 0, 'endColumnIndex': 1}]}}}],
                    'series': [
                        {'series': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 7, 'endColumnIndex': 8}]}}, 'targetAxis': 'LEFT_AXIS', 'color': {'red': 0.26, 'green': 0.52, 'blue': 0.96}},
                        {'series': {'sourceRange': {'sources': [{'sheetId': pnl_sheet_id, 'startRowIndex': 0, 'endRowIndex': num_months + 1, 'startColumnIndex': 8, 'endColumnIndex': 9}]}}, 'targetAxis': 'LEFT_AXIS', 'color': {'red': 0.2, 'green': 0.8, 'blue': 0.4}},
                    ],
                    'headerCount': 1,
                }
            }
        }}},
    ]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': chart_requests}
    ).execute()

print(f"\nDone! Synergy Sheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
print(f"\nSummary:")
print(f"  Revolut transactions: {len(parsed)}")
print(f"  Stripe charges: {len(stripe_charges)}")
print(f"  Months covered: {len(month_order)} ({month_order[0] if month_order else 'N/A'} to {month_order[-1] if month_order else 'N/A'})")
print(f"  Gross Revenue: \u00a3{total_gross:,.2f}")
print(f"  Total Expenses: \u00a3{total_expenses:,.2f}")
print(f"  Total Profit: \u00a3{total_profit:,.2f} ({total_margin:.1f}% margin)")
