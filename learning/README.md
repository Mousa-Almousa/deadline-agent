# Learning steps

These are the scripts I wrote while building up to the agent in the repo root.
They are kept because they show the progression, not because anything imports
them. Each one added exactly one new idea:

| File | What it taught me |
|------|-------------------|
| `classify.py` | Calling the Anthropic API at all — send text, get a one-word label back. |
| `embed_test.py` | What an embedding actually *is*. Turned out I didn't need embeddings for this project, but I wanted to see the numbers. |
| `gmail_connect.py` | Getting through Google OAuth once and proving I was connected. |
| `gmail_read.py` | Reusing a saved token instead of re-authenticating every run, and pulling subjects out of the Gmail payload. |
| `deadline_extract.py` | Asking Claude for structured JSON instead of prose, and parsing it. This is the direct ancestor of `deadline_to_calendar.py`. |

## Running these

Two gotchas:

1. **Paths are relative.** They look for `credentials.json` and `token.json` in
   the current directory, so run them from the repo root:

   ```bash
   ./venv/bin/python learning/gmail_read.py
   ```

2. **`embed_test.py` needs extra packages** that are not in the root
   `requirements.txt`, because they are large and the agent doesn't use them:

   ```bash
   pip install sentence-transformers
   ```
