"""Turn an uploaded invoice (PDF or image) into something the AI can read.

Step 1 (this file, done): check the file really is a PDF/JPEG/PNG/WebP, hash it,
and produce page images (+ text for PDFs) sized for a vision model.
Step 2 (later): send those to the AI via llm.py and parse the JSON fields.
"""

import hashlib
import io
from dataclasses import dataclass, field

import pdfplumber
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # phone photos are usually 2-8 MB
MAX_PDF_PAGES = 3                     # invoices are short; caps AI cost
MAX_IMAGE_EDGE = 1568                 # Claude downscales anything larger, so don't send more
PDF_RENDER_DPI = 150                  # sharp enough for small print on invoices

# Formats the AI vision models accept. HEIC (iPhone default) is not one of them.
ALLOWED_IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class DocumentError(ValueError):
    """The upload can't be used. The message is shown to the user as-is."""


@dataclass
class PreparedDocument:
    kind: str                     # "pdf" or "image"
    media_type: str               # media type detected from the bytes, not the browser's claim
    file_sha256: str              # hash of the original upload (used by the dup_file check)
    size_bytes: int
    page_images: list[bytes] = field(default_factory=list)  # JPEGs, one per page, ready for the AI
    text: str = ""                # embedded PDF text ("" for images and scanned PDFs)
    page_count: int = 1
    pdf_metadata: dict | None = None


def prepare_document(data: bytes) -> PreparedDocument:
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(f"The file is {len(data) / 1e6:.1f} MB. The limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")

    sha = hashlib.sha256(data).hexdigest()
    # Decide by the file's first bytes, not its name: a renamed file can't sneak through.
    if data.startswith(b"%PDF-"):
        return _prepare_pdf(data, sha)
    return _prepare_image(data, sha)


def _prepare_image(data: bytes, sha: str) -> PreparedDocument:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise DocumentError("This isn't a readable PDF or image. Upload a PDF, JPEG, PNG or WebP.")
    if img.format not in ALLOWED_IMAGE_FORMATS:
        raise DocumentError(f"{img.format} images aren't supported. Upload a PDF, JPEG, PNG or WebP "
                            "(on iPhone, export the photo as JPEG).")
    media_type = ALLOWED_IMAGE_FORMATS[img.format]
    # Phone photos are often stored sideways with an EXIF "rotate me" tag; apply it.
    img = ImageOps.exif_transpose(img)
    return PreparedDocument(kind="image", media_type=media_type, file_sha256=sha,
                            size_bytes=len(data), page_images=[_to_ai_jpeg(img)])


def _prepare_pdf(data: bytes, sha: str) -> PreparedDocument:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages[:MAX_PDF_PAGES]
            text = "\n\n".join(p.extract_text() or "" for p in pages).strip()
            # Render pages to images too, so scanned PDFs (no text layer) still work.
            images = [_to_ai_jpeg(p.to_image(resolution=PDF_RENDER_DPI).original) for p in pages]
            return PreparedDocument(kind="pdf", media_type="application/pdf", file_sha256=sha,
                                    size_bytes=len(data), page_images=images, text=text,
                                    page_count=len(pdf.pages),
                                    pdf_metadata={k: str(v) for k, v in (pdf.metadata or {}).items()})
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("This PDF couldn't be opened. It may be damaged or password-protected.")


def _to_ai_jpeg(img: Image.Image) -> bytes:
    """Flatten transparency onto white, shrink to MAX_IMAGE_EDGE, encode as JPEG."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))  # keeps aspect ratio, never enlarges
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()
