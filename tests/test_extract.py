"""Upload tests: every supported format reaches the backend and is prepared for the AI."""

import hashlib
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.extract import MAX_IMAGE_EDGE, prepare_document
from app.main import app

client = TestClient(app)

# Smallest valid PDF with a real text layer (hand-written; pdfplumber tolerates the rough xref).
TEXT_PDF = b"""%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R
  /Resources <</Font <</F1 <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>>>>>>> endobj
4 0 obj <</Length 44>> stream
BT /F1 18 Tf 20 60 Td (INVOICE INV-1001) Tj ET
endstream endobj
trailer <</Root 1 0 R>>
%%EOF"""


def image_bytes(fmt, size=(800, 600), mode="RGB", exif_orientation=None):
    img = Image.new(mode, size, "white")
    out = io.BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    img.save(out, format=fmt, **kwargs)
    return out.getvalue()


def upload(data, name):
    return client.post("/api/extract", files={"file": (name, data)})


def test_jpeg_photo_is_accepted_and_hashed():
    data = image_bytes("JPEG")
    r = upload(data, "photo.jpg")
    assert r.status_code == 200
    body = r.json()
    assert body["file"]["kind"] == "image"
    assert body["file"]["media_type"] == "image/jpeg"
    assert body["file_sha256"] == hashlib.sha256(data).hexdigest()  # hash of the original bytes


def test_png_and_webp_are_accepted():
    for fmt, mime in [("PNG", "image/png"), ("WEBP", "image/webp")]:
        r = upload(image_bytes(fmt), f"scan.{fmt.lower()}")
        assert r.status_code == 200, r.text
        assert r.json()["file"]["media_type"] == mime


def test_transparent_png_is_flattened_to_jpeg():
    doc = prepare_document(image_bytes("PNG", mode="RGBA"))
    assert doc.page_images[0][:3] == b"\xff\xd8\xff"  # JPEG magic bytes


def test_large_phone_photo_is_shrunk_for_ai():
    doc = prepare_document(image_bytes("JPEG", size=(4032, 3024)))
    w, h = Image.open(io.BytesIO(doc.page_images[0])).size
    assert max(w, h) == MAX_IMAGE_EDGE


def test_sideways_phone_photo_is_rotated_upright():
    # Stored landscape 800x600, EXIF orientation 6 = "rotate 90°" -> portrait 600x800
    doc = prepare_document(image_bytes("JPEG", exif_orientation=6))
    assert Image.open(io.BytesIO(doc.page_images[0])).size == (600, 800)


def test_text_pdf_returns_text_and_page_image():
    r = upload(TEXT_PDF, "invoice.pdf")
    assert r.status_code == 200, r.text
    assert r.json()["file"]["has_text_layer"] is True
    doc = prepare_document(TEXT_PDF)
    assert "INV-1001" in doc.text
    assert len(doc.page_images) == 1


def test_scanned_pdf_without_text_still_gets_page_image():
    out = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(out, format="PDF")
    r = upload(out.getvalue(), "scan.pdf")
    assert r.status_code == 200, r.text
    assert r.json()["file"]["has_text_layer"] is False
    assert r.json()["file"]["pages_prepared_for_ai"] == 1


def test_detection_uses_content_not_filename():
    r = upload(image_bytes("PNG"), "looks_like.pdf")
    assert r.status_code == 200
    assert r.json()["file"]["media_type"] == "image/png"


def test_rejects_unsupported_and_broken_files():
    for data, name in [(b"", "empty.jpg"), (b"not an image", "fake.jpg"),
                       (image_bytes("GIF"), "anim.gif"), (b"%PDF-1.4 garbage", "broken.pdf")]:
        r = upload(data, name)
        assert r.status_code == 400, name
        assert r.json()["detail"]  # readable message for the UI


def test_rejects_oversized_file():
    r = upload(b"\xff\xd8\xff" + b"0" * (15 * 1024 * 1024 + 10), "huge.jpg")
    assert r.status_code == 400
    assert "limit" in r.json()["detail"]


def test_homepage_is_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "InvoiceGuard" in r.text
