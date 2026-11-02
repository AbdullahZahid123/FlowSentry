# Development

Use Node 24, Python 3.13+, PostgreSQL 17, and Docker Compose. Frontend dependencies are locked in `frontend/package-lock.json`; backend dependencies are locked in `backend/requirements.lock`.

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
pip install -r backend/requirements.lock
cd frontend
npm ci
npm run dev
```

Copy `backend/.env.example` to `backend/.env`, generate your own secrets, set `DATABASE_URL`, then from `backend` run:

```sh
python -m app.cli migrate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Set `FLOWSENTRY_API_URL=http://127.0.0.1:8000` in `frontend/.env.local`. API requests go through the frontend's same-origin proxy. Development can use the embedded worker; Docker runs separate worker/scheduler processes.

## Checks

```sh
python -m pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
npm audit --omit=dev
```

Backend tests create and drop an isolated random PostgreSQL database. Set `TEST_POSTGRES_ADMIN_URL` to an administrative test-only database URL (default `postgresql://postgres@127.0.0.1:54321/postgres`). Never run them with a production administrative credential. Tests do not use application tables in your normal database.

Review mobile, tablet, and desktop layouts in both themes. Check keyboard focus, Escape/return focus in dialogs, loading/error/empty states, and interactions with real API responses. Marketing samples must be labeled. Prefer shared shadcn primitives and semantic theme variables; no invented uptime/customer claims or placeholder controls.

Database changes require an Alembic revision and a fresh-install/upgrade test. Keep secrets, real execution payloads, and local diagnostic screenshots out of source control. Reviewed documentation screenshots may be added to `docs/assets` only when they contain synthetic sample data. Do not enable provider recovery without a verified public operation and durable state transitions.
