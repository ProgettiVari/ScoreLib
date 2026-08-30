"""Iteration 4 - storage tracking tests.

Verifies:
- /api/pdfs and /api/pdfs/{id} include storage_type, file_path, drive_file_id
- /api/pdfs/upload returns storage_type, file_path, drive_file_id, drive
- pdf.save / pdf.storage / pdf.upload logs are emitted with correct content/meta
- Migration backfilled storage_type and file_path on pre-existing PDFs
- /api/admin/users returns storage_type per user
- /api/admin/stats includes pdfs_total and backed_up_pdfs
"""
import io
import os
import time
import uuid
import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sheet-music-hub-4.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@scorelib.app"
ADMIN_PASSWORD = "Admin02009!"
ADMIN_LOG_PWD = "Rome02009"


def _admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, text)
    c.drawString(100, 700, f"Page line {uuid.uuid4().hex[:6]}")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def headers():
    return _admin_headers()


# upload + verify response shape
def test_upload_returns_storage_fields(headers):
    pdf_bytes = _make_pdf(f"iter4-storage-{uuid.uuid4().hex[:8]}")
    files = [("files", (f"iter4_{uuid.uuid4().hex[:6]}.pdf", pdf_bytes, "application/pdf"))]
    r = requests.post(f"{BASE_URL}/api/pdfs/upload", headers=headers, files=files, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "results" in data and len(data["results"]) == 1
    res = data["results"][0]
    assert res["ok"] is True, res
    assert "storage_type" in res and res["storage_type"] in ("local", "google_drive")
    assert "file_path" in res and res["file_path"].startswith("/")
    assert "drive_file_id" in res
    assert "drive" in res and isinstance(res["drive"], bool)
    # save id for downstream
    pytest.iter4_pdf_id = res["pdf_id"]
    pytest.iter4_file_path = res["file_path"]
    pytest.iter4_storage_type = res["storage_type"]


# GET /api/pdfs and /api/pdfs/{id} include storage_type/file_path/drive_file_id
def test_list_pdfs_includes_storage_fields(headers):
    r = requests.get(f"{BASE_URL}/api/pdfs", headers=headers, timeout=20)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) > 0
    for p in items:
        assert "storage_type" in p, p
        assert p["storage_type"] in ("local", "google_drive")
        assert "file_path" in p and isinstance(p["file_path"], str)
        assert "drive_file_id" in p  # may be None


def test_get_pdf_includes_storage_fields(headers):
    pid = getattr(pytest, "iter4_pdf_id", None)
    assert pid, "previous upload test must have populated pdf_id"
    r = requests.get(f"{BASE_URL}/api/pdfs/{pid}", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["storage_type"] in ("local", "google_drive")
    assert p["file_path"] == pytest.iter4_file_path
    assert "drive_file_id" in p


# Migration: every pre-existing PDF must now have storage_type and file_path populated
def test_migration_backfilled_all_pdfs(headers):
    r = requests.get(f"{BASE_URL}/api/pdfs", headers=headers, timeout=20)
    assert r.status_code == 200
    items = r.json()["items"]
    missing = [p for p in items if not p.get("storage_type") or not p.get("file_path")]
    assert missing == [], f"PDFs missing storage fields: {missing}"


# pdf.save log includes the absolute path in description and meta
def test_pdf_save_log_contains_path(headers):
    pid = getattr(pytest, "iter4_pdf_id", None)
    fpath = getattr(pytest, "iter4_file_path", None)
    assert pid and fpath
    # query logs filtered by event_type pdf.save
    r = requests.post(f"{BASE_URL}/api/admin/logs",
                      json={"password": ADMIN_LOG_PWD},
                      params={"event_type": "pdf.save", "limit": 200}, timeout=15)
    assert r.status_code == 200, r.text
    logs = r.json()["items"]
    # find the log for our pdf_id
    matches = [lg for lg in logs if lg.get("meta", {}).get("pdf_id") == pid]
    assert matches, f"no pdf.save log found for {pid}"
    lg = matches[0]
    assert fpath in lg["description"], f"path missing in description: {lg['description']}"
    assert lg["meta"].get("path") == fpath


# pdf.storage log description starts with "Storage finale: LOCAL · path=" or "Storage finale: GOOGLE_DRIVE · driveFileId="
def test_pdf_storage_log_format(headers):
    pid = getattr(pytest, "iter4_pdf_id", None)
    storage = getattr(pytest, "iter4_storage_type", None)
    assert pid and storage
    r = requests.post(f"{BASE_URL}/api/admin/logs",
                      json={"password": ADMIN_LOG_PWD},
                      params={"event_type": "pdf.storage", "limit": 200}, timeout=15)
    assert r.status_code == 200
    logs = r.json()["items"]
    matches = [lg for lg in logs if lg.get("meta", {}).get("pdf_id") == pid]
    assert matches, f"no pdf.storage log for {pid}"
    desc = matches[0]["description"]
    if storage == "local":
        assert desc.startswith("Storage finale: LOCAL · path=/"), desc
    else:
        assert desc.startswith("Storage finale: GOOGLE_DRIVE · driveFileId="), desc


# Verify ordering: pdf.save before pdf.storage before pdf.upload
def test_log_emission_order(headers):
    pid = getattr(pytest, "iter4_pdf_id", None)
    assert pid
    r = requests.post(f"{BASE_URL}/api/admin/logs",
                      json={"password": ADMIN_LOG_PWD},
                      params={"limit": 1000, "sort": "date_asc"}, timeout=15)
    assert r.status_code == 200
    logs = r.json()["items"]
    by_type = {}
    for lg in logs:
        if lg.get("meta", {}).get("pdf_id") == pid:
            by_type.setdefault(lg["event_type"], lg["created_at"])
    assert "pdf.save" in by_type
    assert "pdf.storage" in by_type
    assert "pdf.upload" in by_type
    assert by_type["pdf.save"] <= by_type["pdf.storage"] <= by_type["pdf.upload"]


# Local-only user (admin without backup) should produce LOCAL storage log
def test_user_without_drive_produces_local(headers):
    # Admin in seed has backup_enabled=True but no google_refresh_token, so upload still falls through to LOCAL
    pid = getattr(pytest, "iter4_pdf_id", None)
    assert getattr(pytest, "iter4_storage_type", None) == "local"
    # And the storage log should reflect LOCAL
    r = requests.post(f"{BASE_URL}/api/admin/logs",
                      json={"password": ADMIN_LOG_PWD},
                      params={"event_type": "pdf.storage", "limit": 200}, timeout=15)
    logs = [lg for lg in r.json()["items"] if lg.get("meta", {}).get("pdf_id") == pid]
    assert logs[0]["description"].startswith("Storage finale: LOCAL")


# /api/admin/users includes storage_type aggregated per user
def test_admin_users_has_storage_type(headers):
    r = requests.get(f"{BASE_URL}/api/admin/users", headers=headers, timeout=15)
    assert r.status_code == 200
    users = r.json()["users"]
    assert users
    for u in users:
        assert "storage_type" in u
        assert u["storage_type"] in ("google_drive", "local_only")


# /api/admin/stats includes pdfs_total and backed_up_pdfs
def test_admin_stats_storage_counts(headers):
    r = requests.get(f"{BASE_URL}/api/admin/stats", headers=headers, timeout=15)
    assert r.status_code == 200
    s = r.json()
    assert "pdfs_total" in s and isinstance(s["pdfs_total"], int)
    assert "backed_up_pdfs" in s and isinstance(s["backed_up_pdfs"], int)
    assert s["backed_up_pdfs"] <= s["pdfs_total"]
