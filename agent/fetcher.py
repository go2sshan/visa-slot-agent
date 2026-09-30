"""Fetch and parse slot sightings from the public checkvisaslots.com tracker pages.

Each visa-type page has a table:
  Visa Location | Visa Type | Earliest Date | Slots on Earliest Date |
  Total Dates Available | Last Seen At | Relative Time
Dates look like "27 Apr, 27"; Last Seen At looks like "28 Sep 2026, 07:57 AM" (UTC).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://checkvisaslots.com/latest-us-visa-availability/{slug}/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal visa-slot monitor; low frequency)",
    "Accept": "text/html",
}


@dataclass(frozen=True)
class Sighting:
    family: str          # L1A, L2, B1, B2, B1/B2, H1B, H4
    visa_label: str      # e.g. "H-1B (Regular)"
    location: str        # e.g. "HYDERABAD VAC"
    earliest_date: str   # ISO date
    slots: int | None    # seats on earliest date (None = N/A)
    total_dates: int | None
    seen_utc: str        # ISO datetime, UTC

    @property
    def key(self) -> tuple:
        return (self.visa_label, self.location, self.seen_utc, self.earliest_date)

    def to_row(self) -> dict:
        return asdict(self)


def _int(s: str) -> int | None:
    s = s.strip()
    return int(s) if s.isdigit() else None


def parse_earliest(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%d %b, %y", "%d %b %y", "%d %b, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse_seen(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%d %b %Y, %I:%M %p", "%d %b %Y %I:%M %p"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


_ROW_RE = re.compile(
    r"(?P<loc>[A-Z][A-Z ]+?(?: VAC)?)\s*\|\s*(?P<visa>[^|]+?)\s*\|\s*"
    r"(?P<earliest>\d{1,2} [A-Z][a-z]{2},? \d{2,4})\s*\|\s*(?P<slots>N/A|\d+)\s*\|\s*"
    r"(?P<total>N/A|\d+)\s*\|\s*(?P<seen>\d{1,2} [A-Z][a-z]{2} \d{4},? \d{1,2}:\d{2} [AP]M)"
)


def _rows_from_html(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[list[str]] = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 6 and cells[0] != "Visa Location":
                rows.append(cells)
    if rows:
        return rows
    # Fallback: page rendered as divs — scan the pipe-joined text.
    text = soup.get_text("|", strip=True)
    for m in _ROW_RE.finditer(text):
        rows.append([m["loc"], m["visa"], m["earliest"], m["slots"], m["total"], m["seen"]])
    return rows


def parse_page(html: str, family: str) -> list[Sighting]:
    out: list[Sighting] = []
    for cells in _rows_from_html(html):
        loc, visa, earliest, slots, total, seen = (c.strip() for c in cells[:6])
        ed, st = parse_earliest(earliest), parse_seen(seen)
        if not ed or not st:
            continue
        out.append(Sighting(
            family=family, visa_label=visa, location=loc.upper(),
            earliest_date=ed.isoformat(), slots=_int(slots), total_dates=_int(total),
            seen_utc=st.isoformat(),
        ))
    return out


def fetch_all(visa_types: dict[str, list[str]], delay: float = 2.0,
              session: requests.Session | None = None) -> tuple[list[Sighting], list[str]]:
    """Returns (sightings, errors)."""
    s = session or requests.Session()
    sightings, errors = [], []
    for family, slugs in visa_types.items():
        for slug in slugs:
            url = BASE.format(slug=slug)
            try:
                r = s.get(url, headers=HEADERS, timeout=20)
                r.raise_for_status()
                rows = parse_page(r.text, family)
                if not rows:
                    errors.append(f"{slug}: page loaded but no rows parsed")
                sightings.extend(rows)
            except Exception as e:  # keep going on one bad page
                errors.append(f"{slug}: {e}")
            time.sleep(delay)
    return sightings, errors
