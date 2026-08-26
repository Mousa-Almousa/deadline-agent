from sentence_transformers import SentenceTransformer

# Load the embedding model (runs locally on your Mac, no API key needed)
model = SentenceTransformer("all-MiniLM-L6-v2")

# Three sentences: two about the same topic, one unrelated
sentences = [
    "When is my final exam?",
    "What date is the test scheduled?",
    "I want to order a pizza",
]

# Turn each sentence into numbers (an embedding)
embeddings = model.encode(sentences)

# Show the shape: how many sentences, how many numbers each became
print("Shape:", embeddings.shape)

# Print the first 5 numbers of the first sentence, just to SEE what an embedding looks like
print("First embedding (first 5 numbers):", embeddings[0][:5])