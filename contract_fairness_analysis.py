import os
import faiss
import json
import requests
import numpy as np
from sentence_transformers import SentenceTransformer
import pytesseract
from pdf2image import convert_from_path
import tempfile

# ---------------- CONFIG ----------------
TEXT_DIR = r"C:\Users\revan\Downloads\InfosysSpringboard\output"
EMBED_MODEL = "all-MiniLM-L6-v2"
OLLAMA_MODEL = "gemma:2b"
TOP_K = 6
MAX_CONTEXT_WORDS = 400
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 600

# Paths for OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

# ---------------- FUNCTIONS ----------------

def preprocess_pdf_to_text(pdf_path):
    """Extract text from PDF using OCR (from datapreprocessingandextraction.py)"""
    pages = convert_from_path(
        pdf_path,
        dpi=300,
        poppler_path=POPPLER_PATH
    )

    full_text = ""
    for i, page in enumerate(pages, start=1):
        full_text += f"\n--- Page {i} ---\n"
        full_text += pytesseract.image_to_string(page, lang="eng")

    return full_text

def load_text_from_file(file_path):
    """Load text from a .txt file"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()

def chunk_text(text, chunk_size=120):
    """Chunk text (from Tokenization.py)"""
    words = text.split()
    return [
        " ".join(words[i:i + chunk_size])
        for i in range(0, len(words), chunk_size)
        if len(words[i:i + chunk_size]) > 20
    ]

def analyze_contract_fairness(text):
    """Analyze contract for fairness score and red flags using FAISS and Ollama"""
    chunks = chunk_text(text)
    if not chunks:
        return {"error": "No chunks created from text"}

    # Embeddings (from Tokenization.py)
    embedder = SentenceTransformer(EMBED_MODEL)
    embeddings = embedder.encode(
        chunks,
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype(np.float32)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    # Query for fairness-related content
    query = "contract fairness red flags penalties unfair terms termination fees deposits mileage insurance"
    query_embedding = embedder.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype(np.float32)

    _, indices = index.search(query_embedding, TOP_K)

    # Collect context chunks (top relevant, no keyword filter)
    context_chunks = []
    word_count = 0

    for i in indices[0]:
        chunk = chunks[i]
        words = chunk.split()
        if word_count + len(words) > MAX_CONTEXT_WORDS:
            break
        context_chunks.append(chunk)
        word_count += len(words)

    context = "\n\n".join(context_chunks)
    if not context.strip():
        return {"error": "No relevant contract clauses found for analysis"}

    # Prompt for fairness analysis
    prompt = f"""
You are a legal expert analyzing lease contracts for fairness and red flags.

Analyze the contract clauses below for:
1. Fairness Score: Rate the overall fairness of the contract on a scale of 1-10 (1 = very unfair, 10 = very fair). Consider factors like balance of rights, clarity, reasonableness of terms.
2. Red Flags: List any potentially unfair, risky, or problematic clauses (e.g., high penalties, one-sided terms, hidden fees).

Use ONLY the clauses provided. Be objective and specific.

Contract clauses:
{context}

Respond with a JSON object in the following format:
{{
  "fairness_score": 7,
  "red_flags": [
    {{
      "clause": "brief description of clause",
      "issue": "why it's a red flag",
      "severity": "low/medium/high"
    }}
  ],
  "summary": "brief overall assessment"
}}
"""

    # Ollama call (from Tokenization.py)
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 600}
            },
            timeout=TIMEOUT
        )
    except requests.exceptions.ConnectionError:
        return {"error": "Ollama is not running. Start it using: ollama serve"}

    if response.status_code != 200:
        return {"error": f"Ollama error: {response.status_code} - {response.text}"}

    data = response.json()
    result = data.get("response", "")

    if len(result.strip()) < 10:
        return {"error": "Weak output from Ollama", "raw": result}

    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse JSON: {e}", "raw": result}

# ---------------- MAIN ----------------

if __name__ == "__main__":
    # Default to lease1.txt for demo
    input_path = r"C:\Users\revan\Downloads\InfosysSpringboard\output\lease1.txt"

    if not os.path.exists(input_path):
        print(f"Default file not found: {input_path}")
        input_path = input("Enter path to PDF or text file: ").strip()
        if not os.path.exists(input_path):
            print(f"File not found: {input_path}")
            exit(1)

    # Load text
    if input_path.lower().endswith(".pdf"):
        print("Processing PDF...")
        text = preprocess_pdf_to_text(input_path)
    elif input_path.lower().endswith(".txt"):
        print("Loading text file...")
        text = load_text_from_file(input_path)
    else:
        print("Unsupported file type. Use .pdf or .txt")
        exit(1)

    if not text.strip():
        print("No text extracted.")
        exit(1)

    print("Analyzing contract for fairness and red flags...")
    result = analyze_contract_fairness(text)

    print("\n" + "=" * 60)
    print("CONTRACT FAIRNESS ANALYSIS")
    print("=" * 60)
    print(json.dumps(result, indent=2))