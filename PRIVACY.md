# Privacy Policy — Deadline Agent

_Last updated: 18 September 2026_

Deadline Agent is a personal, single-user tool. It runs on its owner's own
computer and is not offered as a service to anyone else.

## What it does

It reads the owner's own Gmail messages, uses an AI model to find assignment
and exam deadlines in the text, and creates matching events in the owner's own
Google Calendar.

## What data it accesses

Using Google OAuth, with permission granted by the account owner:

| Scope | What it is used for |
|-------|---------------------|
| `gmail.readonly` | Read message subjects and bodies to look for deadlines. Nothing is modified or deleted. |
| `gmail.send` | Send error reports to the owner's own address when a run fails. |
| `calendar.events` | Create calendar events for deadlines that were found. |

## Where data goes

- **Stored locally only.** The OAuth token, the list of already-processed
  message IDs, and alert bookkeeping are files on the owner's computer. There
  is no server, no database, and no hosted component.
- **Sent to Anthropic.** The subject and body text of each scanned email are
  sent to the Anthropic API so the model can extract deadlines. This is the
  only third party that receives message content. See Anthropic's privacy
  policy: https://www.anthropic.com/legal/privacy
- **Sent to Google.** Calendar events created from those deadlines, and error
  emails sent to the owner.

Nothing is sold, shared, or used for advertising. No analytics or tracking.

## Retention

Message content is not retained by this application. Only Gmail message IDs are
stored, so an email is not processed twice. Deleting the local files removes
everything the application keeps.

## Revoking access

Access can be withdrawn at any time at
https://myaccount.google.com/permissions — this immediately stops all access to
Gmail and Calendar.

## Contact

mr8.e@hotmail.com

## Source code

https://github.com/Mousa-Almousa/deadline-agent
