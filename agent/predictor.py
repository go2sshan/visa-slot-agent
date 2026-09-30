"""Predict when slots are likely to open and what appointment date to expect.

Method (simple, transparent, improves as history grows):
  * Every new sighting is treated as a "release event".
  * Events are bucketed by IST weekday x 2-hour block, weighted by recency
    (half-life 21 days), over the last 60 days.
  * Until a family has ~15 events, a prior from published patterns is blended in
    (releases cluster ~11 PM–6 AM IST; cancellations reappear any time).
  * Expected appointment date = next likely release + median lead time
    (earliest_date − date seen) for that visa family and post.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from .fetcher import Sighting

IST = ZoneInfo("Asia/Kolkata")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HALF_LIFE_DAYS = 21
WINDOW_DAYS = 60
PRIOR_EVENTS = 15


def _prior_hour_weight(h: int) -> float:
    if h in (23, 0, 1):
        return 3.0
    if 2 <= h <= 5:
        return 2.0
    if h == 6:
        return 1.5
    return 0.5


def _prior(weekday: int, block: int) -> float:
    w = (_prior_hour_weight(block * 2) + _prior_hour_weight(block * 2 + 1)) / 2
    return w * (0.7 if weekday >= 5 else 1.0)


PRIOR_TOTAL = sum(_prior(d, b) for d in range(7) for b in range(12))


def _dt(s: Sighting) -> datetime:
    return datetime.fromisoformat(s.seen_utc)


def _lead_days(s: Sighting) -> int:
    return (datetime.fromisoformat(s.earliest_date).date() - _dt(s).date()).days


def _block_label(block: int) -> str:
    def fmt(h):
        h %= 24
        return f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}"
    return f"{fmt(block * 2)}–{fmt(block * 2 + 2)}"


def _next_occurrence(now: datetime, weekday: int, block: int) -> datetime:
    """Next start of (IST weekday, block) strictly after now."""
    now_ist = now.astimezone(IST)
    base = now_ist.replace(hour=block * 2, minute=0, second=0, microsecond=0)
    for add in range(0, 8):
        cand = base + timedelta(days=add)
        if cand.weekday() == weekday and cand > now_ist:
            return cand
    return base + timedelta(days=7)


def analyze(history: list[Sighting], family: str, location: str | None,
            now: datetime, local_tz: ZoneInfo) -> dict:
    cutoff = now - timedelta(days=WINDOW_DAYS)
    ev = [s for s in history if s.family == family
          and (location is None or s.location == location) and _dt(s) >= cutoff]
    n = len(ev)

    scores: dict[tuple[int, int], float] = defaultdict(float)
    for s in ev:
        t = _dt(s).astimezone(IST)
        age = (now - _dt(s)).total_seconds() / 86400
        scores[(t.weekday(), t.hour // 2)] += 0.5 ** (age / HALF_LIFE_DAYS)
    # prior acts as pseudo-events that fade out as real history accumulates
    prior_mass = max(0, PRIOR_EVENTS - n)
    if prior_mass:
        for d in range(7):
            for b in range(12):
                scores[(d, b)] += prior_mass * _prior(d, b) / PRIOR_TOTAL
    total = sum(scores.values()) or 1.0

    top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
    windows = []
    for (d, b), sc in top:
        start = _next_occurrence(now, d, b)
        windows.append({
            "ist": f"{DAYS[d]} {_block_label(b)} IST",
            "share": round(100 * sc / total),
            "next_start_utc": start.astimezone(timezone.utc).isoformat(),
            "next_start_local": start.astimezone(local_tz).strftime("%a %d %b, %I:%M %p %Z"),
        })
    soonest = min(windows, key=lambda w: w["next_start_utc"]) if windows else None

    # hour-of-day profile (IST) — robust even with little data
    hours = [0.0] * 24
    heat = [[0] * 12 for _ in range(7)]  # [IST weekday][2-hour block], raw counts
    for s in ev:
        t = _dt(s).astimezone(IST)
        hours[t.hour] += 1
        heat[t.weekday()][t.hour // 2] += 1

    recent = [s for s in ev if _dt(s) >= now - timedelta(days=30)] or ev
    leads = [_lead_days(s) for s in recent if _lead_days(s) >= 0]
    lead_med = int(median(leads)) if leads else None
    lead_p25 = int(sorted(leads)[len(leads) // 4]) if leads else None

    predicted_date = None
    if soonest and lead_med is not None:
        base_day = datetime.fromisoformat(soonest["next_start_utc"]).astimezone(IST).date()
        predicted_date = {
            "likely": (base_day + timedelta(days=lead_med)).isoformat(),
            "best_case": (base_day + timedelta(days=lead_p25)).isoformat(),
        }

    times = sorted(_dt(s) for s in ev)
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
    last = max(ev, key=_dt) if ev else None

    return {
        "family": family, "location": location or "ALL",
        "events_60d": n,
        "confidence": "low" if n < 10 else "medium" if n < 40 else "high",
        "top_windows": windows,
        "next_window": soonest,
        "hour_profile_ist": hours,
        "heat_ist": heat,
        "median_gap_hours": round(median(gaps), 1) if gaps else None,
        "median_lead_days": lead_med,
        "predicted_appointment": predicted_date,
        "last_seen": last.to_row() if last else None,
    }


def best_locations(history: list[Sighting], family: str, now: datetime, top: int = 3) -> list[dict]:
    """Rank posts by recent activity and short lead time."""
    cutoff = now - timedelta(days=30)
    by_loc: dict[str, list[Sighting]] = defaultdict(list)
    for s in history:
        if s.family == family and _dt(s) >= cutoff:
            by_loc[s.location].append(s)
    ranked = []
    for loc, ev in by_loc.items():
        leads = [_lead_days(s) for s in ev if _lead_days(s) >= 0]
        med = median(leads) if leads else 365
        score = len(ev) / (1 + med / 30)
        ranked.append({"location": loc, "sightings_30d": len(ev),
                       "median_lead_days": int(med), "score": round(score, 2)})
    return sorted(ranked, key=lambda r: -r["score"])[:top]
