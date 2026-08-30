import os
import sys
import json
import base64
import time
import traceback
from datetime import date

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError, TransportError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from anthropic import Anthropic
from dotenv import load_dotenv

import alerts

load_dotenv()

# --- Settings you might want to change ---
TIMEZONE = "Asia/Riyadh"
MAX_EMAILS = 10
MAX_BODY_CHARS = 2000
MODEL = "claude-haiku-4-5-20251001"
SEEN_FILE = "processed.json"
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]


# A dropped connection shouldn't kill an hourly job. The agent already died
# once on a Read timed out to Google's token endpoint -- retrying absorbs that.
TRANSIENT_ERRORS = (TransportError, TimeoutError, ConnectionError)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


def with_retries(label, func):
    """Run func(), retrying a few times on transient network errors."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return func()
        except TRANSIENT_ERRORS as exc:
            if attempt == RETRY_ATTEMPTS:
                raise
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"  {label} failed ({type(exc).__name__}); "
                  f"retry {attempt}/{RETRY_ATTEMPTS - 1} in {wait}s")
            time.sleep(wait)


def sign_in_with_browser():
    """Open the browser for Google sign-in. Needs a human at the keyboard."""
    # Under cron there is no human and no browser, and run_local_server() would
    # sit there blocking forever -- a hung process every hour that we could
    # never email you about, because sending mail needs the sign-in that's
    # stuck. Fail loudly and fast instead.
    if not sys.stdin.isatty() and os.getenv("ALLOW_BROWSER_AUTH") != "1":
        # Work out the path at runtime rather than hardcoding it, so this
        # message stays right even if the project folder gets renamed.
        project_dir = os.path.dirname(os.path.abspath(__file__))
        raise RuntimeError(
            "Google sign-in is needed, but this run isn't interactive "
            "(no terminal attached), so no browser can be opened.\n"
            "Run this by hand once to sign in:\n"
            f"    cd {project_dir} && ./venv/bin/python deadline_to_calendar.py"
        )

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    return flow.run_local_server(port=0)


def get_credentials():
    """Log in to Google, reusing the saved token when we can.

    Four cases, in order:
      1. Saved token covers everything and is valid -> use it.
      2. Saved token is missing a permission        -> sign in again.
      3. Saved token expired but renewable          -> refresh, save the new one.
      4. No token, or the refresh is rejected       -> sign in again.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            # NO scopes argument on purpose. Passing SCOPES here overwrites the
            # token's real granted scopes with the ones we *want*, which makes
            # the has_scopes() check below compare SCOPES against SCOPES and
            # always say yes. Omitting it reads what Google actually granted.
            creds = Credentials.from_authorized_user_file(TOKEN_FILE)
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            print(f"Saved token unreadable ({exc}); signing in again.")
            creds = None

    if creds and not creds.has_scopes(SCOPES):
        missing = [s for s in SCOPES if s not in (creds.scopes or [])]
        print(f"Saved sign-in is missing: {', '.join(missing)}")
        print("Signing in again to approve it.")
        creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            with_retries("token refresh", lambda: creds.refresh(Request()))
        except RefreshError as exc:
            # Token revoked, expired past renewal, or scopes changed underneath
            # us. Not fatal -- just sign in again rather than crashing.
            print(f"Could not renew saved sign-in ({exc}); signing in again.")
            creds = sign_in_with_browser()
    else:
        creds = sign_in_with_browser()

    # Save whatever we ended up with, so the next hourly run reuses it.
    # The original version never wrote refreshed tokens back to disk.
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    return creds


def load_seen_ids():
    """Email IDs we've already handled, as a set so lookups are instant."""
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        print(f"WARNING: {SEEN_FILE} unreadable, treating all emails as new.")
        return set()


def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen_ids), f)


