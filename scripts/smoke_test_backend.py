import requests
import os
import time
import uuid
import json
from sqlalchemy import create_engine, text

API = os.environ.get('API_BASE', 'http://127.0.0.1:5000')
DB_URL = os.environ.get('DATABASE_URL', 'sqlite:///carlease.db')

s = requests.Session()

username = f"smoketest_{int(time.time())}"
password = "smokepass"
print('Using API:', API)
print('Using DB:', DB_URL)

# Register
r = s.post(f"{API}/register", json={'username': username, 'password': password})
print('register', r.status_code, r.text)

# Login
r = s.post(f"{API}/login", json={'username': username, 'password': password})
print('login', r.status_code, r.text)
if r.status_code != 200:
    raise SystemExit('Login failed')

# Connect to DB and insert a lease owned by this user
engine = create_engine(DB_URL)
with engine.connect() as conn:
    # find user id
    user_row = conn.execute(text("SELECT id FROM users WHERE username = :u"), {'u': username}).fetchone()
    if not user_row:
        raise SystemExit('User not found in DB')
    user_id = user_row[0]
    lease_id = str(uuid.uuid4())
    payload = {
        'lease_id': lease_id,
        'file_name': 'smoke.pdf',
        'extracted_text': 'smoke test',
        'datapoints': {},
        'vehicle_info': {},
        'full_extraction': {},
        'job_id': '',
        'uploaded_at': int(time.time())
    }
    # Insert row
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(text(
        "INSERT INTO leases (lease_id, user_id, file_name, extracted_json, job_id, uploaded_at) VALUES (:lease_id, :user_id, :file_name, :extracted_json, :job_id, :uploaded_at)"
    ), {
        'lease_id': lease_id,
        'user_id': user_id,
        'file_name': 'smoke.pdf',
        'extracted_json': json.dumps(payload),
        'job_id': '',
        'uploaded_at': now
    })
    conn.commit()
    print('Inserted lease', lease_id)

# Call my_leases
r = s.get(f"{API}/my_leases")
print('my_leases', r.status_code)
print(r.text)

# Done
print('Smoke test complete')
