#!/usr/bin/env python3
"""One-off CLI fetch, useful for running via an external cron job instead of
(or alongside) the in-process scheduler.

Usage:
    python scripts/fetch_now.py [--terms 25,24] [--no-process] [--limit 25]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db  # noqa: E402
from app.ingest import run_fetch  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", help="Comma-separated term codes, e.g. 25,24")
    parser.add_argument(
        "--no-process", action="store_true", help="Only update listings, skip PDF text/summary extraction"
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="Max new documents to process per document type"
    )
    args = parser.parse_args()

    terms = [t.strip() for t in args.terms.split(",")] if args.terms else None

    init_db()
    result = run_fetch(terms=terms, process_documents=not args.no_process, document_limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
