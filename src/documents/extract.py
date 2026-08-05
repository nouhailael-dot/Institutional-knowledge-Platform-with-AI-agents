"""Turn an uploaded file's bytes into clean text.

Text PDFs and plain text only (.pdf, .txt, .md) — no OCR, no .docx yet. A
scanned PDF yields almost no extractable text, so rather than silently
embedding whitespace we detect that case and raise a message the user can act
on.
"""

from __future__ import annotations

import io

# Below this many characters of extracted text, we treat a PDF as scanned /
# image-only rather than a text PDF. Real documents clear this easily.
_MIN_PDF_CHARS = 40


class ExtractionError(Exception):
    """Raised with a human-readable reason when extraction can't proceed."""


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Dispatch on file extension. Returns cleaned plain text.

    Raises ExtractionError with an actionable message on failure.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _extract_pdf(file_bytes)
    if name.endswith((".txt", ".md", ".markdown")):
        return _clean(file_bytes.decode("utf-8", errors="replace"))
    raise ExtractionError(
        f"Unsupported file type: {filename!r}. Upload a text PDF, .txt or .md."
    )


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError(
            "pypdf is not installed. Run: pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ExtractionError(f"Could not open the PDF: {exc}") from exc

    if reader.is_encrypted:
        # Try the empty password; many "encrypted" PDFs open with it.
        try:
            reader.decrypt("")
        except Exception:
            raise ExtractionError(
                "This PDF is password-protected. Remove the password and retry."
            )

    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            # One bad page shouldn't sink the whole document.
            continue

    text = _clean("\n".join(parts))
    if len(text) < _MIN_PDF_CHARS:
        raise ExtractionError(
            "Almost no text came out of this PDF, so it's most likely scanned "
            "(image-only). OCR isn't supported yet — upload a text-based PDF, "
            "or paste the text directly."
        )
    return text


def _clean(text: str) -> str:
    """Collapse the runs of blank lines and stray whitespace PDFs love to emit."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    out, blanks = [], 0
    for ln in lines:
        if ln.strip():
            out.append(ln)
            blanks = 0
        else:
            blanks += 1
            if blanks <= 1:            # keep single blank lines, drop the rest
                out.append("")
    return "\n".join(out).strip()
