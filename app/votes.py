"""Parse the Granted & Noted List's "Other:" field into structured votes.

That field is the Court's own per-Justice concurrence/dissent breakdown,
e.g. "Thomas (C); Gorsuch (C); Sotomayor (C/J/P, D/P)". Codes:

  C    concurring
  D    dissenting
  /J   in the judgment
  /P   in part

Stacked qualifiers ("C/J/P") and mixed roles ("C/J/P, D/P") are both
used in the real list.
"""

from __future__ import annotations

import re

_SEPARATE_ENTRY_RE = re.compile(r"([A-Za-z][A-Za-z.\- ]*?)\s*\(([CDJP/,\s]*)\)")
_CODE_LABELS = {"C": "Concurrence", "D": "Dissent"}
_PAREN_CODES_RE = re.compile(r"\(([CDJP/,\s]*)\)")


def parse_vote_entries(other_text: str | None) -> list[tuple[str, str]]:
    """Returns [(author, code), ...] with whitespace stripped from codes."""
    if not other_text:
        return []
    entries: list[tuple[str, str]] = []
    for part in other_text.split(";"):
        m = _SEPARATE_ENTRY_RE.search(part)
        if not m:
            continue
        name = m.group(1).strip()
        code = re.sub(r"\s+", "", m.group(2))
        if name and code:
            entries.append((name, code))
    return entries


def code_to_label(code: str) -> str:
    """Human-readable label for a Granted-List code string.

    "C/J/P" -> "Concurrence in the judgment in part"
    "C/P, C/J" -> "Concurrence in part; Concurrence in the judgment"
    """
    labels: list[str] = []
    for part in code.split(","):
        tokens = [t for t in part.strip().split("/") if t]
        if not tokens:
            continue
        label = _CODE_LABELS.get(tokens[0], tokens[0])
        for qualifier in tokens[1:]:
            if qualifier == "J":
                label += " in the judgment"
            elif qualifier == "P":
                label += " in part"
        labels.append(label)
    return "; ".join(labels) if labels else code


def _codes_have_letter(codes: str, letter: str) -> bool:
    return bool(re.search(rf"(?<![A-Z]){letter}(?![A-Za-z])", codes))


def has_dissent(other_text: str | None) -> bool:
    if not other_text:
        return False
    return any(_codes_have_letter(m.group(1), "D") for m in _PAREN_CODES_RE.finditer(other_text))


def has_concurrence(other_text: str | None) -> bool:
    if not other_text:
        return False
    return any(_codes_have_letter(m.group(1), "C") for m in _PAREN_CODES_RE.finditer(other_text))


def vote_breakdown(other_text: str | None) -> list[dict]:
    """Structured votes for the API / UI chips."""
    out: list[dict] = []
    for name, code in parse_vote_entries(other_text):
        out.append(
            {
                "author": name,
                "code": code,
                "label": code_to_label(code),
                "has_dissent": _codes_have_letter(code, "D"),
                "has_concurrence": _codes_have_letter(code, "C"),
            }
        )
    return out
