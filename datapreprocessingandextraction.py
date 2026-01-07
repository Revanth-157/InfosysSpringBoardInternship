import os
import pytesseract
from pdf2image import convert_from_path

# ------------------ PATHS ------------------

# Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

BASE_DIR = r"C:\Users\revan\Downloads\InfosysSpringboard"
PDF_FOLDER = os.path.join(BASE_DIR, "leases")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "output")

# Poppler path
POPPLER_PATH = r"C:\Users\revan\Downloads\InfosysSpringboard\poppler-25.12.0\Library\bin"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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

# ------------------ PROCESS PDFs ------------------

for file in os.listdir(PDF_FOLDER):
    if file.lower().endswith(".pdf"):
        pdf_path = os.path.join(PDF_FOLDER, file)
        output_txt = os.path.join(
            OUTPUT_FOLDER,
            file.replace(".pdf", ".txt")
        )

        print(f"🔍 Processing: {file}")
        text = extract_text_from_pdf(pdf_path)

        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"✅ Saved: {output_txt}")

print("\n🎉 OCR extraction completed successfully!")
