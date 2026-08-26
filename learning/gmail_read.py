from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

# Reuse saved login if we have it; otherwise open the browser once.
if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
else:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as f:
        f.write(creds.to_json())

service = build("gmail", "v1", credentials=creds)

# Get the 5 most recent emails in the inbox.
results = service.users().messages().list(userId="me", maxResults=5).execute()
messages = results.get("messages", [])

print(f"Found {len(messages)} emails.\n")

# For each email, pull out the subject and a snippet of the body.
for msg in messages:
    full = service.users().messages().get(userId="me", id=msg["id"]).execute()
    headers = full["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
    snippet = full.get("snippet", "")
    print("Subject:", subject)
    print("Preview:", snippet)
    print("---")
