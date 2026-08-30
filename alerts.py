"""Email alerting for the deadline agent.

Sends you an email when the agent hits an error, using the same Gmail account
it already reads from -- so there is no new password or API key to manage.

Two paths exist, because a crash during Google sign-in cannot email you (the
sending needs the sign-in that just broke):

  send_alert()   - Gmail is working, mail it now.
  queue_alert()  - Gmail is NOT available. Write it to disk instead, and
                   flush_pending() mails it on the next run that gets through.

That means an auth or network failure still reaches you, just delayed until
connectivity returns, with no outside service involved.

Remaining limitation: everything here runs inside the agent. If your Mac is
asleep and cron never fires, nothing runs, so nothing can be sent or queued.
"""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

# Where we remember what we already alerted about, so an hourly cron job that
# keeps hitting the same error doesn't send you 24 identical emails a day.
ALERT_STATE_FILE = "alert_state.json"
COOLDOWN_HOURS = 6

# Alerts we couldn't send because Gmail wasn't up yet.
PENDING_FILE = "pending_alerts.json"
MAX_PENDING = 20


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # A corrupt state file should never stop an alert from going out.
        return default


def _write_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        print(f"[alerts] could not write {path}: {exc}")


def _recently_alerted(kind):
    """True if we already emailed about this kind of problem inside the cooldown."""
    last_sent = _read_json(ALERT_STATE_FILE, {}).get(kind)
    if not last_sent:
        return False
    try:
        sent_at = datetime.fromisoformat(last_sent)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - sent_at < timedelta(hours=COOLDOWN_HOURS)


def _record_alert(kind):
    state = _read_json(ALERT_STATE_FILE, {})
    state[kind] = datetime.now(timezone.utc).isoformat()
    _write_json(ALERT_STATE_FILE, state)


def _alert_address(gmail):
    """Who to email. ALERT_EMAIL if set, else the signed-in Gmail account."""
    override = os.getenv("ALERT_EMAIL")
    if override:
        return override
    profile = gmail.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def queue_alert(subject, body, kind="generic"):
    """Save an alert to disk because Gmail isn't available to send it.

    Used when the agent dies before sign-in completes. The next successful run
    picks it up via flush_pending().
    """
    pending = _read_json(PENDING_FILE, [])
    pending.append({
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "subject": subject,
        "body": body,
        "kind": kind,
    })
    # Keep only the most recent few: if the machine is offline for a week we
    # want the latest failures, not a thousand copies of the same one.
    _write_json(PENDING_FILE, pending[-MAX_PENDING:])
    print(f"[alerts] queued '{kind}' alert for the next successful run")


def flush_pending(gmail):
    """Send anything queue_alert() saved while Gmail was unreachable."""
    pending = _read_json(PENDING_FILE, [])
    if not pending:
        return 0

    print(f"[alerts] {len(pending)} alert(s) were queued while offline")
    sent = 0
    for item in pending:
        body = (
            f"This alert was queued at {item.get('queued_at', 'unknown time')} "
            f"because the agent could not reach Gmail at the time.\n\n"
            f"{item.get('body', '')}"
        )
        if send_alert(gmail, item.get("subject", "Queued alert"), body,
                      kind=item.get("kind", "generic")):
            sent += 1

    # Clear regardless: suppressed-by-cooldown still counts as handled, and we
    # must not retry these forever.
    _write_json(PENDING_FILE, [])
    return sent


def send_alert(gmail, subject, body, kind="generic"):
    """Email an error report to yourself.

    `kind` groups similar problems together for the cooldown: two different
    JSON parse failures share a kind, so you get one email, not two.

    Returns True if an email actually went out.
    """
    if _recently_alerted(kind):
        print(f"[alerts] suppressed '{kind}' alert (already sent within {COOLDOWN_HOURS}h)")
        return False

    try:
        to_address = _alert_address(gmail)

        message = EmailMessage()
        message.set_content(body)
        message["To"] = to_address
        message["From"] = to_address
        message["Subject"] = f"[Deadline Agent] {subject}"

        # The Gmail API wants the whole email as one base64 string.
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail.users().messages().send(userId="me", body={"raw": raw}).execute()

        _record_alert(kind)
        print(f"[alerts] emailed error report to {to_address}")
        return True
    except Exception as exc:
        # If alerting itself breaks, say so in the cron log and move on. We
        # must never raise from here -- that would hide the original error.
        print(f"[alerts] FAILED to send alert email: {type(exc).__name__}: {exc}")
        return False
