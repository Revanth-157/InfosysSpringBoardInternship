import os
import json
import pytesseract
from pdf2image import convert_from_path
import re
from vehicle_enrichment import extract_vehicle_info

# Paths
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

def preprocess_pdf(pdf_path):
    """Extract text from PDF file path"""
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

def main():
    pdf_path = "Car Lease Agreement.pdf"
    if not os.path.exists(pdf_path):
        print(f"PDF file not found: {pdf_path}")
        return

    print("Extracting text from PDF...")
    extracted_text = preprocess_pdf(pdf_path)

    print("Extracting datapoints...")
    datapoints = extract_datapoints(extracted_text)

    print("Extracting vehicle info...")
    vehicle_info = extract_vehicle_info(extracted_text)

    combined_data = {
        "contract_data": datapoints,
        "vehicle_data": vehicle_info
    }

    print("Combined Data:")
    print(json.dumps(combined_data, indent=4))

if __name__ == "__main__":
    main()
