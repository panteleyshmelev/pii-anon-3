# app/main.py
from fastapi import FastAPI, Response # <--- Add 'Response' to the import

# from app.core.masking import load_spacy_model # This is correctly removed
from app.routes import documents as text_processing_router # This import is correct

app = FastAPI(title="LLM-Powered Text PII Masking API")
app.include_router(text_processing_router.router, prefix="/text", tags=["Text Processing"])

# dummy endpoint to resolve error in console
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Return a 204 No Content response
    return Response(status_code=204)

@app.get("/")
def read_root():
    return {"message": "Welcome to the LLM-Powered Text PII Masking API"}