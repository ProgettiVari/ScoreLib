import os
import sys
import asyncio
import importlib.util
import pathlib
import types
from datetime import datetime, timedelta, timezone
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
    monkeypatch.setenv('ADMIN_EMAIL', 'admin@example.com')
    monkeypatch.setenv('EMAIL_FROM_ADDRESS', 'ScoreLib <no-reply@scorelib.app>')
    monkeypatch.setenv('EMAIL_REPLY_TO', 'support@example.com')
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
        assert json['_subject'] == '[Per: test@example.com] Fallback subject'
        assert json['message'] == '[Messaggio destinato a: test@example.com]\n\n<p>Fallback</p>'
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
        assert json['replyTo']['email'] == 'support@example.com'
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

    result = asyncio.run(module.send_email_via_smtp('user@example.com', 'Brevo subject', '<p>Hello</p>', 'Hello'))

    assert result is True


def test_seed_admin_accepts_admin_pass_env_alias(monkeypatch):
    module = import_server_module()
    monkeypatch.setenv('ADMIN_PASS', 'supersecret')
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('ADMIN_LOG_PASSWORD', raising=False)

    created = {}

    class FakeUsers:
        async def find_one(self, query, *args, **kwargs):
            return None

        async def insert_one(self, doc):
            created.update(doc)
            return None

    module.db = types.SimpleNamespace(users=FakeUsers())
    module.ADMIN_EMAIL = 'admin@example.com'

    asyncio.run(module.seed_admin())

    assert created['email'] == 'admin@example.com'
    assert created['is_admin'] is True
    assert created['password_hash']


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


class FakeOtpStore:
    def __init__(self):
        self.docs = {}

    async def find_one(self, query):
        email = query.get('email')
        return self.docs.get(email)

    async def update_one(self, query, update, upsert=False):
        email = query['email']
        doc = self.docs.setdefault(email, {})
        if '$set' in update:
            doc.update(update['$set'])
        if '$inc' in update:
            doc['attempts'] = doc.get('attempts', 0) + update['$inc'].get('attempts', 0)
        self.docs[email] = doc

    async def delete_one(self, query):
        self.docs.pop(query['email'], None)


def test_issue_login_otp_respects_resend_cooldown(monkeypatch):
    module = import_server_module()
    module.db = types.SimpleNamespace(login_otps=FakeOtpStore())
    module.SMTP_ENABLED = True

    now = datetime.now(timezone.utc)
    module.db.login_otps.docs['user@example.com'] = {
        'email': 'user@example.com',
        'last_sent_at': now.isoformat(),
        'expires_at': (now + timedelta(minutes=10)).isoformat(),
        'attempts': 0,
    }

    async def fake_send(*args, **kwargs):
        return True

    monkeypatch.setattr(module, 'send_email_via_smtp', fake_send)

    result = asyncio.run(module.issue_login_otp('user@example.com'))

    assert result is False


def test_verify_login_otp_locks_after_max_attempts():
    module = import_server_module()
    module.db = types.SimpleNamespace(login_otps=FakeOtpStore())
    module.db.login_otps.docs['user@example.com'] = {
        'email': 'user@example.com',
        'code_hash': module.hash_password('123456'),
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        'attempts': 4,
    }

    result = asyncio.run(module.verify_login_otp('user@example.com', '654321'))

    assert result is False
    rec = module.db.login_otps.docs['user@example.com']
    assert rec.get('blocked_until') is not None or rec.get('attempts', 0) >= 5
