# Car Lease Assistant - Flutter Frontend

This minimal Flutter app uploads a lease PDF to the existing Flask API (`/process_lease_pdf`) and displays the structured JSON response.

Setup:
1. Install Flutter and ensure `flutter doctor` is clean.
2. From the `flutter_frontend` folder run:
   - `flutter pub get`
   - `flutter run` (choose a device or emulator)

Notes:
- If running on Android emulator, the API base is set to `http://10.0.2.2:5000` in `lib/main.dart`. Change `_apiBase` if you run on a real device or different host.
- The backend endpoints exist in `enhanced_api_server.py` and rely on Ollama and Tesseract/poppler for model/ocr. Start the Flask server before using the app:
  `python enhanced_api_server.py`