def build_system_prompt():
    today = date.today()
    prompt = f"""Today's date is {today}, which is a {today.strftime("%A")}.
You extract assignment and exam deadlines from emails. Emails may be in English
or Arabic. Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩) are ordinary digits.

Resolving dates:
- A date with no year means the next time that date occurs after today.
- A weekday name ("Thursday", "الخميس") means the SOONEST occurrence of that
  weekday after today. Never skip a week -- treat "next Thursday" and
  "Thursday" as the same day.
- "tomorrow", "بكرة" and "غدا" mean the day after today.
- Set "date_ambiguous" to true ONLY when the wording could reasonably mean a
  different week, such as "next Thursday" or "الخميس القادم". Use false for an
  explicit date or a plain weekday.

Only graded academic work counts: assignments, exams, quizzes, projects,
submissions. Social plans, invitations and meetings are NOT deadlines.

Reply ONLY with JSON in this exact format, nothing else:
{{"has_deadline": true, "task": "what is due", "course": "course name or Unknown", "due_date": "YYYY-MM-DD", "due_time": "HH:MM or Unknown", "date_ambiguous": false}}
If the email has no deadline, reply exactly: {{"has_deadline": false}}"""

    # Optional per-machine rules, read from EXTRA_RULES in .env. Lets you tune
    # what counts as a deadline for your own inbox without editing this file.
    extra = os.getenv("EXTRA_RULES", "").strip()
    if extra:
        prompt += f"\n\nAdditional rules:\n{extra}"

    return prompt


def plain_text_body(part):
    """Find the text/plain part of an email, walking nested MIME parts.

    Emails are a tree: a forwarded message is often multipart/alternative with
    a text/plain and a text/html child. We want the plain one.
    """
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        raw = base64.urlsafe_b64decode(part["body"]["data"])
        return raw.decode("utf-8", "replace")
    for child in part.get("parts", []) or []:
        found = plain_text_body(child)
        if found:
            return found
    return ""


def clean_body(text):
    """Drop the boilerplate that pads out university email."""
    # The KSU legal disclaimer is ~1000 chars of noise on every message.
    for marker in ("Disclaimer:", "This communication is intended for"):
        if marker in text:
            text = text.split(marker)[0]

    # Collapse runs of blank lines left behind by forwarding.
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False

    return "\n".join(out).strip()[:MAX_BODY_CHARS]


def read_email(gmail, message_id):
    """Pull the subject and preview text for one email."""
    full = gmail.users().messages().get(userId="me", id=message_id).execute()
    headers = full["payload"]["headers"]
    subject = next(
        (h["value"] for h in headers if h["name"] == "Subject"), "(no subject)"
    )

    # The snippet is only Gmail's ~200-char preview. On a forwarded email that
    # is entirely "Get Outlook for iOS" plus From/Sent/To headers, so the real
    # message never reached Claude. Read the actual body instead.
    body = clean_body(plain_text_body(full["payload"]))
    if not body:
        body = full.get("snippet", "")

    return subject, f"Subject: {subject}\n\n{body}"


