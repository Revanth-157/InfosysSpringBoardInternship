import os
import re
import pytesseract
from pdf2image import convert_from_path
from vehicle_enrichment import extract_vehicle_info

# ------------------ PATHS ------------------

# Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

BASE_DIR = r"C:\Users\revan\Downloads\InfosysSpringboard"
PDF_PATH = os.path.join(BASE_DIR, "Car Lease Agreement.pdf")

# Poppler path
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

# ------------------ OCR FUNCTION ------------------

def extract_text_from_pdf(pdf_path):
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

# ------------------ EXTRACTION FUNCTIONS ------------------

def extract_lessor_name(text):
    pattern = r"Lessor\s*Name:\s*([^\n]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None

def extract_lessee_name(text):
    pattern = r"Lessee\s*Name:\s*([^\n]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None

def extract_lease_term(text):
    pattern = r"continue for a period of (\d+) months"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None

def extract_monthly_payment(text):
    pattern = r"monthly lease payment of \$(\d+\.\d+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None

def extract_security_deposit(text):
    pattern = r"security deposit of \$(\d+\.\d+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None

def extract_mileage_allowance(text):
    pattern = r"maximum of (\d+) miles per year"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None

def extract_insurance_requirements(text):
    pattern = r"coverage amounts not less than \$(\d+,?\d*) for bodily injury per person, \$(\d+,?\d*) for bodily injury per accident, and \$(\d+,?\d*) for property damage"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return {
            "bodily_injury_per_person": match.group(1),
            "bodily_injury_per_accident": match.group(2),
            "property_damage": match.group(3)
        }
    return None

# ------------------ COMBINED EXTRACTION FUNCTION ------------------

def extract_combined_info(text: str) -> dict:
    """Extract and combine vehicle and lease information into a single response."""
    vehicle_info = extract_vehicle_info(text)
    lessor_name = extract_lessor_name(text)
    lessee_name = extract_lessee_name(text)
    lease_term = extract_lease_term(text)
    monthly_payment = extract_monthly_payment(text)
    security_deposit = extract_security_deposit(text)
    mileage_allowance = extract_mileage_allowance(text)
    insurance_req = extract_insurance_requirements(text)

    combined = {
        "vehicle_information": {
            "make": vehicle_info.get('make'),
            "model": vehicle_info.get('model'),
            "year": vehicle_info.get('year'),
            "color": vehicle_info.get('color'),
            "vin": vehicle_info.get('vin'),
            "license_plate": vehicle_info.get('license_plate'),
            "odometer_reading": vehicle_info.get('odometer'),
            "decoded_vin_data": vehicle_info.get('decoded'),
            "recalls": vehicle_info.get('recalls')
        },
        "lease_information": {
            "lessor_name": lessor_name,
            "lessee_name": lessee_name,
            "lease_term_months": lease_term,
            "monthly_payment": monthly_payment,
            "security_deposit": security_deposit,
            "mileage_allowance": mileage_allowance,
            "insurance_requirements": insurance_req
        }
    }
    return combined

# ------------------ MAIN ------------------

if __name__ == "__main__":
    for file in os.listdir(LEASES_FOLDER):
        if file.lower().endswith(".pdf"):
            pdf_path = os.path.join(LEASES_FOLDER, file)
            print(f"\n🔍 Processing: {file}")
            text = extract_text_from_pdf(pdf_path)
            print("✅ Text extracted.")

            print("🔍 Extracting combined vehicle and lease information...")
            combined_info = extract_combined_info(text)
            print("✅ Information extracted.")

            print(f"\n--- Combined Information for {file} ---")
            import json
            print(json.dumps(combined_info, indent=2))
