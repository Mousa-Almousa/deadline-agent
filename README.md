# Deadline Agent

Reads my university email, finds assignment and exam deadlines buried in it, and
puts them on my calendar automatically.

I kept missing deadlines that were mentioned halfway down an email I'd skimmed at
2am. This runs every hour in the background and moves them onto my calendar
before I forget they existed.

## What it does

```
Gmail  ──►  Claude  ──►  Google Calendar
(read)     (extract)      (create event)
```

1. Pulls the most recent emails from Gmail over OAuth.
2. Sends the subject and preview text to Claude, which replies with strict JSON:
   either a deadline, or `{"has_deadline": false}`.
3. Turns any deadline into a Google Calendar event — timed if the email gave a
   time, all-day if it didn't.
4. Records the Gmail message ID in `processed.json`, so re-runs never
   double-book the same email.
5. Emails me if anything goes wrong (see [Error alerts](#error-alerts)).

Google Calendar syncs to Apple Calendar, so the events land on my phone and
laptop without any extra work.

### Example run

```
Found 5 emails.

Email: CS340 — Homework 3 posted
  Added to calendar: CS340: Homework 3 on 2026-09-02
---
Email: Netflix: your monthly bill
  No deadline found.
---
```

## Setup

**Requires Python 3.11+** (developed on 3.14).

### 1. Install

```bash
git clone <your-repo-url> deadline-agent && cd deadline-agent
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2. Anthropic API key

```bash
cp .env.example .env
```

Then put your key in `.env`. Get one from the
[Anthropic console](https://console.anthropic.com/settings/keys).

### 3. Google OAuth

In the [Google Cloud Console](https://console.cloud.google.com/):

1. Create a project.
2. Enable the **Gmail API** and the **Google Calendar API**.
3. Under *APIs & Services → Credentials*, create an **OAuth client ID** of type
   **Desktop app**.
4. Download the JSON, rename it to `credentials.json`, and drop it in the
   project root.
5. Under *OAuth consent screen*, add your own Google account as a **test user**
   — otherwise Google blocks the sign-in.

The agent asks for three scopes:

| Scope | Why |
|-------|-----|
| `gmail.readonly` | Read emails. It never modifies or deletes mail. |
| `gmail.send` | Send **you** the error alerts. |
| `calendar.events` | Create the deadline events. |

### 4. First run

Run it by hand once. A browser opens for Google sign-in, and the resulting token
is saved to `token.json` so later runs are silent:

```bash
./venv/bin/python deadline_to_calendar.py
```

> If you ever change the scopes in `SCOPES`, the saved token no longer covers
> what's needed and the agent will ask you to sign in again. That's expected.

## Running hourly

```bash
crontab -e
```

```
0 * * * * cd /Users/you/deadline-agent && ./venv/bin/python deadline_to_calendar.py >> /Users/you/deadline.log 2>&1
```

Use absolute paths and the venv's Python — cron has a minimal environment and
won't find them otherwise.

On macOS, cron only fires while the machine is awake. A missed hour isn't a
problem: nothing was marked processed, so the next run picks those emails up.

## Error alerts

The agent runs unattended, so a failure used to be invisible until a deadline
quietly went missing. It now emails a report to itself through the Gmail account
it's already signed in to — no SMTP password or third-party service to set up.

Two kinds of problem are reported separately, because they behave differently on
the next run:

| | What happened | Next run |
|---|---|---|
| **Skipped** | Claude returned something that wasn't valid JSON | Marked processed, **not** retried — otherwise it would burn an API call every hour forever. Check that email by hand. |
| **Errors** | Transient failure (network down, API error) | Left unprocessed, retried automatically. |

Alerts are grouped by error type with a **6-hour cooldown**, so a persistent
failure sends one email rather than 24 a day.

**Set `ALERT_EMAIL` in `.env`.** Without it, alerts go to the Gmail account the
agent signs in as -- which means they land in the same mailbox it scans, so the
agent reads its own alerts, and you only see them if you check that account.
Point it at the address you actually read.

Two failures used to be invisible, and aren't any more:

- **Transient network errors** (a dropped connection to Google's token
  endpoint) are retried three times with backoff before the run is failed at
  all. This is what killed a run on 2026-08-26.
- **Crashes before sign-in** can't email you, because sending needs the auth
  that just broke. The alert is now saved to `pending_alerts.json` and sent by
  the next run that reaches Gmail.

To send yourself a test alert:

```bash
./venv/bin/python -c "
from googleapiclient.discovery import build
from deadline_to_calendar import get_credentials
import alerts
alerts.send_alert(build('gmail','v1',credentials=get_credentials()),
                  'Test alert', 'If you got this, alerting works.', kind='manual_test')"
```

## Known limitations

Being honest about what this doesn't do:

- **HTML-only emails fall back to the preview snippet.** The agent reads the
  `text/plain` part of a message; if there isn't one, it uses Gmail's snippet
  and may miss content. Bodies are also truncated at `MAX_BODY_CHARS`.
- **Deduplication is per-email, not per-deadline.** If the same assignment is
  mentioned in two separate emails, you get two calendar events.
- **Alerts can't report a run that never happened.** The alert is sent *by* the
  agent, so if the Mac is asleep and cron never fires, nothing is sent and
  nothing warns you. Covering that needs an external dead-man's-switch service.
- **A failure during sign-in is reported late, not never.** Sending mail needs
  the sign-in that just broke, so the alert is written to `pending_alerts.json`
  and emailed by the next run that reaches Gmail. If the machine never gets
  online again, you never hear about it.
- **Relative dates are resolved to the soonest match.** "next Thursday" is
  treated as the coming Thursday, never a week later. When the wording is
  genuinely ambiguous the event title gets `(verify date)` and the description
  explains why -- a confidently wrong date is worse than an obviously uncertain
  one.
- **Timezone is hardcoded** to `Asia/Riyadh` in `TIMEZONE`.
- **No test suite yet.**

## Project structure

```
deadline_to_calendar.py   The agent. This is the whole thing.
alerts.py                 Error-report emails, with cooldown.
requirements.txt          Runtime deps (not a full pip freeze — see the file).
.env.example              Template for your .env.
learning/                 Scripts I wrote while learning. Not imported.
```

Files that are generated and **never committed** — all gitignored:

| File | What it holds |
|------|---------------|
| `.env` | Anthropic API key |
| `credentials.json` | Google OAuth client secret |
| `token.json` | Your saved Google sign-in |
| `processed.json` | Gmail IDs already handled |
| `alert_state.json` | When each alert type was last sent |

## Notes

Built while teaching myself AI engineering. `learning/` has the intermediate
steps, one new idea per file.

The interesting problem turned out not to be the AI part — getting structured
JSON out of Claude is a few lines. It was everything around it: what happens
when the model returns something unparseable, when a token expires at 3am, when
the same email shows up twice, and how a background job tells you it's broken
when you're not watching.
