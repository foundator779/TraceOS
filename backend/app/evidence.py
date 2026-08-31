from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings


ALLOWED_IMAGE_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}


def validate_image(data: bytes, declared_mime: str, settings: Settings) -> tuple[str, int, int]:
    if not data:
        raise ValueError("Image evidence is empty")
    if len(data) > settings.max_image_bytes:
        raise ValueError("Image evidence exceeds the 5 MB limit")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format or ""
            width, height = image.size
    except Exception as exc:
        raise ValueError("Image evidence is not a valid PNG, JPEG, or WebP file") from exc
    actual_mime = ALLOWED_IMAGE_FORMATS.get(fmt)
    if not actual_mime or declared_mime not in ALLOWED_IMAGE_FORMATS.values():
        raise ValueError("Only PNG, JPEG, and WebP image evidence is accepted")
    if actual_mime != declared_mime:
        raise ValueError("Declared content type does not match the image bytes")
    if max(width, height) > settings.max_image_dimension:
        raise ValueError("Image dimensions exceed 4096 pixels")
    return actual_mime, width, height


def demo_evidence_png() -> bytes:
    """A deterministic, clearly watermarked synthetic sign-in alert."""
    image = Image.new("RGB", (1200, 720), "#F7F5EF")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    title = ImageFont.load_default(size=44)
    draw.rounded_rectangle((55, 55, 1145, 665), radius=30, fill="#11100F")
    draw.text((95, 90), "IDENTITY SECURITY ALERT", fill="#D7D1B0", font=font)
    draw.text((95, 145), "Unfamiliar sign-in", fill="#FFFFFF", font=title)
    draw.text((95, 230), "Account: analyst@northstar.example", fill="#FFFFFF", font=font)
    draw.text((95, 280), "Location: Montreal, CA", fill="#FFFFFF", font=font)
    draw.text((95, 330), "Time: 2026-08-01 09:42 UTC", fill="#FFFFFF", font=font)
    draw.text((95, 380), "Device: Chrome on Windows", fill="#FFFFFF", font=font)
    draw.rounded_rectangle((95, 455, 650, 535), radius=18, fill="#D7D1B0")
    draw.text((125, 480), "Risk signal: NEW REGION", fill="#11100F", font=font)
    draw.text((835, 600), "DEMO SYNTHETIC", fill="#D7D1B0", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


class EvidenceStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def put(self, case_id: str, evidence_id: str, data: bytes, mime_type: str) -> str:
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
        object_name = f"{case_id}/{evidence_id}{suffix}"
        if self.settings.evidence_bucket:
            from google.cloud import storage

            blob = storage.Client(project=self.settings.google_cloud_project).bucket(
                self.settings.evidence_bucket
            ).blob(object_name)
            blob.upload_from_string(data, content_type=mime_type, if_generation_match=0)
            return f"gs://{self.settings.evidence_bucket}/{object_name}"
        path = Path(self.settings.evidence_local_path) / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.resolve().as_uri()

    def get(self, storage_uri: str) -> bytes:
        if storage_uri.startswith("gs://"):
            from google.cloud import storage

            bucket_name, object_name = storage_uri[5:].split("/", 1)
            return storage.Client(project=self.settings.google_cloud_project).bucket(
                bucket_name
            ).blob(object_name).download_as_bytes()
        if storage_uri.startswith("file:"):
            from urllib.parse import unquote, urlparse

            return Path(unquote(urlparse(storage_uri).path.lstrip("/"))).read_bytes()
        raise FileNotFoundError("Evidence content is not stored as an image object")
