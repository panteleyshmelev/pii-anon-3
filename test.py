# test.py (updated to be Windows-terminal friendly)
import os
import requests
import json
from dotenv import load_dotenv

# --- Load Configuration from your .env file ---
load_dotenv()
API_KEY = os.getenv("ANYTHINGLLM_KEY")
ENDPOINT = os.getenv("ANYTHINGLLM_URL")
WORKSPACE = os.getenv("ANYTHINGLLM_WS")

# --- Define Request Details ---
CHAT_URL = f"{ENDPOINT}/api/v1/workspace/{WORKSPACE}/chat"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Use the same prompt structure from your app
ALLOWED_PII_TYPES = [
    "Name", "EmailAddress", "PhoneNumber", "PhysicalAddress",
    "SocialSecurityNumber", "SingaporeNRIC", "DateOfBirth"
]
PROMPT_TEMPLATE = f"""
You are an expert PII extractor. Return **only** a JSON array of objects. Each object must have two keys: "type" (one of {', '.join(ALLOWED_PII_TYPES)}) and "value".

TEXT TO ANALYSE:
---
{{text}}
---
JSON Response:
"""
SAMPLE_TEXT = "Contact Jane Doe at jane.doe@example.com."

PAYLOAD = {
    "message": PROMPT_TEMPLATE.format(text=SAMPLE_TEXT),
    "mode": "chat",
    "options": {"temperature": 0.0}
}

# --- Main Test Logic ---
def test_anythingllm_connection():
    print("--- Starting AnythingLLM Connection Test ---")

    if not all([ENDPOINT, API_KEY, WORKSPACE]):
        print("\n[ERROR] Missing one or more environment variables in your .env file.")
        print("Please check ANYTHINGLLM_URL, ANYTHINGLLM_KEY, and ANYTHINGLLM_WS.")
        return

    print(f"Attempting to call API at: {CHAT_URL}")

    try:
        response = requests.post(CHAT_URL, headers=HEADERS, json=PAYLOAD, timeout=90)
        
        print(f"\n[OK] Request Sent. HTTP Status Code: {response.status_code}")
        
        print("\n--- RAW RESPONSE TEXT ---")
        print(response.text)
        print("-------------------------\n")

        # Try to parse the JSON to give an extra hint
        try:
            response_data = response.json()
            print("[OK] Response was valid JSON.")
            print("\n--- PARSED JSON (formatted) ---")
            print(json.dumps(response_data, indent=2))
            print("-------------------------------\n")
        except Exception as e:
            print(f"[WARNING] Could not parse the raw response as JSON. Error: {e}")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] A connection error occurred: {e}")

if __name__ == "__main__":
    test_anythingllm_connection()