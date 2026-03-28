"""
Finance API - FastAPI wrapper around the existing finance Python scripts.

Each endpoint runs the corresponding script as a subprocess and returns
the output + exit code. This avoids rewriting any business logic.

Endpoints:
  POST /run/fetch-data?entity=flowstate|synergy
  POST /run/build-sheet?entity=flowstate|synergy
  POST /run/scan-invoices?account=all|flowstate|flowstatesystems|synergy
  POST /run/match-invoices?entity=flowstate|synergy
  POST /run/full-pipeline          -- runs everything in order
  GET  /health                     -- health check
  GET  /status                     -- last run status for each step
"""
import os
import sys
import json
import time
import subprocess
import base64
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Header, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI(title="Flowstate Finance API", version="1.0.0")

# Simple API key auth
API_KEY = os.environ.get('FINANCE_API_KEY', '')
SCRIPTS_DIR = os.environ.get('FINANCE_SCRIPTS_DIR', '/app/scripts')
PYTHON = sys.executable
DATA_DIR = os.environ.get('FINANCE_DATA_DIR', '')
STATUS_FILE = os.path.join(DATA_DIR, 'api_run_status.json') if DATA_DIR else '/tmp/api_run_status.json'

# Script mapping
SCRIPTS = {
    'fetch_flowstate': 'fetch_data.py',
    'fetch_synergy': 'synergy_fetch_data.py',
    'build_flowstate': 'build_finance_sheet.py',
    'build_synergy': 'synergy_build_finance_sheet.py',
    'scan_invoices': 'scan_invoices.py',
    'match_flowstate': 'match_invoices.py',
    'match_synergy': 'match_invoices.py',
}


def check_auth(api_key: Optional[str]):
    """Verify API key if one is configured."""
    if API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def load_status():
    try:
        with open(STATUS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_status(status):
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)


def update_step_status(step: str, success: bool, output: str, duration: float):
    status = load_status()
    status[step] = {
        'success': success,
        'timestamp': datetime.now().isoformat(),
        'duration_seconds': round(duration, 1),
        'output_tail': output[-2000:] if output else '',
    }
    save_status(status)


