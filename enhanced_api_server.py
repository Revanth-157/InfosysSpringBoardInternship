"""
Enhanced Flask API Server for Car Lease Analysis
Integrates: PDF OCR extraction, Vehicle enrichment (NHTSA), heuristic contract analysis,
and a cloud chatbot backend (configurable). For this deployment the preferred
provider is Mistral (set `MISTRAL_API_KEY` and optionally `MISTRAL_API_URL`/`MISTRAL_MODEL`).
Chat is job-scoped.
"""
from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
import os
import tempfile
import pytesseract
from pdf2image import convert_from_path
import re
import requests
import json
# Heavy ML libraries are imported lazily inside endpoints to speed up startup (avoid blocking health checks)
from vehicle_enrichment import extract_vehicle_info, extract_full_lease_fields
from contract_fairness_analysis import analyze_contract_fairness
import threading
import uuid
import time
# Database
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
# In-memory job store for background analysis tasks
JOBS = {}
# Simple chat context store keyed by job_id (keeps system prompt + messages)
CHATS = {}

# --- DATABASE CONFIGURATION (PostgreSQL via SQLAlchemy) ---
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/carlease')

# Try to use the configured DATABASE_URL (Postgres). If it's not reachable
# fall back to a local SQLite file so the server can run without Docker/Postgres.
def _create_engine_with_fallback(url):
    try:
        e = create_engine(url, echo=False)
        # Try a quick connection to validate availability
        conn = e.connect()
        conn.close()
        print(f"[db] Using DATABASE_URL: {url}")
        return e
    except Exception as ex:
        print(f"[db] Warning: cannot connect to DATABASE_URL={url}: {ex}")
        sqlite_url = 'sqlite:///carlease.db'
        print(f"[db] Falling back to SQLite: {sqlite_url}")
        e = create_engine(sqlite_url, echo=False, connect_args={"check_same_thread": False})
        return e

engine = _create_engine_with_fallback(DATABASE_URL)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    leases = relationship('Lease', back_populates='owner')


class Lease(Base):
    __tablename__ = 'leases'
    id = Column(Integer, primary_key=True)
    lease_id = Column(String(64), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    file_name = Column(String(256))
    extracted_json = Column(Text)  # JSON dump of extraction + datapoints
    job_id = Column(String(64))
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    owner = relationship('User', back_populates='leases')


def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        print('[init_db] Database tables created or already exist')
    except Exception as e:
        print('[init_db] Failed to initialize database:', e)


init_db()

# Create a default test user for convenience (only if not exists)
try:
    db = SessionLocal()
    if not db.query(User).filter(User.username == 'testuser').first():
        u = User(username='testuser', password_hash=generate_password_hash('testpass'))
        db.add(u)
        db.commit()
        print('[init_db] Created default test user: testuser / testpass')
    db.close()
except Exception as e:
    print('[init_db] Could not create default test user:', e)

# JWT config
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev_jwt_secret_change_me')
JWT_ALGO = 'HS256'
JWT_EXP_SECONDS = int(os.environ.get('JWT_EXP_SECONDS', '3600'))


def generate_jwt(user_id: int, username: str):
    payload = {
        'sub': str(user_id),
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXP_SECONDS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def get_user_from_request(req):
    # Try Authorization header first
    auth = req.headers.get('Authorization')
    print(f'[get_user_from_request] Authorization header present: {bool(auth)}')
    if auth:
        print(f'[get_user_from_request] Authorization header starts with: {auth[:20]}...')
    
    if auth and auth.lower().startswith('bearer '):
        token = auth.split(None, 1)[1].strip()
        print(f'[get_user_from_request] Attempting to decode JWT token: {token[:30]}...')
        try:
            decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
            user_id = int(decoded.get('sub'))
            username = decoded.get('username')
            print(f'[get_user_from_request] JWT decoded successfully. user_id={user_id}, username={username}')
            db = SessionLocal()
            user = db.query(User).filter(User.id == user_id).first()
            db.close()
            if user:
                print(f'[get_user_from_request] User found in DB: {user.username}')
            else:
                print(f'[get_user_from_request] User NOT found in DB for user_id={user_id}')
            return user
        except ExpiredSignatureError as e:
            print(f'[get_user_from_request] JWT token expired: {e}')
            return None
        except InvalidTokenError as e:
            print(f'[get_user_from_request] JWT token invalid: {e}')
            return None

    # Fallback to Flask session
    if 'user_id' in session:
        print(f'[get_user_from_request] Using Flask session. user_id={session["user_id"]}')
        db = SessionLocal()
        user = db.query(User).filter(User.id == session['user_id']).first()
        db.close()
        return user
    
    print('[get_user_from_request] No auth header and no session. User is None.')
    return None

app = Flask(__name__)
app.secret_key = 'dev_secret_key_please_change'

# Allow CORS from any origin and allow common methods/headers (use only in dev)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
# Increase max upload size to 50 MB
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# --- USER AUTH (Postgres via SQLAlchemy) ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return jsonify({'error': 'username exists'}), 400
        user = User(username=username, password_hash=generate_password_hash(password))
        db.add(user)
        db.commit()
        return jsonify({'status': 'success', 'message': 'registered'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'invalid credentials'}), 401
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'invalid credentials'}), 401
        # Set session for browsers and also return JWT for API clients
        session['user_id'] = user.id
        session['username'] = user.username
        token = generate_jwt(user.id, user.username)
        return jsonify({'status': 'success', 'message': 'logged in', 'token': token}), 200
    finally:
        db.close()


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return jsonify({'status': 'success', 'message': 'logged out'})


