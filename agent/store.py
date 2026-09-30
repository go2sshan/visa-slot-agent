"""History of every sighting ever seen, kept as CSV in the repo (data/sightings.csv)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .fetcher import Sighting

FIELDS = ["family", "visa_label", "location", "earliest_date", "slots", "total_dates", "seen_utc"]


def _opt_int(v):
    return int(v) if v not in ("", None) else None


def load(path: Path) -> list[Sighting]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return [Sighting(r["family"], r["visa_label"], r["location"], r["earliest_date"],
                         _opt_int(r["slots"]), _opt_int(r["total_dates"]), r["seen_utc"])
                for r in csv.DictReader(f)]


def merge(path: Path, fresh: list[Sighting]) -> tuple[list[Sighting], list[Sighting]]:
    """Adds unseen sightings to the CSV. Returns (all_history, new_ones)."""
    history = load(path)
    known = {s.key for s in history}
    new = []
    for s in fresh:
        if s.key not in known:
            known.add(s.key)
            new.append(s)
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if write_header:
                w.writeheader()
            for s in sorted(new, key=lambda x: x.seen_utc):
                w.writerow(s.to_row())
    return history + new, new


def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
