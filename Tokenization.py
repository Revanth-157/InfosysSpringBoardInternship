import os
import faiss
import json
import requests
import numpy as np
from sentence_transformers import SentenceTransformer

# ---------------- CONFIG ----------------
TEXT_DIR = r"C:\Users\revan\Downloads\InfosysSpringboard\output"
EMBED_MODEL = "all-MiniLM-L6-v2"
OLLAMA_MODEL = "gemma:2b"
TOP_K = 6
MAX_CONTEXT_WORDS = 400
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 600
# ---------------------------------------


# 1️⃣ Load documents safely
documents = []

if not os.path.exists(TEXT_DIR):
    raise FileNotFoundError(f"TEXT_DIR not found: {TEXT_DIR}")

for file in os.listdir(TEXT_DIR):
    if file.endswith(".txt"):
        with open(os.path.join(TEXT_DIR, file), "r", encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()
            if text:
                documents.append(text)

print(f"Loaded {len(documents)} lease documents")

if not documents:
    raise ValueError("No text files found or all files are empty")


# 2️⃣ Chunking
def chunk_text(text, chunk_size=120):
    words = text.split()
    return [
        " ".join(words[i:i + chunk_size])
        for i in range(0, len(words), chunk_size)
        if len(words[i:i + chunk_size]) > 20
    ]


chunks = []
for doc in documents:
    chunks.extend(chunk_text(doc))

print(f"Created {len(chunks)} text chunks")

if not chunks:
    raise ValueError("Chunking failed — no chunks created")


# 3️⃣ FAISS embeddings (FIX: float32)
embedder = SentenceTransformer(EMBED_MODEL)

embeddings = embedder.encode(
    chunks,
    convert_to_numpy=True,
    normalize_embeddings=True
).astype(np.float32)

index = faiss.IndexFlatL2(embeddings.shape[1])
index.add(embeddings)

print("FAISS index built")


# 4️⃣ Query (FIX: float32 + correct shape)
query = "lease payment fees penalties early termination mileage insurance"

query_embedding = embedder.encode(
    [query],
    convert_to_numpy=True,
    normalize_embeddings=True
).astype(np.float32)

_, indices = index.search(query_embedding, TOP_K)


# 5️⃣ Filter useful chunks
KEYWORDS = [
    "payment", "fee", "penalty", "termination",
    "mileage", "insurance", "cost", "deposit"
]

context_chunks = []
word_count = 0

for i in indices[0]:
    chunk = chunks[i]
    if any(k in chunk.lower() for k in KEYWORDS):
        words = chunk.split()
        if word_count + len(words) > MAX_CONTEXT_WORDS:
            break
        context_chunks.append(chunk)
        word_count += len(words)

context = "\n\n".join(context_chunks)

if not context.strip():
    raise ValueError("❌ No relevant lease clauses found")

print("\n--- CONTEXT SENT TO OLLAMA ---")
print(context[:1000])
print("--------------------------------")


# 6️⃣ Prompt
prompt = f"""
You are a professional car lease negotiation expert.

Using ONLY the lease clauses below:
1. Identify negotiable fees, deposits, mileage limits, penalties
2. Explain how customers can negotiate each item
3. Provide example negotiation phrases customers can say

Lease clauses:
{context}

Respond with a JSON object in the following format:
{{
  "negotiable_items": [
    {{
      "item": "fee name",
      "description": "brief description",
      "negotiation_tips": "how to negotiate",
      "example_phrase": "example phrase"
    }}
  ],
  "summary": "overall summary"
}}
"""


# 7️⃣ Ollama call
print("\nGenerating negotiation advice...\n")

try:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 500}
        },
        timeout=TIMEOUT
    )
except requests.exceptions.ConnectionError:
    raise RuntimeError("❌ Ollama is not running. Start it using: ollama serve")

if response.status_code != 200:
    print(f"Error: {response.status_code}")
    print(response.text)
    exit()

data = response.json()
result = data.get("response", "")

if len(result.strip()) < 10:
    print("\n⚠️ Weak output from Ollama")
    print("Raw result:", repr(result))
else:
    try:
        parsed = json.loads(result)
        print("Parsed JSON:")
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError as e:
        print(f"\n❌ Failed to parse JSON: {e}")
        print("Raw result:")
        print(result)


# 8️⃣ Final output
print("\n\n" + "=" * 60)
print("NEGOTIATION ADVICE (GEMMA)")
print("=" * 60)
# The JSON is already printed above
