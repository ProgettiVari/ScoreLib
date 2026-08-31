"""Iteration 3 admin endpoints tests: /api/admin/users, /api/admin/stats, pdf.open log."""
import os
import io
import time
import uuid
import requests
import pytest

# Ensure env vars are loaded for test credentials
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env.test"), verbose=False)
except Exception:
    pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sheet-music-hub-4.preview.emergentagent.com").rstrip("/")


# ---- helper fixture: a normal (non-admin) registered user
@pytest.fixture(scope="module")
def normal_user_token(api_client):
    email = f"normal_{uuid.uuid4().hex[:8]}@example.com"
    r = api_client.post(f"{BASE_URL}/api/auth/register",
                        json={"email": email, "password": "Pass1234!"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


class TestAdminUsersEndpoint:
    def test_no_token_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/users")
        assert r.status_code == 401

    def test_non_admin_returns_403(self, normal_user_token):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers={"Authorization": f"Bearer {normal_user_token}"})
        assert r.status_code == 403
        assert "amministratore" in r.json().get("detail", "").lower()

    def test_admin_returns_users_list_with_required_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "users" in data and "total" in data
        assert isinstance(data["users"], list)
        assert data["total"] == len(data["users"])
        assert data["total"] >= 1
        required = {"user_id", "email", "name", "auth_provider", "is_admin",
                    "backup_enabled", "drive_connected", "storage_type",
                    "pdf_count", "backed_up_pdfs"}
        for u in data["users"]:
            missing = required - set(u.keys())
            assert not missing, f"missing fields in user obj: {missing}"
            assert u["storage_type"] in ("google_drive", "local_only")
            assert isinstance(u["pdf_count"], int)
            assert isinstance(u["backed_up_pdfs"], int)

    def test_admin_list_includes_admin_user(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
        assert r.status_code == 200
        emails = [u["email"] for u in r.json()["users"]]
        assert "admin@scorelib.app" in emails
        admin_obj = next(u for u in r.json()["users"] if u["email"] == "admin@scorelib.app")
        assert admin_obj["is_admin"] is True


class TestAdminStatsEndpoint:
    def test_no_token_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats")
        assert r.status_code == 401

    def test_non_admin_returns_403(self, normal_user_token):
        r = requests.get(f"{BASE_URL}/api/admin/stats",
                         headers={"Authorization": f"Bearer {normal_user_token}"})
        assert r.status_code == 403

    def test_admin_returns_full_stats(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        keys = ["users_total", "google_users", "local_users",
                "pdfs_total", "backed_up_pdfs", "shared_libraries",
                "events_24h", "errors_24h"]
        for k in keys:
            assert k in d, f"missing key {k}"
            assert isinstance(d[k], int)
        # consistency
        assert d["users_total"] >= 1
        assert d["google_users"] + d["local_users"] == d["users_total"]
        assert d["backed_up_pdfs"] <= d["pdfs_total"]


# ---- pdf.open log event when calling GET /api/pdfs/{id}
class TestPdfOpenLog:
    def test_pdf_open_logs_event(self, api_client, auth_headers):
        # find an existing PDF (may be from previous tests)
        r = requests.get(f"{BASE_URL}/api/pdfs", headers=auth_headers)
        assert r.status_code == 200
        items = r.json().get("items", [])
        if not items:
            pytest.skip("No PDFs available to open in admin library")
        pid = items[0]["id"]
        # call GET /api/pdfs/{id}
        rr = requests.get(f"{BASE_URL}/api/pdfs/{pid}", headers=auth_headers)
        assert rr.status_code == 200, rr.text
        # small delay for log insert
        time.sleep(0.5)
        # query admin logs and look for pdf.open
        rl = api_client.post(f"{BASE_URL}/api/admin/logs",
                             json={"password": os.environ.get("ADMIN_LOG_PASSWORD", "Rome02009")},
                             params={"event_type": "pdf.open", "limit": 50})
        assert rl.status_code == 200
        types = [it.get("event_type") for it in rl.json().get("items", [])]
        assert "pdf.open" in types, f"pdf.open log not found, got types={types}"
