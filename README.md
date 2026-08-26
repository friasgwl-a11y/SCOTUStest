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
  streaming each download to a temp file. Orders read the first
  `SCOTUS_MAX_PDF_PAGES` pages; opinions read up to
  `SCOTUS_OPINION_MAX_PDF_PAGES` (much larger by default), since a case's
  concurrences and dissents can run well past the syllabus alone.
- **Reproduces the Court's own syllabus, and every concurrence/dissent,
  verbatim** for opinions that have them (`app/summarizer.py`), rather
  than summarizing them further: the Reporter of Decisions' syllabus is
  already an authoritative, condensed statement of the facts, question,
  and holding, and a Justice's separate opinion is that Justice's own
  words -- re-summarizing either can only lose accuracy, not add any.
  Opinions also carry the Court's own one-line holding (scraped from the
  case-name link's `title` attribute) as a quick lead-in above the full
  syllabus. Each is shown as a preview with a "Read more" link to its own
  full-text page, so the case detail page stays scannable.
  - Each Justice's concurrence/dissent is located in the PDF text **by
    name**, using the Granted & Noted List's own concurrence/dissent
    breakdown (see below) as the ground truth for who wrote what --
    not by guessing at heading text blindly. The two data sources can
    land at different times (the PDF is processed as soon as it's
    scraped; the Granted & Noted List match can arrive earlier or later),
    so this runs opportunistically whenever an opinion is read back out
    and backfills once both are on hand, without ever re-downloading the
    PDF (`ensure_separate_opinions` in `app/ingest.py`).
  - **Falls back to a generated summary** only when there's no syllabus to
    show -- most orders, and the rare short per curiam opinion. A
    dependency-free extractive summarizer (word-frequency sentence
    scoring) always works offline; if `ANTHROPIC_API_KEY` is set, it's
    upgraded to a real abstractive summary from Claude instead, with any
    failure falling back to the extractive summary silently.
  - Orders are flagged **notable** when their text mentions a dissent,
    concurrence, separate statement, or a grant/stay of certiorari.
- **Stores** everything in SQLite (`app/models.py`), so re-running a fetch
  only downloads/processes documents it hasn't seen before.
- **Tracks term-level context** (`app/term_scraper.py`, `app/term_ingest.py`):
  - Which term the Court's own site currently labels the "Current Term"
    (no date-guessing), plus a granted-case count for it and for next term,
    parsed from the Court's own **Granted & Noted List** PDF.
  - **Majority author and a per-Justice concurrence/dissent breakdown**
    for each opinion, also parsed from the Granted & Noted List rather
    than inferred from opinion text -- the Court's own document already
    states e.g. `Author: J. Kavanaugh` / `Other: Thomas (C); Jackson (D)`
    per case, which is far more reliable. Docket numbers are normalized
    (`app/dockets.py`) before matching, since the Granted & Noted List
    annotates them with flags (`*`, `#`, `)1`) that the opinion listing
    doesn't carry -- matching the raw annotated form silently missed and
    left author/dissent metadata blank. Every tracked term is matched
    this way, not just the current and next one.
  - Every opinion card and its detail page shows this as a **9-pixel
    "bench" graphic** -- one square per seat on the Court, colored by
    vote (author/concurrence/dissent/joined-in-full) -- built entirely
    from the author + concurrence/dissent breakdown already fetched
    above. There's no roster of sitting Justices anywhere in this app
    (one would go stale on its own), so any seat not otherwise
    identified is shown as a plain "joined in full" square rather than
    guessing who occupies it.
  - The next upcoming oral argument day, with case names and docket
    numbers, parsed from the Court's monthly **Argument Calendar** PDFs.
  - The **question(s) presented** for every case in a term's Granted &
    Noted List, fetched from the Court's per-docket "Questions Presented"
    PDF (`app/qp_scraper.py`) at a URL built directly from the docket
    number -- no per-case page scraping needed. Reachable by clicking the
    granted-case count on the home page.
  - Refreshed independently of opinions/orders, at most every
    `SCOTUS_TERM_DATA_REFRESH_HOURS` (default 12), since this changes far
    less often.
- **Partitions "quick reference" from "look back further"**: Opinions
  default to a **Recent** view (last `SCOTUS_RECENT_OPINION_DAYS` days,
  default 30), with **This Term** and **Past Terms** one click away.
  Orders default to the **current term only** -- old order lists don't
  gain new entries once a term ends, so they'd otherwise just be noise --
  with older terms reachable via the term dropdown. The point: the
  dashboard's job is "what did the Court just do," not an archive browser,
  though the archive is fully there when you want it.
- **Serves** a REST API (`app/api/routes.py`) and a dashboard (`static/`)
  with real client-side routing (Home / Opinions / Orders / a full detail
  page per case / Questions Presented, each a real URL — not a popup),
  search/filter/sort, a
  "Refresh now" button, and an in-process scheduler that re-fetches
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
| `SCOTUS_TERM_DATA_REFRESH_HOURS` | `12` | How often to re-fetch the current-term label, Granted & Noted List, and argument calendars |
| `SCOTUS_QP_FETCH_LIMIT` | `20` | Max Questions Presented PDFs fetched per term, per refresh cycle |
| `SCOTUS_RECENT_OPINION_DAYS` | `30` | How many days back the Opinions "Recent" view covers |
| `SCOTUS_OPINION_MAX_PDF_PAGES` | `100` | Pages read per opinion PDF (large enough to reach concurrences/dissents) |
| `SCOTUS_OPINION_MAX_STORED_TEXT_CHARS` | `500000` | Cap on extracted text stored per opinion |

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
- `GET /api/term-summary` — current/next term labels and granted-case counts
- `GET /api/argument-calendar?days=` — next N upcoming argument days with cases
- `GET /api/questions-presented?term=` — every QP fetched so far for a term
- `GET /api/opinions?term=&scope=&justice=&q=&has_dissent=&sort=&limit=&offset=` — list opinions
  (`sort` is one of `date_desc`, `date_asc`, `author`, `docket`; `scope` is
  `recent` (last `SCOTUS_RECENT_OPINION_DAYS` days), `term` (current term),
  or omitted for no date/term restriction beyond an explicit `term=`)
