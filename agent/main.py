"""Entry point: python -m agent.main   (run every ~10 min by GitHub Actions)"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import fetcher, notify, predictor, store

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "sightings.csv"
STATE = ROOT / "data" / "state.json"
DASH_DATA = ROOT / "docs" / "data.json"
FRESH_HOURS = 6  # don't alert on sightings older than this


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def wanted(s: fetcher.Sighting, cfg: dict) -> bool:
    if cfg.get("locations") and s.location not in cfg["locations"]:
        return False
    lad = cfg.get("latest_acceptable_date")
    if lad and s.earliest_date > str(lad):
        return False
    return True


def run(fixture_dir: Path | None = None, now: datetime | None = None) -> dict:
    cfg = load_config()
    now = now or datetime.now(timezone.utc)
    local_tz = ZoneInfo(cfg.get("local_timezone", "UTC"))
    group = int(cfg.get("group_size", 1))

    if fixture_dir:  # offline test mode: <slug>.html files
        fresh, errors = [], []
        for fam, slugs in cfg["visa_types"].items():
            for slug in slugs:
                f = fixture_dir / f"{slug}.html"
                if f.exists():
                    fresh += fetcher.parse_page(f.read_text(), fam)
    else:
        fresh, errors = fetcher.fetch_all(cfg["visa_types"], cfg.get("request_delay_seconds", 2))

    first_run = not HISTORY.exists()
    history, new = store.merge(HISTORY, fresh)
    state = store.load_state(STATE)

    families = list(cfg["visa_types"].keys())
    preds = {f: predictor.analyze(history, f, None, now, local_tz) for f in families}

    # --- alerts ---
    alerts = 0
    if first_run:
        notify.send(f"✅ Visa slot agent started. Watching {', '.join(families)} at "
                    f"{len(cfg['locations'])} posts. Seeded {len(new)} recent sightings.")
    else:
        for s in sorted(new, key=lambda x: x.earliest_date):
            if not wanted(s, cfg):
                continue
            if now - datetime.fromisoformat(s.seen_utc) > timedelta(hours=FRESH_HOURS):
                continue
            loc_pred = predictor.analyze(history, s.family, s.location, now, local_tz)
            notify.send(notify.slot_alert(s, loc_pred, local_tz, group))
            alerts += 1

    # --- daily digest ---
    ranks = {f: predictor.best_locations(history, f, now) for f in families}
    local_now = now.astimezone(local_tz)
    dh = int(cfg.get("daily_digest_hour", -1))
    if dh >= 0 and local_now.hour == dh and state.get("last_digest") != local_now.date().isoformat():
        notify.send(notify.digest(list(preds.values()), ranks))
        state["last_digest"] = local_now.date().isoformat()

    # --- dashboard data ---
    per_loc = {f: {loc: predictor.analyze(history, f, loc, now, local_tz)
                   for loc in cfg["locations"]} for f in families}
    recent = sorted((s.to_row() for s in history
                     if datetime.fromisoformat(s.seen_utc) >= now - timedelta(days=14)),
                    key=lambda r: r["seen_utc"], reverse=True)[:300]
    DASH_DATA.parent.mkdir(parents=True, exist_ok=True)
    DASH_DATA.write_text(json.dumps({
        "generated_utc": now.isoformat(),
        "local_timezone": cfg.get("local_timezone"),
        "group_size": group,
        "latest_acceptable_date": str(cfg.get("latest_acceptable_date") or ""),
        "families": families,
        "predictions": preds,
        "per_location": per_loc,
        "best_locations": ranks,
        "recent": recent,
        "fetch_errors": errors,
    }, indent=1))

    state["last_run_utc"] = now.isoformat()
    state["last_errors"] = errors
    store.save_state(STATE, state)
    summary = {"fetched": len(fresh), "new": len(new), "alerts": alerts, "errors": errors}
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, help="parse local <slug>.html files instead of fetching")
    ap.add_argument("--now", help="override current time (ISO, UTC) for testing")
    a = ap.parse_args()
    run(a.fixtures, datetime.fromisoformat(a.now) if a.now else None)
