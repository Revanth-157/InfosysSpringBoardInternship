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
TOP_K = 6
MAX_CONTEXT_WORDS = 400
TIMEOUT = 600

# Paths for OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

import re
import json
from typing import Dict, Any, List, Optional
from vehicle_enrichment import extract_vehicle_info


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except Exception:
        return None


def analyze_contract_fairness(text: str, vehicle_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Lightweight heuristic fairness analysis (no LLMs).

    - Uses regex heuristics to find key financial and term values.
    - Uses `vehicle_info` (from NHTSA) when provided to factor in recalls/safety.
    - Returns a dict with `fairness_score` (1-10), `red_flags`, `green_flags`, and `summary`.
    """
    # Basic extraction helpers
    def _find(pattern: str) -> Optional[str]:
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else None

    monthly = _safe_float(_find(r"Monthly\s+Payment[:\s\$]*([\d,]+\.?\d*)") or _find(r"monthly lease payment of\s*\$?([\d,]+\.?\d*)"))
    deposit = _safe_float(_find(r"security deposit[:\s\$]*([\d,]+\.?\d*)"))
    late_fee = _safe_float(_find(r"late fee[:\s\$]*([\d,]+\.?\d*)"))
    mileage_allowance = None
    ma = _find(r"(\d{1,6})\s*miles\s*per\s*year") or _find(r"maximum of\s*(\d{1,6})\s*miles per year")
    if ma:
        try:
            mileage_allowance = int(ma.replace(',', ''))
        except Exception:
            mileage_allowance = None
    excess_rate = _safe_float(_find(r"excess mileage.*?\$([\d\.]+)") or _find(r"charged at a rate of\s*\$?([\d\.]+)\s*per mile"))
    early_term = True if re.search(r"early termination|termination fee|early terminate", text, re.I) else False
    gap_insurance = True if re.search(r"gap insurance", text, re.I) else False

    # Start with neutral score
    score = 7.0
    red_flags: List[Dict[str, Any]] = []
    green_flags: List[Dict[str, Any]] = []

    # Analyze monthly vs deposit
    if monthly is None:
        red_flags.append({"clause": "Monthly payment missing", "issue": "Unable to find monthly payment", "severity": "high"})
        score -= 2
    else:
        if deposit is not None and monthly > 0 and deposit > monthly * 3:
            red_flags.append({"clause": "High security deposit", "issue": f"Deposit {deposit} is more than 3x monthly payment {monthly}", "severity": "medium"})
            score -= 1
        if monthly > 2000:
            red_flags.append({"clause": "High monthly payment", "issue": f"Monthly payment {monthly} appears high", "severity": "medium"})
            score -= 1
        else:
            green_flags.append({"benefit": "Affordable monthly payment", "value": f"{monthly}"})

    # Late fee
    if late_fee is not None:
        if monthly and late_fee > monthly * 0.5:
            red_flags.append({"clause": "High late fee", "issue": f"Late fee {late_fee} is >50% of monthly payment", "severity": "high"})
            score -= 2
        else:
            green_flags.append({"benefit": "Reasonable late fee", "value": f"{late_fee}"})

    # Mileage
    if mileage_allowance is not None:
        if mileage_allowance < 10000:
            red_flags.append({"clause": "Low mileage allowance", "issue": f"{mileage_allowance} miles/year is low", "severity": "medium"})
            score -= 1
        else:
            green_flags.append({"benefit": "Generous mileage allowance", "value": f"{mileage_allowance} miles/year"})
    else:
        red_flags.append({"clause": "Mileage allowance missing", "issue": "Could not find mileage allowance", "severity": "medium"})
        score -= 1

    # Excess mileage rate
    if excess_rate is not None:
        if excess_rate > 0.25:
            red_flags.append({"clause": "High excess mileage rate", "issue": f"{excess_rate}/mile is high", "severity": "medium"})
            score -= 1
        else:
            green_flags.append({"benefit": "Reasonable excess mileage rate", "value": f"{excess_rate}/mile"})

    # Early termination
    if early_term:
        red_flags.append({"clause": "Early termination clause", "issue": "Contract contains early termination terms that may penalize lessee", "severity": "medium"})
        score -= 1

    # Gap insurance is positive
    if gap_insurance:
        green_flags.append({"benefit": "Gap insurance included", "value": "Protects lessee against total loss shortfall"})
        score += 0.5

    # Vehicle info / NHTSA recalls influence
    try:
        if not vehicle_info:
            vehicle_info = extract_vehicle_info(text)
        recalls = vehicle_info.get('recalls') if isinstance(vehicle_info, dict) else None
        if recalls:
            num_recalls = len(recalls)
            red_flags.append({"clause": "Vehicle recalls", "issue": f"{num_recalls} recall(s) found for this vehicle", "severity": "medium" if num_recalls < 5 else "high"})
            score -= min(2, num_recalls * 0.3)
            # include recall summaries as red flags
            for r in recalls[:5]:
                desc = r.get('component') or r.get('summary') or r.get('nhtsa_action') or str(r)
                red_flags.append({"clause": "Recall detail", "issue": desc, "severity": "low"})
        else:
            green_flags.append({"benefit": "No recalls found", "value": "NHTSA reported no recalls for this vehicle"})
    except Exception:
        # Non-fatal; don't block analysis
        pass

    # Normalize score to 1-10
    final = max(1, min(10, round(score)))

    summary = f"Fairness score {final} based on fees, mileage, deposits, termination clauses and vehicle recalls."

    return {
        "fairness_score": final,
        "red_flags": red_flags,
        "green_flags": green_flags,
        "summary": summary
    }
    