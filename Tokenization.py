import os
import faiss
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# ---------------- CONFIG ----------------
TEXT_DIR = r"C:\Users\revan\Downloads\InfosysSpringboard\output"
EMBED_MODEL = "all-MiniLM-L6-v2"
LLM_MODEL = "google/flan-t5-base"
TOP_K = 5
MAX_CONTEXT_WORDS = 400
# ---------------------------------------

# 1️⃣ Load documents
documents = []
for file in os.listdir(TEXT_DIR):
    if file.endswith(".txt"):
        with open(os.path.join(TEXT_DIR, file), "r", encoding="utf-8") as f:
            documents.append(f.read())

print(f"Loaded {len(documents)} lease documents")

# 2️⃣ Chunking
def chunk_text(text, chunk_size=100):
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

chunks = []
for doc in documents:
    chunks.extend(chunk_text(doc))

print(f"Created {len(chunks)} text chunks")

# 3️⃣ FAISS with normalization (IMPORTANT)
embedder = SentenceTransformer(EMBED_MODEL)
embeddings = embedder.encode(chunks, normalize_embeddings=True)

index = faiss.IndexFlatIP(embeddings.shape[1])  # cosine similarity
index.add(embeddings)
print("FAISS index built")

# 4️⃣ Query
query = "Which clauses in a car lease can be negotiated to reduce price, fees, or penalties?"
query_embedding = embedder.encode([query], normalize_embeddings=True)

_, indices = index.search(query_embedding, TOP_K)

# Build context safely
context_chunks = []
word_count = 0
for i in indices[0]:
    words = chunks[i].split()
    if word_count + len(words) > MAX_CONTEXT_WORDS:
        break
    context_chunks.append(chunks[i])
    word_count += len(words)

context = "\n\n".join(context_chunks)

# DEBUG (optional but useful)
print("\n--- RETRIEVED CONTEXT ---")
print(context[:800])
print("------------------------\n")

# 5️⃣ Load LLM
tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(LLM_MODEL)

# 6️⃣ STRONG TASK-STYLE PROMPT (CRITICAL FIX)
prompt = f"""
Task: Extract negotiation opportunities from a car lease.

From the lease text below:
1. List clauses that can be negotiated
2. Identify any fees or penalties
3. Explain how each item can be reduced
4. Give practical negotiation advice

Lease text:
{context}

Output format:
- Negotiable Clause:
- Why it matters:
- How to negotiate it:
"""

inputs = tokenizer(
    prompt,
    return_tensors="pt",
    truncation=True,
    max_length=512
)

outputs = model.generate(
    **inputs,
    max_new_tokens=350,
    temperature=0.0,
    repetition_penalty=1.3,
    no_repeat_ngram_size=3
)

response = tokenizer.decode(outputs[0], skip_special_tokens=True)

print("\n" + "=" * 60)
print("NEGOTIATION ADVICE")
print("=" * 60)
print(response)
