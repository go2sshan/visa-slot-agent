# US Visa Slot Agent — India

Watches US visa appointment openings at all five Indian posts (Chennai, Hyderabad,
Mumbai, New Delhi, Kolkata — consulate interview **and** VAC biometrics) for
**L1A, L2, B1, B2, B1/B2, H1B and H4**, then:

- 🟢 **Telegram alert** within ~10 minutes of a new opening (post, earliest date, seats, dates open)
- 🔮 **Forecast**: which IST day + 2‑hour window slots most often drop, when that window next
  starts in *your* time zone, and the appointment date you'd likely get
- 📊 **Daily digest** at 8 AM your time, and a **live dashboard** (GitHub Pages)

It never logs into your visa account and never books anything — you book yourself on
the official portal. Data comes from the public crowd‑sourced tracker
checkvisaslots.com, read politely (one page every 2 s, every 10 min).

## Setup (≈15 minutes)

1. **Telegram** — reuse your stock‑screener bot or create one with @BotFather.
   Get your chat id by messaging the bot, then opening
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copying `chat.id`.
2. **GitHub repo** — create a new **public** repo (public = unlimited free Actions minutes;
   the repo holds only slot data, nothing personal) and upload this folder.
   *Private repo?* Change the cron to `*/30 * * * *` to stay inside the free 2,000 min/month.
3. **Secrets** — Settings → Secrets and variables → Actions → add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. **Actions** — Actions tab → enable workflows → *visa-slot-monitor* → **Run workflow**.
   You should get "✅ Visa slot agent started" on Telegram.
5. **Dashboard** — Settings → Pages → Source: *Deploy from a branch* → `main` / `/docs`.
   Your page appears at `https://<you>.github.io/<repo>/`.

## Tune it — `config.yaml`

| Setting | What it does |
|---|---|
| `group_size` | People on one booking. The portal hides a slot that has fewer seats than this; alerts warn you. |
| `latest_acceptable_date` | Only alert for appointment dates on/before this. |
| `locations` | Remove posts you don't want (keep `X VAC` for biometrics). |
| `visa_types` | Families → tracker pages. |
| `daily_digest_hour` | Local hour for the forecast digest (`-1` = off). |

## How the forecast works

Every new sighting is a "drop". Drops from the last 60 days are bucketed by IST weekday ×
2‑hour window, with recent weeks weighted more (21‑day half‑life). Until a visa type has
~15 drops, a starter pattern (most releases ~11 PM–6 AM IST) fills the gaps, and the
confidence label says *low*. Expected appointment date = next likely drop + the median
lead time (earliest date − day seen) at that post over the last 30 days. Accuracy grows
as history builds in `data/sightings.csv` — give it 2–3 weeks.

## Run locally

```bash
pip install -r requirements.txt
python -m agent.main                      # live check (prints alerts if no Telegram secrets)
python -m agent.main --fixtures tests/fixtures   # offline test with a saved page
```

## Notes

- If the tracker changes its page layout, runs will report "no rows parsed" in the
  dashboard footer and the Actions log; `agent/fetcher.py` is the only file to adjust.
- GitHub may delay scheduled runs by a few minutes at busy times.
- Rules worth knowing (2026): only one free reschedule, then the fee is paid again;
  Dropbox/interview waiver is now narrow, so most H1B/H4/L1/L2 applicants need an interview slot.