def require_login():
    return 'user_id' in session


@app.route('/my_leases', methods=['GET'])
def my_leases():
    user = get_user_from_request(request)
    print(f'[my_leases] User authenticated: {user}')
    if not user:
        print('[my_leases] No user found - returning 401')
        return jsonify({'error': 'authentication required'}), 401
    
    print(f'[my_leases] Fetching leases for user_id={user.id} ({user.username})')
    db = SessionLocal()
    try:
        rows = db.query(Lease).filter(Lease.user_id == user.id).order_by(Lease.uploaded_at.desc()).all()
        print(f'[my_leases] Found {len(rows)} leases for this user')
        leases = []
        for r in rows:
            try:
                payload = json.loads(r.extracted_json) if r.extracted_json else {}
            except Exception:
                payload = {}
            payload.update({'lease_id': r.lease_id, 'file_name': r.file_name, 'uploaded_at': r.uploaded_at.isoformat()})
            leases.append(payload)
        print(f'[my_leases] Returning {len(leases)} leases')
        return jsonify({'status': 'success', 'leases': leases})
    finally:
        db.close()


@app.route('/compare_leases', methods=['POST'])
def compare_leases():
    if not require_login():
        return jsonify({'error': 'authentication required'}), 401
    data = request.get_json() or {}
    lease_ids = data.get('lease_ids', [])
    db = SessionLocal()
    try:
        rows = db.query(Lease).filter(Lease.lease_id.in_(lease_ids)).all()
        leases = []
        for r in rows:
            try:
                payload = json.loads(r.extracted_json) if r.extracted_json else {}
            except Exception:
                payload = {}
            payload.update({'lease_id': r.lease_id, 'file_name': r.file_name, 'uploaded_at': r.uploaded_at.isoformat()})
            leases.append(payload)
        return jsonify({'status': 'success', 'leases': leases})
    finally:
        db.close()


# Paths for OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard2 - Copy\poppler-25.12.0\Library\bin"


def preprocess_pdf(uploaded_file):
    """Extract text from uploaded PDF using OCR"""
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
    """Extract key datapoints from lease text using regex"""
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


@app.before_request
def log_request_info():
    try:
        print(f"Incoming request: {request.remote_addr} {request.method} {request.path}")
        print(f"Content-Type: {request.content_type} Content-Length: {request.content_length}")
    except Exception:
        # Do not raise from logging
        pass


