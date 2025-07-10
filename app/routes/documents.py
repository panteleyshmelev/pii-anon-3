# app/routes/documents.py

import os
import re
import uuid
import json
import traceback
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from app.core.masking import extract_pii_flat_list, group_pii_with_context
from app.core.identity_resolver import IdentityStore
import fitz  # PyMuPDF
import docx  # For .docx files

router = APIRouter()

UPLOAD_DIR = "data/uploads"
MASKED_TXTS_DIR = "data/masked_txts"
UNMASKED_TXTS_DIR = "data/unmasked_txts"
IDENTITY_STORE_PATH = "data/identity_store.json"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(MASKED_TXTS_DIR, exist_ok=True)
os.makedirs(UNMASKED_TXTS_DIR, exist_ok=True)


class DemaskRequest(BaseModel):
    masked_text: str


@router.post("/mask-document", tags=["Document Processing"])
async def mask_document_endpoint(file: UploadFile = File(...)):
    """
    Uploads a document, performs PII extraction and identity resolution,
    and returns a masked text file.
    """
    file_id = str(uuid.uuid4())
    original_file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")
    masked_txt_path = os.path.join(MASKED_TXTS_DIR, f"masked_{file_id}.txt")

    with open(original_file_path, "wb") as buffer:
        buffer.write(await file.read())

    # --- 1. Text Extraction ---
    try:
        print(f"[STATUS] Step 1/5: Extracting text from '{file.filename}'...")
        full_text = ""
        file_extension = file.filename.lower().split('.')[-1]
        if file_extension == "pdf":
            with fitz.open(original_file_path) as doc:
                full_text = "".join(page.get_text() for page in doc)
        elif file_extension == "txt":
            with open(original_file_path, "r", encoding="utf-8") as f:
                full_text = f.read()
        elif file_extension == "docx":
            doc = docx.Document(original_file_path)
            text_parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text_parts.append(cell.text)
            full_text = "\n".join(text_parts)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type.")
        
        if not full_text.strip():
            raise HTTPException(status_code=400, detail="File contains no text.")
            
    except Exception as e:
        if os.path.exists(original_file_path): os.remove(original_file_path)
        raise HTTPException(status_code=500, detail=f"Failed to extract text: {e}")

    # --- 2. PII Processing Workflow ---
    try:
        print("[STATUS] Step 2/5: Sending text to LLM for initial PII extraction...")
        pii_list = extract_pii_flat_list(full_text)
        print(f"[STATUS] -> Found {len(pii_list)} potential PII entities.")
        
        if not pii_list:
            if os.path.exists(original_file_path): os.remove(original_file_path)
            return PlainTextResponse(content=full_text, media_type='text/plain')

        print("[STATUS] Step 3/5: Sending PII list to LLM for contextual grouping...")
        grouped_pii = group_pii_with_context(full_text, pii_list)
        person_count = len(grouped_pii.get("persons", {}))
        unlinked_count = len(grouped_pii.get("unlinked_pii", {}))
        print(f"[STATUS] -> LLM grouped PII into {person_count} profile(s) and found {unlinked_count} unlinked category(ies).")
        
        print("[STATUS] Step 4/5: Resolving identities and updating knowledge store...")
        identity_manager = IdentityStore()
        document_masking_map = identity_manager.resolve_and_update(grouped_pii)
        print("[STATUS] -> Knowledge store updated.")

        masked_text = full_text
        for original_value, placeholder in sorted(document_masking_map.items(), key=lambda item: len(item[0]), reverse=True):
            masked_text = re.sub(re.escape(original_value), placeholder, masked_text, flags=re.IGNORECASE)
        print("[STATUS] Step 5/5: Text masking complete.")

        # Save the final masked file
        with open(masked_txt_path, "w", encoding="utf-8") as f_out:
            f_out.write(masked_text)
        
        # --- ADDED SUCCESS MESSAGE ---
        print(f"\n[SUCCESS] Masked file saved successfully to: {masked_txt_path}\n")

    except Exception as e:
        traceback.print_exc()
        if os.path.exists(original_file_path): os.remove(original_file_path)
        raise HTTPException(status_code=500, detail=f"An error occurred during PII processing: {e}")

    # --- 3. Cleanup and Respond ---
    if os.path.exists(original_file_path):
        os.remove(original_file_path)
    
    return PlainTextResponse(content=masked_text, media_type='text/plain')


@router.post("/demask-text", tags=["Document Processing"])
async def demask_text_endpoint(request: DemaskRequest):
    """
    Accepts masked text, finds all placeholders, saves the demasked
    text to a file, and returns the demasked text in the response.
    """
    print("\n[STATUS] Demasking request received.")
    
    unmasked_file_id = str(uuid.uuid4())
    unmasked_txt_path = os.path.join(UNMASKED_TXTS_DIR, f"demasked_{unmasked_file_id}.txt")
    
    if not os.path.exists(IDENTITY_STORE_PATH):
        raise HTTPException(status_code=404, detail="Identity store not found. Cannot demask.")
        
    with open(IDENTITY_STORE_PATH, "r", encoding="utf-8") as f:
        identity_store = json.load(f)
    print("[STATUS] -> Loaded identity store.")

    reverse_map = {}
    for person_data in identity_store.get("persons", {}).values():
        for pii_category in person_data.values():
            if isinstance(pii_category, dict):
                reverse_map.update(pii_category)
                
    for pii_category in identity_store.get("unlinked_pii", {}).values():
        if isinstance(pii_category, dict):
            reverse_map.update(pii_category)
    print(f"[STATUS] -> Built reverse map with {len(reverse_map)} total entries.")

    masked_text = request.masked_text
    demasked_text = masked_text
    
    placeholders_found = re.findall(r'(\[.+?\])', masked_text)
    print(f"[STATUS] -> Found {len(placeholders_found)} placeholders in the text.")
    
    for placeholder in placeholders_found:
        original_value = reverse_map.get(placeholder)
        if original_value:
            demasked_text = demasked_text.replace(placeholder, original_value)
        else:
            print(f"[WARNING] Found placeholder '{placeholder}' in text but not in identity store. Skipping.")
            
    try:
        with open(unmasked_txt_path, "w", encoding="utf-8") as f_out:
            f_out.write(demasked_text)
        # --- ADDED SUCCESS MESSAGE ---
        print(f"[SUCCESS] Demasked file saved successfully to: {unmasked_txt_path}\n")
    except Exception as e:
        print(f"[ERROR] Failed to save demasked file: {e}")
            
    print("[STATUS] -> Demasking complete.")
    return PlainTextResponse(content=demasked_text)