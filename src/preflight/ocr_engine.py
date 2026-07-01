"""
Pre-flight OCR Engine — Tesseract conditional fallback.

Architecture constraint (from the design diagram):
  "Tesseract OCR (conditional fallback, only if text layer is empty/garbled)"

This module is ONLY invoked when PyMuPDF's native text extraction produces
fewer than MIN_TEXT_CHARS non-whitespace characters on a page — meaning the
page is likely a scanned image with no embedded text layer.

Calling this on every page would be prohibitively slow at scale (thousands of
candidates). The conditional gate keeps OCR cost proportional to actual need.

Dependencies:
  - pytesseract (Python wrapper)
  - Pillow (PIL Image)
  - Tesseract binary must be installed on the system PATH

Graceful degradation: if pytesseract/Pillow are not installed, or if the
Tesseract binary is not found, this module returns ("", "ocr_unavailable")
and logs a warning — it NEVER crashes the pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Minimum non-whitespace chars from native PDF extraction before OCR kicks in.
# Set low (50) so we catch genuinely empty pages but don't waste time on
# pages that have even a modest amount of embedded text.
MIN_TEXT_CHARS = 50


def _tesseract_available() -> bool:
    """Check at import time whether pytesseract and Tesseract binary are usable."""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


_TESSERACT_OK: bool = _tesseract_available()
if not _TESSERACT_OK:
    logger.warning(
        "[ocr_engine] pytesseract or Tesseract binary not available — "
        "OCR fallback disabled. Scanned PDFs will yield empty text."
    )


def should_ocr(native_text: str) -> bool:
    """
    Return True if the native extracted text is too sparse to be useful and
    OCR should be attempted.

    `native_text` is the raw string returned by fitz for a single page.
    """
    return len(native_text.replace(" ", "").replace("\n", "")) < MIN_TEXT_CHARS


def ocr_page(page) -> Tuple[str, str]:
    """
    Run Tesseract OCR on a single PyMuPDF page object.

    Returns:
        (text, note) where:
          text — the extracted string (empty string on failure)
          note — a short status string for provenance logging
                 ("ocr_success" | "ocr_unavailable" | "ocr_failed:<reason>")

    Never raises.
    """
    if not _TESSERACT_OK:
        return ("", "ocr_unavailable")

    try:
        import pytesseract
        from PIL import Image

        # Render the page to a high-DPI pixmap for better OCR accuracy.
        # 300 DPI is the standard minimum for reliable OCR on text.
        mat = page.get_matrix() if hasattr(page, "get_matrix") else None
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Use the eng lang; if multi-language support is needed, pass lang="eng+hin"
        # etc. — but that requires additional Tesseract language packs installed.
        text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        return (text, "ocr_success")

    except Exception as exc:
        logger.warning(f"[ocr_engine] OCR failed: {exc}")
        return ("", f"ocr_failed:{type(exc).__name__}")


def ocr_page_if_needed(page, native_text: str) -> Tuple[str, str]:
    """
    Convenience wrapper: checks `should_ocr`, runs `ocr_page` if true,
    otherwise returns the native text with note "native_text_ok".

    This is the single call-site that resume_extractor uses — callers don't
    need to know the threshold logic.
    """
    if should_ocr(native_text):
        ocr_text, note = ocr_page(page)
        return (ocr_text if ocr_text.strip() else native_text, note)
    return (native_text, "native_text_ok")
