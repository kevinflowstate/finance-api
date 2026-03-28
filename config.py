"""
Centralised path configuration for finance scripts.

On Kevin's Mac: uses local paths (default).
On Railway/server: set FINANCE_DATA_DIR env var to persistent volume path.
"""
import os

# If FINANCE_DATA_DIR is set, all data lives there. Otherwise, use local Mac paths.
DATA_DIR = os.environ.get('FINANCE_DATA_DIR', '')
IS_SERVER = bool(DATA_DIR)

if IS_SERVER:
    # Server mode - everything in one directory on persistent volume
    REVOLUT_DIR = DATA_DIR
    CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')
    GOOGLE_CREDENTIALS_PATH = os.path.join(DATA_DIR, 'google_credentials.json')

    # Google tokens
    GOOGLE_TOKEN_FLOWSTATE = os.path.join(DATA_DIR, 'google_token.pickle')
    GOOGLE_TOKEN_FLOWSTATESYSTEMS = os.path.join(DATA_DIR, 'google_token_flowstatesystems.pickle')
    GOOGLE_TOKEN_SYNERGY = os.path.join(DATA_DIR, 'google_token_synergy.pickle')

    # Revolut certs - Flowstate
    REVOLUT_CERT_PATH = os.path.join(DATA_DIR, 'certificate.pem')
    REVOLUT_KEY_PATH = os.path.join(DATA_DIR, 'private.key')

    # Revolut certs - Synergy
    SYNERGY_CERT_PATH = os.path.join(DATA_DIR, 'synergy_public.pem')
    SYNERGY_KEY_PATH = os.path.join(DATA_DIR, 'synergy_private.pem')

    # Revolut credentials
    REVOLUT_CREDS_PATH = os.path.join(DATA_DIR, 'credentials.json')
    SYNERGY_CREDS_PATH = os.path.join(DATA_DIR, 'synergy_credentials.json')

    # Data files
    TRANSACTIONS_PATH = os.path.join(DATA_DIR, 'transactions_raw.json')
    SYNERGY_TRANSACTIONS_PATH = os.path.join(DATA_DIR, 'synergy_transactions_raw.json')
    STRIPE_CHARGES_PATH = os.path.join(DATA_DIR, 'stripe_charges.json')
    STRIPE_CUSTOMER_MAP_PATH = os.path.join(DATA_DIR, 'stripe_customer_map.json')
    SYNERGY_STRIPE_CHARGES_PATH = os.path.join(DATA_DIR, 'synergy_stripe_charges.json')
    SYNERGY_STRIPE_CUSTOMER_MAP_PATH = os.path.join(DATA_DIR, 'synergy_stripe_customer_map.json')
    INVOICE_SCAN_STATE_PATH = os.path.join(DATA_DIR, 'invoice_scan_state.json')

else:
    # Local Mac mode - original hardcoded paths
    REVOLUT_DIR = '/Users/kevinharkin/flowstate/revolut'
    CONFIG_PATH = os.path.expanduser(
        "~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/"
        "My Drive/Flowstate/Claude's Stuff/.config.json"
    )
    GOOGLE_CREDENTIALS_PATH = os.path.expanduser(
        "~/Library/CloudStorage/GoogleDrive-kevin.flowstate@gmail.com/"
        "My Drive/Flowstate/Claude's Stuff/google_credentials.json"
    )

    GOOGLE_TOKEN_FLOWSTATE = '/Users/kevinharkin/flowstate/telegram-mcp/google_token.pickle'
    GOOGLE_TOKEN_FLOWSTATESYSTEMS = os.path.join(REVOLUT_DIR, 'google_token_flowstatesystems.pickle')
    GOOGLE_TOKEN_SYNERGY = os.path.join(REVOLUT_DIR, 'google_token_synergy.pickle')

    REVOLUT_CERT_PATH = os.path.join(REVOLUT_DIR, 'certificate.pem')
    REVOLUT_KEY_PATH = os.path.join(REVOLUT_DIR, 'private.key')
    SYNERGY_CERT_PATH = os.path.join(REVOLUT_DIR, 'synergy_public.pem')
    SYNERGY_KEY_PATH = os.path.join(REVOLUT_DIR, 'synergy_private.pem')
    REVOLUT_CREDS_PATH = os.path.join(REVOLUT_DIR, 'credentials.json')
    SYNERGY_CREDS_PATH = os.path.join(REVOLUT_DIR, 'synergy_credentials.json')

    TRANSACTIONS_PATH = os.path.join(REVOLUT_DIR, 'transactions_raw.json')
    SYNERGY_TRANSACTIONS_PATH = os.path.join(REVOLUT_DIR, 'synergy_transactions_raw.json')
    STRIPE_CHARGES_PATH = os.path.join(REVOLUT_DIR, 'stripe_charges.json')
    STRIPE_CUSTOMER_MAP_PATH = os.path.join(REVOLUT_DIR, 'stripe_customer_map.json')
    SYNERGY_STRIPE_CHARGES_PATH = os.path.join(REVOLUT_DIR, 'synergy_stripe_charges.json')
    SYNERGY_STRIPE_CUSTOMER_MAP_PATH = os.path.join(REVOLUT_DIR, 'synergy_stripe_customer_map.json')
    INVOICE_SCAN_STATE_PATH = os.path.join(REVOLUT_DIR, 'invoice_scan_state.json')


# Google Sheet IDs (same everywhere)
FLOWSTATE_SHEET_ID = '1p1PRsots8UL_BmajWXTwouo3Gm43w1drA_QfZ37vjX0'
SYNERGY_SHEET_ID = '1TSd-Sa8DSv7iBEWfj0m1QLhDLdklpLTp0WWtAqjpKQI'

# Drive folder IDs
ACCOUNTS_ROOT_FOLDER = '1z-z8iHKHFHuGRxOCf_koSjJchMVlxpiE'
FLOWSTATE_ACCOUNTS_FOLDER = '1vX0zlVB0JZEOhLU5udr8ebM3cqXraAeb'
SYNERGY_ACCOUNTS_FOLDER = '1nhQAU85zlSal7v8CaxR-SIrRVyMPTg3l'
