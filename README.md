# AI Leads Tracker

A FastAPI-based lead ingestion and campaign application that collects leads, enriches them, sends email campaigns, and tracks replies.

## Features

- FastAPI backend with templated UI dashboards
- Google Places lead ingestion support
- Lead verification, email normalization, and duplicate suppression
- SMTP campaign sending with delivery tracking
- IMAP reply polling stub for reply tracking
- Celery background worker support with Redis
- PostgreSQL support via SQLModel and Alembic migrations

## Quick Start

1. Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

3. Copy the example environment file:

```powershell
copy .env.example .env
```

4. Update `.env` with your values.

5. Run the application locally:

```powershell
uvicorn app.main:app --reload
```

6. Open the app in your browser at `http://127.0.0.1:8000`.

## Environment Variables

Required values in `.env`:

- `DATABASE_URL` - database connection string
- `SESSION_SECRET` - session signing secret
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`
- `GOOGLE_PLACES_API_KEY` (optional for Google lead lookup)

Optional values:

- `REDIS_URL` - Redis URL for Celery
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` - Google OAuth
- `FORCE_HTTPS` - `true`/`false`
- `SESSION_SECURE_COOKIE` - `true`/`false`
- `ADMIN_EMAIL` - admin login email

## Local Development

- `uvicorn app.main:app --reload` starts the web server.
- Use `alembic upgrade head` after updating models.
- `celery -A celery_tasks.celery worker --loglevel=info` starts a Celery worker.
- `docker-compose up --build` can start the app with Redis if configured.

## API Endpoints

- `GET /health` — health check
- `GET /` — homepage
- `GET /dashboard` — admin dashboard
- `GET /login` and `POST /login` — login flow
- `POST /leads/fetch` — fetch leads from Google Places
- `GET /leads` — list leads
- `GET /campaigns` — list campaigns
- `GET /campaigns/{campaign_id}` — campaign details
- `GET /campaigns/{campaign_id}/replies` — campaign replies
- `POST /campaigns/send` — send campaign emails

## Testing

Run the repository tests with:

```powershell
pytest -q
```

## GitHub Actions

This repository includes GitHub Actions workflows for:

- `ci.yml` — install dependencies, run migrations, and execute tests on `main` and `master`
- `deploy.yml` — build and publish a Docker image to GitHub Container Registry on `main`/`master`
- `pages.yml` — publish `docs/` to GitHub Pages on `main`/`master`

## Deployment

### Docker

The `deploy.yml` workflow builds and pushes the Docker image to GitHub Container Registry at `ghcr.io/<owner>/<repo>`.

### Fly.io

This repository includes a `fly.toml` configuration and a GitHub Actions workflow at `.github/workflows/fly-deploy.yml`.

To deploy on Fly.io:

1. Create a Fly app:
   ```powershell
   flyctl apps create ai-leads-tracker
   ```
2. Set required secrets in GitHub:
   - `FLY_API_TOKEN`
   - `DATABASE_URL`
   - `REDIS_URL`
   - `SESSION_SECRET`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`
   - `GOOGLE_PLACES_API_KEY`
3. Push to `main` or `master` and the workflow will deploy automatically.

### Production

- Use PostgreSQL instead of SQLite.
- Set `FORCE_HTTPS=true` and `SESSION_SECURE_COOKIE=true`.
- Run `alembic upgrade head` before starting.
- Host the app on Render, Railway, Fly.io, or similar.

### Supabase

This app supports Supabase Postgres as the database provider. Set `DATABASE_URL` to your Supabase connection string, for example:

```powershell
DATABASE_URL="postgresql://postgres:<password>@<project-ref>.db.supabase.co:5432/postgres"
```

When using Supabase:

- Use a separate Redis provider and set `REDIS_URL`.
- Keep `SESSION_SECRET` secure.
- Configure `SMTP_*` values for email sending.
- Run `alembic upgrade head` after deployment.

## Notes

- The repo currently stores a local SQLite database by default unless `DATABASE_URL` is set.
- The `templates/` and `static/` directories provide the dashboard UI and form flows.
- The `enrich/` folder contains helper stubs for lead enrichment.

## Useful Commands

```powershell
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
pytest -q
```
