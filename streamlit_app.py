import streamlit as st
import os
import pytesseract
from pdf2image import convert_from_path
import tempfile
import re
import faiss
import json
import requests
import numpy as np
from sentence_transformers import SentenceTransformer
from vehicle_enrichment import extract_vehicle_info

# ---------------- CONFIG ----------------
EMBED_MODEL = "all-MiniLM-L6-v2"
OLLAMA_MODEL = "gemma:2b"
TOP_K = 6
MAX_CONTEXT_WORDS = 400
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 600
GROK_API_URL = os.getenv('GROK_API_URL', '')
GROK_API_KEY = os.getenv('GROK_API_KEY', '')

# Paths
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

# ---------------- FUNCTIONS ----------------

def preprocess_pdf(uploaded_file):
    """Extract text from uploaded PDF"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_path = tmp_file.name

    try:
        pages = convert_from_path(
            tmp_path,
            dpi=300,
            poppler_path=POPPLER_PATH
        )

        full_text = ""
        for i, page in enumerate(pages, start=1):
            full_text += f"\n--- Page {i} ---\n"
            full_text += pytesseract.image_to_string(page, lang="eng")

        return full_text
    finally:
        os.unlink(tmp_path)

def extract_datapoints(text):
    """Extract key datapoints from lease text"""
    datapoints = {}

    # Extract fees
    fee_match = re.search(r'Fees:\s*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if fee_match:
        datapoints['fee_details'] = fee_match.group(1).strip()

    # Extract deposit
    deposit_match = re.search(r'Deposit:\s*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if deposit_match:
        datapoints['deposit_details'] = deposit_match.group(1).strip()

    # Extract mileage limit
    mileage_match = re.search(r'Mileage Limit(.*?)(?:\n|$)', text, re.IGNORECASE)
    if mileage_match:
        datapoints['mileage_limit_details'] = mileage_match.group(1).strip()

    # Extract excess mileage
    excess_match = re.search(r'Excess Mileage:\s*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if excess_match:
        datapoints['excess_mileage_details'] = excess_match.group(1).strip()

    # Extract fuel
    fuel_match = re.search(r'Fuel:\s*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if fuel_match:
        datapoints['fuel_details'] = fuel_match.group(1).strip()

    return datapoints

def get_negotiation_advice(text):
    """Get negotiation advice using FAISS and Ollama"""
    # Chunk text
    def chunk_text(text, chunk_size=120):
        words = text.split()
        return [
            " ".join(words[i:i + chunk_size])
            for i in range(0, len(words), chunk_size)
            if len(words[i:i + chunk_size]) > 20
        ]

    chunks = chunk_text(text)
    if not chunks:
        return {"error": "No chunks created"}

    # Embeddings
    embedder = SentenceTransformer(EMBED_MODEL)
    embeddings = embedder.encode(chunks, convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    # Query
    query = "lease payment fees penalties early termination mileage insurance"
    query_embedding = embedder.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
    _, indices = index.search(query_embedding, TOP_K)

    # Filter context
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
        return {"error": "No relevant lease clauses found"}

    # Prompt
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

    # Prefer Grok API, else fallback to Ollama
    def _call_llm(prompt_text, max_tokens=500, temperature=0.1):
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

        try:
            r = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": prompt_text, "stream": False, "options": {"num_predict": max_tokens}}, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json().get('response', '')
        except Exception:
            pass
        return ''

    result = _call_llm(prompt)
    if not result:
        return {"error": "LLM call failed (Grok/Ollama)"}

    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError:
        # Try to extract JSON substring
        m = re.search(r"(\{[\s\S]*\})", result)
        if m:
            try:
                parsed = json.loads(m.group(1))
                return parsed
            except Exception:
                pass
        return {"error": "Failed to parse JSON from LLM", "raw": result}

# ---------------- STREAMLIT UI ----------------

st.title("Lease Processing Application")

st.header("1. Preprocess PDF (Extract Text)")
uploaded_file = st.file_uploader("Upload a PDF lease document", type="pdf")

if uploaded_file is not None:
    if st.button("Extract Text"):
        with st.spinner("Extracting text from PDF..."):
            extracted_text = preprocess_pdf(uploaded_file)
        st.success("Text extracted!")
        st.text_area("Extracted Text", extracted_text, height=300)

        # Store in session
        st.session_state['extracted_text'] = extracted_text

st.header("2. Extract Datapoints")
if 'extracted_text' in st.session_state:
    if st.button("Extract Key Datapoints"):
        datapoints = extract_datapoints(st.session_state['extracted_text'])
        st.json(datapoints)
        st.session_state['datapoints'] = datapoints

st.header("3. Get Negotiation Advice")
if 'extracted_text' in st.session_state:
    if st.button("Generate Negotiation Advice"):
        with st.spinner("Generating advice..."):
            advice = get_negotiation_advice(st.session_state['extracted_text'])
        st.json(advice)

st.header("4. Vehicle Enrichment")
if 'extracted_text' in st.session_state:
    if st.button("Extract Vehicle Info"):
        with st.spinner("Extracting VINs and decoding vehicle info..."):
            vehicle_info = extract_vehicle_info(st.session_state['extracted_text'])
        if not vehicle_info.get('vins'):
            st.warning("No VINs detected in the extracted text. You can try a different document or check OCR quality.")
        st.json(vehicle_info)
        st.session_state['vehicle_info'] = vehicle_info

st.header("5. Combined Contract and Vehicle Data")
if 'extracted_text' in st.session_state and 'datapoints' in st.session_state and 'vehicle_info' in st.session_state:
    if st.button("Generate Combined Response"):
        combined_data = {
            "contract_data": st.session_state['datapoints'],
            "vehicle_data": st.session_state['vehicle_info']
        }
        st.json(combined_data)
        st.session_state['combined_data'] = combined_data
