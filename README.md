# Car Lease Assistant (Infosys Springboard)

This repository contains a **Car Lease Assistant** toolkit with:

- A **Flask backend API** that accepts lease PDF uploads, extracts text via OCR, parses lease terms, performs fairness analysis, and stores results (with user accounts + JWT auth).
- A **Flutter frontend** UI to upload lease PDFs, view analysis, compare leases, and chat about a lease.
- A **Streamlit exploratory UI** for quick experimentation with extraction, negotiation advice, and vehicle VIN enrichment.
- A **heuristic fairness scoring engine** to highlight red flags, green flags, and compute a simple fairness score.

> ⚠️ This project is currently oriented toward local development. Some paths and configuration are hard-coded for a Windows environment.

---

## 🧩 Repository Structure

```
├── enhanced_api_server.py      # Main Flask backend, auth + job polling + chat
├── api_server.py               # Simpler earlier Flask prototype
├── contract_fairness_analysis.py  # Fairness scoring heuristics
├── vehicle_enrichment.py       # VIN lookup + NHTSA decoding
├── Tokenization.py             # LLM-based negotiation advice support
├── streamlit_app.py            # Streamlit experimental UI
├── flutter_frontend/           # Flutter app for upload + analysis + chat
├── requirements.txt            # Python dependencies
├── poppler-25.12.0/            # Bundled Poppler binaries (Windows)
├── leases/                     # (Optional) saved lease folder
├── output/                     # (Optional) output folder
└── ...
```

---

## 🚀 Getting Started (Python Backend)

### 1) Create a Python virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 2) Install requirements

```bash
pip install -r requirements.txt
```

### 3) Run the server

```bash
python enhanced_api_server.py
```

This will start a Flask server at **http://127.0.0.1:5000** by default.

### Backend Notes
- The server uses **SQLite (`carlease.db`) by default** if `DATABASE_URL` isn't configured.
- JWT secrets default to `dev_jwt_secret_change_me`. Set `JWT_SECRET` environment variable for production.
- OCR requires **Tesseract** + **Poppler** to be installed (paths are currently hard-coded for Windows in the source).

---

## 📱 Running the Flutter Frontend

### 1) Install Flutter

Follow the official Flutter installation: https://flutter.dev/docs/get-started/install

### 2) Run the app

From repository root:

```bash
cd flutter_frontend
flutter pub get
flutter run
```

The app expects the backend at **http://127.0.0.1:5000** for desktop/web and **http://10.0.2.2:5000** for Android emulator.

---

## 🧪 Streamlit UI (Optional)

```bash
python streamlit_app.py
```

Then open the URL printed by Streamlit (usually `http://localhost:8501`).

---

## 🧠 What this Project Does

### ✅ PDF -> Lease Data (OCR + Parsing)
- Extracts text via `pytesseract` + `pdf2image`
- Parses common lease datapoints (payment, mileage, fees, deposits)

### ✅ Fairness Analysis + Flags
- Provides a fairness score (1–10)
- Highlights red flags (e.g. high fees, low mileage, steep penalties)
- Highlights green flags (e.g. gap insurance included)

### ✅ Chat & Negotiation Advice
- Backend supports chat scoped to a lease `job_id`
- Negotiation tips can be generated using local LLMs (Ollama/Grok) and FAISS semantic search

### ✅ Saved Lease Storage
- Users can register/login
- Uploaded leases are stored in the database and can be reloaded later

---

## 🛠️ Improvements You Can Make

- ✅ Make file paths configurable (Tesseract + Poppler)
- ✅ Add a structured README for running locally (this file)
- ✅ Add unit tests for parsing & scoring
- ✅ Make job state resilient across server restarts (persist to DB)
- ✅ Improve error reporting for missing LLM / backend failures

---

## 🧷 Useful Commands

| Action | Command |
|------|---------|
| Install Python deps | `pip install -r requirements.txt` |
| Run backend | `python enhanced_api_server.py` |
| Run Flutter UI | `cd flutter_frontend && flutter run` |
| Run Streamlit UI | `python streamlit_app.py` |

---

## 📦 Notes / Caveats
- The current backend is optimized for local dev.
- Paths for Tesseract/Poppler are hard-coded (Windows). You’ll need to adjust them for other platforms.
- The Flutter UI assumes the API is reachable on localhost.

---

If you'd like, I can also add a concise `docker-compose.yml` to run the backend + PostgreSQL + Flutter web build together, or help convert the hard-coded paths into ENV variables for cross-platform compatibility.