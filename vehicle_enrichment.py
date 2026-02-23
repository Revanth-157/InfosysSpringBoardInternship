import re
import requests
import os
import json
from typing import List, Dict, Optional

# NHTSA VPIC API (free, rate-limited)
NHTSA_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
NHTSA_RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&year={year}&format=json"


def extract_vins_from_text(text: str) -> List[str]:
    """Find candidate VINs in text (17-char, excluding I/O/Q).

    Returns a list of unique VINs found, uppercased.
    """
    if not text:
        return []

    # VIN: 17 alphanumeric characters excluding I, O, Q
    pattern = r"\b([A-HJ-NPR-Z0-9]{17})\b"
    found = re.findall(pattern, text.upper())
    # Deduplicate while preserving order
    seen = set()
    vins = []
    for v in found:
        if v not in seen:
            seen.add(v)
            vins.append(v)
    return vins


def extract_make_from_text(text: str) -> Optional[str]:
    """Extract vehicle make from text using regex."""
    pattern = r"Make:\s*([A-Za-z\s]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_model_from_text(text: str) -> Optional[str]:
    """Extract vehicle model from text using regex."""
    pattern = r"Model:\s*([A-Za-z0-9\s]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_year_from_text(text: str) -> Optional[str]:
    """Extract vehicle year from text using regex."""
    pattern = r"Year:\s*(\d{4})"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_color_from_text(text: str) -> Optional[str]:
    """Extract vehicle color from text using regex."""
    pattern = r"Color:\s*([A-Za-z\s]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_license_plate_from_text(text: str) -> Optional[str]:
    """Extract license plate from text using regex."""
    pattern = r"License Plate Number:\s*([A-Z0-9\s]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_odometer_from_text(text: str) -> Optional[str]:
    """Extract odometer reading from text using regex."""
    pattern = r"Odometer Reading at Lease Commencement:\s*(\d+)\s*miles"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def decode_vin_nhtsa(vin: str, timeout: int = 10) -> Optional[Dict]:
    """Call NHTSA VPIC API to decode a VIN. Returns parsed dict or None on failure."""
    if not vin or len(vin) != 17:
        return None

    try:
        url = NHTSA_DECODE_URL.format(vin=vin)
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    results = data.get("Results")
    if not results or not isinstance(results, list):
        return None

    r = results[0]
    # Return all fields from the API response for comprehensive extraction
    out = r.copy()
    out["VIN"] = vin  # Ensure VIN is included
    return out


def get_vehicle_recalls(make: str, model: str, year: str, timeout: int = 10) -> Optional[List[Dict]]:
    """Fetch vehicle recalls from NHTSA API based on make, model, year."""
    if not make or not model or not year:
        return None

    try:
        url = NHTSA_RECALLS_URL.format(make=make.upper(), model=model.upper(), year=year)
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    results = data.get("results", [])
    if not isinstance(results, list):
        return None

    # Return list of recall dicts
    return results


def extract_vehicle_info(text: str, use_nhtsa: bool = True) -> Dict:
    """High-level helper: extract vehicle info from text and (optionally) decode VINs via NHTSA.

    Returns a dict with keys:
      - make: extracted make
      - model: extracted model
      - year: extracted year
      - color: extracted color
      - vin: extracted VIN (first one if multiple)
      - license_plate: extracted license plate
      - odometer: extracted odometer reading
      - decoded: decoded info dict from NHTSA (if available)
      - recalls: list of recall dicts from NHTSA (if available)
    """
    result = {
        "make": extract_make_from_text(text),
        "model": extract_model_from_text(text),
        "year": extract_year_from_text(text),
        "color": extract_color_from_text(text),
        "vin": None,
        "license_plate": extract_license_plate_from_text(text),
        "odometer": extract_odometer_from_text(text),
        "decoded": None,
        "recalls": None
    }

    vins = extract_vins_from_text(text)
    if vins:
        result["vin"] = vins[0]  # Take the first VIN
        if use_nhtsa:
            decoded = decode_vin_nhtsa(vins[0])
            if decoded:
                result["decoded"] = decoded
                # Fetch recalls using make, model, year from decoded data or fallback to text extraction
                make = decoded.get("Make") or result.get("make")
                model = decoded.get("Model") or result.get("model")
                year = decoded.get("ModelYear") or result.get("year")
                if make and model and year:
                    recalls = get_vehicle_recalls(make, model, year)
                    if recalls:
                        result["recalls"] = recalls

    return result

    # Additional heuristics: if lessor/lessee not found by regex, scan nearby lines
    # (This code is unreachable because of early return above. Move heuristics earlier.)


