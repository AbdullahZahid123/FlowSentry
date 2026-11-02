"""Generate local Compose secrets once. Never prints or overwrites credentials."""
from pathlib import Path
import argparse,secrets
parser=argparse.ArgumentParser()
parser.add_argument('--output',default='.env')
args=parser.parse_args()
path=Path(args.output)
if path.exists():raise SystemExit('Configuration already exists; no values changed.')
value='\n'.join(['# Generated local deployment configuration. Keep this file private.','APP_ENV=development','WEB_PORT=3100','FRONTEND_URL=http://localhost:3100','SESSION_COOKIE_SECURE=false','DB_PASSWORD='+secrets.token_hex(24),'APP_SECRET_KEY='+secrets.token_urlsafe(48),'ENCRYPTION_KEY='+secrets.token_hex(32),'ALLOW_PRIVATE_NETWORK=false',''])
path.write_text(value,encoding='utf-8')
try:path.chmod(0o600)
except OSError:pass
print('Configuration generated at '+str(path)+'. Secrets were not printed.')
