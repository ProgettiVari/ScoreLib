import os
import sys
import io
import uuid
import pytest
import requests
from reportlab.pdfgen import canvas

# Allow tests in this folder to import backend modules (e.g. pdf_processor)
# directly, since pytest only adds this folder's own directory to sys.path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Try to load .env.test if available (convenience), but env vars are the source of truth
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env.test"), verbose=False)
except Exception:
    pass  # .env.test not found, use env vars or defaults

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sheet-music-hub-4.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@scorelib.app")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin02009!")  # env var or fallback


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api_client):
    r = api_client.post(f"{BASE_URL}/api/auth/login",
                        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"admin login failed {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _make_pdf_bytes(text: str = "Jazz worship gospel test content unique sample") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, text)
    c.drawString(100, 700, "Page one body line.")
    c.showPage()
    c.drawString(100, 750, "Second page note coro lead sheet")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="session")
def sample_pdf_bytes():
    # unique content per session to avoid duplicate
    return _make_pdf_bytes(f"Jazz worship gospel UNIQUE-{uuid.uuid4().hex[:8]} test")


@pytest.fixture(scope="session")
def sample_pdf_bytes_2():
    return _make_pdf_bytes(f"Another piano solo UNIQUE-{uuid.uuid4().hex[:8]} sample")