def _regex_search(pattern: str, text: str, flags=0) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def extract_full_lease_fields(text: str, use_nhtsa: bool = True, use_llm: bool = False, ollama_url: Optional[str] = None) -> Dict:
    """Extract a wide range of lease fields from raw lease text.

    - Uses heuristic regex extraction for common lease fields (lessor/lessee, dates, payments,
      mileage allowance, insurance requirements, VINs, etc.).
    - When `use_nhtsa` is True will call `extract_vehicle_info` to decode VIN and fetch recalls.
    - When `use_llm` is True and `ollama_url` is provided, will attempt a best-effort POST to the
      LLM endpoint to get a structured extraction (this is an optional enhancement; failures fall
      back to heuristics).

    Returns a dict containing the extracted fields.
    """
    out: Dict = {}

    # Parties
    out['lessor_name'] = _regex_search(r"Lessor\s*[:\-]?\s*Name\s*[:\-]?\s*(.+)", text, re.I) or _regex_search(r"Lessor[:\s]+([A-Za-z0-9\s,\.]+)", text, re.I)
    out['lessor_address'] = _regex_search(r"Lessor[:\s\n\r]+[\s\S]*?Address[:\-]?\s*([A-Za-z0-9\s,\.]+)", text, re.I)
    out['lessor_phone'] = _regex_search(r"Lessor[\s\S]*?Phone[:\-]?\s*([\d\(\)\-\s\.]+)", text, re.I)
    out['lessor_email'] = _regex_search(r"Lessor[\s\S]*?Email[:\-]?\s*([\w\.\-]+@[\w\.\-]+)", text, re.I)

    out['lessee_name'] = _regex_search(r"Lessee\s*[:\-]?\s*Name\s*[:\-]?\s*(.+)", text, re.I) or _regex_search(r"Lessee[:\s]+([A-Za-z0-9\s,\.]+)", text, re.I)
    out['lessee_address'] = _regex_search(r"Lessee[\s\S]*?Address[:\-]?\s*([A-Za-z0-9\s,\.]+)", text, re.I)
    out['lessee_phone'] = _regex_search(r"Lessee[\s\S]*?Phone[:\-]?\s*([\d\(\)\-\s\.]+)", text, re.I)
    out['lessee_email'] = _regex_search(r"Lessee[\s\S]*?Email[:\-]?\s*([\w\.\-]+@[\w\.\-]+)", text, re.I)
    out['drivers_license'] = _regex_search(r"Driver(?:'s)? License(?: Number)?[:\-]?\s*([A-Z0-9\-]+)", text, re.I)

    # Leased Vehicle - textual fields
    out['make'] = extract_make_from_text(text) or _regex_search(r"Make[:\s]*([A-Za-z\s]+)", text, re.I)
    out['model'] = extract_model_from_text(text) or _regex_search(r"Model[:\s]*([A-Za-z0-9\s]+)", text, re.I)
    out['year'] = extract_year_from_text(text) or _regex_search(r"Year[:\s]*(\d{4})", text, re.I)
    out['color'] = extract_color_from_text(text) or _regex_search(r"Color[:\s]*([A-Za-z\s]+)", text, re.I)
    out['license_plate'] = extract_license_plate_from_text(text) or _regex_search(r"License Plate(?: Number)?[:\s]*([A-Z0-9\s]+)", text, re.I)
    out['odometer'] = extract_odometer_from_text(text) or _regex_search(r"Odometer(?: Reading)?(?: at Lease Commencement)?:?\s*(\d+)", text, re.I)

    # VINs (list) and pick first
    vins = extract_vins_from_text(text)
    out['vins'] = vins
    out['vin'] = vins[0] if vins else None

    # Lease financial terms
    out['monthly_payment'] = _regex_search(r"Monthly\s+Payment[:\s\$]*([\d,]+\.?\d*)", text, re.I) or _regex_search(r"monthly lease payment of\s*\$?([\d,]+\.?\d*)", text, re.I)
    out['security_deposit'] = _regex_search(r"security deposit[:\s\$]*([\d,]+\.?\d*)", text, re.I)
    out['late_fee'] = _regex_search(r"late fee[:\s\$]*([\d,]+\.?\d*)", text, re.I)

    # Mileage
    out['mileage_allowance_per_year'] = _regex_search(r"(\d{1,6})\s*miles\s*per\s*year", text, re.I) or _regex_search(r"maximum of\s*(\d{1,6})\s*miles per year", text, re.I)
    out['excess_mileage_rate'] = _regex_search(r"charged at a rate of\s*\$?([\d\.]+)\s*per mile", text, re.I) or _regex_search(r"excess mileage.*?\$([\d\.]+)", text, re.I)

    # Term and dates
    out['lease_term_months'] = _regex_search(r"period of\s*(\d{1,3})\s*months", text, re.I)
    out['term_start'] = _regex_search(r"commence(?:s)? on\s*([\w\d,\s/-]+)\b", text, re.I)
    out['term_end'] = _regex_search(r"ending on\s*([\w\d,\s/-]+)\b", text, re.I)

    # Insurance, maintenance, termination
    out['insurance_required'] = _regex_search(r"maintain\s+comprehensive and collision insurance[\s\S]*?not less than\s*(.*?)(\.|$)", text, re.I)
    out['maintenance_responsibility'] = _regex_search(r"Lessee shall be responsible for (.*?)\.", text, re.I)
    out['early_termination_clause'] = _regex_search(r"Early Termination[\s\S]*?([\s\S]{0,300}?)\n\d+\.", text, re.I)

    # Governing law
    out['governing_law'] = _regex_search(r"governed by and construed in accordance with the laws of the State of ([A-Za-z]+)", text, re.I)

    # Use NHTSA to decode VIN and populate extra vehicle fields if requested
    if use_nhtsa and out.get('vin'):
        try:
            decoded = decode_vin_nhtsa(out['vin'])
            if decoded:
                out['decoded'] = decoded
                # enrich make/model/year with decoded values if missing
                out.setdefault('make', decoded.get('Make') or out.get('make'))
                out.setdefault('model', decoded.get('Model') or out.get('model'))
                out.setdefault('year', decoded.get('ModelYear') or out.get('year'))
                # include common decoded fields that may be helpful
                for k in ('BodyClass', 'VehicleType', 'PlantCountry', 'Manufacturer', 'EngineModel'):
                    if decoded.get(k):
                        out.setdefault(k.lower(), decoded.get(k))
                # recalls
                try:
                    make = decoded.get('Make') or out.get('make')
                    model = decoded.get('Model') or out.get('model')
                    year = decoded.get('ModelYear') or out.get('year')
                    if make and model and year:
                        recalls = get_vehicle_recalls(make, model, str(year))
                        if recalls:
                            out['recalls'] = recalls
                except Exception:
                    pass
        except Exception:
            out['decoded_error'] = 'nhtsa_lookup_failed'

    # Optional LLM extraction: best-effort; don't raise on failure
    if use_llm:
        try:
            prompt = (
                "Extract a JSON object containing these fields from the lease text: "
                "lessor_name, lessor_email, lessee_name, lessee_email, vin, make, model, year, monthly_payment, "
                "security_deposit, mileage_allowance_per_year, excess_mileage_rate, lease_term_months, term_start, term_end. "
                "Return only valid JSON with null for missing fields.\nLease text:\n" + text
            )

            # Determine LLM endpoint: prefer provided ollama_url, else environment GROK_API_URL, else ollama
            grok_url = os.getenv('GROK_API_URL', '')
            grok_key = os.getenv('GROK_API_KEY', '')

            def _call_llm(prompt_text):
                # Try Grok
                if grok_url:
                    headers = {'Content-Type': 'application/json'}
                    if grok_key:
                        headers['Authorization'] = f'Bearer {grok_key}'
                    try:
                        r = requests.post(grok_url, json={"prompt": prompt_text, "max_tokens": 800}, headers=headers, timeout=15)
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

                # Try provided ollama_url
                if ollama_url:
                    try:
                        r = requests.post(ollama_url, json={"prompt": prompt_text, "max_tokens": 800}, timeout=15)
                        if r.status_code == 200:
                            return r.text
                    except Exception:
                        pass

                return ''

            resp_text = _call_llm(prompt)
            if resp_text:
                # Try to parse raw JSON from the response text
                m = re.search(r"(\{[\s\S]*\})", resp_text)
                if m:
                    try:
                        parsed = json.loads(m.group(1))
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                if v is not None:
                                    out[k] = v
                    except Exception:
                        pass
        except requests.RequestException:
            out['llm_error'] = 'llm_unreachable'

    # Additional heuristics: if lessor/lessee names not found, scan nearby lines
    try:
        if not out.get('lessor_name'):
            # Find 'Lessor' section and look for a following 'Name:' or the next non-empty line
            m = re.search(r"\bLessor\b", text, re.IGNORECASE)
            if m:
                start = m.end()
                snippet = text[start:start+300]
                nm = re.search(r"Name[:\s]*([A-Za-z0-9\s,\.\&'-]{2,80})", snippet, re.IGNORECASE)
                if nm:
                    out['lessor_name'] = nm.group(1).strip()
                else:
                    # fallback: first line with letters
                    lines = [l.strip() for l in snippet.splitlines() if l.strip()]
                    if lines:
                        out['lessor_name'] = lines[0][:80]

        if not out.get('lessee_name'):
            m = re.search(r"\bLessee\b", text, re.IGNORECASE)
            if m:
                start = m.end()
                snippet = text[start:start+300]
                nm = re.search(r"Name[:\s]*([A-Za-z0-9\s,\.\&'-]{2,80})", snippet, re.IGNORECASE)
                if nm:
                    out['lessee_name'] = nm.group(1).strip()
                else:
                    lines = [l.strip() for l in snippet.splitlines() if l.strip()]
                    if lines:
                        out['lessee_name'] = lines[0][:80]
    except Exception:
        pass

    return out


