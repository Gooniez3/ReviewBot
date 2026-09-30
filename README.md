# ReviewBot

ReviewBot is a GitHub App that accepts signed pull-request webhooks, queues work
in Redis/RQ, fetches the PR's unified diff through the GitHub API, prepares that
diff deterministically, and posts a summary comment. AI review and inline review
comments are intentionally not enabled yet.

## Current architecture

```text
GitHub pull request
  -> signed webhook
  -> FastAPI (main.py)
  -> Redis/RQ queue
  -> worker.review_pull_request (worker.py)
  -> GitHub API diff fetch
  -> deterministic review preparation (review/)
  -> GitHub issue comment
```

The current milestone parses unified diffs, maps exact line coordinates, filters
non-reviewable files, applies explicit input budgets, prepares chunks on file and
hunk boundaries, and validates synthetic finding candidates. It does not call an
AI provider or create GitHub inline review payloads.

## Local prerequisites

- Windows PowerShell
- Python 3.12 and a virtual environment at `.venv`
- Docker Desktop (for the documented Redis command), or another Redis server
- ngrok for receiving GitHub webhooks during local development
- A configured GitHub App

Install Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start Redis with Docker:

```powershell
docker run --name reviewbot-redis --rm -p 6379:6379 redis:7-alpine
```

Start FastAPI on port 8001 in a second PowerShell window:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --env-file .env --host 127.0.0.1 --port 8001
```

Start the RQ worker in a third PowerShell window:

```powershell
& ".\.venv\Scripts\dotenv.exe" run -- `
  ".\.venv\Scripts\rq.exe" worker `
  --url redis://localhost:6379 `
  --worker-class rq.worker.SimpleWorker `
  reviews
```

`SimpleWorker` is the native-Windows local-development worker. A production
deployment should later use an appropriate RQ worker on Linux.

Expose FastAPI in a fourth PowerShell window:

```powershell
ngrok http 8001
```

Configure the GitHub App webhook URL as the ngrok HTTPS URL followed by
`/webhook`.

## Environment variables

Create `.env` locally from `.env.example`. The required variable names are:

- `GITHUB_APP_ID`
- `GITHUB_WEBHOOK_SECRET`
- `GITHUB_PRIVATE_KEY`
- `REDIS_URL`

Never commit `.env`, a `.pem` private key, installation tokens, or webhook
secret values.

## Tests

Run the complete deterministic suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

## Current limitations and roadmap

- Deleted-only files, binary files, generated output, lock files, and combined
  merge diffs are skipped with explicit reasons.
- Oversized input is skipped at deterministic file or hunk boundaries; code is
  not silently truncated.
- Finding validation exists, but no model currently generates findings.
- Inline GitHub review comments are not implemented.
- Future milestones may add a provider abstraction and structured analysis,
  followed separately by inline-review delivery and production deployment.