def get_negotiation_advice(text):
    """
    Heuristic negotiation advice generator (no LLMs).

    Identifies common negotiable items and returns practical tips and example phrases.
    """
    try:
        # Use structured extraction to find key fields
        data = extract_full_lease_fields(text, use_nhtsa=True, use_llm=False)
    except Exception:
        # Fallback to lightweight datapoints
        data = extract_datapoints(text)

    items = []

    monthly = data.get('monthly_payment') or data.get('monthly')
    if monthly:
        items.append({
            'item': 'Monthly Payment',
            'tips': 'Request a lower monthly payment, extended term, or lower interest; offer a larger initial payment to reduce monthly cost.',
            'example': 'Is there flexibility to lower the monthly payment by adjusting the term or offering a higher upfront payment?'
        })

    if data.get('security_deposit'):
        items.append({
            'item': 'Security Deposit',
            'tips': 'Ask to reduce, waive, or convert to refundable based on condition; offer proof of good credit.',
            'example': 'Can the security deposit be reduced or waived with a credit check or by adding automatic payments?'
        })

    if data.get('mileage_allowance_per_year'):
        items.append({
            'item': 'Mileage Allowance',
            'tips': 'Negotiate for a higher annual mileage allowance or lower excess-mileage charge; if you drive less, ask for a lower rate.',
            'example': 'Can the annual mileage allowance be increased to X miles per year or the excess-mileage rate lowered?'
        })

    if data.get('excess_mileage_rate'):
        items.append({
            'item': 'Excess Mileage Rate',
            'tips': 'Request a cap on the per-mile charge or a reduced dollar-per-mile rate.',
            'example': 'Would you consider lowering the excess-mileage charge to $0.10/mile?'
        })

    if data.get('late_fee'):
        items.append({
            'item': 'Late Fee',
            'tips': 'Ask for a grace period, lower late fee, or graduated penalties instead of flat large fees.',
            'example': 'Is there a 5–10 day grace period before late fees apply, or can the late fee be reduced?'
        })

    if data.get('early_termination_clause'):
        items.append({
            'item': 'Early Termination',
            'tips': 'Negotiate limits to termination penalties or allow transfer of lease to another party.',
            'example': 'Can termination penalties be reduced or can the lease be transferred without excessive fees?'
        })

    summary = 'Identify negotiable items and ask for reductions on high fees, increased mileage allowance, and clearer termination terms.'
    return {'negotiable_items': items, 'summary': summary}


