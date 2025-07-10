# app/core/masking.py

import os, json, re, requests
from typing import Dict, List

# Load config directly here as it's self-contained
API_KEY  = os.getenv("ANYTHINGLLM_KEY")
API_URL  = os.getenv("ANYTHINGLLM_URL")
WS_SLUG  = os.getenv("ANYTHINGLLM_WS")
CHAT_URL = f"{API_URL}/api/v1/workspace/{WS_SLUG}/chat"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# --- Prompt 1: Simple PII Extraction ---
EXTRACTION_PROMPT = """
You are a PII (Personally Identifiable Information) extraction machine.
Your ONLY job is to find and list every single piece of PII from the text below.
Return ONLY a JSON array of objects. Each object must have two keys: "type" and "value".
Do not miss any. If there are two names, list two objects.

Allowed "type" values: Name, EmailAddress, PhoneNumber, PhysicalAddress, SingaporeNRIC, SocialSecurityNumber, DateOfBirth.

TEXT TO ANALYSE:
---
{text}
---
"""

# --- Prompt 2: Contextual Grouping ---
GROUPING_PROMPT = """
You are an entity resolution expert. Your job is to group the provided list of PII into profiles based on the context of the full document text.

**RULES:**
1.  Analyze the full text to understand which PII belongs to which person.
2.  Return ONLY a single JSON object with two top-level keys: "persons" and "unlinked_pii".
3.  Under "persons", create a unique key for each person found (e.g., "person_1", "person_2").
4.  Each person's object should contain keys like "names", "emails", "phones", etc., with the corresponding PII values in a list.
5.  Any PII from the list that cannot be confidently linked to a person should be placed under "unlinked_pii", categorized by its type.

**FULL DOCUMENT TEXT FOR CONTEXT:**
---
{text}
---

**LIST OF PII TO GROUP:**
---
{pii_list_json}
---
"""

def extract_pii_flat_list(text: str) -> List[Dict]:
    """Step 1: Gets a simple flat list of all PII from the text."""
    prompt = EXTRACTION_PROMPT.format(text=text)
    payload = {"message": prompt, "mode": "chat", "options": {"temperature": 0}}
    resp = requests.post(CHAT_URL, headers=HEADERS, json=payload, timeout=90)
    resp.raise_for_status()
    raw_response = resp.json().get("textResponse", "[]")
    
    # Simple regex to find the JSON array
    match = re.search(r'\[.*\]', raw_response, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return []

def group_pii_with_context(text: str, pii_list: List[Dict]) -> Dict:
    """Step 2: Takes the flat PII list and asks the LLM to group it based on context."""
    pii_list_json = json.dumps(pii_list, indent=2)
    prompt = GROUPING_PROMPT.format(text=text, pii_list_json=pii_list_json)
    payload = {"message": prompt, "mode": "chat", "options": {"temperature": 0.1}}
    resp = requests.post(CHAT_URL, headers=HEADERS, json=payload, timeout=120)
    resp.raise_for_status()
    raw_response = resp.json().get("textResponse", "{}")

    # More robust JSON finding
    match = re.search(r'\{.*\}', raw_response, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return {"persons": {}, "unlinked_pii": {}}