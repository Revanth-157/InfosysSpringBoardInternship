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
MAX_CONTEXT_WORDS = 500  # Increased for more detail
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 600
GROK_API_URL = os.getenv('GROK_API_URL', '')
GROK_API_KEY = os.getenv('GROK_API_KEY', '')

# ---------------- PROMPT TEMPLATE ----------------
# Using a template allows you to modify instructions without touching the logic.
LEASE_TEMPLATE = """
### ROLE
You are a senior Automotive Finance Auditor and Negotiation Expert. 

### TASK
Analyze the provided lease document excerpts. Provide a detailed breakdown of the financial health of this deal.

### CONTEXT: LEASE EXCERPTS
{context}

### ANALYSIS REQUIREMENTS
1. **Red Flags**: Identify hidden costs, predatory clauses, or unusually high penalties.
2. **Green Flags**: Identify consumer-friendly terms (e.g., gap insurance, low fees).
3. **Negotiable Items**: Identify fees, mileage limits, or deposits that can be modified.

### OUTPUT FORMAT
You MUST respond strictly in valid JSON format.
{{
  "negotiation_advice": {{
    "negotiable_items": [
      {{
        "item": "Name of fee/term",
        "description": "Definition",
        "negotiation_strategy": "How to reduce it",
        "example_phrase": "Script for the customer"
      }}
    ],
    "red_flags": [
      {{
        "issue": "Specific concern",
        "severity": "High/Medium/Low",
        "why": "Risk explanation"
      }}
    ],
    "green_flags": [
      {{
        "benefit": "Positive term",
        "value": "Benefit to consumer"
      }}
    ],
    "deal_rating": "Score 1-10",
    "final_summary": "Overall expert opinion"
  }}
}}
"""

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

print(f"✅ Loaded {len(documents)} lease documents")

# 2️⃣ Chunking
def chunk_text(text, chunk_size=120):
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size) if len(words[i:i + chunk_size]) > 20]

chunks = []
for doc in documents:
    chunks.extend(chunk_text(doc))

print(f"✅ Created {len(chunks)} text chunks")

# 3️⃣ FAISS embeddings
embedder = SentenceTransformer(EMBED_MODEL)
embeddings = embedder.encode(chunks, convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
index = faiss.IndexFlatL2(embeddings.shape[1])
index.add(embeddings)

# 4️⃣ Querying
query = "lease payment fees penalties early termination mileage insurance security deposit"
query_embedding = embedder.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
_, indices = index.search(query_embedding, TOP_K)

# 5️⃣ Filter & Context Building
KEYWORDS = ["payment", "fee", "penalty", "termination", "mileage", "insurance", "cost", "deposit", "charge"]
context_chunks = []
word_count = 0

for i in indices[0]:
    chunk = chunks[i]
    if any(k in chunk.lower() for k in KEYWORDS):
        words = chunk.split()
        if word_count + len(words) > MAX_CONTEXT_WORDS: break
        context_chunks.append(chunk)
        word_count += len(words)

context = "\n\n".join(context_chunks)

# 6️⃣ Generate Prompt using Template
full_prompt = LEASE_TEMPLATE.format(context=context)

# 7️⃣ Ollama call
print("\n🚀 Sending request to LLM (Grok preferred, Ollama fallback)...")

def _call_llm(prompt_text, max_tokens=1000, temperature=0.1):
  if GROK_API_URL:
    headers = {'Content-Type': 'application/json'}
    if GROK_API_KEY:
      headers['Authorization'] = f'Bearer {GROK_API_KEY}'
    try:
      r = requests.post(GROK_API_URL, json={"prompt": prompt_text, "max_tokens": max_tokens, "temperature": temperature}, headers=headers, timeout=TIMEOUT)
      if r.status_code == 200:
        j = r.json()
        for k in ('text', 'response', 'output', 'generated_text', 'result'):
          if k in j and isinstance(j[k], str):
            return j[k]
        if isinstance(j.get('candidates'), list) and j['candidates']:
          c = j['candidates'][0]
          parts = c.get('content', {}).get('parts') or c.get('parts')
          if parts:
            return parts[0].get('text') if isinstance(parts[0], dict) else str(parts[0])
        return r.text
    except Exception:
      pass

  # Fallback to Ollama
  try:
    r = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": prompt_text, "stream": False, "options": {"num_predict": max_tokens, "temperature": temperature}}, timeout=TIMEOUT)
    if r.status_code == 200:
      return r.json().get('response', '')
  except Exception:
    pass
  return ''

try:
  result = _call_llm(full_prompt)
  if not result:
    print("❌ LLM call failed (Grok/Ollama)")
  else:
    clean_result = result.strip().replace("```json", "").replace("```", "")
    try:
      parsed = json.loads(clean_result)
      print("\n" + "="*30 + " DETAILED ANALYSIS " + "="*30)
      print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
      print("\n❌ Failed to parse JSON. Raw output below:")
      print(result)
except Exception as e:
  print(f"❌ Error during LLM call: {e}")

print("\n" + "="*79)