# ---------------- TOKENIZATION-STYLE ANALYSIS -------------------
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
{
  "negotiation_advice": {
    "negotiable_items": [
      {
        "item": "Name of fee/term",
        "description": "Definition",
        "negotiation_strategy": "How to reduce it",
        "example_phrase": "Script for the customer"
      }
    ],
    "red_flags": [
      {
        "issue": "Specific concern",
        "severity": "High/Medium/Low",
        "why": "Risk explanation"
      }
    ],
    "green_flags": [
      {
        "benefit": "Positive term",
        "value": "Benefit to consumer"
      }
    ],
    "deal_rating": "Score 1-10",
    "final_summary": "Overall expert opinion"
  }
}
"""


def tokenization_style_analysis(text):
    """Lightweight wrapper: perform heuristic fairness analysis (no LLMs).

    Uses the `analyze_contract_fairness` function from `contract_fairness_analysis`.
    """
    try:
        return analyze_contract_fairness(text)
    except Exception as e:
        return {"error": str(e)}


@app.route('/tokenization_analyze', methods=['POST'])
def tokenization_route():
    """Endpoint: Accepts JSON with 'text' (or optionally a file via multipart) and returns Tokenization-style analysis."""
    if request.content_type and request.content_type.startswith('multipart'):
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        text = preprocess_pdf(file)
    else:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'No text provided'}), 400
        text = data['text']

    try:
        analysis = tokenization_style_analysis(text)
        return jsonify({'status': 'success', 'analysis': analysis})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "Car Lease Analysis API"})


@app.route('/process_lease_pdf', methods=['POST'])
def process_lease_pdf():
    """
    Process a lease PDF file and extract all information
    Combines: text extraction, datapoints, vehicle info, and full analysis (fairness + negotiation)
    
    Query params (optional):
      - fast_mode=true: skip NHTSA calls only (keeps LLM analysis for fairness/negotiation)
      - use_nhtsa=true/false: enable/disable NHTSA VIN decoding (default true unless fast_mode)
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400

    # Parse fast-mode: skips NHTSA but keeps LLM analysis
    fast_mode = request.args.get('fast_mode', 'false').lower() == 'true'
    use_nhtsa = request.args.get('use_nhtsa', 'false' if fast_mode else 'true').lower() == 'true'

    try:
        # Extract text from PDF (slowest step - OCR)
        extracted_text = preprocess_pdf(file)

        # Quick datapoints extraction
        datapoints = extract_datapoints(extracted_text)

        # Use OCR-extracted text and vehicle enrichment ONLY (no LLM merging here)
        vehicle_info = extract_vehicle_info(extracted_text)
        
        # Extract full lease fields immediately for initial response
        full_extraction = extract_full_lease_fields(extracted_text, use_nhtsa=use_nhtsa, use_llm=False)

        # Create a background job to run heavy analysis (negotiation/fairness/LLM merges)
        job_id = str(uuid.uuid4())
        JOBS[job_id] = {
            'status': 'pending',
            'result': None,
            'started_at': time.time()
        }

        # Persist the immediate extraction so the chat assistant can access it
        JOBS[job_id]['extracted_contract'] = {
            'text': extracted_text,
            'full_extraction': full_extraction,
            'datapoints': datapoints,
            'vehicle_info': vehicle_info
        }

        # Store lease record in the database (associate with logged-in user if present)
        lease_id = str(uuid.uuid4())
        lease_payload = {
            'lease_id': lease_id,
            'file_name': file.filename,
            'extracted_text': extracted_text,
            'datapoints': datapoints,
            'vehicle_info': vehicle_info,
            'full_extraction': full_extraction,
            'job_id': job_id,
            'uploaded_at': time.time()
        }
        db = SessionLocal()
        try:
            lease_row = Lease(
                lease_id=lease_id,
                file_name=file.filename,
                extracted_json=json.dumps(lease_payload),
                job_id=job_id
            )
            user = get_user_from_request(request)
            print(f'[process_lease_pdf] User from get_user_from_request: {user}')
            if user:
                lease_row.user_id = user.id
                print(f'[process_lease_pdf] Assigning lease to user_id={user.id} ({user.username})')
            else:
                print(f'[process_lease_pdf] NO USER FOUND - lease will have user_id=NULL')
            db.add(lease_row)
            db.commit()
            print(f'[process_lease_pdf] Lease saved to DB with lease_id={lease_id}, user_id={lease_row.user_id}')
        except Exception as e:
            db.rollback()
            print('[process_lease_pdf] Failed to save lease to DB:', e)
        finally:
            db.close()

        def _background_work(jobid, text, use_nhtsa_flag):
            try:
                negotiation = get_negotiation_advice(text)
                fairness = tokenization_style_analysis(text)
                merged = dict(full_extraction)
                merged['negotiation_advice'] = negotiation
                merged['fairness_analysis'] = fairness
                JOBS[jobid]['result'] = {
                    'negotiation_advice': negotiation,
                    'fairness_analysis': fairness,
                    'full_extraction': merged
                }
                JOBS[jobid]['extracted_contract'] = merged
                JOBS[jobid]['status'] = 'done'
                
                # Update the database with complete analysis results
                db_update = SessionLocal()
                try:
                    lease_row = db_update.query(Lease).filter(Lease.job_id == jobid).first()
                    if lease_row:
                        complete_payload = json.loads(lease_row.extracted_json) if lease_row.extracted_json else {}
                        complete_payload.update({
                            'negotiation_advice': negotiation,
                            'fairness_analysis': fairness
                        })
                        lease_row.extracted_json = json.dumps(complete_payload)
                        db_update.commit()
                        print(f'[_background_work] Updated lease {jobid} with complete analysis results')
                    else:
                        print(f'[_background_work] Lease not found for job_id={jobid}')
                except Exception as e:
                    db_update.rollback()
                    print(f'[_background_work] Failed to update lease in DB: {e}')
                finally:
                    db_update.close()
            except Exception as e:
                JOBS[jobid]['result'] = {'error': str(e)}
                JOBS[jobid]['status'] = 'error'

        # Start background thread (daemon so it won't block shutdown)
        t = threading.Thread(target=_background_work, args=(job_id, extracted_text, use_nhtsa), daemon=True)
        t.start()

        try:
            system_prompt = (
                "You are a helpful negotiation assistant for car lease contracts. "
                "Use the provided lease extraction data to answer questions, suggest negotiation strategies, and highlight risks. "
                "Provide concise, actionable advice.\n\n"
                "Lease Extraction JSON:\n" + json.dumps(full_extraction) + "\n\n"
                "Key Datapoints:\n" + json.dumps(datapoints)
            )
        except Exception:
            system_prompt = "You are a helpful negotiation assistant for car lease contracts. Use the provided lease data to assist the user."

        CHATS[job_id] = [
            {"role": "system", "content": system_prompt},
        ]

        response_data = {
            "status": "pending",
            "job_id": job_id,
            "lease_id": lease_id,
            "extracted_text": extracted_text,
            "lease_datapoints": datapoints,
            "vehicle_info": vehicle_info,
            "full_extraction": full_extraction,
            "summary": {
                "file": file.filename,
                "text_length": len(extracted_text),
                "extraction_started": True,
                "fast_mode": fast_mode,
                "features_used": {
                    "nhtsa_decoding": use_nhtsa,
                    "llm_analysis": False
                }
            }
        }

        try:
            print("[process_lease_pdf] immediate response:\n", json.dumps(response_data, indent=2)[:4000])
        except Exception:
            print("[process_lease_pdf] immediate response (unable to serialize)")
        return jsonify(response_data)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("Error processing PDF:\n", tb)
        return jsonify({'error': 'Server error processing PDF', 'detail': str(e)}), 500


