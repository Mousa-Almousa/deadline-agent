import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
emails = [
    "Offers on Netflix subscriptions",
    "Final exam schedule ",
    "Hey wanna play?",
    "Professor Mousa Changed the final exam date",
]
for email in emails: 
	response = client.messages.create(
		model="claude-haiku-4-5-20251001",
		max_tokens=100,
		system="""You are helping a uni student to sort only the important emails to him, reply with exactly one word: Ignored or Intrested""",
		messages=[
			{"role":"user","content": email}
]
)
	label = response.content[0].text
	print(label, "->", email)
