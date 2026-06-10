# News Parser API

Backend API and background worker scaffold for news scraping.

## Local Development

1. Copy `.env.example` to `.env` and adjust values if needed.
2. Install dependencies:

```powershell
uv sync
```

3. Run the API:

```powershell
uv run uvicorn app.main:app --reload
```

For local scripts outside Docker, use a local Redis URL:

```powershell
$env:REDIS_URL="redis://localhost:6379/0"
uv run python scripts/parse_tasnim_latest.py
```

## Docker

```powershell
docker compose up --build
```
