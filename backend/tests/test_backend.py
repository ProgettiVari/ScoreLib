"""Comprehensive backend tests for Scorelib."""
import io
import os
import re
import sys
import time
import types
import uuid
import requests
import pytest

# Allow direct imports from the backend directory for local unit tests.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://sheet-music-hub-4.preview.emergentagent.com").rstrip("/")


# ---------------- AUTH ----------------
class TestAuth:
    def test_health(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_register_and_duplicate(self, api_client):
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        r = api_client.post(f"{BASE_URL}/api/auth/register",
                            json={"email": email, "password": "Pass1234!"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data and "user" in data
        assert data["user"]["email"] == email
        # duplicate
        r2 = api_client.post(f"{BASE_URL}/api/auth/register",
                             json={"email": email, "password": "Pass1234!"})
        assert r2.status_code == 409

    def test_register_short_password(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/register",
                            json={"email": f"x_{uuid.uuid4().hex[:6]}@example.com", "password": "abc"})
        assert r.status_code == 422

    def test_login_admin_and_me(self, api_client, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 10
        r = api_client.get(f"{BASE_URL}/api/auth/me",
                           headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["email"] == "admin@scorelib.app"

    def test_login_wrong_password(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login",
                            json={"email": "admin@scorelib.app", "password": "wrong!!"})
        assert r.status_code == 401

    def test_me_no_token(self, api_client):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_forgot_existing_returns_ok(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/forgot",
                            json={"email": "admin@scorelib.app"})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_forgot_unknown_returns_ok(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/forgot",
                            json={"email": f"nope_{uuid.uuid4().hex[:6]}@example.com"})
        assert r.status_code == 200

    def test_reset_invalid_token(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/reset",
                            json={"token": "INVALID_TOKEN_XYZ", "password": "NewPass123!"})
        assert r.status_code == 400


class TestAccessRequests:
    def test_approved_request_blocks_new_submission(self, api_client, auth_headers):
        email = f"approved_{uuid.uuid4().hex[:8]}@example.com"
        name = "Tester Approved"

        r1 = api_client.post(f"{BASE_URL}/api/auth/request-access", json={"name": name, "email": email})
        assert r1.status_code == 200, r1.text

        r2 = api_client.post(f"{BASE_URL}/api/admin/access-requests/approve", json={"email": email}, headers=auth_headers)
        assert r2.status_code == 200, r2.text

        r3 = api_client.post(f"{BASE_URL}/api/auth/request-access", json={"name": name, "email": email})
        assert r3.status_code == 409, r3.text

    def test_rejected_request_can_be_resubmitted(self, api_client, auth_headers):
        email = f"rejected_{uuid.uuid4().hex[:8]}@example.com"
        name = "Tester Rejected"

        r1 = api_client.post(f"{BASE_URL}/api/auth/request-access", json={"name": name, "email": email})
        assert r1.status_code == 200, r1.text

        r2 = api_client.post(f"{BASE_URL}/api/admin/access-requests/reject", json={"email": email}, headers=auth_headers)
        assert r2.status_code == 200, r2.text

        r3 = api_client.post(f"{BASE_URL}/api/auth/request-access", json={"name": name, "email": email})
        assert r3.status_code == 200, r3.text


# ---------------- PROFILE / SETTINGS ----------------
class TestProfileSettings:
    def test_patch_profile(self, api_client, auth_headers):
        r = api_client.patch(f"{BASE_URL}/api/profile",
                             json={"name": "Admin Tester", "how_found": "test", "profile_completed": True},
                             headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Admin Tester"
        assert data["profile_completed"] is True

    def test_backup_toggle(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/settings/backup",
                            json={"enabled": False}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["backup_enabled"] is False
        # Activating requires Drive connection; admin seed has no refresh_token.
        r2 = api_client.post(f"{BASE_URL}/api/settings/backup",
                             json={"enabled": True}, headers=auth_headers)
        assert r2.status_code == 400  # Drive non connesso
        assert "Drive" in r2.json().get("detail", "")

    def test_change_password_wrong_current(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/settings/password",
                            json={"current_password": "WRONG", "new_password": "WhatEver123!"},
                            headers=auth_headers)
        assert r.status_code == 401

    def test_change_email_wrong_password(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/settings/email",
                            json={"password": "WRONG", "new_email": "newmail@example.com"},
                            headers=auth_headers)
        assert r.status_code == 401


# ---------------- PDFs ----------------
@pytest.fixture(scope="class")
def uploaded_pdf(api_client, auth_headers, sample_pdf_bytes):
    files = {"files": (f"test_{uuid.uuid4().hex[:6]}.pdf", sample_pdf_bytes, "application/pdf")}
    r = requests.post(f"{BASE_URL}/api/pdfs/upload",
                      headers={"Authorization": auth_headers["Authorization"]},
                      files=files)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    if res.get("duplicate"):
        # Re-use existing record from previous class within the same session
        return {"ok": True, "pdf_id": res["existing_id"], "pages": 2, "ocr": False}
    assert res["ok"] is True, res
    return res


class TestPdfs:
    def test_upload_invalid_pdf(self, auth_headers):
        files = {"files": ("bad.pdf", b"NOTAPDF DATA", "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/pdfs/upload",
                          headers={"Authorization": auth_headers["Authorization"]},
                          files=files)
        assert r.status_code == 200
        res = r.json()["results"][0]
        assert res["ok"] is False
        assert "Non è un PDF valido" in res.get("error", "")

    def test_upload_real_pdf(self, uploaded_pdf):
        assert uploaded_pdf["ok"] is True
        assert uploaded_pdf["pages"] >= 1
        assert "pdf_id" in uploaded_pdf
        assert "ocr" in uploaded_pdf

    def test_upload_duplicate(self, auth_headers, sample_pdf_bytes, uploaded_pdf):
        # send same content again
        files = {"files": ("dup.pdf", sample_pdf_bytes, "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/pdfs/upload",
                          headers={"Authorization": auth_headers["Authorization"]},
                          files=files)
        assert r.status_code == 200
        res = r.json()["results"][0]
        assert res.get("duplicate") is True
        assert res["ok"] is False

    def test_list_pdfs(self, api_client, auth_headers, uploaded_pdf):
        r = api_client.get(f"{BASE_URL}/api/pdfs?sort=date_desc", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "tags" in d
        ids = [x["id"] for x in d["items"]]
        assert uploaded_pdf["pdf_id"] in ids

    def test_list_pdfs_sort_variants(self, api_client, auth_headers):
        for s in ["date_asc", "name_asc", "name_desc"]:
            r = api_client.get(f"{BASE_URL}/api/pdfs?sort={s}", headers=auth_headers)
            assert r.status_code == 200

    def test_patch_favorite_and_tags(self, api_client, auth_headers, uploaded_pdf):
        pid = uploaded_pdf["pdf_id"]
        r = api_client.patch(f"{BASE_URL}/api/pdfs/{pid}",
                             json={"is_favorite": True, "tags": ["jazz", "Worship"]},
                             headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["is_favorite"] is True
        assert "jazz" in d["tags"] and "worship" in d["tags"]

        r2 = api_client.get(f"{BASE_URL}/api/pdfs?favorite=true", headers=auth_headers)
        assert r2.status_code == 200
        ids = [x["id"] for x in r2.json()["items"]]
        assert pid in ids

        r3 = api_client.get(f"{BASE_URL}/api/pdfs?tag=jazz", headers=auth_headers)
        assert pid in [x["id"] for x in r3.json()["items"]]

    def test_get_pdf_file_inline(self, auth_headers, uploaded_pdf):
        pid = uploaded_pdf["pdf_id"]
        r = requests.get(f"{BASE_URL}/api/pdfs/{pid}/file", headers=auth_headers)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" not in cd.lower()
        assert r.content[:4] == b"%PDF"


def test_clean_pdf_text_removes_music_symbols():
    from pdf_processor import clean_pdf_text

    text = "Pace vera pace œ ˙ œ 1 2 3 … D7 G#min GesùCristo"

    cleaned = clean_pdf_text(text)

    assert "Pace" in cleaned
    assert "œ" not in cleaned
    assert "˙" not in cleaned
    assert "…" not in cleaned
    assert "D7" not in cleaned
    assert "G#min" not in cleaned
    assert "Gesù Cristo" in cleaned
    assert "GesùCristo" not in cleaned


def test_clean_pdf_text_keeps_common_words_while_removing_chords():
    from pdf_processor import clean_pdf_text

    text = "LA-7 la tua fedeltà DO SOL FA DO son sulla via"

    cleaned = clean_pdf_text(text)

    assert "la tua fedeltà" in cleaned
    assert "DO SOL FA DO" not in cleaned
    assert "son sulla via" in cleaned


def test_clean_pdf_text_preserves_apostrophes_and_normalizes_typographic_quotes():
    from pdf_processor import clean_pdf_text

    text = "L’amore è qui"

    cleaned = clean_pdf_text(text)

    assert "L'amore" in cleaned
    assert "è qui" in cleaned


def test_clean_pdf_text_removes_decorative_number_tokens():
    from pdf_processor import clean_pdf_text

    text = "Canto ~ 542 ~ della domenica"

    cleaned = clean_pdf_text(text)

    assert "~ 542 ~" not in cleaned
    assert "Canto" in cleaned
    assert "domenica" in cleaned


def test_has_useful_page_text_threshold():
    import pdf_processor

    assert pdf_processor._has_useful_page_text("Questo è un testo valido con parole sufficienti.") is True
    assert pdf_processor._has_useful_page_text("Solo poche parole") is False
    assert pdf_processor._has_useful_page_text("   ") is False


def test_has_boilerplate_text_detects_watermark():
    import pdf_processor

    assert pdf_processor._has_boilerplate_text("Creato in un convertitore da foto PDF con un clic Scarica qui") is True
    assert pdf_processor._has_boilerplate_text("Questo è un documento di esempio creato da un convertitore PDF online") is True
    assert pdf_processor._has_boilerplate_text("Questa pagina contiene testo reale e contenuto utile") is False


def test_normalize_pdf_text_removes_diacritics_and_replaces_typos():
    import pdf_processor

    normalized = pdf_processor.normalize_pdf_text("Gesù Cristo è qui. Gest Diò!")
    assert "Gesù" in normalized
    assert "Dio" in normalized
    assert "Cristo" in normalized
    assert "è" not in normalized


def test_extract_page_metadata_detects_cantico_number():
    import pdf_processor

    metadata = pdf_processor.extract_page_metadata("Canto 542 della domenica")
    assert metadata.get("cantico") == 542


def test_boilerplate_text_alone_does_not_trigger_ocr():
    """Regression test: boilerplate should NOT trigger OCR on its own.
    This was the bug that caused 54-page PDFs to take 90+ seconds."""
    import io
    import fitz
    from reportlab.pdfgen import canvas as reportlab_canvas
    import pdf_processor
    
    # Create a PDF page with only boilerplate text (no real content, no images)
    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 10)
    c.drawString(100, 700, "Creato in un convertitore da foto PDF con un clic")
    c.drawString(100, 680, "Scarica qui www.example.com")
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    
    # Extract pages - should NOT attempt OCR since:
    # - page has boilerplate (detected)
    # - BUT page has no images
    # - AND page has text > 40 chars
    # - AND page has word_count >= 3
    pages_text, raw_texts, total_pages, used_ocr, page_labels = pdf_processor.extract_pages(pdf_bytes)
    
    assert total_pages == 1
    assert raw_texts[0].startswith("Creato in un convertitore")
    # boilerplate text alone should NOT trigger OCR or improve text
    assert used_ocr is False, "Boilerplate alone should not trigger OCR"


def test_page_has_images_detects_image_page():
    import pdf_processor

    class DummyPage:
        def get_images(self, full=True):
            return [(1, 2, 3)]

    assert pdf_processor._page_has_images(DummyPage()) is True


def test_ocr_page_text_prefers_rapidocr_when_available(monkeypatch):
    import pdf_processor

    class DummyPage:
        def get_pixmap(self, alpha=False, dpi=150):
            return types.SimpleNamespace(width=1, height=1, samples=b"\x00\x00\x00")

    class FakeRapidOCR:
        def __init__(self):
            self.calls = 0

        def __call__(self, img):
            self.calls += 1
            return types.SimpleNamespace(txts=("RAPID OCR TEXT",))

    rapid_engine = FakeRapidOCR()

    class FakeImage:
        @staticmethod
        def frombytes(*args, **kwargs):
            return object()

    monkeypatch.setattr(pdf_processor, "_rapidocr_engine", None)
    monkeypatch.setattr(pdf_processor, "_create_rapidocr_engine", lambda: rapid_engine)
    monkeypatch.setattr(pdf_processor, "_tesseract_ocr_text", lambda page: "TESSERACT OCR TEXT")

    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=FakeImage))
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=lambda img: img))

    text = pdf_processor._ocr_page_text(DummyPage())

    assert text == "RAPID OCR TEXT"
    assert rapid_engine.calls == 1


def test_ocr_page_text_prefers_direct_embedded_image_ocr(monkeypatch):
    import pdf_processor

    class DummyPage:
        def get_images(self, full=True):
            return [(1,)]

        def extract_image(self, xref):
            return {"image": b"embedded-image-bytes", "ext": "png"}

    calls = {"direct": 0, "fallback": 0}

    def fake_direct(page, timings=None, page_num=None):
        calls["direct"] += 1
        return "DIRECT IMAGE OCR"

    def fake_tesseract(page, timings=None, page_num=None):
        calls["fallback"] += 1
        return "FALLBACK OCR"

    monkeypatch.setattr(pdf_processor, "_ocr_direct_image", fake_direct)
    monkeypatch.setattr(pdf_processor, "_tesseract_ocr_text", fake_tesseract)
    monkeypatch.setattr(pdf_processor, "_extract_text_with_rapidocr", lambda page, timings=None: "")

    text = pdf_processor._ocr_page_text(DummyPage())

    assert text == "DIRECT IMAGE OCR"
    assert calls == {"direct": 1, "fallback": 0}


def test_ocr_page_text_falls_back_to_tesseract_when_rapidocr_fails(monkeypatch):
    import pdf_processor

    class DummyPage:
        def get_pixmap(self, alpha=False, dpi=150):
            return types.SimpleNamespace(width=1, height=1, samples=b"\x00\x00\x00")

    class FakeImage:
        @staticmethod
        def frombytes(*args, **kwargs):
            return object()

    def fail_engine():
        raise RuntimeError("rapidocr failed")

    monkeypatch.setattr(pdf_processor, "_rapidocr_engine", None)
    monkeypatch.setattr(pdf_processor, "_create_rapidocr_engine", fail_engine)
    monkeypatch.setattr(pdf_processor, "_tesseract_ocr_text", lambda page, timings=None, page_num=None: "TESSERACT OCR TEXT")
    monkeypatch.setattr(pdf_processor, "_extract_text_with_rapidocr", lambda page, timings=None: "")
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=FakeImage))
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=lambda img: img))

    text = pdf_processor._ocr_page_text(DummyPage())

    assert text == "TESSERACT OCR TEXT"


def test_find_tesseract_binary_falls_back_when_explicit_path_is_invalid(monkeypatch):
    import pdf_processor

    monkeypatch.setenv("TESSERACT_PATH", "/nonexistent/tesseract")
    monkeypatch.setattr(pdf_processor.shutil, "which", lambda name: "/usr/bin/tesseract")

    found = pdf_processor._find_tesseract_binary()

    assert found == "/usr/bin/tesseract"


def test_ocr_page_text_does_not_call_google_vision_when_tesseract_is_missing(monkeypatch):
    import pdf_processor

    class DummyPage:
        pass

    called = {"vision": False}

    def fake_extract(page):
        called["vision"] = True
        return ""

    monkeypatch.setattr(pdf_processor, "_find_tesseract_binary", lambda: "")
    monkeypatch.setattr(pdf_processor, "_extract_text_with_google_vision", fake_extract)
    monkeypatch.setattr(pdf_processor, "_warn_no_ocr_backend", lambda: None)

    try:
        import pytesseract  # noqa: F401
    except Exception:
        pass

    text = pdf_processor._ocr_page_text(DummyPage())

    assert text == ""
    assert called["vision"] is False


# ---------------- SEARCH ----------------
class TestSearch:
    def test_normalize_pdf_text_collapses_apostrophe_spacing(self):
        import pdf_processor

        assert pdf_processor.normalize_pdf_text("dall' amore") == "dall'amore"
        assert pdf_processor.normalize_pdf_text("dall'amore") == pdf_processor.normalize_pdf_text("dall' amore")

    def test_normalize_search_query_handles_accents_apostrophes_and_case(self):
        import pdf_processor

        assert pdf_processor.normalize_search_query("perché") == "perche"
        assert pdf_processor.normalize_search_query("PERCHÉ") == "perche"
        assert pdf_processor.normalize_search_query("città") == "citta"
        assert pdf_processor.normalize_search_query("cuor'e") == "cuor'e"
        assert pdf_processor.normalize_search_query("l’amore") == "l'amore"
        assert pdf_processor.normalize_search_query("l amore") == "l amore"

    def test_build_apostrophe_tolerant_regex_matches_variants(self):
        import pdf_processor

        pattern = pdf_processor.build_apostrophe_tolerant_regex("l'amore")
        assert re.search(pattern, "l'amore", re.IGNORECASE)
        assert re.search(pattern, "l amore", re.IGNORECASE)
        assert re.search(pattern, "LAMORE", re.IGNORECASE)
        assert re.search(pattern, "l’amore", re.IGNORECASE)
        assert re.search(pattern, "l   amore", re.IGNORECASE)
        
        # Validate cuor'e/cuor e as a separate pattern (d'amore → damore case)
        pattern_cuore = pdf_processor.build_apostrophe_tolerant_regex("cuor'e")
        assert re.search(pattern_cuore, "cuore", re.IGNORECASE)
        assert re.search(pattern_cuore, "cuor e", re.IGNORECASE)

    def test_text_matches_query_handles_common_variants(self):
        import pdf_processor

        assert pdf_processor.text_matches_query("Quando mi sento", "quando mi sento") is True
        assert pdf_processor.text_matches_query("Quando mi sento", "QUANDO MI SENTO") is True
        assert pdf_processor.text_matches_query("cuor'e nel vento", "cuore") is True
        assert pdf_processor.text_matches_query("l'amore infinito", "l amore") is True
        assert pdf_processor.text_matches_query("d'amore", "damore") is True

    def test_text_matches_query_handles_minor_ocr_differences(self):
        import pdf_processor

        assert pdf_processor.text_matches_query("piu", "pid") is True
        assert pdf_processor.text_matches_query("piu", "più") is True
        assert pdf_processor.text_matches_query("l'amore", "l amore") is True
        assert pdf_processor.text_matches_query("citta", "città") is True

    def test_make_snippet_separates_lines_with_periods(self):
        import pdf_processor

        snippet = pdf_processor.make_snippet("Prima linea\nSeconda linea", "Prima")

        assert "Prima linea" in snippet
        assert "Seconda linea" in snippet

    def test_search_returns_results(self, api_client, auth_headers, uploaded_pdf):
        # word from uploaded pdf body
        r = api_client.get(f"{BASE_URL}/api/search?q=jazz", headers=auth_headers)
        assert r.status_code == 200
        results = r.json()["results"]
        assert isinstance(results, list)
        if results:
            r0 = results[0]
            for k in ["pdf_id", "title", "page", "snippet", "source", "match_in"]:
                assert k in r0

    def test_search_no_token(self):
        r = requests.get(f"{BASE_URL}/api/search?q=x")
        assert r.status_code == 401


# ---------------- LIBRARIES ----------------
class TestLibraries:
    def test_create_list_add_share(self, api_client, auth_headers, uploaded_pdf):
        # create
        r = api_client.post(f"{BASE_URL}/api/libraries",
                            json={"name": f"TEST_LIB_{uuid.uuid4().hex[:6]}", "description": "test"},
                            headers=auth_headers)
        assert r.status_code == 200
        lib = r.json()
        assert "share_token" in lib and "id" in lib
        lib_id = lib["id"]

        # list
        rl = api_client.get(f"{BASE_URL}/api/libraries", headers=auth_headers)
        assert rl.status_code == 200
        ids = [x["id"] for x in rl.json()["items"]]
        assert lib_id in ids

        # add pdf
        rp = api_client.post(f"{BASE_URL}/api/libraries/{lib_id}/pdfs",
                             json={"pdf_ids": [uploaded_pdf["pdf_id"]]},
                             headers=auth_headers)
        assert rp.status_code == 200
        assert uploaded_pdf["pdf_id"] in rp.json()["added"]

        # shared without auth -> 401
        rs = requests.get(f"{BASE_URL}/api/shared/{lib['share_token']}")
        assert rs.status_code == 401
        # with auth -> 200
        rs2 = requests.get(f"{BASE_URL}/api/shared/{lib['share_token']}", headers=auth_headers)
        assert rs2.status_code == 200
        d = rs2.json()
        assert "pdfs" in d and len(d["pdfs"]) >= 1

        # cleanup
        api_client.delete(f"{BASE_URL}/api/libraries/{lib_id}", headers=auth_headers)

    def test_add_to_library_skips_protected(self, api_client, auth_headers, sample_pdf_bytes):
        # upload one protected pdf and one normal pdf
        files1 = {"files": (f"protected_{uuid.uuid4().hex[:6]}.pdf", sample_pdf_bytes, "application/pdf")}
        r1 = requests.post(f"{BASE_URL}/api/pdfs/upload",
                           headers={"Authorization": auth_headers["Authorization"]},
                           files=files1)
        assert r1.status_code == 200
        pid_protected = r1.json()["results"][0]["pdf_id"]

        r2 = api_client.patch(f"{BASE_URL}/api/pdfs/{pid_protected}",
                               json={"is_protected": True},
                               headers=auth_headers)
        assert r2.status_code == 200

        files2 = {"files": (f"normal_{uuid.uuid4().hex[:6]}.pdf", sample_pdf_bytes, "application/pdf")}
        r3 = requests.post(f"{BASE_URL}/api/pdfs/upload",
                           headers={"Authorization": auth_headers["Authorization"]},
                           files=files2)
        assert r3.status_code == 200
        pid_normal = r3.json()["results"][0]["pdf_id"]

        # create library and add both
        rl = api_client.post(f"{BASE_URL}/api/libraries",
                             json={"name": f"TEST_LIB_{uuid.uuid4().hex[:6]}", "description": "test"},
                             headers=auth_headers)
        assert rl.status_code == 200
        lib_id = rl.json()["id"]

        rp = api_client.post(f"{BASE_URL}/api/libraries/{lib_id}/pdfs",
                             json={"pdf_ids": [pid_protected, pid_normal]},
                             headers=auth_headers)
        assert rp.status_code == 200
        data = rp.json()
        assert pid_normal in data["added"]
        assert pid_protected in data["protected"]
        assert pid_protected not in data["added"]

        api_client.delete(f"{BASE_URL}/api/libraries/{lib_id}", headers=auth_headers)


# ---------------- ADMIN LOGS ----------------
class TestAdminLogs:
    def test_admin_logs_correct_pwd(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/admin/logs",
                            json={"password": "Rome02009"})
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "types" in d

    def test_admin_logs_wrong_pwd(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/admin/logs",
                            json={"password": "wrong"})
        assert r.status_code == 401
