"""Turn an uploaded file into text for the knowledge store.

Supported: plain text and Markdown, PDF (text layer), Word (.docx), HTML, CSV and JSON, Jupyter
notebooks and source code in the common languages. Line breaks, symbols and indentation are kept
as they are; the old path removed every character outside a small set, which destroyed code,
addresses and tables.

Not supported, and reported as such instead of producing garbage: scanned PDFs and images (no
OCR engine is installed), old .doc files, spreadsheets, archives and other binary formats.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_CHARACTERS = 2_000_000

CODE_LANGUAGES = {
    ".py": "Python", ".pyw": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".hpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".scala": "Scala",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch", ".r": "R",
    ".lua": "Lua", ".pl": "Perl", ".dart": "Dart", ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".gradle": "Gradle",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".ini": "INI", ".cfg": "INI", ".xml": "XML", ".dockerfile": "Dockerfile",
}  # fmt: skip
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl"}
UNSUPPORTED = {
    ".png": "an image", ".jpg": "an image", ".jpeg": "an image", ".gif": "an image", ".bmp": "an image", ".webp": "an image",
    ".tif": "an image", ".tiff": "an image", ".doc": "an old Word document (save it as .docx)", ".xls": "a spreadsheet",
    ".xlsx": "a spreadsheet (save it as .csv)", ".ppt": "a presentation", ".pptx": "a presentation", ".zip": "an archive",
    ".7z": "an archive", ".rar": "an archive", ".exe": "a program", ".dll": "a program", ".mp3": "audio", ".wav": "audio",
    ".mp4": "video", ".mov": "video", ".epub": "an e-book",
}  # fmt: skip
UPLOAD_TYPES = sorted({suffix.lstrip(".") for suffix in [*CODE_LANGUAGES, *TEXT_SUFFIXES, ".pdf", ".docx", ".html", ".htm", ".ipynb"]})


class IngestError(ValueError):
    """The file cannot be turned into text, with a reason a person can act on."""


@dataclass
class Extracted:
    text: str
    kind: str  # "file" or "code"
    title: str
    language: str = ""
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _suffix(name: str) -> str:
    lowered = name.lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if lowered in {"dockerfile", "makefile"}:
        return ".dockerfile" if lowered == "dockerfile" else ".sh"
    return "." + lowered.rsplit(".", 1)[-1] if "." in lowered else ""


def _decode(data: bytes, warnings: list[str]) -> str:
    utf16 = data.startswith((b"\xff\xfe", b"\xfe\xff"))
    sample = data[:8192]
    control = sum(1 for byte in sample if byte < 9 or 13 < byte < 32)
    if not utf16 and (b"\x00" in sample or control > len(sample) * 0.1):
        raise IngestError("This looks like a binary file, not text.")
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            if encoding == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    warnings.append("The file is not UTF-8; it was read as Windows-1252, so some characters may be wrong.")
    return data.decode("cp1252", errors="replace")


def _pdf(data: bytes, warnings: list[str], meta: dict[str, Any]) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover - listed in requirements
        raise IngestError("PDF support needs the 'pypdf' package (pip install pypdf).") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise IngestError("This PDF is password-protected. Remove the password and upload it again.")
        pages = []
        empty = 0
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[page {number}]\n{text}")
            else:
                empty += 1
        meta["pages"] = len(reader.pages)
    except PdfReadError as exc:
        raise IngestError(f"The PDF could not be read: {exc}") from exc
    if not pages:
        raise IngestError(
            "This PDF has no text layer (it is probably a scan). Reading scans needs OCR, which is not installed."
        )
    if empty:
        warnings.append(f"{empty} of {empty + len(pages)} page(s) had no text (scanned or image-only) and were skipped.")
    return "\n\n".join(pages)


def _docx(data: bytes, warnings: list[str], meta: dict[str, Any]) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - listed in requirements
        raise IngestError("Word support needs the 'python-docx' package (pip install python-docx).") from exc
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise IngestError(f"The Word document could not be read: {exc}") from exc
    parts: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        level = re.search(r"heading (\d)", style)
        if level:
            parts.append(f"{'#' * int(level.group(1))} {text}")
        elif style == "title":
            parts.append(f"# {text}")
        elif "list" in style:
            parts.append(f"- {text}")
        else:
            parts.append(text)
    for table in document.tables:
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        if any(row.strip(" |") for row in rows):
            parts.append("\n".join(rows))
    meta["paragraphs"] = len(document.paragraphs)
    meta["tables"] = len(document.tables)
    if not parts:
        raise IngestError("The Word document contains no text.")
    return "\n\n".join(parts)


def _html(text: str) -> str:
    try:
        import trafilatura

        extracted = trafilatura.extract(text, include_formatting=True, include_tables=True)
        if extracted and extracted.strip():
            return extracted
    except Exception:
        pass
    without_code = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", text)
    plain = re.sub(r"(?s)<[^>]+>", " ", without_code)
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", plain)).strip()


def _notebook(text: str, warnings: list[str]) -> str:
    try:
        notebook = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestError(f"The notebook is not valid JSON: {exc}") from exc
    parts = []
    for cell in notebook.get("cells", []):
        source = cell.get("source", "")
        body = "".join(source) if isinstance(source, list) else str(source)
        if not body.strip():
            continue
        parts.append(f"```\n{body.rstrip()}\n```" if cell.get("cell_type") == "code" else body.rstrip())
    if not parts:
        raise IngestError("The notebook has no cells with content.")
    return "\n\n".join(parts)


def extract_file(name: str, data: bytes, *, max_characters: int = MAX_CHARACTERS) -> Extracted:
    """Text of an uploaded file, or IngestError saying why it cannot be read."""

    if not data:
        raise IngestError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise IngestError(f"The file is {len(data) / 1024 / 1024:.0f} MB; the limit is {MAX_FILE_BYTES // 1024 // 1024} MB.")
    suffix = _suffix(name)
    warnings: list[str] = []
    meta: dict[str, Any] = {"bytes": len(data), "suffix": suffix}
    kind, language = "file", ""
    if suffix in UNSUPPORTED:
        extra = " Reading text out of images needs OCR, which is not installed." if "image" in UNSUPPORTED[suffix] else ""
        raise IngestError(f"{name} is {UNSUPPORTED[suffix]}, which cannot be read as text.{extra}")
    if suffix == ".pdf" or data.startswith(b"%PDF-"):
        text = _pdf(data, warnings, meta)
    elif suffix == ".docx":
        text = _docx(data, warnings, meta)
    elif suffix in {".html", ".htm"}:
        text = _html(_decode(data, warnings))
    elif suffix == ".ipynb":
        text = _notebook(_decode(data, warnings), warnings)
    elif suffix in CODE_LANGUAGES:
        text, kind, language = _decode(data, warnings), "code", CODE_LANGUAGES[suffix]
    elif suffix in TEXT_SUFFIXES or not suffix:
        text = _decode(data, warnings)
    else:
        # An extension this app does not know: accept it only if it really is text.
        text = _decode(data, warnings)
        warnings.append(f"'{suffix}' is not a file type this app knows; it was read as plain text.")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if not text.strip():
        raise IngestError("No text was found in the file.")
    if len(text) > max_characters:
        warnings.append(f"The file has {len(text):,} characters; only the first {max_characters:,} were kept.")
        text = text[:max_characters]
    meta["characters"] = len(text)
    if language:
        meta["language"] = language
    return Extracted(text=text, kind=kind, title=name, language=language, warnings=warnings, meta=meta)
