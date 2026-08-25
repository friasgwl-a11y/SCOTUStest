"""Normalize Supreme Court docket numbers.

The Granted & Noted List annotates dockets with typographic flags that
are *not* part of the docket itself:

  *    list-legend flag (often a per-curiam / unsigned decision)
  #    list-legend flag
  )    a stray closing paren from PDF line wrapping
  )N   consolidated companion marker, e.g. "24-1021)1"
  )N*  both of the above

Opinion listing pages, Questions Presented URLs, and the Court's own
docket pages all use the clean form ("24-171", "25A312"). Matching the
raw annotated form against those sources silently misses, which is why
majority-author / concurrence / dissent metadata never attached.
"""

from __future__ import annotations

import re

# Strip one trailing annotation. Applied in a loop so stacked markers
# like ")1*" collapse in a single pass without a brittle combined regex.
_TRAILING_FLAG_RE = re.compile(r"(?:\)\d+|\))[*#]*|[*#]+$")


def normalize_docket(raw: str | None) -> str:
    """Return the canonical docket ("24-171", "25A312"), or "" if empty."""
    if not raw:
        return ""
    docket = re.sub(r"\s+", "", raw)
    while True:
        cleaned = _TRAILING_FLAG_RE.sub("", docket)
        if cleaned == docket:
            return docket
        docket = cleaned
