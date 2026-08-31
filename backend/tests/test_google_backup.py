"""Tests for Google OAuth and Drive backup endpoints (Iteration 2)."""
import os
import requests
import pytest

# Try to load .env.test if available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env.test"), verbose=False)
except Exception:
    pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sheet-music-hub-4.preview.emergentagent.com").rstrip("/")
EXPECTED_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "239524592693-qhl4tacfd7t1ids24bq9tq5dj31a8mlk.apps.googleusercontent.com")


# -------- Google OAuth URL --------
class TestGoogleOAuthUrl:
    def test_auth_url_returns_url_and_state(self, api_client):
        redirect = "https://example.com/auth/google/callback"
        r = api_client.post(f"{BASE_URL}/api/auth/google/url",
                            json={"redirect_uri": redirect})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "url" in data and "state" in data
        assert isinstance(data["state"], str) and len(data["state"]) > 8
        assert "accounts.google.com" in data["url"]
        assert f"client_id={EXPECTED_CLIENT_ID}" in data["url"]
        # redirect_uri encoded
        assert "redirect_uri=" in data["url"]
        assert "scope=" in data["url"]
        # ensure state is forwarded into url
        assert f"state={data['state']}" in data["url"]


# -------- Google OAuth code exchange --------
class TestGoogleOAuthExchange:
    def test_invalid_code_login_returns_401(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/google",
                            json={"code": "INVALID_FAKE_CODE_xyz",
                                  "redirect_uri": "https://example.com/auth/google/callback"})
        # 401 expected per spec; 503 if google not configured
        assert r.status_code in (401, 503), r.text
        if r.status_code == 401:
            assert "Google" in r.json().get("detail", "")

    def test_connect_requires_jwt(self, api_client):
        # No Authorization header
        r = requests.post(f"{BASE_URL}/api/auth/google/connect",
                          json={"code": "x", "redirect_uri": "https://example.com/auth/google/callback"})
        assert r.status_code == 401

    def test_connect_invalid_code_returns_401(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/auth/google/connect",
                            json={"code": "INVALID_FAKE_CODE_xyz",
                                  "redirect_uri": "https://example.com/auth/google/callback"},
                            headers=auth_headers)
        assert r.status_code in (401, 503)


# -------- /api/auth/me extra fields --------
class TestAuthMeExtraFields:
    def test_me_has_admin_and_drive_fields(self, api_client, auth_headers):
        r = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert "has_google_drive" in d, d
        assert "is_admin" in d, d
        assert isinstance(d["has_google_drive"], bool)
        assert isinstance(d["is_admin"], bool)
        # admin seed must be admin
        assert d["is_admin"] is True
        # admin seed has no Drive yet
        assert d["has_google_drive"] is False


# -------- /api/backup/status --------
class TestBackupStatus:
    def test_status_admin(self, api_client, auth_headers):
        r = api_client.get(f"{BASE_URL}/api/backup/status", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["backup_enabled", "drive_connected", "drive_email",
                  "total_pdfs", "backed_up_pdfs", "pending_pdfs", "last_backup_at"]:
            assert k in d, f"missing key {k} in {d}"
        assert isinstance(d["backup_enabled"], bool)
        assert isinstance(d["drive_connected"], bool)
        assert isinstance(d["total_pdfs"], int)
        assert isinstance(d["backed_up_pdfs"], int)
        assert isinstance(d["pending_pdfs"], int)
        assert d["pending_pdfs"] == max(0, d["total_pdfs"] - d["backed_up_pdfs"])
        # admin seed has no drive
        assert d["drive_connected"] is False

    def test_status_no_token(self):
        r = requests.get(f"{BASE_URL}/api/backup/status")
        assert r.status_code == 401


# -------- /api/backup/run and /api/backup/test --------
class TestBackupRunTest:
    def test_run_without_drive_returns_400(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/backup/run", headers=auth_headers)
        assert r.status_code == 400, r.text
        assert "Drive" in r.json().get("detail", "")

    def test_test_without_drive_returns_400(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/backup/test", headers=auth_headers)
        assert r.status_code == 400, r.text
        assert "Drive" in r.json().get("detail", "")

    def test_run_no_token(self):
        r = requests.post(f"{BASE_URL}/api/backup/run")
        assert r.status_code == 401


# -------- /api/settings/backup --------
class TestSettingsBackup:
    def test_disable_always_ok(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/settings/backup",
                            json={"enabled": False}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["backup_enabled"] is False

    def test_enable_without_drive_returns_400(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/settings/backup",
                            json={"enabled": True}, headers=auth_headers)
        assert r.status_code == 400
        assert "Drive" in r.json().get("detail", "")