- `GET /api/opinions/{id}` — full opinion detail, including the full
  syllabus and each `separate_opinion_texts` entry (`author`, `code`,
  `label`, `text`) verbatim
- `POST /api/opinions/{id}/summarize` — generate this opinion's summary now (idempotent)
- `GET /api/orders?term=&order_type=&notable=&q=&limit=&offset=` — list orders
- `GET /api/orders/{id}` — full order detail
- `POST /api/orders/{id}/summarize` — generate this order's summary now (idempotent)
- `GET /api/fetch-runs` — recent fetch run history
- `POST /api/refresh` — trigger an immediate fetch in the background

Every other path (e.g. `/`, `/opinions`, `/opinion/123`,
`/opinion/123/syllabus`, `/opinion/123/separate/0`) serves the dashboard
shell — it's a single-page app with client-side routing, so a direct link
or a page refresh on any of those URLs works correctly.

## Project layout

```
app/
  scraper.py        # HTML parsing of the opinions/orders listing pages
  term_scraper.py    # Current-term label, Granted & Noted List, argument calendars
  qp_scraper.py       # Questions Presented PDFs (URL built from docket number)
  dockets.py          # Normalizes docket numbers (strips list-legend/consolidation flags)
  votes.py            # Parses the Granted & Noted List's "Other:" concurrence/dissent codes
  pdf_extract.py     # PDF download + text extraction
  summarizer.py       # Boilerplate stripping, syllabus + separate-opinion extraction, summarization
  ingest.py           # Orchestrates scrape -> store -> extract -> summarize
  term_ingest.py      # Orchestrates term-level data refresh + caching
  models.py           # SQLAlchemy models (Opinion, Order, FetchRun, TermSummary,
                       #   ArgumentEntry, QuestionPresented, SeparateOpinionText)
  scheduler.py        # Background periodic fetch
  api/routes.py       # REST API
  main.py             # FastAPI app entrypoint + SPA-fallback routing
static/               # Single-page dashboard (client-side router in app.js)
scripts/fetch_now.py  # CLI for a one-off fetch
tests/                # Unit tests (fixtures = real saved HTML/PDF from the Court's site)
```

## Memory behaviour (running on a small/free instance)

Free hosting tiers typically cap a service at 512MB, and PDF parsing is by
far the most memory-hungry thing here. The design keeps peak usage around
**80MB** measured end-to-end for orders (full scrape of both listing pages
plus several summaries); a single long opinion with concurrences/dissents
can push its own peak higher (still comfortably under budget -- see below),
but only one document is ever read at a time:

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
- **Page cap.** Orders read the first `SCOTUS_MAX_PDF_PAGES` (default 20)
  pages. Opinions read up to `SCOTUS_OPINION_MAX_PDF_PAGES` (default
  100) -- much larger, since concurrences/dissents (reproduced verbatim)
  can run well past the syllabus at the front. Measured at ~0.5MB RSS per
  page with pypdf, so even a 100-page opinion stays well under budget;
  it's still one document at a time (below), so this raises one case's
  peak, not the ceiling.
- **Downloads stream to a temp file**, so raw PDF bytes never sit in RAM.
- **One document at a time.** A process-wide lock serializes extraction,
  so concurrent visitors can't multiply peak memory.
- **One web worker**, since a second would double the ceiling without
  helping on a free instance.

If you still hit the limit, the strongest knobs are
`SCOTUS_AUTO_PROCESS_DAYS=0`, a lower `SCOTUS_OPINION_MAX_PDF_PAGES`, and
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
- **Next conference day and next opinion-release day are not tracked.**
  The Court doesn't publish these as text anywhere found -- only as colors
  on a calendar graphic (a static PDF, and an interactive JS calendar
  widget that loads each month's data via an ASP.NET AJAX callback). That
  isn't reliably scrapable, so rather than guess or build something
  fragile, this is intentionally left out. Argument days, by contrast,
  *are* published as plain text (the monthly Argument Calendar PDFs) and
  are tracked.
- The argument-calendar parser has one known cosmetic gap: when two cases
  share a single calendar slot (consolidated for one hour of argument),
  their docket/case-name text isn't split back into two separate entries.
  Rare in practice; see the comment in `app/term_scraper.py`.
- Some slip opinions' PDF fonts don't map the "fi"/"ffi" ligature glyph
  back to plain text, so pypdf occasionally drops or splits a letter in
  words like "officials" or "five" (e.g. "offcials", "fve"). This is a
  font-encoding quirk of the source PDF, not a bug in the extracted
  boundaries -- the reproduced syllabus text is otherwise verbatim. Read
  the linked PDF for anything where the exact wording matters.
- Concurrences/dissents are located by author name, matched against the
  Granted & Noted List's own breakdown -- reliable for *which* Justices
  wrote separately, but a Justice not found in the extracted text (most
  often because a very long case's dissent falls past
  `SCOTUS_OPINION_MAX_PDF_PAGES`/`SCOTUS_OPINION_MAX_STORED_TEXT_CHARS`)
  is silently omitted rather than shown incorrectly. Read the linked PDF
  if a separate opinion you expect isn't there.