def run_script(script_name: str, args: list = None, timeout: int = 300) -> dict:
    """Run a finance script and return results."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail=f"Script not found: {script_name}")

    cmd = [PYTHON, script_path] + (args or [])
    env = os.environ.copy()

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
        duration = time.time() - start
        output = result.stdout + result.stderr
        success = result.returncode == 0

        return {
            'success': success,
            'exit_code': result.returncode,
            'output': output[-3000:],  # Last 3000 chars
            'duration_seconds': round(duration, 1),
        }
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        return {
            'success': False,
            'exit_code': -1,
            'output': f'Script timed out after {timeout}s',
            'duration_seconds': round(duration, 1),
        }
    except Exception as e:
        duration = time.time() - start
        return {
            'success': False,
            'exit_code': -1,
            'output': str(e),
            'duration_seconds': round(duration, 1),
        }


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/status")
def status(x_api_key: Optional[str] = Header(None)):
    check_auth(x_api_key)
    return load_status()


@app.post("/run/fetch-data")
def fetch_data(
    entity: str = Query(..., regex="^(flowstate|synergy)$"),
    x_api_key: Optional[str] = Header(None),
):
    check_auth(x_api_key)
    script = SCRIPTS[f'fetch_{entity}']
    step_name = f'fetch_{entity}'

    result = run_script(script, timeout=300)
    update_step_status(step_name, result['success'], result['output'], result['duration_seconds'])
    return result


@app.post("/run/build-sheet")
def build_sheet(
    entity: str = Query(..., regex="^(flowstate|synergy)$"),
    x_api_key: Optional[str] = Header(None),
):
    check_auth(x_api_key)
    script = SCRIPTS[f'build_{entity}']
    step_name = f'build_{entity}'

    result = run_script(script, timeout=180)
    update_step_status(step_name, result['success'], result['output'], result['duration_seconds'])
    return result


@app.post("/run/scan-invoices")
def scan_invoices(
    account: str = Query("all", regex="^(all|flowstate|flowstatesystems|synergy)$"),
    x_api_key: Optional[str] = Header(None),
):
    check_auth(x_api_key)
    args = [] if account == "all" else ['--account', account]
    step_name = f'scan_invoices_{account}'

    result = run_script('scan_invoices.py', args=args, timeout=300)
    update_step_status(step_name, result['success'], result['output'], result['duration_seconds'])
    return result


@app.post("/run/match-invoices")
def match_invoices(
    entity: str = Query(..., regex="^(flowstate|synergy)$"),
    x_api_key: Optional[str] = Header(None),
):
    check_auth(x_api_key)
    step_name = f'match_{entity}'

    result = run_script('match_invoices.py', args=['--entity', entity], timeout=180)
    update_step_status(step_name, result['success'], result['output'], result['duration_seconds'])
    return result


@app.post("/run/full-pipeline")
def full_pipeline(x_api_key: Optional[str] = Header(None)):
    """Run the complete Friday finance pipeline in order."""
    check_auth(x_api_key)

    steps = [
        ('fetch_flowstate', 'fetch_data.py', [], 300),
        ('fetch_synergy', 'synergy_fetch_data.py', [], 300),
        ('build_flowstate', 'build_finance_sheet.py', [], 180),
        ('build_synergy', 'synergy_build_finance_sheet.py', [], 180),
        ('scan_invoices', 'scan_invoices.py', [], 300),
        ('match_flowstate', 'match_invoices.py', ['--entity', 'flowstate'], 180),
        ('match_synergy', 'match_invoices.py', ['--entity', 'synergy'], 180),
    ]

    results = {}
    all_success = True
    total_start = time.time()

    for step_name, script, args, timeout in steps:
        result = run_script(script, args=args, timeout=timeout)
        update_step_status(step_name, result['success'], result['output'], result['duration_seconds'])
        results[step_name] = result

        if not result['success']:
            all_success = False
            # Continue running remaining steps even if one fails

    total_duration = round(time.time() - total_start, 1)

    return {
        'success': all_success,
        'total_duration_seconds': total_duration,
        'steps': results,
    }


# ============================================================
# DATA MANAGEMENT ENDPOINTS
# ============================================================

@app.post("/data/upload")
async def upload_file(
    filename: str = Query(...),
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None),
):
    """Upload a file to the /data volume. Used for initial setup."""
    check_auth(x_api_key)
    if not DATA_DIR:
        raise HTTPException(status_code=500, detail="FINANCE_DATA_DIR not set")

    # Security: only allow known filenames
    ALLOWED_FILES = {
        'config.json', 'credentials.json', 'synergy_credentials.json',
        'certificate.pem', 'private.key', 'synergy_public.pem', 'synergy_private.pem',
        'google_token.pickle', 'google_token_flowstatesystems.pickle', 'google_token_synergy.pickle',
        'transactions_raw.json', 'synergy_transactions_raw.json',
        'stripe_charges.json', 'stripe_customer_map.json',
        'synergy_stripe_charges.json', 'synergy_stripe_customer_map.json',
        'invoice_scan_state.json',
    }

    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=400, detail=f"Filename not allowed: {filename}")

    filepath = os.path.join(DATA_DIR, filename)
    contents = await file.read()
    with open(filepath, 'wb') as f:
        f.write(contents)

    return {"uploaded": filename, "size_bytes": len(contents)}


@app.get("/data/list")
def list_data(x_api_key: Optional[str] = Header(None)):
    """List files in the /data volume."""
    check_auth(x_api_key)
    if not DATA_DIR or not os.path.exists(DATA_DIR):
        return {"files": []}

    files = []
    for f in sorted(os.listdir(DATA_DIR)):
        path = os.path.join(DATA_DIR, f)
        if os.path.isfile(path):
            files.append({
                "name": f,
                "size_bytes": os.path.getsize(path),
                "modified": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            })
    return {"files": files}
