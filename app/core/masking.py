# app/core/masking.py
import os, json, re, requests
from dataclasses import dataclass
from typing import List, Tuple, Dict
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────  Config  ─────────────────────────
API_KEY  = os.getenv("ANYTHINGLLM_KEY")
API_URL  = os.getenv("ANYTHINGLLM_URL")
WS_SLUG  = os.getenv("ANYTHINGLLM_WS")
CHAT_URL = f"{API_URL}/api/v1/workspace/{WS_SLUG}/chat"
HEADERS  = {"Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"}

# ─────────────────────────  PII types  ──────────────────────
ALLOWED_TYPES = {
    "Name", "EmailAddress", "PhoneNumber",
    "PhysicalAddress", "SingaporeNRIC",
    "SocialSecurityNumber", "DateOfBirth"
}
TYPE_SYNONYMS = {
    "Birthdate": "DateOfBirth",
    "SSN":       "SocialSecurityNumber",
    "Alternate Phone Number": "PhoneNumber",
}


PROMPT = """
You are a PII (Personally Identifiable Information) extraction machine.

**CRITICAL RULES:**
1.  **EXTRACT VERBATIM:** You MUST extract the text *exactly* as it appears in the source. Do NOT change, add, infer, or normalize any information. If a phone number is "87654321", you must extract "87654321", NOT "+65 87654321".
2.  **EXTRACT ALL:** You MUST find every single instance of PII. If there are two different phone numbers, your output must contain two seperate objects for each phone number, etc.
3.  **JSON ONLY:** Your entire response must be ONLY a single JSON array. Do not add any text before or after the array.

--- EXAMPLE START ---
Input Text:
"Contact admin Jane Smith at jane@web.com or call 555-1111 for help. The primary contact is John at john.doe@work.com, phone 555-2222."

JSON Response:
[
  {{"type": "Name", "value": "Jane Smith"}},
  {{"type": "EmailAddress", "value": "jane@web.com"}},
  {{"type": "PhoneNumber", "value": "555-1111"}},
  {{"type": "Name", "value": "John"}},
  {{"type": "EmailAddress", "value": "john.doe@work.com"}},
  {{"type": "PhoneNumber", "value": "555-2222"}}
]
--- EXAMPLE END ---

Return ONLY a JSON array of objects, as shown in the example.
Allowed "type" values: {types}.
NO other text. Analyse the entire text carefully.

TEXT TO ANALYSE:
---
{text}
---
"""
# --- END: IMPROVED FEW-SHOT PROMPT ---


# ─────────────────────────  Helpers  ────────────────────────
BRACKETS_RE = re.compile(r"\[.*\]", re.DOTALL) # Changed to match any content between brackets
SMART_QUOTES = str.maketrans({"“":'"', "”":'"', "’":"'","‘":"'"})

@dataclass
class PiiEntity:
    type: str
    value: str

def _first_json_array(raw: str) -> str:
    raw = raw.translate(SMART_QUOTES)
    # This regex is more robust for finding a JSON array in the LLM's output
    match = BRACKETS_RE.search(raw)
    if not match:
        if raw.strip().startswith("["): # Handle cases where LLM returns just the array
            return raw.strip()
        raise ValueError("No JSON array found in LLM response")
    text = match.group(0)
    return re.sub(r",\s*([}\]])", r"\1", text)  # strip trailing commas

# ─────────────────────────  Core  ───────────────────────────
def extract_pii(text: str) -> List[PiiEntity]:
    prompt = PROMPT.format(types=", ".join(sorted(ALLOWED_TYPES)), text=text)
    payload = {"message": prompt, "mode": "chat", "options": {"temperature": 0}}
    
    resp = requests.post(CHAT_URL, headers=HEADERS, json=payload, timeout=90)
    if resp.status_code >= 400:
        print(f"\n--- DEBUG: AnythingLLM returned an error! ---")
        print(f"Status Code: {resp.status_code}")
        print(f"Response Body: {resp.text}")
        print("-------------------------------------------\n")
    resp.raise_for_status()

    response_data = resp.json()
    raw_llm_output = response_data.get("textResponse", "")
    if not raw_llm_output:
        return []

    arr = json.loads(_first_json_array(raw_llm_output))
    entities: List[PiiEntity] = []

    for item in arr:
        item_type = item.get("type")
        item_value = item.get("value")
        if item_type and item_value:
            # Normalize the type using synonyms
            t = TYPE_SYNONYMS.get(item_type, item_type)
            if t in ALLOWED_TYPES:
                entities.append(PiiEntity(t, str(item_value)))
                
    return entities

# --- START: CORRECTED MASKING LOGIC ---
# This version correctly handles multiple occurrences of the same PII value.
# In app/core/masking.py

def mask(text: str, entities: List[PiiEntity]) -> Tuple[str, Dict[str,str]]:
    print("\n--- DEBUG: Inside 'mask' function. ---")
    
    # Map of {original_value: placeholder} to ensure "John Doe" always gets "[NAME_0]"
    value_to_placeholder_map = {}
    
    # The final unmasking map {placeholder: original_value}
    unmasking_map = {}
    
    # Counter for placeholder indices, e.g., NAME: 0, EMAILADDRESS: 0
    counters = defaultdict(int)

    print("--- DEBUG: Starting loop to assign placeholders...")
    # First, iterate through all found entities to assign a unique placeholder to each unique PII *value*.
    for ent in entities:
        if ent.value not in value_to_placeholder_map:
            # If we haven't seen this value before, create a new placeholder for it.
            pii_type_upper = ent.type.upper()
            key = f"[{pii_type_upper}_{counters[pii_type_upper]}]"
            counters[pii_type_upper] += 1
            
            value_to_placeholder_map[ent.value] = key
            unmasking_map[key] = ent.value
            # Use [:50] to avoid printing very long strings to the terminal
            print(f"  - Assigned placeholder '{key}' for value '{ent.value[:50]}'")

    print(f"--- DEBUG: Finished assigning placeholders. Total unique values to replace: {len(value_to_placeholder_map)}")

    # Now, replace the text, starting with the longest strings first
    masked = text
    print("\n--- DEBUG: Starting loop to replace text in document...")
    for val in sorted(value_to_placeholder_map.keys(), key=len, reverse=True):
        ph = value_to_placeholder_map[val]
        print(f"  - Replacing '{val[:50]}' with '{ph}'")
        masked = re.sub(re.escape(val), ph, masked, flags=re.IGNORECASE)
    
    print("--- DEBUG: Finished replacing text.")
    print(f"--- DEBUG: Returning masked text (length: {len(masked)}) and unmasking map (size: {len(unmasking_map)}).")
    print("---------------------------------------\n")
        
    return masked, unmasking_map
# --- END: CORRECTED MASKING LOGIC ---


# ─────────────────────────  Convenience  ────────────────────
def mask_text(text: str) -> Tuple[str, Dict[str,str]]:
    entities = extract_pii(text)
    return mask(text, entities)

# ─────────────────────────  Backward-compat wrappers ─────────
# These keep the old import paths working in your routes/documents.py file.
get_pii_entities = extract_pii
create_masked_text_and_map = mask
