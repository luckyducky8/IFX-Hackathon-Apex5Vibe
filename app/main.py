"""FastAPI app: API routes under /api, and the single-page UI from /static.

Run:  .\\venv\\Scripts\\python.exe -m uvicorn app.main:app --reload
Open: http://localhost:8000
"""

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from app.extract import MAX_UPLOAD_BYTES, DocumentError, prepare_document

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Invoice fraud checks")


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    # Read one byte past the limit so oversized uploads are rejected without loading all of them.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        doc = prepare_document(data)
    except DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "fields": None,  # AI extraction not built yet (build step 3); the UI says so
        "file_sha256": doc.file_sha256,
        "pdf_metadata": doc.pdf_metadata,
        "file": {
            "name": file.filename,
            "kind": doc.kind,
            "media_type": doc.media_type,
            "size_bytes": doc.size_bytes,
            "page_count": doc.page_count,
            "pages_prepared_for_ai": len(doc.page_images),
            "has_text_layer": bool(doc.text),
        },
    }


# Mounted last so /api/* routes take priority. html=True serves index.html at "/".
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
