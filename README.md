# ReviewBot

ReviewBot is a GitHub App that accepts signed pull-request webhooks, queues work
in Redis/RQ, fetches the PR's unified diff through the GitHub API, prepares that
diff deterministically, and runs a local fake review provider. It posts aggregate
dry-run counts only; finding contents and inline review comments are not posted.

## Current architecture

```text
GitHub pull request
  -> signed webhook
  -> FastAPI (main.py)
  -> Redis/RQ queue
  -> worker.review_pull_request (worker.py)
  -> GitHub API diff fetch
  -> deterministic review preparation (review/)
  -> FakeReviewProvider
  -> deterministic finding validation and caps
  -> GitHub issue comment
```

The current milestone adds a provider contract and deterministic dry-run
orchestration. Phase 1 remains authoritative for parsing, exact coordinates,
file eligibility, input budgets, semantic validation, and duplicate handling.
The fake provider has no network access, API key, or environment configuration.
Its synthetic findings are fixtures, not detected defects.

A future hosted-provider adapter must treat raw response text or JSON as
untrusted, enforce response byte and item limits, and parse it inside the adapter.
Malformed output must not cross the adapter boundary. Only successfully parsed
strict `FindingCandidate` domain objects may enter orchestration.

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

No AI-provider API key is required or supported in this milestone.

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
- The current provider is deterministic fake data; it does not detect real bugs.
- Findings are validated and counted but their contents are not posted.
- Inline GitHub review comments and review decisions are not implemented.
- Provider failure degrades to a safe aggregate summary without retry or an
  agent loop.
- Future milestones may add a bounded hosted-provider adapter, followed
  separately by inline-review delivery and production deployment.