def extract_deadline(client, system_prompt, email_text):
    """Ask Claude for the deadline. Returns a dict, or None if it wasn't valid JSON."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": email_text}],
    )

    answer = response.content[0].text
    cleaned = answer.replace("```json", "").replace("```", "").strip()

    # Claude sometimes answers correctly and then adds a sentence explaining
    # itself. Plain json.loads() rejects that with "Extra data", so we decode
    # only the first JSON object and ignore whatever follows it.
    start = cleaned.find("{")
    if start != -1:
        try:
            data, _end = json.JSONDecoder().raw_decode(cleaned[start:])
            return data
        except json.JSONDecodeError:
            pass

    # Genuinely unparseable. Don't kill the whole run over one weird email --
    # report it and let the caller keep going.
    print(f"  Could not parse Claude's reply: {cleaned[:200]!r}")
    return None


def add_to_calendar(calendar, data, source_subject=""):
    """Create the calendar event and return its title."""
    title = f"{data['course']}: {data['task']}"

    # A confidently wrong date is worse than an obviously uncertain one, so
    # say so in the title when the email's wording could mean another week.
    if data.get("date_ambiguous"):
        title += " (verify date)"

    notes = [f"Added automatically by the deadline agent from: {source_subject}"]
    if data.get("date_ambiguous"):
        notes.append(
            "WARNING: the email used relative wording (e.g. 'next Thursday'). "
            "This date was resolved to the soonest matching day -- check the "
            "original email before relying on it."
        )
    description = "\n\n".join(notes)

    if data.get("due_time", "Unknown") == "Unknown":
        event = {
            "summary": title,
            "description": description,
            "start": {"date": data["due_date"]},
            "end": {"date": data["due_date"]},
        }
    else:
        start = f"{data['due_date']}T{data['due_time']}:00"
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start, "timeZone": TIMEZONE},
            "end": {"dateTime": start, "timeZone": TIMEZONE},
        }

    calendar.events().insert(calendarId="primary", body=event).execute()
    return title


# Set as soon as we're connected to Gmail. The crash handler at the bottom
# reads this so it can still email you about a failure that happened halfway
# through the run. "global" below means "assign to this outer variable,
# don't make a new local one with the same name".
GMAIL = None


def main():
    global GMAIL

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    creds = get_credentials()
    gmail = build("gmail", "v1", credentials=creds)
    calendar = build("calendar", "v3", credentials=creds)
    GMAIL = gmail

    # Anything that failed before sign-in on an earlier run gets mailed now.
    alerts.flush_pending(gmail)

    seen_ids = load_seen_ids()
    system_prompt = build_system_prompt()

    results = gmail.users().messages().list(userId="me", maxResults=MAX_EMAILS).execute()
    messages = results.get("messages", [])
    print(f"Found {len(messages)} emails.\n")

    # Problems pile up here instead of crashing the run. The two kinds are
    # tracked separately because they behave differently on the next run:
    #   skipped -> marked as processed, will NOT be retried
    #   errors  -> not marked, so the next run tries them again
    skipped = []
    errors = []

    for msg in messages:
        if msg["id"] in seen_ids:
            continue

        try:
            subject, email_text = read_email(gmail, msg["id"])
            print("Email:", subject)

            data = extract_deadline(client, system_prompt, email_text)

            if data is None:
                # Marked as processed below on purpose: an email Claude can't
                # parse would otherwise be retried every hour forever, costing
                # an API call each time. You get one alert, then we move on.
                skipped.append(f"- {subject}\n  Claude's reply wasn't valid JSON.")
            elif data.get("has_deadline"):
                title = add_to_calendar(calendar, data, subject)
                print("  Added to calendar:", title, "on", data["due_date"])
            else:
                print("  No deadline found.")

            seen_ids.add(msg["id"])
            save_seen_ids(seen_ids)

        except Exception as exc:
            # One bad email shouldn't stop the other nine from being processed.
            print(f"  ERROR on this email: {type(exc).__name__}: {exc}")
            errors.append(
                f"- message id {msg['id']}\n  {type(exc).__name__}: {exc}"
            )

        print("---")

    if skipped or errors:
        sections = [
            f"The deadline agent finished, but "
            f"{len(skipped) + len(errors)} email(s) had problems."
        ]
        if skipped:
            sections.append(
                f"SKIPPED ({len(skipped)}) - marked as processed, will NOT be "
                f"retried. Check these by hand if you were expecting a "
                f"deadline:\n\n" + "\n\n".join(skipped)
            )
        if errors:
            sections.append(
                f"ERRORS ({len(errors)}) - not marked as processed, the next "
                f"run will try again:\n\n" + "\n\n".join(errors)
            )

        alerts.send_alert(
            gmail,
            f"{len(skipped) + len(errors)} email(s) had problems",
            "\n\n".join(sections),
            kind="per_email_failure",
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Something broke badly enough to stop the whole run.
        report = (
            f"The deadline agent crashed and did not finish.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Full traceback:\n{traceback.format_exc()}"
        )
        print(report)

        if GMAIL is not None:
            alerts.send_alert(GMAIL, "Agent crashed", report,
                              kind=f"crash:{type(exc).__name__}")
        else:
            # We crashed before Gmail was ready, so we can't send mail now.
            # Save it: the next run that reaches Gmail will send it for us.
            alerts.queue_alert("Agent crashed before sign-in", report,
                               kind=f"crash:{type(exc).__name__}")

        raise SystemExit(1)
