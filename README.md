# SCOTUS Tracker

A self-hosted dashboard that tracks the Supreme Court of the United States'
opinions and orders: it scrapes them directly from supremecourt.gov,
downloads and extracts the text of each PDF, generates a summary, and
presents everything in a searchable, filterable web dashboard.

## What it does

- **Scrapes** the Court's opinions (`/opinions/slipopinion/{term}`) and
  orders (`/orders/ordersofthecourt/{term}`) listing pages for one or more
  terms. There is no JSON/RSS feed for this data, so the HTML is parsed
  directly (see `app/scraper.py` for the exact markup this relies on).
- **Downloads and extracts** PDF text (`app/pdf_extract.py`, via `pypdf`),
  streaming each download to a temp file and reading only the first
  `SCOTUS_MAX_PDF_PAGES` pages.
- **Summarizes** each document (`app/summarizer.py`):
  - Opinions carry the Court's own one-line syllabus/holding (scraped from
    the case-name link's `title` attribute) for free.
  - A dependency-free extractive summarizer (word-frequency sentence
    scoring) runs on the syllabus or full text and always works offline.
  - If `ANTHROPIC_API_KEY` is set, summaries are upgraded to a real
    abstractive summary from Claude instead; any failure falls back to the
    extractive summary silently.
  - Orders are flagged **notable** when their text mentions a dissent,
    concurrence, separate statement, or a grant/stay of certiorari.
- **Stores** everything in SQLite (`app/models.py`), so re-running a fetch
  only downloads/processes documents it hasn't seen before.
- **Serves** a REST API (`app/api/routes.py`) and a static dashboard
  (`static/`) for browsing, searching, and filtering opinions and orders,
  with a "Refresh now" button and an in-process scheduler that re-fetches
  periodically.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # optional, defaults work out of the box

uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/ — on first run the server kicks off a
background fetch (scrape listings + process a batch of PDFs), so the
dashboard will start empty and fill in over the next minute or so. Refresh
the page, or hit "Refresh now."

### Configuration

All settings are environment variables with defaults (see
`.env.example` and `app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `SCOTUS_TERMS` | `25,24` | Comma-separated term codes to track (`25` = OT2025) |
| `SCOTUS_FETCH_INTERVAL_MINUTES` | `180` | Background re-fetch cadence |
| `SCOTUS_FETCH_ON_STARTUP` | `true` | Run a fetch immediately at startup |
| `SCOTUS_DATA_DIR` | `./data` | Where the SQLite DB file lives |
| `ANTHROPIC_API_KEY` | unset | Enables Claude-generated summaries |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Model used for summaries |
| `SCOTUS_REQUEST_DELAY_SECONDS` | `1.0` | Delay between requests to the Court's site |

A single fetch caps how many new PDFs it processes per run (25 by default,
see `document_limit` in `app/ingest.py`) so it stays fast; any backlog
drains over subsequent scheduled runs.

### Manual / cron-driven fetch

Instead of (or alongside) the in-process scheduler, you can run a fetch
as a one-off command, e.g. from an external cron job:

```bash
python scripts/fetch_now.py --terms 25,24 --limit 50
```

## API

- `GET /api/stats` — counts, latest activity, last fetch run, tracked terms
- `GET /api/opinions?term=&justice=&q=&limit=&offset=` — list opinions
- `GET /api/opinions/{id}` — full opinion detail including extracted text
- `GET /api/orders?term=&order_type=&notable=&q=&limit=&offset=` — list orders
- `GET /api/orders/{id}` — full order detail including extracted text
- `GET /api/fetch-runs` — recent fetch run history
- `POST /api/refresh` — trigger an immediate fetch in the background

## Project layout

```
app/
  scraper.py      # HTML parsing of the opinions/orders listing pages
  pdf_extract.py  # PDF download + text extraction
  summarizer.py    # Boilerplate stripping, syllabus extraction, summarization
  ingest.py        # Orchestrates scrape -> store -> extract -> summarize
  models.py        # SQLAlchemy models (Opinion, Order, FetchRun)
  scheduler.py     # Background periodic fetch
  api/routes.py    # REST API
  main.py          # FastAPI app entrypoint
static/            # Vanilla HTML/CSS/JS dashboard
scripts/fetch_now.py  # CLI for a one-off fetch
tests/             # Scraper + summarizer unit tests (fixtures = real HTML)
```

## Memory behaviour (running on a small/free instance)

Free hosting tiers typically cap a service at 512MB, and PDF parsing is by
far the most memory-hungry thing here. The design keeps peak usage around
**80MB** measured end-to-end (full scrape of both listing pages plus
several summaries):

- **`pypdf`, not `pdfplumber`.** Measured on the same 77-page slip
  opinion, pdfplumber peaked at ~354MB and pypdf at ~39MB. pdfplumber's
  layout/table analysis is what costs that; we only need plain text.
- **Lazy summarization.** Only documents released within
  `SCOTUS_AUTO_PROCESS_DAYS` (default 1) are summarized in the background.
  Everything else is summarized the first time someone opens it, then
  cached. Set `SCOTUS_AUTO_PROCESS_DAYS=0` for fully-on-demand.
- **Opinions read well before summarizing.** The Court's own one-line
  holding is scraped from the listing page, so the list is informative
  with zero PDFs downloaded.
- **Page cap.** Only the first `SCOTUS_MAX_PDF_PAGES` (default 20) pages
  are read; a slip opinion's syllabus and holding are at the front.
- **Downloads stream to a temp file**, so raw PDF bytes never sit in RAM.
- **One document at a time.** A process-wide lock serializes extraction,
  so concurrent visitors can't multiply peak memory.
- **One web worker**, since a second would double the ceiling without
  helping on a free instance.

If you still hit the limit, the strongest knobs are
`SCOTUS_AUTO_PROCESS_DAYS=0`, a lower `SCOTUS_MAX_PDF_PAGES`, and
`SCOTUS_TERMS=25` (one term instead of two).

## Deploying so you can view it from a phone/browser anywhere

This app needs a server; running it only on your own laptop means only
that laptop can open it. The included `render.yaml` lets you deploy it to
[Render](https://render.com) in a few clicks:

1. Sign in at render.com (free account, GitHub login works).
2. **New** -> **Blueprint**, pick this repo and the `claude/scotus-dashboard-gccq2j`
   branch. Render reads `render.yaml` and configures the service automatically.
3. Click **Apply** / **Create**. The first build takes a few minutes.
4. Once it says "Live," open the `https://<something>.onrender.com` URL —
   that link works from any device, including your phone.

Notes:
- Render's free tier spins the service down after inactivity; the first
  request after a while will be slow while it wakes back up.
- The free tier's disk is not persistent across deploys/restarts, so the
  SQLite database (and everything fetched so far) resets when that
  happens. For a demo this is fine — hit "Refresh now" and it repopulates
  in a minute or two. For a permanent deployment, add a persistent disk
  (paid plan) or point `SCOTUS_DATABASE_URL` at an external database.

## Testing

```bash
pip install -r requirements.txt
pytest
```

Scraper tests run against saved real HTML fixtures in `tests/fixtures/`, so
they don't hit the network.

## Notes & limitations

- This scrapes public HTML pages that Court staff can restructure without
  notice; if the site's markup changes, `app/scraper.py` will need updating
  (its docstring records the exact structure it was built against).
- The offline extractive summarizer is a reasonable approximation, not a
  substitute for reading the opinion. Always check the linked PDF for
  anything that matters.
- Be a good citizen: the default request delay/timeout are intentionally
  conservative. Don't crank up fetch frequency or parallelism against
  supremecourt.gov.
