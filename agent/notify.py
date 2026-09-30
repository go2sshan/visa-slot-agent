"""Telegram alerts (same Bot API you use for the stock screener)."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .fetcher import Sighting

IST = ZoneInfo("Asia/Kolkata")
PORTAL = "https://www.ustraveldocs.com/in/"


def send(text: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram disabled] would send:\n" + text + "\n")
        return False
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=20)
        if not r.ok:
            print("Telegram error:", r.status_code, r.text[:200])
            return False
    return True


def _fmt_seen(s: Sighting, local_tz: ZoneInfo) -> str:
    t = datetime.fromisoformat(s.seen_utc)
    return (f"{t.astimezone(IST):%a %d %b %I:%M %p} IST · "
            f"{t.astimezone(local_tz):%a %d %b %I:%M %p %Z}")


def slot_alert(s: Sighting, pred: dict, local_tz: ZoneInfo, group_size: int) -> str:
    ed = datetime.fromisoformat(s.earliest_date)
    seats = "seats unknown" if s.slots is None else f"{s.slots} seat{'s' * (s.slots != 1)}"
    warn = ""
    if s.slots is not None and s.slots < group_size:
        warn = f"\n⚠️ Fewer seats than your group of {group_size} — may not show for you."
    kind = "Biometrics (VAC)" if s.location.endswith("VAC") else "Consulate interview"
    lines = [
        f"🟢 <b>{s.family} slot opened — {s.location}</b>",
        f"{s.visa_label} · {kind}",
        f"📅 Earliest: <b>{ed:%a %d %b %Y}</b> ({seats}"
        + (f", {s.total_dates} dates open" if s.total_dates else "") + ")",
        f"👀 Seen: {_fmt_seen(s, local_tz)}{warn}",
    ]
    nw = pred.get("next_window")
    if nw:
        lines.append(f"🔮 If you miss it, next likely drop: {nw['ist']} "
                     f"(= {nw['next_start_local']}), ~{nw['share']}% of past drops")
    if pred.get("predicted_appointment"):
        pa = pred["predicted_appointment"]
        lines.append(f"🗓 Expected date then: ~{pa['likely']} (best case {pa['best_case']})")
    lines.append(f"👉 Log in and book now: {PORTAL}")
    return "\n".join(lines)


def digest(preds: list[dict], ranks: dict[str, list[dict]]) -> str:
    out = ["📊 <b>Daily visa slot forecast (India)</b>"]
    for p in preds:
        out.append(f"\n<b>{p['family']}</b> — {p['events_60d']} drops in 60d, "
                   f"confidence {p['confidence']}")
        nw = p.get("next_window")
        if nw:
            out.append(f"  ⏰ Check: {nw['ist']} → {nw['next_start_local']}")
        if p.get("predicted_appointment"):
            out.append(f"  🗓 Likely appointment date: ~{p['predicted_appointment']['likely']}")
        best = ranks.get(p["family"]) or []
        if best:
            out.append("  🏢 Best posts: " + ", ".join(
                f"{b['location']} ({b['sightings_30d']} drops, ~{b['median_lead_days']}d out)"
                for b in best))
    return "\n".join(out)
