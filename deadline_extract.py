import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from anthropic import Anthropic
from dotenv import load_dotenv
from datetime import date
today = date.today()

# --- Setup: load API key and connect to Claude ---
load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# --- Setup: connect to Gmail (reuse saved login) ---
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

service = build("gmail", "v1", credentials=creds)

# --- Read the 5 most recent emails ---
results = service.users().messages().list(userId="me", maxResults=5).execute()
messages = results.get("messages", [])
print(f"Found {len(messages)} emails.\n")

# --- The instructions for Claude (the "rules") ---
system_prompt = f"""Today's date is {today}.
You extract assignment and exam deadlines from emails.
If the email gives a date without a year, assume the next time that date occurs after today.
Reply ONLY with JSON in this exact format, nothing else:
{{"has_deadline": true, "task": "what is due", "course": "course name or Unknown", "due_date": "YYYY-MM-DD", "due_time": "HH:MM or Unknown"}}
If the email has no deadline, reply exactly: {{"has_deadline": false}}"""

# --- For EACH email: read it, ask Claude, clean and parse the answer ---
for msg in messages:
    full = service.users().messages().get(userId="me", id=msg["id"]).execute()
    headers = full["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
    snippet = full.get("snippet", "")
    email_text = f"Subject: {subject}\n\n{snippet}"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=system_prompt,
        messages=[
            {"role": "user", "content": email_text}
        ]
    )

    answer = response.content[0].text

    # NEW: strip the markdown fences Claude sometimes adds, then parse to real data
    cleaned = answer.replace("```json", "").replace("```", "").strip()
    data = json.loads(cleaned)

    # NEW: print the extracted deadline nicely, using the parsed data
    print("Email:", subject)
    if data["has_deadline"]:
        print("  Task:", data["task"])
        print("  Course:", data["course"])
        print("  Due:", data["due_date"], data["due_time"])
    else:
        print("  No deadline found.")
    print("---")