"""Email alerting for the deadline agent.

Sends you an email when the agent hits an error, using the same Gmail account
it already reads from -- so there is no new password or API key to manage.

Important limitation: this only fires while the script is actually running.
If your Mac is asleep and cron never starts the job, nothing runs, so nothing
can email you. Catching that case needs an outside service, not this file.
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


def _load_state():
    """Read the record of past alerts. Returns {} if the file isn't there yet."""
    if not os.path.exists(ALERT_STATE_FILE):
        return {}
    try:
        with open(ALERT_STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # A corrupt state file should never stop an alert from going out.
        return {}


def _save_state(state):
    try:
        with open(ALERT_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as exc:
        print(f"[alerts] could not save alert state: {exc}")


def _recently_alerted(kind):
    """True if we already emailed about this kind of problem inside the cooldown."""
    last_sent = _load_state().get(kind)
    if not last_sent:
        return False
    try:
        sent_at = datetime.fromisoformat(last_sent)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - sent_at < timedelta(hours=COOLDOWN_HOURS)


def _record_alert(kind):
    state = _load_state()
    state[kind] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


def _alert_address(gmail):
    """Who to email. Defaults to the signed-in Gmail account -- itself."""
    override = os.getenv("ALERT_EMAIL")
    if override:
        return override
    profile = gmail.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


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
