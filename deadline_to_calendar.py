import os
import json
from datetime import date
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
else:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as f:
        f.write(creds.to_json())

gmail = build("gmail", "v1", credentials=creds)
calendar = build("calendar", "v3", credentials=creds)

today = date.today()

# NEW: load the list of email IDs we've already processed (once, before the loop)
SEEN_FILE = "processed.json"
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE) as f:
        seen_ids = json.load(f)
else:
    seen_ids = []

results = gmail.users().messages().list(userId="me", maxResults=10).execute()
messages = results.get("messages", [])
print(f"Found {len(messages)} emails.\n")

system_prompt = f"""Today's date is {today}.
You extract assignment and exam deadlines from emails.
If the email gives a date without a year, assume the next time that date occurs after today.
Reply ONLY with JSON in this exact format, nothing else:
{{"has_deadline": true, "task": "what is due", "course": "course name or Unknown", "due_date": "YYYY-MM-DD", "due_time": "HH:MM or Unknown"}}
If the email has no deadline, reply exactly: {{"has_deadline": false}}"""

for msg in messages:
    # NEW: skip already-processed emails BEFORE spending anything on the API
    if msg["id"] in seen_ids:
        continue

    full = gmail.users().messages().get(userId="me", id=msg["id"]).execute()
    headers = full["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
    snippet = full.get("snippet", "")
    email_text = f"Subject: {subject}\n\n{snippet}"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": email_text}]
    )

    answer = response.content[0].text
    cleaned = answer.replace("```json", "").replace("```", "").strip()
    data = json.loads(cleaned)

    print("Email:", subject)

    if data["has_deadline"]:
        title = f"{data['course']}: {data['task']}"
        if data["due_time"] == "Unknown":
            event = {
                "summary": title,
                "start": {"date": data["due_date"]},
                "end": {"date": data["due_date"]},
            }
        else:
            start = f"{data['due_date']}T{data['due_time']}:00"
            event = {
                "summary": title,
                "start": {"dateTime": start, "timeZone": "Asia/Riyadh"},
                "end": {"dateTime": start, "timeZone": "Asia/Riyadh"},
            }
        calendar.events().insert(calendarId="primary", body=event).execute()
        print("  Added to calendar:", title, "on", data["due_date"])
    else:
        print("  No deadline found.")

    # NEW: mark this email as processed and save immediately
    seen_ids.append(msg["id"])
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_ids, f)

    print("---")
