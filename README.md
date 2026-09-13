# CalDAV Codeforces Bot

[English](README.md) | [Русский](README_RU.md)

A Telegram bot that tracks [Codeforces](https://codeforces.com) contests, announces them to users, creates events in their **CalDAV calendars** (Yandex or any custom CalDAV server), and sends reminders before the start.

## Features

- **Contest tracking** — polls the Codeforces API and announces new upcoming contests to all users.
- **"I will participate"** — one tap creates the contest as an event in every active CalDAV calendar connected by the user.
- **Smart event creation** — before writing, the bot checks whether the event already exists (by UID) and whether it overlaps with other events in the calendar (recurring events are expanded locally).
- **Reminders** — configurable lead times (default: 60 / 15 / 5 minutes before start), with deduplication so each reminder fires exactly once.
- **Yandex and generic CalDAV** — connect with a Yandex account (email + app password) or any CalDAV server (URL + login + app password), with an in-chat connection wizard and calendar picker.
- **Encrypted credentials** — calendar passwords are encrypted with Fernet; a change of the encryption key is detected and users are asked to reconnect.
- **SSRF protection** — local / loopback / private-network CalDAV addresses are rejected unless explicitly enabled.
- **Admin panel** — admins can emulate a contest (name, start time, duration) and get an announcement report.

## How it works

```
Codeforces API ──▶ parser (every 10 min by default) ──▶ SQLite (Contest)
                              │
                              ▼
                   announcement to all users
                              │
                       "I will participate"
                              │
          user's CalDAV calendars ◀── event created (UID cf-contest-{id})
                              │
        reminders scheduler (every 10 s) ──▶ Telegram messages at chosen offsets
```

- Contest and event times are stored as naive UTC; all user-facing times are displayed in **Europe/Moscow**.
- Reminders are deduplicated via a notification log; entries older than 30 days are cleaned up automatically.
- Per-user locks and re-checks guard against races (double submissions, concurrent calendar setup).

## Requirements

- Python **3.12+** (or Docker 29+ / Docker Compose v2+)

## Quick start

### 1. Configure

```bash
cp .env.example .env
```

Fill in the required values:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `SECRET_KEY` | yes | Fernet key used to encrypt calendar passwords. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ADMIN_IDS` | no | Comma-separated Telegram user IDs with admin access |
| `DATABASE_URL` | no | SQLAlchemy DSN (default `sqlite+aiosqlite:///bot.db`) |
| `PARSE_INTERVAL_SECONDS` | no | Codeforces polling interval (default `600`) |
| `REMIND_INTERVAL_SECONDS` | no | Reminder check interval (default `10`) |
| `ALLOW_LOCAL_CALDAV` | no | Allow CalDAV servers on local/private addresses (default `false`) |

> **Keep `SECRET_KEY` stable.** Losing it makes stored calendar passwords undecryptable — users will have to reconnect their calendars.

### 2. Run

**With Docker Compose (recommended):**

```bash
docker compose up -d --build
docker compose logs -f
```

Data is persisted in the `bot-data` named volume (SQLite at `/data/bot.db` inside the container). In Docker the `DATABASE_URL` from `.env` is overridden with `sqlite+aiosqlite:////data/bot.db` automatically.

**Without Docker:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

### For users

- `/start` — main menu: connect a calendar, manage notifications.
- **Connect a calendar** — choose Yandex (a step-by-step app-password guide is provided in chat) or a custom CalDAV server; the bot validates credentials, lists available calendars, and lets you pick one. Up to 10 calendars per user; each can be toggled on/off or removed in the settings.
- **Notifications** — pick lead times from 5 minutes up to 1 week (up to 10 per user).
- **Announcements** — new contests arrive with a "🔥 I will participate" button that writes the event into all your active calendars and reports per-calendar results (created / already present / overlaps / errors).
- `/cancel` — abort any in-progress setup wizard.

### For admins

- `/admin` — admin panel.
- `/create` — create an emulated contest (name, start time in Moscow time, duration) and announce it to all users with a delivery report.

Admins are excluded from announcements, reminders, and calendar connection.

## Project structure

```
main.py                    # entry point: dispatcher, routers, scheduler
config.py                  # env configuration
db/
  models.py                # SQLAlchemy models + lightweight migrations
handlers/
  start.py                 # /start, main menu
  admin.py                 # /admin, /create (contest emulation)
  calendar_setup.py        # calendar connection wizard (FSM)
  calendar_settings.py     # list / toggle / delete calendars
  contest.py               # "I will participate" → CalDAV events
  notify_settings.py       # reminder offsets
  common.py                # safe message-editing helpers
keyboards/inline.py        # all inline keyboards
services/
  cf_parser.py             # Codeforces contest.list polling
  scheduler.py             # announcements, reminders, log cleanup
  caldav_service.py        # CalDAV client: list, find by UID, overlaps, add event
  crypto.py                # Fernet encryption + key fingerprint
  guides.py                # in-chat Yandex app-password guide
  text.py                  # formatting (durations, MSK times, pluralization)
Dockerfile                 # python:3.12-slim image, non-root user, /data volume
docker-compose.yml         # service + bot-data volume
```

## Security notes

- Calendar passwords are stored encrypted (Fernet) and are never shown back to the user.
- A fingerprint of `SECRET_KEY` is stored per calendar; if the key changes, decryption is refused and users are prompted to reconnect instead of silently failing.
- CalDAV URLs pointing to localhost / private networks are rejected unless `ALLOW_LOCAL_CALDAV=true`.
- Plain HTTP (non-TLS) CalDAV endpoints require an explicit confirmation step.

## Known limitations

- Calendar events are **only created** — if Codeforces reschedules a contest, the event in the calendar is not updated; there is also no "unregister" flow that removes events.
- FSM (wizard) state is kept in memory — an in-progress setup wizard is lost on bot restart.
- Overlap detection downloads all calendar events (no server-side time-range filtering), which can be slow on very large calendars.
- Contest announcements are marked as announced even if delivery to some users failed (e.g. blocked bot) — delivery is best-effort.
- Reminders and announcements are not sent to admins by design.
