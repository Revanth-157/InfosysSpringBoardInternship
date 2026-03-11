from flask import Flask, request, jsonify
import os
import tempfile
import pytesseract
from pdf2image import convert_from_path
import re
import requests
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss
import json
from vehicle_enrichment import extract_vehicle_info
from contract_fairness_analysis import analyze_contract_fairness
from Tokenization import chunk_text, get_negotiation_advice as get_neg_advice

app = Flask(__name__)

# Paths
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

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

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400

    try:
        # Extract text
        extracted_text = preprocess_pdf(file)

        # Extract datapoints
        datapoints = extract_datapoints(extracted_text)

        # Extract vehicle info
        vehicle_info = extract_vehicle_info(extracted_text)

        # Get negotiation advice
        neg_advice = get_neg_advice(extracted_text)

        # Analyze fairness
        fairness = analyze_contract_fairness(extracted_text)

        # Combined data
        combined_data = {
            "contract_data": datapoints,
            "vehicle_data": vehicle_info,
            "negotiation_advice": neg_advice,
            "fairness_analysis": fairness
        }

        return jsonify({
            'extracted_text': extracted_text,
            'datapoints': datapoints,
            'vehicle_info': vehicle_info,
            'negotiation_advice': neg_advice,
            'fairness_analysis': fairness,
            'combined_data': combined_data
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
