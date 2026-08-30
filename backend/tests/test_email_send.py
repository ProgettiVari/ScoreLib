import os
import sys
import asyncio
import importlib.util
import pathlib
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from dotenv import load_dotenv

load_dotenv(Path('.') / '.env', override=False)

@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'testsecret')
    monkeypatch.setenv('MONGO_URL', 'mongodb://localhost:27017')
    monkeypatch.setenv('DB_NAME', 'test')
    monkeypatch.setenv('EMAIL_FROM_ADDRESS', 'ScoreLib <no-reply@scorelib.app>')
    yield

def import_server_module():
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    try:
        spec = importlib.util.spec_from_file_location('server_under_test', backend_dir / 'server.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['server_under_test'] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if str(backend_dir) in sys.path:
            sys.path.remove(str(backend_dir))

def test_send_email_function_exists():
    module = import_server_module()
    assert hasattr(module, 'send_email')
    assert callable(module.send_email)
    assert module.send_email.__code__.co_argcount >= 3

class DummyResponse:
    def __init__(self, status_code=200, text='ok'):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        return None

class DummyAsyncClient:
    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        assert url == 'https://formsubmit.co/ajax/no-reply%40scorelib.app'
        assert json['_subject'] == 'Fallback subject'
        assert json['message'] == '<p>Fallback</p>'
        assert json['email'] == 'no-reply@scorelib.app'
        assert headers['Content-Type'] == 'application/json'
        return DummyResponse()

class DummyHTTPX:
    AsyncClient = DummyAsyncClient
    HTTPStatusError = Exception


class DummyAsyncClientBrevo:
    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        assert url == 'https://api.brevo.com/v3/smtp/email'
        assert json['to'][0]['email'] == 'user@example.com'
        assert headers['api-key'] == 'test-brevo-key'
        return DummyResponse(status_code=202)


class DummyHTTPXBrevo:
    AsyncClient = DummyAsyncClientBrevo
    HTTPStatusError = Exception


class FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, func, *args):
        self.calls.append((func, args))


class FakeAccessRequests:
    def __init__(self):
        self.updates = []

    async def find_one(self, query):
        return {"name": "Tester User"}

    async def update_one(self, query, update):
        self.updates.append((query, update))


def test_send_email_via_formsubmit(monkeypatch):
    module = import_server_module()
    monkeypatch.setattr(module, 'httpx', DummyHTTPX)

    asyncio.run(module.send_email('test@example.com', 'Fallback subject', '<p>Fallback</p>'))


def test_send_email_via_smtp_uses_brevo_api(monkeypatch):
    module = import_server_module()
    module.SMTP_ENABLED = True
    module.BREVO_API_KEY = 'test-brevo-key'
    monkeypatch.setattr(module, 'httpx', DummyHTTPXBrevo)

    result = asyncio.run(module.send_email_via_smtp('user@example.com', 'Brevo subject', '<p>Hello</p>'))

    assert result is True


def test_approve_access_enqueues_outcome_email(monkeypatch):
    module = import_server_module()
    fake_requests = FakeAccessRequests()
    module.db = types.SimpleNamespace(access_requests=fake_requests)
    module.log_event = AsyncMock()

    background = FakeBackgroundTasks()

    result = asyncio.run(module.approve_access({'email': 'user@example.com'}, background, 'admin-id'))

    assert result == {'ok': True}
    assert fake_requests.updates
    assert len(background.calls) == 1
    assert background.calls[0][0] is module.send_access_request_outcome_email
    assert background.calls[0][1] == ('user@example.com', 'approved', 'Tester User')


def test_reject_access_enqueues_outcome_email(monkeypatch):
    module = import_server_module()
    fake_requests = FakeAccessRequests()
    module.db = types.SimpleNamespace(access_requests=fake_requests)
    module.log_event = AsyncMock()

    background = FakeBackgroundTasks()

    result = asyncio.run(module.reject_access({'email': 'user@example.com'}, background, 'admin-id'))

    assert result == {'ok': True}
    assert fake_requests.updates
    assert len(background.calls) == 1
    assert background.calls[0][0] is module.send_access_request_outcome_email
    assert background.calls[0][1] == ('user@example.com', 'rejected', 'Tester User')
