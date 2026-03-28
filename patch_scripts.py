#!/usr/bin/env python3
"""
Patch finance scripts for server deployment.

Creates copies in /app/scripts/ with hardcoded Mac paths replaced by
environment-variable-driven paths from config.py.

Run once during Docker build. Original scripts in ~/flowstate/revolut/ are untouched.
"""
import os
import re
import shutil

SRC_DIR = os.environ.get('FINANCE_SRC_DIR', '/app/revolut')
DST_DIR = os.environ.get('FINANCE_SCRIPTS_DIR', '/app/scripts')
DATA_DIR = os.environ.get('FINANCE_DATA_DIR', '/data')

os.makedirs(DST_DIR, exist_ok=True)

# Scripts to patch
SCRIPTS = [
    'fetch_data.py',
    'synergy_fetch_data.py',
    'build_finance_sheet.py',
    'synergy_build_finance_sheet.py',
    'scan_invoices.py',
    'match_invoices.py',
]

# Path replacements: (original pattern, replacement)
REPLACEMENTS = [
    # REVOLUT_DIR
    (r"REVOLUT_DIR\s*=\s*['\"].*?['\"]", f"REVOLUT_DIR = '{DATA_DIR}'"),

    # CONFIG_PATH - the Google Drive config
    (
        r"CONFIG_PATH\s*=\s*os\.path\.expanduser\(.*?\)",
        f"CONFIG_PATH = '{DATA_DIR}/config.json'"
    ),
    (
        r"CONFIG_PATH\s*=\s*os\.expanduser\(.*?\)",
        f"CONFIG_PATH = '{DATA_DIR}/config.json'"
    ),

    # Main Flowstate Google token (in build_finance_sheet.py, synergy_build_finance_sheet.py)
    (
        r'token_path\s*=\s*os\.path\.expanduser\(.*?google_token\.pickle.*?\)',
        f"token_path = '{DATA_DIR}/google_token.pickle'"
    ),

    # Match invoices token
    (
        r'TOKEN_PATH\s*=\s*["\'].*?google_token\.pickle["\']',
        f"TOKEN_PATH = '{DATA_DIR}/google_token.pickle'"
    ),

    # scan_invoices.py account tokens
    (
        r"'token':\s*\".*?telegram-mcp/google_token\.pickle\"",
        f"'token': \"{DATA_DIR}/google_token.pickle\""
    ),
    (
        r"'token':\s*\".*?google_token_flowstatesystems\.pickle\"",
        f"'token': \"{DATA_DIR}/google_token_flowstatesystems.pickle\""
    ),
    (
        r"'token':\s*\".*?google_token_synergy\.pickle\"",
        f"'token': \"{DATA_DIR}/google_token_synergy.pickle\""
    ),

    # Revolut cert paths (fetch_data.py)
    (
        r"CERT_PATH\s*=\s*os\.path\.join\(REVOLUT_DIR,\s*'certificate\.pem'\)",
        f"CERT_PATH = '{DATA_DIR}/certificate.pem'"
    ),
    (
        r"KEY_PATH\s*=\s*os\.path\.join\(REVOLUT_DIR,\s*'private\.key'\)",
        f"KEY_PATH = '{DATA_DIR}/private.key'"
    ),

    # Synergy cert paths (synergy_fetch_data.py)
    (
        r"CERT_PATH\s*=\s*os\.path\.join\(REVOLUT_DIR,\s*'synergy_public\.pem'\)",
        f"CERT_PATH = '{DATA_DIR}/synergy_public.pem'"
    ),
    (
        r"KEY_PATH\s*=\s*os\.path\.join\(REVOLUT_DIR,\s*'synergy_private\.pem'\)",
        f"KEY_PATH = '{DATA_DIR}/synergy_private.pem'"
    ),

    # Hardcoded revolut dir in build scripts (the raw path, not via join)
    (
        r"'/Users/kevinharkin/flowstate/revolut'",
        f"'{DATA_DIR}'"
    ),

    # scan_invoices state file path
    (
        r"STATE_FILE\s*=\s*os\.path\.join\(.*?,\s*'invoice_scan_state\.json'\)",
        f"STATE_FILE = '{DATA_DIR}/invoice_scan_state.json'"
    ),

    # scan_invoices STATE_PATH
    (
        r'STATE_PATH\s*=\s*["\'].*?invoice_scan_state\.json["\']',
        f"STATE_PATH = '{DATA_DIR}/invoice_scan_state.json'"
    ),

    # Catch-all: any remaining /Users/kevinharkin/flowstate/revolut/ inline paths
    (
        r"'/Users/kevinharkin/flowstate/revolut/([^']+)'",
        f"'{DATA_DIR}/\\1'"
    ),
    (
        r'"/Users/kevinharkin/flowstate/revolut/([^"]+)"',
        f'"{DATA_DIR}/\\1"'
    ),
]


def patch_file(filename):
    src = os.path.join(SRC_DIR, filename)
    dst = os.path.join(DST_DIR, filename)

    with open(src, 'r') as f:
        content = f.read()

    original = content
    for pattern, replacement in REPLACEMENTS:
        content = re.sub(pattern, replacement, content)

    changes = content != original
    with open(dst, 'w') as f:
        f.write(content)

    status = "PATCHED" if changes else "unchanged"
    print(f"  {filename}: {status}")


if __name__ == '__main__':
    print(f"Patching scripts from {SRC_DIR} -> {DST_DIR}")
    print(f"Data directory: {DATA_DIR}\n")

    for script in SCRIPTS:
        src = os.path.join(SRC_DIR, script)
        if os.path.exists(src):
            patch_file(script)
        else:
            print(f"  {script}: MISSING (skipped)")

    print("\nDone.")
