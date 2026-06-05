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

## Docker

```powershell
docker compose up --build
```
