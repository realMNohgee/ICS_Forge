# ICS_Forge 🗓️
![CI](https://github.com/realMNohgee/ICS_Forge/actions/workflows/ci.yml/badge.svg) ![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg) ![License](https://img.shields.io/badge/license-MIT-blue.svg)

**Generate and validate RFC 5545 iCalendar (`.ics`) files from scratch — zero dependencies, pure Python standard library.**

ICS_Forge creates standards-compliant calendar events you can import into Google Calendar, Apple Calendar, Outlook, or any agent scheduler — and validates or lists events in existing `.ics` files. No `icalendar` library, no pip install, no network.

🧰 **[Tool on Hermtica Marketplace](https://hermtica.com/marketplace)** — the open, agent-agnostic marketplace for AI agent tools.

> Part of the **Trust & Reliability Layer for Agentic AI** — deterministic, verifiable artifacts that agents and humans can exchange without a shared runtime.

## Why it exists

Agents that book meetings, schedule reminders, or hand off deadlines need a portable, unambiguous way to express *when*. `.ics` is the universal calendar interchange format, but generating it by hand means getting RFC 5545 details right: escaping `,` `;` `\` and newlines, line-folding at 75 octets, `TZID` vs UTC (`Z`) timestamps, and required fields (`UID`, `DTSTAMP`, `DTSTART`, `SUMMARY`). ICS_Forge bakes all of that in and gives you a validator to prove a file is well-formed — so an agent can emit a calendar event and a downstream tool can trust it.

## One tool, many domains

| Domain | What ICS_Forge does for you |
|---|---|
| 📅 **Calendar / scheduling** | Generate importable `.ics` events for Google/Apple/Outlook; validate before you send |
| 🤖 **Agentic AI** | Deterministic, verifiable calendar artifacts agents can emit and validate (works as a CI gate via exit codes) |
| 🧪 **QA / testing** | `validate` exits nonzero on malformed files — use it to gate pipelines that produce or consume `.ics` |
| 🔎 **Data auditing** | `list` extracts every event's `UID`/`SUMMARY`/`DTSTART`/`DTEND` for inspection or reconciliation |
| ⏰ **Reminders / automation** | Pipe events into cron jobs, notification systems, or meeting-reminder bots |
| 🧰 **Interop / tooling** | A stdlib-only building block for any tool that needs to emit standards-compliant calendar data |

## Install

```bash
git clone git@github.com:realMNohgee/ICS_Forge.git
cd ICS_Forge
python3 ICS_Forge.py --help
```

No dependencies — works on Python 3.7+ (macOS's system Python included).

## Quick start

```bash
# Generate an event (times are emitted as UTC with a trailing Z)
python3 ICS_Forge.py create --title "Team Standup" \
  --start 2026-08-20T09:00:00 --end 2026-08-20T09:30:00

# Emit in a specific timezone (floating local time with a TZID parameter)
python3 ICS_Forge.py create --title "Standup" \
  --start 2026-08-20T09:00:00 --end 2026-08-20T09:30:00 \
  --tzid America/Chicago

# Save to a file, with description + location
python3 ICS_Forge.py create --title "Board Meeting, Q3" \
  --start 2026-08-21T14:00:00 --end 2026-08-21T15:30:00 \
  --desc "Review Q3 numbers; discuss strategy." \
  --location "HQ, Room 4" \
  --output board.ics

# Validate a file (exit 0 = valid, nonzero = violations)
python3 ICS_Forge.py validate board.ics

# List every event in a file
python3 ICS_Forge.py list board.ics
```

## Subcommands

### `create`
Generate a valid `.ics` with `VCALENDAR` / `VERSION:2.0` / `PRODID` / `VEVENT` / `UID` / `DTSTAMP` / `DTSTART` / `DTEND` / `SUMMARY` (+ optional `DESCRIPTION`, `LOCATION`).

```
--title TITLE       Event title (SUMMARY)
--start START       Start time, ISO 8601 (2026-08-20T09:00:00)
--end END           End time, ISO 8601
--desc DESC         Optional description
--location LOCATION Optional location
--tzid TZID         IANA timezone (e.g. America/Chicago) → floating local time
                    without it, times are emitted as UTC (trailing Z)
--uid UID           Optional UID (defaults to a UUID4)
--output/-o FILE    Write to FILE instead of stdout
```

### `validate`
Parse a `.ics` and report a list of violations: confirms `VCALENDAR` + `VERSION:2.0` are present, every `VEVENT` has `UID` + `DTSTART` + `SUMMARY`, and `DTSTART`/`DTEND` are parseable dates. Exits nonzero when there are any errors — safe to use as a CI gate.

### `list`
List every `VEVENT`'s `UID`, `SUMMARY`, `DTSTART`, and `DTEND`.

Every subcommand supports `--format text|json` (before **or** after the subcommand).

## RFC 5545 correctness

- **Text escaping** — `,` `;` `\` and newlines are backslash-escaped in `SUMMARY`/`DESCRIPTION`/`LOCATION`.
- **Line folding** — logical lines are folded at 75 octets (on UTF-8 character boundaries), joined with `CRLF` + a single space.
- **Timestamps** — `--tzid` emits `DTSTART;TZID=…` (floating local time); otherwise the time is emitted as UTC with a trailing `Z`.
- **Required fields** — `UID`, `DTSTAMP`, `DTSTART`, `DTEND`, `SUMMARY` are always present.

## License

MIT — see [LICENSE](LICENSE).

---

🧰 **[Tool on Hermtica Marketplace](https://hermtica.com/marketplace)** — the open, agent-agnostic marketplace for AI agent tools.
