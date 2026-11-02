"""Standalone, signal-aware services and database administration."""
import argparse,logging,signal,threading,time
from pathlib import Path
from app.core import config
from app.core.migrations import upgrade_schema,adopt_existing_schema
from app.worker import drain_outbox_once,deliver_notifications_once,sync_integrations_once
from app.modules.retention import run_retention_once
from app.modules.status_alerts import evaluate_status_alerts_once

def main():
 parser=argparse.ArgumentParser(prog='python -m app.cli')
 parser.add_argument('service',choices=['migrate','adopt-schema','worker','scheduler','retention','health'])
 parser.add_argument('--role',choices=['worker','scheduler'])
 args=parser.parse_args()
 logging.basicConfig(level=config.settings.log_level,format='%(asctime)s %(levelname)s %(name)s: %(message)s')
 if args.service=='migrate':upgrade_schema();return
 if args.service=='adopt-schema':adopt_existing_schema();return
 if args.service=='retention':print(run_retention_once());return
 if args.service=='health':
  if not args.role:parser.error('health requires --role')
  import tempfile
  path=Path(tempfile.gettempdir())/('flowsentry-'+args.role+'.heartbeat')
  raise SystemExit(0 if path.exists() and time.time()-path.stat().st_mtime<max(300,config.settings.http_outbound_timeout_seconds*config.settings.worker_batch_size+60) else 1)
 stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 interval=config.settings.worker_interval_seconds if args.service=='worker' else 15
 heartbeat=Path('/tmp/flowsentry-'+args.service+'.heartbeat')
 if not heartbeat.parent.exists():
  import tempfile
  heartbeat=Path(tempfile.gettempdir())/heartbeat.name
 last_retention=0.0
 while not stop.is_set():
  try:
   if args.service=='worker':drain_outbox_once();deliver_notifications_once()
   else:
    sync_integrations_once()
    if time.monotonic()-last_retention>60:run_retention_once();evaluate_status_alerts_once();last_retention=time.monotonic()
   heartbeat.touch()
  except Exception:logging.exception('%s iteration failed',args.service)
  stop.wait(max(0.2,interval))

if __name__=='__main__':main()
