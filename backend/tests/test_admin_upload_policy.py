import asyncio
import io
import os
import sys
from pathlib import Path

from reportlab.pdfgen import canvas

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pdf_bytes(page_count=1, text="Ti amo"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for _ in range(page_count):
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_upload_preflight_rejects_too_many_pages():
    import server

    try:
        server._inspect_pdf_for_upload_limits(_pdf_bytes(page_count=3), max_pages=2)
        assert False, "expected an HTTPException"
    except server.HTTPException as exc:
        assert exc.status_code == 413
        assert "massimo 2 pagine" in exc.detail


def test_upload_limits_for_normal_user_are_env_driven(monkeypatch):
    import server

    monkeypatch.setattr(server, "MAX_USER_UPLOAD_FILES_PER_REQUEST", 1)
    monkeypatch.setattr(server, "MAX_USER_UPLOAD_SIZE_BYTES", 1234)
    monkeypatch.setattr(server, "MAX_USER_PDF_PAGES", 7)

    limits = server._upload_limits_for_user(False)

    assert limits["files_per_request"] == 1
    assert limits["file_size_bytes"] == 1234
    assert limits["pdf_pages"] == 7
    assert limits["active_jobs"] == server.MAX_USER_ACTIVE_JOBS


def test_format_search_result_keeps_query_and_match_text():
    import server

    result = server.format_search_result(
        {"id": "pdf_1", "title": "Canto"},
        {"page": 1, "text": "O Signore, io Ti amo con tutto il cuore"},
        "Ti amo",
        100,
    )

    assert result["query"] == "Ti amo"
    assert result["match_text"] == "Ti amo"
    assert "Ti amo" in result["snippet"]


def test_gemini_admin_status_never_exposes_secret_keys(monkeypatch):
    import pdf_processor

    monkeypatch.setattr(pdf_processor, "GEMINI_API_KEYS", ["SECRET_ONE", "SECRET_TWO"])
    monkeypatch.setattr(pdf_processor, "GEMINI_API_KEY", "SECRET_ONE")
    monkeypatch.setattr(pdf_processor, "_GEMINI_EXHAUSTED_KEYS", {"SECRET_ONE"})
    monkeypatch.setattr(pdf_processor, "_GEMINI_KEY_STATS", {})
    monkeypatch.setattr(pdf_processor, "_GEMINI_LAST_QUOTA_EVENT", None)

    pdf_processor._record_gemini_key_event(0, "selected")
    status = pdf_processor.get_gemini_admin_status()
    rendered = str(status)

    assert status["key_count"] == 2
    assert status["exhausted_key_indexes"] == [0]
    assert "SECRET_ONE" not in rendered
    assert "SECRET_TWO" not in rendered


def test_unban_access_updates_request_user_and_logs(monkeypatch):
    import server

    class AccessRequests:
        def __init__(self):
            self.update = None

        async def update_one(self, query, update, upsert=False):
            self.update = (query, update, upsert)

    class Users:
        def __init__(self):
            self.update = None

        async def update_many(self, query, update):
            self.update = (query, update)

    class Logs:
        def __init__(self):
            self.docs = []

        async def insert_one(self, doc):
            self.docs.append(doc)

    fake_db = type("FakeDB", (), {
        "access_requests": AccessRequests(),
        "users": Users(),
        "app_logs": Logs(),
    })()
    monkeypatch.setattr(server, "db", fake_db)

    result = asyncio.run(server.unban_access({"email": "USER@Example.com"}, user_id="admin-id"))

    assert result == {"ok": True}
    assert fake_db.access_requests.update[0] == {"email": "user@example.com"}
    assert fake_db.access_requests.update[1]["$set"]["status"] == "pending"
    assert fake_db.users.update[0] == {"email": "user@example.com"}
    assert fake_db.app_logs.docs[0]["event_type"] == "access.unbanned"