@app.route('/extract_text', methods=['POST'])
def extract_text():
    """Extract text from PDF only"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400

    try:
        text = preprocess_pdf(file)
        return jsonify({
            "status": "success",
            "text": text,
            "length": len(text)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/analyze_lease_text', methods=['POST'])
def analyze_lease_text():
    """Analyze lease text (without PDF upload)"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    text = data['text']
    try:
        datapoints = extract_datapoints(text)
        # Use OCR-based vehicle enrichment only (no LLM merging)
        vehicle_info = extract_vehicle_info(text)
        full_extraction = vehicle_info
        negotiation_advice = get_negotiation_advice(text)
        # Use tokenization_style_analysis (heuristic) for fairness calculation
        fairness_analysis = tokenization_style_analysis(text)

        return jsonify({
            "status": "success",
            "lease_datapoints": datapoints,
            "vehicle_info": vehicle_info,
            "full_extraction": full_extraction,
            "negotiation_advice": negotiation_advice,
            "fairness_analysis": fairness_analysis
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/extract_vehicle_info', methods=['POST'])
def extract_vehicle_info_endpoint():
    """Extract vehicle information from text"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    try:
        # Provide both vehicle-only extraction and full lease extraction
        vehicle_info = extract_vehicle_info(data['text'])
        # Return OCR/enrichment-only extraction (no LLM enhancement)
        full_extraction = vehicle_info
        return jsonify({
            "status": "success",
            "vehicle_info": vehicle_info,
            "full_extraction": full_extraction
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/analyze_contract_fairness', methods=['POST'])
def analyze_fairness():
    """Analyze contract fairness"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    try:
        fairness = analyze_contract_fairness(data['text'])
        return jsonify({
            "status": "success",
            "fairness_analysis": fairness
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_negotiation_advice', methods=['POST'])
def get_advice():
    """Get negotiation advice for lease"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    try:
        advice = get_negotiation_advice(data['text'])
        return jsonify({
            "status": "success",
            "advice": advice
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Health endpoint (responds to OPTIONS preflight and GET)
@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    if request.method == 'OPTIONS':
        # Return 200 with CORS headers handled by flask-cors
        return ('', 200)
    return jsonify({
        "status": "ok",
        "service": "Car Lease Analysis API",
        "hosts": [
            request.host,
            request.remote_addr
        ]
    })


@app.route('/analysis_status/<job_id>', methods=['GET'])
def analysis_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({'error': 'job_not_found'}), 404
    resp = {
        'job_id': job_id,
        'status': job.get('status'),
        'started_at': job.get('started_at')
    }
    if job.get('status') in ('done', 'error'):
        resp['result'] = job.get('result')
    return jsonify(resp)


@app.route('/extract_datapoints', methods=['POST'])
def get_datapoints():
    """Extract lease datapoints"""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    try:
        datapoints = extract_datapoints(data['text'])
        return jsonify({
            "status": "success",
            "datapoints": datapoints
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _call_chat_llm(prompt_text, api_key=None, model=None, timeout=12):
    """
    Helper to call a cloud LLM provider for chat. Currently configured to use
    Mistral (configurable via `MISTRAL_API_KEY`, `MISTRAL_API_URL`, `MISTRAL_MODEL`).

    If no Mistral key is provided, returns None to trigger the local heuristic
    fallback assistant.
    """

    # Prefer an explicit API key param, then environment variable.
    mistral_key = api_key or os.getenv('MISTRAL_API_KEY')
    if not mistral_key:
        print("[_call_chat_llm] No MISTRAL_API_KEY provided; using local fallback")
        return None

    mistral_model = model or os.getenv('MISTRAL_MODEL', 'open-mistral-7b')
    mistral_api_url = os.getenv('MISTRAL_API_URL', 'https://api.mistral.ai/v1/chat/completions')

    try:
        print(f"[_call_chat_llm] Calling Mistral at {mistral_api_url} model={mistral_model}")

        headers = {
            "Authorization": f"Bearer {mistral_key}",
            "Content-Type": "application/json"
        }

        # Mistral chat/completions endpoint expects messages format
        body = {
            "model": mistral_model,
            "messages": [
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        # Use connect/read timeout tuple so we fail fast and fall back locally
        response = requests.post(mistral_api_url, json=body, headers=headers, timeout=(5, timeout))
        print(f"[_call_chat_llm] Mistral response status: {response.status_code}")

        if response.status_code == 200:
            j = response.json()

            # Mistral returns: {"choices": [{"message": {"content": "..."}}]}
            text = None
            if isinstance(j, dict) and 'choices' in j and isinstance(j['choices'], list) and len(j['choices']) > 0:
                c0 = j['choices'][0]
                if isinstance(c0, dict) and 'message' in c0:
                    msg = c0['message']
                    if isinstance(msg, dict) and 'content' in msg:
                        text = msg['content']

            if text:
                print("[_call_chat_llm] Mistral returned successfully")
                return text.strip()
            else:
                print("[_call_chat_llm] Mistral returned no text; falling back")
        else:
            # Log body to help debug errors
            body_preview = response.text[:400] if response is not None else '<no body>'
            print(f"[_call_chat_llm] Mistral error: status {response.status_code}, body={body_preview}")
    except requests.exceptions.Timeout:
        print("[_call_chat_llm] Mistral request timed out")
    except requests.exceptions.ConnectionError as e:
        print(f"[_call_chat_llm] Mistral connection error: {e}")
    except Exception as e:
        print(f"[_call_chat_llm] Mistral call failed: {e}")

    # Provider unavailable — return None to trigger the local heuristic fallback
    print("[_call_chat_llm] Mistral unavailable; will use local heuristic fallback")
    return None


def build_local_assistant_response(job_id, user_message):
    """
    Enhanced local assistant fallback that uses stored extraction and heuristic analyzers
    to produce a helpful reply when Ollama is unavailable.
    """
    try:
        job = JOBS.get(job_id, {})
        extracted = job.get('extracted_contract') or {}

        # If extracted is a dict with a 'text' field, prefer that for analysis
        text = extracted.get('text') if isinstance(extracted, dict) else None
        if not text:
            # Try to pull text from background result if available
            res = job.get('result') or {}
            fe = res.get('full_extraction') if isinstance(res, dict) else None
            text = fe.get('raw_text') if isinstance(fe, dict) else None

        # Gather datapoints and short summaries
        datapoints = extracted.get('datapoints') if isinstance(extracted, dict) else None
        vehicle_info = extracted.get('vehicle_info') if isinstance(extracted, dict) else None
        full_extraction = extracted.get('full_extraction') if isinstance(extracted, dict) else None

        # Build comprehensive response
        parts = []
        parts.append("🤖 **Local Negotiation Assistant** (Ollama not available)")
        parts.append("")

        # Show key extracted data
        if full_extraction:
            parts.append("📋 **Lease Summary:**")
            if full_extraction.get('lessee_name'):
                parts.append(f"• Lessee: {full_extraction['lessee_name']}")
            if full_extraction.get('lessor_name'):
                parts.append(f"• Lessor: {full_extraction['lessor_name']}")
            if full_extraction.get('monthly_payment'):
                parts.append(f"• Monthly Payment: \\${full_extraction['monthly_payment']}")
            if full_extraction.get('lease_term_months'):
                parts.append(f"• Term: {full_extraction['lease_term_months']} months")
            if full_extraction.get('mileage_allowance_per_year'):
                parts.append(f"• Annual Mileage: {full_extraction['mileage_allowance_per_year']} miles")
            parts.append("")

        if vehicle_info:
            parts.append("🚗 **Vehicle Info:**")
            for key in ['make', 'model', 'year', 'vin']:
                if vehicle_info.get(key):
                    parts.append(f"• {key.title()}: {vehicle_info.get(key)}")
            parts.append("")

        # Answer the user's specific question
        if user_message:
            msg_lower = user_message.lower()
            if 'monthly' in msg_lower or 'payment' in msg_lower:
                parts.append("💰 **Monthly Payment Advice:**")
                parts.append("• Current: $" + str(full_extraction.get('monthly_payment', 'unknown')))
                parts.append("• Negotiation tips: Ask for lower rate, longer term, or higher mileage allowance")
                parts.append("• Example: 'Can we reduce the monthly payment by extending the term?'")
            elif 'mileage' in msg_lower:
                parts.append("📊 **Mileage Advice:**")
                parts.append("• Allowance: " + str(full_extraction.get('mileage_allowance_per_year', 'unknown')) + " miles/year")
                parts.append("• Excess rate: $" + str(full_extraction.get('excess_mileage_rate', 'unknown')) + "/mile")
                parts.append("• Negotiate for higher allowance or lower excess rate")
            elif 'deposit' in msg_lower:
                parts.append("🏦 **Security Deposit Advice:**")
                parts.append("• Amount: $" + str(full_extraction.get('security_deposit', 'unknown')))
                parts.append("• Ask to reduce, waive, or convert to refundable")
                parts.append("• Example: 'Can the deposit be reduced with a credit check?'")
            elif 'fair' in msg_lower or 'good' in msg_lower:
                parts.append("⚖️ **Fairness Assessment:**")
                parts.append("• This appears to be a standard lease agreement")
                parts.append("• Key terms: 36-month term, $350/month, 12k miles/year")
                parts.append("• Consider negotiating deposit and mileage terms")
            else:
                parts.append("💡 **General Negotiation Tips:**")
                parts.append("• Focus on monthly payment, security deposit, and mileage allowance")
                parts.append("• Ask for concessions based on your credit or driving record")
                parts.append("• Be prepared to walk away if terms aren't favorable")

        # Fallback general summary
        if len(parts) == 1:
            parts.append('I have analyzed your lease document. Key terms extracted:')
            if full_extraction:
                parts.append('• Monthly payment, term, mileage allowance, and vehicle details are available')
            parts.append('Ask me specific questions about payments, mileage, or fairness!')

        return "\n".join(parts)
    except Exception as e:
        print('Local assistant build failed:', e)
        return "🤖 Local Assistant: I'm here to help with lease negotiation! Ask me about monthly payments, mileage, deposits, or general fairness. (Ollama not available)"


@app.route('/extract_full_lease', methods=['POST'])
def extract_full_lease():
    """Extract full lease fields using `extract_full_lease_fields`.

    Accepts JSON body: {"text": "...", "use_llm": true/false}
    """
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    # For this deployment, LLM-based enhancement is disabled. We perform heuristic
    # extraction and NHTSA decoding only.
    use_llm = False
    try:
        result = extract_full_lease_fields(data['text'], use_nhtsa=True, use_llm=False)
        return jsonify({"status": "success", "full_extraction": result, "note": "LLM-based enhancement disabled"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/chat/<job_id>', methods=['POST'])
def chat_for_job(job_id):
    """Chat endpoint bound to a specific job_id. The job's extraction data is used
    as the system context for the assistant. Request body JSON:
      {"message": "user message"}
    
    Uses Grok (xAI) if available; otherwise uses local heuristic assistant.
    Error details are never exposed to the frontend—always returns 200 with a reply.
    """
    if job_id not in CHATS:
        return jsonify({'error': 'chat_context_not_found', 'message': 'No chat context for this job_id'}), 404

    data = request.get_json() or {}
    user_msg = data.get('message')
    if not user_msg:
        return jsonify({'error': 'No message provided'}), 400

    # Append user message to conversation
    CHATS[job_id].append({"role": "user", "content": user_msg})

    # Build a simple combined prompt: include system prompt and last few exchanges
    try:
        # Use up to last 10 messages for context
        recent = CHATS[job_id][-10:]
        prompt_parts = []
        for m in recent:
            role = m.get('role')
            content = m.get('content')
            if role == 'system':
                prompt_parts.append(f"SYSTEM:\n{content}\n")
            elif role == 'user':
                prompt_parts.append(f"USER:\n{content}\n")
            else:
                prompt_parts.append(f"ASSISTANT:\n{content}\n")
        prompt_text = "\n---\n".join(prompt_parts)
    except Exception:
        prompt_text = user_msg

    # Try to call Grok (via helper). If unavailable, use local fallback.
    reply = _call_chat_llm(prompt_text)
    
    if reply is None:
        # Grok not available — use local fallback assistant
        fallback_reply = build_local_assistant_response(job_id, user_msg)
        CHATS[job_id].append({"role": "assistant", "content": fallback_reply})
        # Return 200 with the fallback reply and a subtle note (not an error)
        return jsonify({'status': 'success', 'reply': fallback_reply, 'assistant_type': 'local_fallback'}), 200

    # Append assistant reply to conversation
    CHATS[job_id].append({"role": "assistant", "content": reply})
    return jsonify({'status': 'success', 'reply': reply, 'assistant_type': 'grok'})



@app.route('/chat_health', methods=['GET'])
def chat_health():
    """Diagnostic endpoint to verify chat LLM connectivity.

    Tests Mistral API if `MISTRAL_API_KEY` is configured. Returns 200 with
    a status and never raises an error to the caller.
    """
    mistral_api_key = os.getenv('MISTRAL_API_KEY')

    if not mistral_api_key:
        return jsonify({'status': 'warning', 'message': 'No MISTRAL_API_KEY configured. Using local fallback.', 'assistant_type': 'local_fallback'}), 200

    try:
        mistral_model = os.getenv('MISTRAL_MODEL', 'open-mistral-7b')
        mistral_api_url = os.getenv('MISTRAL_API_URL', 'https://api.mistral.ai/v1/chat/completions')

        headers = {
            "Authorization": f"Bearer {mistral_api_key}",
            "Content-Type": "application/json"
        }

        body = {
            "model": mistral_model,
            "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
            "max_tokens": 10
        }

        print(f"[chat_health] Testing Mistral at {mistral_api_url}")
        response = requests.post(mistral_api_url, json=body, headers=headers, timeout=(5,10))
        print(f"[chat_health] Response status: {response.status_code}")

        if response.status_code == 200:
            j = response.json()
            text = None
            # Mistral format: {"choices": [{"message": {"content": "..."}}]}
            if isinstance(j, dict) and 'choices' in j and isinstance(j['choices'], list) and len(j['choices']) > 0:
                c0 = j['choices'][0]
                if isinstance(c0, dict) and 'message' in c0:
                    msg = c0.get('message')
                    if isinstance(msg, dict):
                        text = msg.get('content')

            if text:
                return jsonify({'status': 'ok', 'assistant_type': 'mistral', 'response': text.strip()}), 200
            else:
                return jsonify({'status': 'warning', 'message': 'Mistral returned no text', 'assistant_type': 'local_fallback'}), 200
        else:
            body_preview = response.text[:400] if response is not None else '<no body>'
            return jsonify({'status': 'warning', 'message': f'Mistral error {response.status_code}. Using local fallback.', 'assistant_type': 'local_fallback', 'details': body_preview}), 200
    except requests.exceptions.Timeout:
        return jsonify({'status': 'warning', 'message': 'Mistral request timed out. Using local fallback.', 'assistant_type': 'local_fallback'}), 200
    except requests.exceptions.ConnectionError:
        return jsonify({'status': 'warning', 'message': 'Mistral connection error. Using local fallback.', 'assistant_type': 'local_fallback'}), 200
    except Exception as e:
        return jsonify({'status': 'warning', 'message': f'Mistral unavailable ({str(e)}); using local fallback', 'assistant_type': 'local_fallback'}), 200



if __name__ == '__main__':
    # Check for required dependencies
    print("Starting Enhanced Car Lease Analysis API...")
    
    # Check Mistral configuration
    mistral_api_key = os.getenv('MISTRAL_API_KEY')
    mistral_model = os.getenv('MISTRAL_MODEL', 'open-mistral-7b')

    if mistral_api_key:
        print(f"✅ Chat LLM: Mistral {mistral_model} (MISTRAL_API_KEY configured)")
        print("  Chat will use Mistral cloud for responses")
    else:
        print("⚠️  Chat LLM: No MISTRAL_API_KEY configured")
        print("  Chat will use local heuristic assistant as fallback")
        print("  To enable Mistral cloud, set the MISTRAL_API_KEY environment variable")
        print("  Optional: Set MISTRAL_MODEL (default: open-mistral-7b) or MISTRAL_API_URL")
    print("")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
