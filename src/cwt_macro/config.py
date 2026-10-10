"""Small, deliberately limited local credential-file loader. Never prints values."""
import os
import re
from pathlib import Path

KEYS = ('APIFY_TOKEN', 'TAVILY_API_KEY', 'APIFY_ACTOR_ID')


def load_env_file(path='.env', required=False):
    """Read KEY=value, quoted values and whole-line comments, without expansion.

    Validate the entire file before changing the environment. Existing nonempty
    environment values take precedence. This does not execute shell expressions.
    """
    path = Path(path)
    if not path.exists():
        if required:
            raise ValueError('Credential file does not exist; copy .env.example to a private .env file')
        return False
    pending = {}
    for number, raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError(f'Invalid credential-file syntax on line {number}; values are hidden')
        if key not in KEYS:
            raise ValueError(f'Unsupported credential-file setting on line {number}; only the three example settings are accepted')
        if key in pending:
            raise ValueError(f'Duplicate credential-file setting on line {number}')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed credential-file quote on line {number}; values are hidden')
            value = value[1:-1]
        if any(c.isspace() for c in value) or '$' in value or '`' in value:
            raise ValueError(f'Invalid credential-file value on line {number}; values are hidden')
        pending[key] = value
    for key, value in pending.items():
        if not os.getenv(key):
            os.environ[key] = value
    return True


def setup_status():
    """Presence is not authentication, quota, Actor compatibility or coverage."""
    required = ('APIFY_TOKEN', 'TAVILY_API_KEY')
    status = {key: bool(os.getenv(key, '').strip()) for key in required}
    missing = [key for key, present in status.items() if not present]
    return {'credential_presence': status, 'ready_to_attempt_live_ingestion': not missing,
            'missing_settings': missing, 'authentication_verified': False,
            'actor_access_verified': False,
            'note': 'Offline presence check only. No API calls, charges or credential values.'}


def require_live_credentials():
    missing = setup_status()['missing_settings']
    if missing:
        raise ValueError('Live ingestion requires both credentials before any service run starts. Missing: '
                         + ', '.join(missing) + '. See docs/credential_setup.md.')
