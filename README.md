AI Leads Tracker

Quickstart

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and set your keys (Google Places API key, SMTP creds, IMAP creds).

3. Run the app:

```bash
uvicorn app.main:app --reload
```

Overview

- `app/` contains the FastAPI application, services, and models.
- `app/services/google_places.py` fetches leads from Google Places when `GOOGLE_PLACES_API_KEY` is set.
- `app/services/leads.py` enriches, verifies, normalizes, and debounces Google lead results.
- `app/services/emailer.py` sends campaigns via SMTP and tracks retry attempts.
- `app/services/imap_tracker.py` provides a reply polling stub for IMAP.
- `enrich/` contains enrichment and validation helper stubs.

API endpoints

- `GET /health` — health check.
- `POST /leads/fetch` — fetch leads from Google Places and save verified/enriched leads.
- `GET /leads` — list all saved leads.
- `GET /dashboard` — UI dashboard for lead and campaign management.
- `GET /campaigns` — list campaigns and status metadata.
- `GET /campaigns/{campaign_id}` — retrieve campaign details.
- `GET /campaigns/{campaign_id}/replies` — view tracked replies for a campaign.
- `POST /campaigns/send` — send an SMTP campaign to saved leads with email addresses.

Status transitions

- `draft` — campaign is created but not yet sent.
- `sending` — campaign send process is underway.
- `sent` — campaign emails were successfully delivered.
- `partial` — campaign delivered to some recipients but with failures.
- `failed` — campaign failed to deliver.

Notes

This scaffold now includes practical lead ingestion flows and campaign logging. Next integration work can add real enrichment providers, IMAP reply mapping, and a UI/dashboard.

Background worker

- To process sends and IMAP work reliably in production, a Celery worker with Redis is supported.
- To run locally with Redis (requires Redis installed or use Docker):

```bash
redis-server &
celery -A celery_tasks.celery worker --loglevel=info
```

Or with Docker Compose:

```bash
docker-compose up --build
```

Production deployment

- Set `DATABASE_URL` to a production database, for example:
  `postgresql+psycopg2://user:pass@db:5432/leads_db`
- Set `SESSION_SECRET` to a strong random value.
- Set `SESSION_SECURE_COOKIE=true` and `FORCE_HTTPS=true` in production.
- Run database migrations before starting:

```bash
alembic upgrade head
```

Supabase Postgres support

- Supabase can be used as the Postgres database provider for this app.
- Supabase does not host Python or Celery, so you still need a separate app host such as Fly.io, Render, Railway, or Heroku.
- Set `DATABASE_URL` to the Supabase connection string prepared in the Supabase project settings.
- Use an external Redis service for `REDIS_URL` because Supabase does not provide Redis.
- Example Supabase-compatible database URL:
  `postgresql://postgres:<password>@<project-ref>.db.supabase.co:5432/postgres`

Production-ready recommendations

- Use PostgreSQL instead of SQLite.
- Run the app with a process manager or via Gunicorn/Uvicorn workers.
- Configure SMTP credentials and an email provider with bounce handling.
- Use HTTPS and secure session cookies.

Supabase Postgres + Render/Railway

- Use Supabase only as the Postgres provider (`DATABASE_URL`).
- Use an external Redis provider for `REDIS_URL` such as Upstash, Redis Cloud, or a managed Redis instance.
- Deploy the Python app to a container-friendly host like Render or Railway.
- Example host setup:
  1. Create a new service on Render/Railway.
  2. Connect your GitHub repo.
  3. Set the start command to:
     `gunicorn -k uvicorn.workers.UvicornWorker app.main:app -b 0.0.0.0:$PORT`
  4. Set environment variables:
     - `DATABASE_URL` → Supabase connection string
     - `REDIS_URL` → Redis provider URL
     - `SESSION_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_PLACES_API_KEY`, `FORCE_HTTPS=true`, `SESSION_SECURE_COOKIE=true`
  5. Run `alembic upgrade head` after deployment if your host supports one-time commands.
- This lets Supabase handle the database while Render/Railway hosts the FastAPI app and serves web traffic.

Hosting on cPanel

1. Verify your cPanel account supports Python apps and a virtual environment.
2. Upload the repository files to a directory under your cPanel account.
3. In cPanel, open "Setup Python App" and create a new app using Python 3.11.
4. Set the app directory to your project folder and install dependencies from `requirements.txt`.
5. Create a `.env` file in the project root with production values.
6. Set `DATABASE_URL` to your cPanel database (MySQL/PostgreSQL) and update `app/main.py` if needed.
7. In cPanel, start the Python app; it will serve via the cPanel passenger gateway.
8. Use cPanel’s MySQL/PostgreSQL manager to create the database, then run `alembic upgrade head` via SSH if available.

Hosting on GitHub

1. Push the repository to a GitHub repo.
2. Add `.github/workflows/deploy.yml` or use GitHub Actions for CI/CD.
3. For GitHub Pages, only static frontend is supported; this app needs a server host.
4. To host from GitHub, connect with a hosting provider like Render, Fly.io, Railway, or Heroku.
5. Configure the service to deploy from the GitHub repo and set environment variables.
6. Enable build commands:
   - `pip install -r requirements.txt`
   - `alembic upgrade head`
   - `gunicorn -k uvicorn.workers.UvicornWorker app.main:app -b 0.0.0.0:$PORT`

Fly.io deployment

1. Make sure you are logged in with `fly auth login`.
2. Create or select an app:
   ```bash
   fly apps create ai-leads-tracker
   ```
3. If you already created the app manually, use `fly launch --no-deploy --name ai-leads-tracker --dockerfile Dockerfile`.
4. Set the required secrets:
   ```bash
   fly secrets set \
     DATABASE_URL="postgresql://..." \
     REDIS_URL="redis://..." \
     SESSION_SECRET="your-strong-secret" \
     SMTP_HOST="..." \
     SMTP_PORT="587" \
     SMTP_USERNAME="..." \
     SMTP_PASSWORD="..." \
     SMTP_FROM="Your Name <you@example.com>" \
     GOOGLE_CLIENT_ID="..." \
     GOOGLE_CLIENT_SECRET="..." \
     GOOGLE_PLACES_API_KEY="..." \
     FORCE_HTTPS=true \
     SESSION_SECURE_COOKIE=true
   ```
5. Deploy:
   ```bash
   fly deploy
   ```
6. Open your app:
   ```bash
   fly open
   ```

Fly worker (optional)

If you want Celery worker support, create a second Fly app for the worker and deploy it with the command:
```bash
fly apps create ai-leads-worker
fly deploy --config fly-worker.toml
```


1. Create a GitHub repo and push the code.
2. Ensure GitHub Container Registry is enabled for your account.
3. The workflow in `.github/workflows/deploy.yml` publishes Docker images to `ghcr.io/<owner>/<repo>:latest`.
4. On your deployment host, pull `ghcr.io/<owner>/<repo>:latest` and run it with the proper env vars.
5. Use the same database and SMTP env vars as defined in `.env.example`.

GitHub Pages static preview

1. The `docs/` directory now contains a static landing page preview.
2. The workflow in `.github/workflows/pages.yml` publishes this preview to GitHub Pages whenever `main` is pushed.
3. Enable Pages in the repository settings and choose the `gh-pages` branch.
4. The live preview will show the marketing landing page, not the backend app.

CSV import preview

- Use the "Preview CSV" button on the dashboard to upload a CSV and see a sample of rows plus duplicate detection before importing.