if __name__ == '__main__':
    # Quick local test using the sample text (a subset of the user's example)
    sample = '''Car Lease Agreement\nThis Car Lease Agreement ("Agreement") is entered into on ,\nby and between the Lessor and the Lessee, collectively referred to as "Parties."\n1. Parties\n1.1. Lessor\nName: Auto Lease Corp.\nAddress: 123 Main Street, Anytown, IN 46201\nPhone: (317) 555-1234\nEmail: info@autoleasecorp.com\n1.2. Lessee\nName: John Doe\nAddress: 456 Oak Avenue, Indianapolis, IN 46202\nPhone: (317) 555-5678\nEmail: john.doe@example.com\nDriver's License Number:\n2. Leased Vehicle\n• Make: Toyota\n• Model: Camry\n• Year: 2024\n• Color: Silver\n• Vehicle Identification Number (VIN): JTDKN3DP3R3000000\n• License Plate Number: IN A12 3BC\n• Odometer Reading at Lease Commencement: miles\n3. Lease Term\nThe term of this Agreement shall commence on and shall\ncontinue for a period of 36 months, ending on .\n4. Lease Payments\n4.1. Monthly Payment\nThe Lessee shall pay to the Lessor a monthly lease payment of $350.00 on the 1st\nday of each month, commencing on .\n4.2. Security Deposit\nThe Lessee shall pay a security deposit of $700.00 upon the execution of this\nAgreement.\n5. Mileage Allowance\nThe Lessee is permitted to drive the vehicle for a maximum of 12000 miles per\nyear. Any mileage exceeding this allowance will be charged at a rate of $0.20 per\nmile at the end of the lease term.'''

    print('Running quick extractor on sample...')
    res = extract_full_lease_fields(sample, use_nhtsa=False)
    import json
    print(json.dumps(res, indent=2))
