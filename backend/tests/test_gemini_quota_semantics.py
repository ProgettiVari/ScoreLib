import os
import sys

sys.path.insert(0, "C:/Users/miche/Downloads/boh-emerg-cleanup-final-1/boh-emerg-cleanup-final/backend")
os.environ.setdefault("JWT_SECRET", "quota-semantics-test-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "quota_semantics_test")

import pdf_processor
import server


class DummyResponse:
    def __init__(self, status_code, headers=None, text="", payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status: {self.status_code}")

    def json(self):
        return self._payload or {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


def _configure_gemini(monkeypatch):
    monkeypatch.setattr(pdf_processor, "GEMINI_API_KEYS", ["key0", "key1"])
    monkeypatch.setattr(pdf_processor, "GEMINI_API_KEY", "key0")
    monkeypatch.setattr(pdf_processor, "_GEMINI_EXHAUSTED_KEYS", set())
    monkeypatch.setattr(pdf_processor, "_render_page_for_gemini", lambda page: b"png")


def test_one_exhausted_key_and_one_success_does_not_wait(monkeypatch):
    _configure_gemini(monkeypatch)

    def fake_post(url, json, headers, timeout):
        if headers["x-goog-api-key"] == "key0":
            return DummyResponse(429, {"Retry-After": "0"}, "daily quota exceeded")
        return DummyResponse(200, payload={"candidates": [{"content": {"parts": [{"text": "done"}]}}]})

    monkeypatch.setattr(pdf_processor.httpx, "post", fake_post)
    timings = {}

    assert pdf_processor._gemini_ocr_page(object(), timings=timings, page_num=41) == "done"
    assert timings.get("gemini_quota_waiting") is not True


def test_all_keys_exhausted_sets_waiting(monkeypatch):
    _configure_gemini(monkeypatch)
    monkeypatch.setattr(
        pdf_processor.httpx,
        "post",
        lambda url, json, headers, timeout: DummyResponse(429, {"Retry-After": "0"}, "daily quota exceeded"),
    )
    timings = {}

    assert pdf_processor._gemini_ocr_page(object(), timings=timings, page_num=41) == ""
    assert timings["gemini_quota_waiting"] is True
    assert timings["gemini_quota_reason"] == "all_keys_exhausted"


def test_empty_pending_does_not_wait_when_all_pages_are_extracted():
    assert server._should_wait_for_gemini_quota(
        {"gemini_quota_waiting": True},
        [],
        [f"page {page}" for page in range(1, 55)],
        list(range(1, 55)),
        54,
        [],
    ) is False


def test_incomplete_pages_still_wait_when_quota_is_exhausted():
    assert server._should_wait_for_gemini_quota(
        {"gemini_quota_waiting": True},
        [41],
        [f"page {page}" for page in range(1, 41)],
        list(range(1, 42)),
        54,
        list(range(1, 41)),
    ) is True
