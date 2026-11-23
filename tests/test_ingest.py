"""Reading uploaded files: real PDF and Word files built in the test, source code, notebooks,
and clear refusals for what cannot be read."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

import pytest

from modules import backup, data_stores
from modules.ingest import UPLOAD_TYPES, IngestError, extract_file
from modules.knowledge_store import KnowledgeStore
from modules.research import ingest_file, ingest_text, process_url
from tests.test_knowledge_store import ConceptEmbedder
from web_research_module import WebResearchModule


def make_pdf(pages: list[str]) -> bytes:
    """A small valid PDF with one line of text per page (an empty string makes a page without text)."""

    objects: list[bytes] = []
    page_ids = [3 + 2 * index for index in range(len(pages))]
    font_id = 3 + 2 * len(pages)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{page} 0 R' for page in page_ids)}] /Count {len(pages)} >>".encode())
    for index, text in enumerate(pages):
        content_id = page_ids[index] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n")
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return output.getvalue()


def make_docx() -> bytes:
    import docx

    document = docx.Document()
    document.add_heading("Backup policy", level=1)
    document.add_paragraph("Every database is copied nightly at 02:00.")
    document.add_heading("Retention", level=2)
    document.add_paragraph("Copies are kept for 30 days.")
    document.add_paragraph("Check the log each morning", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Server", "Owner"
    table.cell(1, 0).text, table.cell(1, 1).text = "db-01", "Priya"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


# --- formats --------------------------------------------------------------------------------------------


def test_pdf_text_is_read_page_by_page():
    extracted = extract_file("manual.pdf", make_pdf(["The reactor valve opens at 40 psi.", "Close it before maintenance."]))

    assert extracted.kind == "file" and extracted.meta["pages"] == 2
    assert "[page 1]\nThe reactor valve opens at 40 psi." in extracted.text
    assert "[page 2]\nClose it before maintenance." in extracted.text
    assert extracted.warnings == []


def test_pdf_pages_without_text_are_reported_not_invented():
    partly = extract_file("partly_scanned.pdf", make_pdf(["Only this page has text.", ""]))
    assert "1 of 2 page(s) had no text" in partly.warnings[0]

    with pytest.raises(IngestError, match="no text layer.*OCR, which is not installed"):
        extract_file("scan.pdf", make_pdf(["", ""]))


def test_password_protected_and_damaged_pdfs_are_refused_with_a_reason():
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["secret text"]))))
    writer.encrypt("hunter2")
    locked = io.BytesIO()
    writer.write(locked)

    with pytest.raises(IngestError, match="password-protected"):
        extract_file("locked.pdf", locked.getvalue())
    with pytest.raises(IngestError, match="could not be read"):
        extract_file("broken.pdf", b"%PDF-1.4\nthis is not really a pdf")


def test_word_documents_keep_headings_lists_and_tables():
    extracted = extract_file("policy.docx", make_docx())

    assert "# Backup policy" in extracted.text and "## Retention" in extracted.text
    assert "Every database is copied nightly at 02:00." in extracted.text
    assert "- Check the log each morning" in extracted.text
    assert "Server | Owner\ndb-01 | Priya" in extracted.text
    assert extracted.meta["tables"] == 1

    with pytest.raises(IngestError, match="Word document could not be read"):
        extract_file("fake.docx", b"not a zip file at all")


def test_source_code_is_kept_exactly():
    code = "def area(r):\n    # pi * r^2\n    return 3.14159 * r ** 2 if r > 0 else {'error': \"bad\"}\n"

    extracted = extract_file("geometry.py", code.encode("utf-8"))

    assert (extracted.kind, extracted.language) == ("code", "Python")
    assert extracted.text == code
    assert extract_file("App.tsx", b"export const App = () => <div/>;").language == "TypeScript"
    assert extract_file("Dockerfile", b"FROM python:3.13\nRUN pip install x").language == "Dockerfile"


def test_notebooks_html_and_plain_text():
    notebook = {"cells": [{"cell_type": "markdown", "source": ["# Analysis\n", "Load the data."]}, {"cell_type": "code", "source": "df = load()\ndf.head()"}]}
    extracted = extract_file("analysis.ipynb", json.dumps(notebook).encode())
    assert "# Analysis\nLoad the data." in extracted.text and "```\ndf = load()\ndf.head()\n```" in extracted.text

    page = extract_file("page.html", b"<html><head><style>p{color:red}</style><script>track()</script></head><body><h1>Title</h1><p>Body text here.</p></body></html>")
    assert "Body text here." in page.text and "track()" not in page.text and "color:red" not in page.text

    assert extract_file("notes.txt", "café — résumé".encode("utf-8")).text == "café — résumé"
    legacy = extract_file("old.txt", "café".encode("cp1252"))
    assert legacy.text == "café" and "not UTF-8" in legacy.warnings[0]
    assert extract_file("data.csv", b"name,score\r\nana,5\r\n").text == "name,score\nana,5\n"


def test_what_cannot_be_read_is_refused_clearly():
    with pytest.raises(IngestError, match="is an image.*OCR, which is not installed"):
        extract_file("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    with pytest.raises(IngestError, match="a spreadsheet \\(save it as .csv\\)"):
        extract_file("budget.xlsx", b"PK\x03\x04")
    with pytest.raises(IngestError, match="binary file"):
        extract_file("mystery.bin", b"\x00\x01\x02\x03" * 100)
    with pytest.raises(IngestError, match="empty"):
        extract_file("empty.txt", b"")
    with pytest.raises(IngestError, match="No text was found"):
        extract_file("blank.txt", b"   \n\n  ")


def test_very_long_files_are_cut_with_a_warning_and_big_ones_refused(monkeypatch):
    extracted = extract_file("long.txt", ("word " * 5000).encode(), max_characters=1000)
    assert len(extracted.text) == 1000 and "only the first 1,000 were kept" in extracted.warnings[0]

    monkeypatch.setattr("modules.ingest.MAX_FILE_BYTES", 10)
    with pytest.raises(IngestError, match="the limit is"):
        extract_file("big.txt", b"x" * 11)


def test_upload_types_cover_documents_and_code():
    assert {"pdf", "docx", "md", "txt", "csv", "json", "html", "ipynb", "py", "js", "ts", "java", "go", "rs", "sql"} <= set(UPLOAD_TYPES)
    assert "png" not in UPLOAD_TYPES and "exe" not in UPLOAD_TYPES


# --- into the knowledge store ---------------------------------------------------------------------------


@pytest.fixture
def module(tmp_path) -> WebResearchModule:
    return WebResearchModule(str(tmp_path / "kb"), embedder=ConceptEmbedder())


def test_uploaded_pdf_word_and_code_become_searchable(module):
    pdf = ingest_file(module, name="manual.pdf", data=make_pdf(["The reactor valve opens at 40 psi."]))
    word = ingest_file(module, name="policy.docx", data=make_docx())
    code = ingest_file(module, name="geometry.py", data=b"def area(radius):\n    return 3.14159 * radius ** 2\n")

    assert (pdf["status"], word["status"], code["status"]) == ("success", "success", "success")
    assert code["kind"] == "code" and code["language"] == "Python"
    assert module.semantic_search("reactor valve psi")[0]["title"] == "manual.pdf"
    hit = module.semantic_search("how long are copies kept retention")[0]
    assert hit["title"] == "policy.docx" and hit["heading"] == "Retention"
    found = module.semantic_search("area radius")[0]
    assert found["kind"] == "code" and "return 3.14159 * radius ** 2" in found["text"] and found["start_line"] == 1
    assert module.get_processing_summary()["by_kind"] == {"file": 2, "code": 1}


def test_uploading_the_same_file_again_is_recognised(module):
    data = make_pdf(["The reactor valve opens at 40 psi."])
    first = ingest_file(module, name="manual.pdf", data=data)

    again = ingest_file(module, name="manual.pdf", data=data)

    assert first["unchanged"] is False and again["unchanged"] is True
    assert module.get_processing_summary()["total_urls"] == 1


def test_unreadable_upload_stores_nothing(module):
    result = ingest_file(module, name="photo.jpg", data=b"\xff\xd8\xff" + b"\x00" * 20)

    assert result["status"] == "error" and "image" in result["error"]
    assert module.get_processing_summary()["total_urls"] == 0


def test_ingested_text_keeps_code_and_symbols(module):
    result = ingest_text(module, name="snippet.md", text="Use `x <= 3 && y != 4` then call f(x)[0] -> {ok: true}", source_type="knowledge_note")

    assert result["status"] == "success"
    assert "x <= 3 && y != 4" in module.semantic_search("call")[0]["text"]
    assert ingest_text(module, name="empty.md", text="  ")["status"] == "error"


def test_processing_a_url_stores_the_page_with_its_headings(module, monkeypatch):
    page = {
        "status": "success",
        "url": "https://example.org/guide",
        "title": "Guide",
        "content": "# Setup\n\nInstall the tool.\n\n## Recover access\n\nUse the recover link when locked out.",
        "timestamp": "2026-11-23T10:00:00",
        "word_count": 14,
    }
    monkeypatch.setattr(module, "extract_content_from_url", lambda url: dict(page))

    result = process_url(module, "example.org/guide")

    assert result["stored"] is True and result["chunks_count"] == 2
    hit = module.semantic_search("how do I reset my password")[0]
    assert (hit["url"], hit["kind"], hit["heading"]) == ("https://example.org/guide", "url", "Recover access")


# --- the database in backups ----------------------------------------------------------------------------


def test_backup_takes_a_consistent_copy_of_the_live_database_and_restores_it(tmp_path, monkeypatch):
    root = tmp_path / "home"
    for name, part in (("data", "data"), ("knowledge", "knowledge_bank"), ("logs", "logs"), ("config", "config")):
        (root / part).mkdir(parents=True, exist_ok=True)
        monkeypatch.setitem(data_stores._ROOT_NAMES, name, root / part)
    monkeypatch.setattr(data_stores, "DATA_ROOT", root / "data")
    monkeypatch.setattr(data_stores, "KNOWLEDGE_ROOT", root / "knowledge_bank")
    monkeypatch.setattr(data_stores, "LOG_ROOT", root / "logs")
    monkeypatch.setattr(data_stores, "CONFIG_ROOT", root / "config")
    folder = root / "knowledge_bank" / "web_research"
    store = KnowledgeStore(folder, embedder=ConceptEmbedder())
    store.add_document("file:pets.md", "Pets", "The feline sleeps on the sofa.", kind="file")
    # The connection stays open and the change is still in the write-ahead log, as in the running app.
    assert (folder / "knowledge.sqlite3-wal").exists()

    archive = tmp_path / "backup.zip"
    backup.create_archive(archive, ["knowledge_index"])

    with zipfile.ZipFile(archive) as packed:
        names = packed.namelist()
        assert "files/knowledge/web_research/knowledge.sqlite3" in names
        assert not any(name.endswith(("-wal", "-shm")) for name in names)
        copy = tmp_path / "copy.sqlite3"
        copy.write_bytes(packed.read("files/knowledge/web_research/knowledge.sqlite3"))
    connection = sqlite3.connect(copy)
    assert connection.execute("SELECT title FROM documents").fetchall() == [("Pets",)]  # the logged change is in the copy
    connection.close()
    backup.verify_archive(archive)

    store.add_document("file:later.md", "Later", "An invoice arrived.", kind="file")
    store.close()
    backup.restore_archive(archive, store_keys=["knowledge_index"], snapshot_first=False)

    restored = KnowledgeStore(folder, embedder=ConceptEmbedder())
    assert [row["title"] for row in restored.list_documents()] == ["Pets"]
    assert restored.search("kitten")[0]["title"] == "Pets"
    restored.close()
