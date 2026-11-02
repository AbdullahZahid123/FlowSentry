# Deployment and operations

## Published container images

Download the installation archive from the GitHub release, extract it, and generate configuration once with `python scripts/configure.py`. Use both Compose files for image-based installs:

```sh
docker compose -f compose.yaml -f compose.release.yaml pull
docker compose -f compose.yaml -f compose.release.yaml up -d --no-build
```

The release override selects `ghcr.io/abdullahzahid123/flowsentry-backend:v0.1.0` and `ghcr.io/abdullahzahid123/flowsentry-web:v0.1.0` for Linux AMD64/ARM64. Set `FLOWSENTRY_VERSION` to pin a different published tag. Keep using both files for subsequent operations; omit the override only when deliberately building from source. The backend image serves the API, migration, worker, and scheduler roles. Images carry source/revision labels and build provenance/SBOM attestations.

Back up the database and encryption key before upgrading. Review the target release's migration notes before changing the version. The default local HTTP binding still requires HTTPS and secure-cookie configuration before network exposure.

## Services

`docker compose up --build -d` runs PostgreSQL, a one-shot migration service, the API, a worker, a scheduler, and the web application. The web service is bound to `127.0.0.1:3100`; the API and database have no host port. PostgreSQL data lives in the `flowsentry_postgres-data` named volume. Do not use `docker compose down -v` on a deployment whose data you need.

```sh
docker compose ps
docker compose logs --tail 100 api worker scheduler
docker compose exec api python -m app.cli retention
```

API liveness is `/health/live`; readiness is `/health/ready` and requires database connectivity and the expected migration revision. Worker/scheduler health checks require a recent heartbeat. Notification results and attempts are visible in the app. A successful notification means the transport accepted it, not that a person read it.

## HTTPS deployment

Place a TLS reverse proxy in front of the loopback web port. Set these values in `.env`, then recreate the services:

```dotenv
APP_ENV=production
FRONTEND_URL=https://monitor.example.com
SESSION_COOKIE_SECURE=true
```

Production startup rejects missing/placeholder secrets, invalid encryption keys, insecure cookies, and a non-HTTPS frontend URL. Keep the database and API off the public network. Preserve streaming responses at the proxy: disable buffering for `/api/events/stream`, allow long-lived connections, and set an appropriate read timeout. The app refetches canonical resources when the stream reconnects.

Request IDs are returned in `X-Request-ID` and included in API logs. The bundled rate limiter is process-local; keep one API process or enforce shared rate limits in your reverse proxy before scaling replicas. Size PostgreSQL connections and resources for your installation. This repository does not include a managed TLS endpoint or production infrastructure provisioning.

## Email and Telegram

Set SMTP variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`) for email and password-reset delivery. Port 465 with TLS uses implicit TLS; other TLS ports use STARTTLS. Set `TELEGRAM_BOT_TOKEN` for Telegram. Create the channel and target recipient/chat in the app, send a test, then attach it to a rule. The worker retries failed delivery with bounded backoff and records attempts. Delivery is at least once: a crash after the provider accepts a message but before its database acknowledgement may send a duplicate.

## Migrations and upgrades

Back up before upgrades. Build the new images and run `docker compose up -d`; the migration service must succeed before the API and workers start. To run migrations separately:

```sh
docker compose run --rm migrate
```

For a legacy database originally created with `create_all`, first run `python -m app.cli adopt-schema` in the backend environment. Adoption checks the existing structure and refuses an unknown schema. Then run `python -m app.cli migrate`. Do not stamp arbitrary databases manually.

## Back up and restore

Use the included platform-independent script; it streams binary data without PowerShell redirection corruption:

```sh
python scripts/backup.py backup --output backups/flowsentry.dump
```

Back up `.env` separately in an encrypted secret store. The dump contains user data and encrypted integration credentials; treat both the dump and keys as sensitive. Copy backups off the host and periodically test restoration.

Restore into a **new, empty** Compose deployment, with its own project name and volume, after placing the original encryption/signing keys into that deployment's private configuration. Stop API/worker/scheduler/web writers before restore. The restore command refuses a nonempty database:

```sh
python scripts/backup.py restore --input backups/flowsentry.dump --project flowsentry-restore
docker compose -p flowsentry-restore up -d
```

The script requires the target PostgreSQL container to be running and does not create infrastructure, delete data, or restore configuration secrets. Never point a restore at the source deployment.

## Retention

The scheduler clears processed inbound payloads after 30 days while preserving deduplication metadata, and removes terminal executions older than 90 days only when they are not incident/recovery evidence. Pending events are retained. Published outbox rows expire after seven days and health snapshots after 90 days. Each pass is bounded. The backend environment can override `RETENTION_EVENT_PAYLOAD_SECONDS` and `RETENTION_EXECUTION_SECONDS` (minimum one day); add them to a Compose override if needed. Evidence attached to incidents is retained until a separate explicit policy is implemented.

## Failure recovery

Accepted ingestion events are committed with outbox work before the API responds. Restarting containers preserves these rows. Leases expire and jobs are reclaimed; poison events reach a recorded dead-letter state after bounded attempts. Inspect database-backed event/job state and logs before replaying. Never delete dedupe records to force a retry. Polling reconciles saved n8n executions; events for executions not saved by n8n can only come from the Error Workflow.
