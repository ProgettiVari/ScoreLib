import os
import io
import re
import uuid
import base64
import hashlib
import logging
import secrets
import asyncio
import psutil
import shutil
import subprocess
import time
import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import aiofiles
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
import httpx
import smtplib
import fitz
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import quote

from auth_utils import (
    hash_password, verify_password, create_jwt, decode_jwt,
    get_client_ip, get_current_user_id, get_optional_user_id,
)
from pdf_processor import build_apostrophe_tolerant_regex, build_content_signature, extract_pages, compress_pdf, make_snippet, clean_pdf_text, normalize_pdf_text, normalize_search_query, text_matches_query, extract_page_metadata, _calculate_match_quality, _content_signature_similarity, gemini_daily_quota_available
import google_integration as gi

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

def _sanitize_pdf_filename(name: str) -> str:
    safe_name = re.sub(r"[^\w\-.]", "_", (name or "").strip())
    return safe_name if safe_name.lower().endswith(".pdf") else f"{safe_name}.pdf"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return max(minimum, default)


MAX_USER_ACTIVE_JOBS = _env_int("MAX_USER_ACTIVE_JOBS", 1, 1)
MAX_GLOBAL_PROCESSING_JOBS = _env_int("MAX_GLOBAL_PROCESSING_JOBS", 1, 1)
MAX_USER_UPLOAD_FILES_PER_REQUEST = _env_int("MAX_USER_UPLOAD_FILES_PER_REQUEST", _env_int("MAX_UPLOAD_FILES_PER_REQUEST", 1, 1), 1)
MAX_USER_UPLOAD_SIZE_BYTES = _env_int("MAX_USER_UPLOAD_SIZE_BYTES", _env_int("MAX_UPLOAD_SIZE_BYTES", 15 * 1024 * 1024, 1), 1)
MAX_USER_PDF_PAGES = _env_int("MAX_USER_PDF_PAGES", 80, 0)
MAX_USER_OCR_CANDIDATE_PAGES = _env_int("MAX_USER_OCR_CANDIDATE_PAGES", 25, 0)
MAX_ADMIN_UPLOAD_SIZE_BYTES = _env_int("MAX_ADMIN_UPLOAD_SIZE_BYTES", 100 * 1024 * 1024, 1)
MAX_ADMIN_PDF_PAGES = _env_int("MAX_ADMIN_PDF_PAGES", 0, 0)
MAX_ADMIN_OCR_CANDIDATE_PAGES = _env_int("MAX_ADMIN_OCR_CANDIDATE_PAGES", 0, 0)
ACTIVE_UPLOAD_JOB_STATUSES = ["queued", "processing", "waiting_for_gemini_quota"]
_pdf_processing_semaphore = asyncio.Semaphore(MAX_GLOBAL_PROCESSING_JOBS)

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
APP_NAME = os.environ.get("APP_NAME", "ScoreLib")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").lower().strip()
ADMIN_RESET_PASSWORD = os.environ.get("ADMIN_LOG_PASSWORD") or os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASS")
WORKER_SECRET = os.environ.get("WORKER_SECRET", "")
EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", f"{APP_NAME} <no-reply@scorelib.app>").strip()
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "").strip()
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://scorelib.vercel.app").rstrip("/")
BACKEND_CORS_ORIGINS = [origin.strip() for origin in os.environ.get("BACKEND_CORS_ORIGINS", "").split(",") if origin.strip()]
FORMSUBMIT_BASE_URL = os.environ.get("FORMSUBMIT_BASE_URL", "https://formsubmit.co").strip()
FORM_SUBMIT_DEST_EMAIL = os.environ.get("FORM_SUBMIT_DEST_EMAIL", EMAIL_FROM_ADDRESS).strip()
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "").strip()


def get_admin_password() -> Optional[str]:
    for key in ("ADMIN_PASSWORD", "ADMIN_PASS", "ADMIN_LOG_PASSWORD", "ADMIN_RESET_PASSWORD"):
        value = os.environ.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _is_admin_user(user: Optional[dict]) -> bool:
    if not user:
        return False
    return bool(user.get("is_admin") or user.get("email", "").lower() == ADMIN_EMAIL)


async def _restore_gemini_daily_state() -> None:
    import pdf_processor

    record = await db.config.find_one({"key": "gemini_daily_state"}, {"_id": 0})
    state = record.get("state") if record else None
    pdf_processor.load_gemini_daily_state(state)
    if record and state and state.get("day") != pdf_processor.get_gemini_daily_state()["day"]:
        await db.config.delete_one({"key": "gemini_daily_state"})


async def _persist_gemini_daily_state() -> None:
    import pdf_processor

    try:
        await db.config.update_one(
            {"key": "gemini_daily_state"},
            {"$set": {"key": "gemini_daily_state", "state": pdf_processor.get_gemini_daily_state(), "updated_at": iso_now()}},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("GEMINI_DAILY_STATE_PERSIST_FAILED error=%s", repr(exc))


def _upload_limits_for_user(is_admin: bool) -> Dict[str, int]:
    return {
        "files_per_request": 5 if is_admin else MAX_USER_UPLOAD_FILES_PER_REQUEST,
        "file_size_bytes": MAX_ADMIN_UPLOAD_SIZE_BYTES if is_admin else MAX_USER_UPLOAD_SIZE_BYTES,
        "pdf_pages": MAX_ADMIN_PDF_PAGES if is_admin else MAX_USER_PDF_PAGES,
        "ocr_candidate_pages": MAX_ADMIN_OCR_CANDIDATE_PAGES if is_admin else MAX_USER_OCR_CANDIDATE_PAGES,
        "active_jobs": 0 if is_admin else MAX_USER_ACTIVE_JOBS,
        "global_processing_jobs": MAX_GLOBAL_PROCESSING_JOBS,
    }


async def _count_active_upload_jobs(user_id: Optional[str] = None) -> int:
    query: Dict[str, Any] = {"status": {"$in": ACTIVE_UPLOAD_JOB_STATUSES}}
    if user_id:
        query["user_id"] = user_id
    return await db.upload_jobs.count_documents(query)


def _inspect_pdf_for_upload_limits(content: bytes, *, max_pages: int = 0, max_ocr_candidates: int = 0) -> Dict[str, int]:
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            page_count = int(doc.page_count or 0)
            if page_count <= 0:
                raise HTTPException(status_code=400, detail="Il PDF non contiene pagine leggibili")
            if max_pages and page_count > max_pages:
                raise HTTPException(status_code=413, detail=f"PDF troppo lungo: massimo {max_pages} pagine")
            ocr_candidates = 0
            if max_ocr_candidates:
                for page in doc:
                    text = page.get_text("text") or ""
                    words = len(re.findall(r"\w+", text))
                    has_images = bool(page.get_images(full=True))
                    if has_images or words < 8:
                        ocr_candidates += 1
                    if ocr_candidates > max_ocr_candidates:
                        raise HTTPException(status_code=413, detail=f"Troppe pagine da OCR: massimo {max_ocr_candidates} pagine immagine per upload")
            return {"page_count": page_count, "ocr_candidate_pages": ocr_candidates}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("PDF.UPLOAD_PREFLIGHT_FAILED error=%s", repr(exc))
        raise HTTPException(status_code=400, detail="Il file caricato non è un PDF valido")


if "<" in FORM_SUBMIT_DEST_EMAIL and ">" in FORM_SUBMIT_DEST_EMAIL:
    FORM_SUBMIT_DEST_EMAIL = FORM_SUBMIT_DEST_EMAIL.split("<")[-1].strip(" >")
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
SMTP_ENABLED = bool(BREVO_API_KEY)
# One-time login codes: proof that the caller controls the email address.
LOGIN_OTP_TTL_MINUTES = 10
LOGIN_OTP_MAX_ATTEMPTS = 5
LOGIN_OTP_RESEND_COOLDOWN_SECONDS = 60

@asynccontextmanager
async def lifespan(app: FastAPI):
    # OCR diagnostics at startup
    from pdf_processor import _find_tesseract_binary
    import shutil

    def try_install_tesseract():
        if shutil.which("tesseract"):
            return
        logger.info("Attempting fallback Tesseract install at startup")
        try:
            subprocess.run(["apt-get", "update"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["apt-get", "install", "-y", "--no-install-recommends", "tesseract-ocr"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            logger.info("Fallback Tesseract install succeeded")
        except Exception as exc:
            logger.warning("Fallback Tesseract install failed: %s", exc)

    try_install_tesseract()
    tesseract_path = _find_tesseract_binary()
    logger.info(f"OCR diagnostic: TESSERACT_PATH={os.environ.get('TESSERACT_PATH')}, found={tesseract_path}, which='{shutil.which('tesseract')}'")
    await ensure_indexes()
    await _restore_gemini_daily_state()
    await seed_admin()
    await migrate_single_owner()
    safe_create_task(access_request_reminder_loop())
    # Startup job recovery
    stuck_jobs = await db.upload_jobs.find({"status": {"$in": ["processing", "queued"]}}).to_list(1000)
    await db.upload_jobs.update_many(
        {"status": {"$in": ["processing", "queued"]}},
        {"$set": {"status": "queued", "error": "requeued_at_startup", "updated_at": iso_now()}},
    )
    for _j in stuck_jobs:
        safe_create_task(process_pdf_job(_j["id"]))
    await _resume_waiting_gemini_jobs()
    yield

ENABLE_DOCS = os.environ.get("ENABLE_DOCS", "0") == "1"
app = FastAPI(
    title=APP_NAME,
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

async def _maintenance_state() -> dict:
    record = await db.config.find_one({"key": "maintenance"}, {"_id": 0})
    return record or {"enabled": False}

async def _request_is_admin(request: Request) -> bool:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "): return False
    user_id = decode_jwt(authorization.split(" ", 1)[1].strip())
    user = await db.users.find_one({"user_id": user_id}) if user_id else None
    return _is_admin_user(user)

@app.middleware("http")
async def enforce_maintenance(request: Request, call_next):
    public_paths = {"/api/auth/login", "/api/auth/login/verify-otp", "/api/system/status"}
    if request.url.path.startswith("/api") and request.url.path not in public_paths and request.method != "OPTIONS":
        state = await _maintenance_state()
        if state.get("enabled") and not await _request_is_admin(request):
            return JSONResponse(status_code=503, content={"maintenance": True, "message": "Scorelib è temporaneamente in manutenzione. Riprova tra poco."})
    return await call_next(request)

# Use the same X-Forwarded-For-aware IP resolution used for logging.
limiter = Limiter(key_func=get_client_ip)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
cors_origins = ["https://scorelib.vercel.app", "https://vercel.app", "https://onrender.com", "http://localhost:3000", "http://127.0.0.1:3000", FRONTEND_URL]
if BACKEND_CORS_ORIGINS:
    cors_origins.extend([origin for origin in BACKEND_CORS_ORIGINS if origin not in cors_origins])
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com https://api.fontshare.com; connect-src 'self' https://scorelib-backend.onrender.com https://scorelib-backend-docker.onrender.com https://fonts.googleapis.com https://api.fontshare.com https://vercel.live https://*.vercel.app; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; worker-src 'self' blob:; base-uri 'self'",
}

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
        if response is None:
            response = Response("Internal server error", status_code=500)
    except RuntimeError as exc:
        if "No response returned" in str(exc):
            logger.warning("Request pipeline ended without response for %s %s", request.method, request.url)
        else:
            logger.exception("Unhandled runtime error in request pipeline")
        response = Response("Internal server error", status_code=500)
    except Exception as exc:
        logger.exception("Unhandled exception in request pipeline")
        response = Response("Internal server error", status_code=500)
    for name, value in SECURITY_HEADERS.items():
        if name not in response.headers:
            response.headers[name] = value
    return response

api = APIRouter(prefix="/api")

logger = logging.getLogger("scorelib")
logging.basicConfig(level=logging.INFO)

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user_id(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """Validate the JWT and re-check the account status against the DB on every request."""
    token = creds.credentials if creds and creds.credentials else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = decode_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="Non autenticato")

    email = (user.get("email") or "").lower()
    banned_flags = (
        user.get("is_banned") is True
        or user.get("banned") is True
        or user.get("deleted") is True
        or user.get("removed") is True
    )
    if banned_flags:
        raise HTTPException(status_code=403, detail="Utente non autorizzato")

    if not (user.get("is_admin", False) or email == ADMIN_EMAIL):
        req = await db.access_requests.find_one({"email": email})
        if not req or req.get("status") != "approved":
            raise HTTPException(status_code=401, detail="Non autenticato")
        if req.get("status") in {"banned", "rejected"}:
            raise HTTPException(status_code=403, detail="Utente non autorizzato")

    return user_id


async def get_optional_user_id(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[str]:
    token = creds.credentials if creds and creds.credentials else None
    if not token:
        return None

    user_id = decode_jwt(token)
    if not user_id:
        return None

    user = await db.users.find_one({"user_id": user_id})
    if not user:
        return None

    email = (user.get("email") or "").lower()
    if (
        user.get("is_banned") is True
        or user.get("banned") is True
        or user.get("deleted") is True
        or user.get("removed") is True
    ):
        return None

    if not (user.get("is_admin", False) or email == ADMIN_EMAIL):
        req = await db.access_requests.find_one({"email": email})
        if not req or req.get("status") != "approved":
            return None

    return user_id


def safe_create_task(coro):
    async def wrapper():
        try:
            await coro
        except Exception:
            logger.exception("Unhandled background task error")

    return asyncio.create_task(wrapper())

if "scorelib.app" in EMAIL_FROM_ADDRESS:
    logger.warning("EMAIL_FROM_ADDRESS usa dominio scorelib.app. Assicurati che il dominio sia verificato nel provider email.")

# ----------------- Helpers -----------------
def iso_now(): return datetime.now(timezone.utc).isoformat()

def clean_doc(doc: dict) -> dict:
    """Rimuove _id o lo converte in stringa per rendere il documento JSON-safe."""
    if not doc: return doc
    if "_id" in doc: doc["_id"] = str(doc["_id"])
    return doc

async def log_event(event_type: str, description: str, user_id: Optional[str] = None, level: str = "info", meta: Optional[dict] = None):
    doc = {
        "event_type": event_type,
        "description": description,
        "user_id": user_id,
        "level": level,
        "meta": meta or {},
        "created_at": iso_now(),
    }
    await db.app_logs.insert_one(doc)
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(f"[{event_type.upper()}] {description} (user={user_id})")

async def send_email(to_email: str, subject: str, html: str):
    if SMTP_ENABLED:
        logger.info("Tentativo invio email via SMTP a %s subject=%s", to_email, subject)
        sent = await send_email_via_smtp(to_email, subject, html)
        if sent:
            return True
        logger.info("SMTP fallito, fallback a FormSubmit per %s", to_email)
    else:
        logger.info("SMTP non configurato, invio diretto via FormSubmit a %s subject=%s", to_email, subject)
    return await send_email_via_formsubmit(to_email, subject, html)

def _generate_otp_code() -> str:
    """Cryptographically random 6-digit code (uses `secrets`, not `random`)."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def issue_login_otp(email: str) -> bool:
    """Create a one-time login code for `email` and send it, replacing any
    previous outstanding code. Returns False if it could not be delivered.

    Resends are rate-limited to avoid spamming the same inbox, and repeated
    failures are treated as a temporary lockout rather than exposing technical
    details to the user.
    """
    email = email.lower().strip()
    existing = await db.login_otps.find_one({"email": email})
    if existing:
        last_sent_at = existing.get("last_sent_at")
        if isinstance(last_sent_at, str):
            try:
                last_sent_at = datetime.fromisoformat(last_sent_at)
            except ValueError:
                last_sent_at = None
        if last_sent_at and isinstance(last_sent_at, datetime):
            if last_sent_at.tzinfo is None:
                last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
            seconds_since = (datetime.now(timezone.utc) - last_sent_at).total_seconds()
            if seconds_since < LOGIN_OTP_RESEND_COOLDOWN_SECONDS:
                logger.warning("OTP resend rate-limited for %s seconds=%s", email, seconds_since)
                return False

    code = _generate_otp_code()
    code_hash = hash_password(code)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_OTP_TTL_MINUTES)
    await db.login_otps.update_one(
        {"email": email},
        {"$set": {
            "email": email,
            "code_hash": code_hash,
            "expires_at": expires_at,
            "attempts": 0,
            "last_sent_at": iso_now(),
            "created_at": iso_now(),
        }},
        upsert=True,
    )
    if not SMTP_ENABLED:
        logger.error("Impossibile inviare il codice di accesso a %s: email transazionale (Brevo) non configurata", email)
        return False
    subject = f"{APP_NAME}: il tuo codice di accesso"
    html_message = f"""
    <html>
      <body style="margin:0;padding:24px;background-color:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
        <div style="max-width:600px;margin:0 auto;background-color:#ffffff;border:1px solid #d1d5db;border-radius:16px;overflow:hidden;">
          <div style="background-color:#111111;padding:18px 24px;color:#ffffff;">
            <p style="margin:0 0 4px 0;font-size:12px;text-transform:uppercase;letter-spacing:1.6px;opacity:0.75;">{APP_NAME}</p>
            <h2 style="margin:0;font-size:24px;line-height:1.2;">Il tuo codice di accesso</h2>
          </div>
          <div style="padding:24px;color:#111111;">
            <p style="margin:0 0 16px 0;font-size:16px;line-height:1.6;">Usa questo codice per completare l'accesso:</p>
            <p style="margin:0 0 16px 0;font-size:32px;font-weight:700;letter-spacing:6px;">{code}</p>
            <p style="margin:0;font-size:14px;line-height:1.5;color:#6b7280;">Scade tra {LOGIN_OTP_TTL_MINUTES} minuti. Se non hai richiesto l'accesso, ignora questa email.</p>
          </div>
        </div>
      </body>
    </html>
    """
    text_message = (
        f"Il tuo codice di accesso a {APP_NAME} e': {code}\n\n"
        f"Scade tra {LOGIN_OTP_TTL_MINUTES} minuti. Se non hai richiesto l'accesso, ignora questa email."
    )
    sent = await send_email_via_smtp(email, subject, html_message, text_message)
    if not sent:
        logger.error("Invio del codice di accesso fallito per %s", email)
    return sent


async def verify_login_otp(email: str, code: str) -> bool:
    """Check `code` against the outstanding OTP for `email`, enforcing
    expiry and a max-attempts lockout. Consumes the OTP on success."""
    rec = await db.login_otps.find_one({"email": email})
    if not rec:
        return False
    expires_at = rec.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.login_otps.delete_one({"email": email})
        return False
    locked_until = rec.get("locked_until")
    if isinstance(locked_until, str):
        locked_until = datetime.fromisoformat(locked_until)
    if locked_until and isinstance(locked_until, datetime):
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            return False

    if rec.get("attempts", 0) >= LOGIN_OTP_MAX_ATTEMPTS:
        await db.login_otps.update_one(
            {"email": email},
            {"$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}}
        )
        return False
    if not verify_password(code.strip(), rec["code_hash"]):
        attempts = int(rec.get("attempts", 0)) + 1
        await db.login_otps.update_one({"email": email}, {"$set": {"attempts": attempts}})
        if attempts >= LOGIN_OTP_MAX_ATTEMPTS:
            await db.login_otps.update_one(
                {"email": email},
                {"$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}}
            )
        return False
    await db.login_otps.delete_one({"email": email})
    return True


async def send_email_via_formsubmit(to_email: str, subject: str, message: str, text_message: Optional[str] = None) -> bool:
    if not to_email:
        logger.warning("send_email_via_formsubmit: to_email non specificata")
        return False
    logger.info("Invio email via FormSubmit a %s subject=%s", to_email, subject)
    from_email = EMAIL_FROM_ADDRESS
    if "<" in from_email and ">" in from_email:
        from_email = from_email.split("<")[-1].strip(" >")
    # NOTE: FormSubmit.co only forwards to the fixed inbox baked into the
    # target URL (FORM_SUBMIT_DEST_EMAIL) -- it cannot deliver to `to_email`
    # directly. Prepending the intended recipient makes it possible for
    # whoever reads that inbox to forward the message manually.
    recipient_note = f"[Messaggio destinato a: {to_email}]\n\n"
    payload = {
        "name": APP_NAME,
        "email": from_email,
        "message": recipient_note + (message if message else (text_message or "")),
        "_subject": f"[Per: {to_email}] {subject}",
        "_template": "table",
        "_captcha": "false",
    }
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        target_url = f"{FORMSUBMIT_BASE_URL}/ajax/{quote(FORM_SUBMIT_DEST_EMAIL, safe='')}"
        logger.info("Tentativo FormSubmit verso %s subject=%s", FORM_SUBMIT_DEST_EMAIL, subject)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(target_url, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("FormSubmit inviato a %s status=%s", FORM_SUBMIT_DEST_EMAIL, resp.status_code)
            return True
    except httpx.HTTPStatusError as http_exc:
        logger.error("FormSubmit HTTP %s per %s: %s", http_exc.response.status_code, FORM_SUBMIT_DEST_EMAIL, http_exc)
    except Exception as exc:
        logger.error("Errore FormSubmit per %s: %s", FORM_SUBMIT_DEST_EMAIL, exc)
    return False

async def send_email_via_smtp(to_email: str, subject: str, message: str, text_message: Optional[str] = None) -> bool:
    """Invia email via Brevo API con versione HTML e testo semplice."""
    if not to_email:
        return False

    api_key_effettiva = (BREVO_API_KEY or os.environ.get("BREVO_API_KEY", "")).strip()
    if not api_key_effettiva:
        logger.warning("Brevo API key non configurata: email non inviata")
        return False

    from_email = EMAIL_FROM_ADDRESS
    if "<" in from_email and ">" in from_email:
        from_email = from_email.split("<")[-1].strip(" >")

    logger.info("Invio email via Brevo API a %s subject=%s", to_email, subject)
    logger.info("Verifica BREVO_API_KEY - Lunghezza carattere: %d", len(api_key_effettiva))

    text_body = text_message or re.sub(r"<[^>]+>", "", message)

    payload = {
        "sender": {"name": APP_NAME, "email": from_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": message,
        "textContent": text_body,
    }
    if EMAIL_REPLY_TO:
        payload["replyTo"] = {"email": EMAIL_REPLY_TO, "name": APP_NAME}

    headers = {
        "api-key": api_key_effettiva,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("Brevo API inviata a %s status=%s", to_email, resp.status_code)
            return True
    except httpx.HTTPStatusError as http_exc:
        logger.error("Brevo API HTTP %s per %s: %s", http_exc.response.status_code, to_email, http_exc)
    except Exception as exc:
        logger.error("Errore Brevo API per %s: %s", to_email, exc)
    return False

async def send_access_request_outcome_email(email: str, status: str, name: Optional[str] = None):
    try:
        safe_name = name or email
        logger.info("send_access_request_outcome_email status=%s email=%s name=%s", status, email, safe_name)

        if status == "approved":
            subject = "ScoreLib — Accesso approvato"
            badge = "✅ Approvato"
            headline = "La tua richiesta è stata approvata."
            body = "Ora puoi accedere a ScoreLib con questa email."
        elif status == "rejected":
            subject = "ScoreLib — Accesso non approvato"
            badge = "❌ Non approvato"
            headline = "La tua richiesta non è stata approvata."
            body = "Se vuoi, puoi inviare una nuova richiesta in qualsiasi momento."
        else:
            subject = "ScoreLib — Richiesta in attesa"
            badge = "⏳ In attesa"
            headline = "La tua richiesta è ancora in attesa di revisione."
            body = "Controlla anche la cartella spam se non ricevi subito l'email."

        html_message = f"""
        <html>
          <body style="margin:0;padding:24px;background-color:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
            <div style="max-width:600px;margin:0 auto;background-color:#ffffff;border:1px solid #d1d5db;border-radius:16px;overflow:hidden;">
              <div style="background-color:#111111;padding:18px 24px;color:#ffffff;">
                <p style="margin:0 0 4px 0;font-size:12px;text-transform:uppercase;letter-spacing:1.6px;opacity:0.75;">ScoreLib</p>
                <h2 style="margin:0;font-size:24px;line-height:1.2;">{badge}</h2>
              </div>
              <div style="padding:24px;color:#111111;">
                <p style="margin:0 0 8px 0;font-size:16px;line-height:1.6;">Ciao <strong>{safe_name}</strong>,</p>
                <p style="margin:0 0 12px 0;font-size:16px;line-height:1.6;">{headline}</p>
                <p style="margin:0 0 16px 0;font-size:16px;line-height:1.6;">{body}</p>
                <p style="margin:0 0 18px 0;">
                  <a href="https://scorelib.vercel.app/login" style="display:inline-block;background-color:#000000;color:#ffffff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600;">Apri ScoreLib</a>
                </p>
                <p style="margin:0;font-size:12px;line-height:1.5;color:#6b7280;">Grazie,<br>Team ScoreLib</p>
              </div>
            </div>
          </body>
        </html>
        """
        text_message = f"Ciao {safe_name},\n\n{headline}\n{body}\n\nApri ScoreLib: https://scorelib.vercel.app/login\n\nGrazie,\nTeam ScoreLib"

        sent = False
        if SMTP_ENABLED:
            sent = await send_email_via_smtp(email, subject, html_message, text_message)
        if not sent:
            logger.info("FormSubmit fallback per esito richiesta accesso a %s", email)
            sent = await send_email_via_formsubmit(email, subject, html_message, text_message)
            if not sent:
                logger.error("Tutti i metodi di invio email sono falliti per %s", email)
    except Exception:
        logger.exception("Errore inatteso durante l'invio dell'email di esito richiesta accesso a %s", email)

async def send_access_request_reminder_email(email: str, name: Optional[str] = None):
    try:
        safe_name = name or email
        logger.info("send_access_request_reminder_email email=%s name=%s", email, safe_name)
        subject = "ScoreLib: richiesta di accesso ancora in attesa"
        message = (
            f"Ciao {safe_name},\n\n"
            f"La tua richiesta di accesso a ScoreLib per {email} è ancora in attesa perché l'amministratore non ha ancora risposto.\n"
            "Se non ti rispondo, la richiesta resterà in attesa.\n"
            "Puoi attendere o inviare una nuova richiesta.\n\n"
            "Grazie,\nTeam ScoreLib"
        )
        sent = False
        if SMTP_ENABLED:
            sent = await send_email_via_smtp(email, subject, message)
        if not sent:
            await send_email_via_formsubmit(email, subject, message)
    except Exception:
        logger.exception("Errore inatteso durante l'invio del promemoria di richiesta accesso a %s", email)

async def send_pending_access_request_reminders():
    threshold = datetime.now(timezone.utc) - timedelta(days=3)
    cutoff = threshold.isoformat()
    query = {
        "status": "pending",
        "created_at": {"$lte": cutoff},
        "$or": [
            {"reminder_sent_at": {"$exists": False}},
            {"reminder_sent_at": None}
        ],
    }
    logger.info("Ricerca richieste accesso pending oltre 3 giorni cutoff=%s", cutoff)
    reqs = await db.access_requests.find(query).to_list(1000)
    logger.info("Trovate %d richieste pending da ricordare", len(reqs))
    for req in reqs:
        try:
            await send_access_request_reminder_email(req["email"], req.get("name"))
            await db.access_requests.update_one(
                {"_id": req["_id"]},
                {"$set": {"reminder_sent_at": iso_now()}}
            )
            logger.info("Promemoria inviato per %s", req["email"])
        except Exception as exc:
            logger.error("Errore invio promemoria access request per %s: %s", req["email"], exc)

async def access_request_reminder_loop():
    await send_pending_access_request_reminders()
    while True:
        await asyncio.sleep(24 * 3600)
        await send_pending_access_request_reminders()

async def ensure_indexes():
    async def safe_create_index(collection, keys, **kwargs):
        try:
            await collection.create_index(keys, **kwargs)
        except Exception as e:
            if "IndexKeySpecsConflict" in str(e) or "IndexOptionsConflict" in str(e):
                try:
                    idx_name = "_".join([f"{k}_{v}" for k, v in (keys if isinstance(keys, list) else [(keys, 1)])])
                    logger.warning(f"Conflitto indice su {collection.name}.{idx_name}, tento drop/recreate.")
                    await collection.drop_index(idx_name)
                    await collection.create_index(keys, **kwargs)
                except Exception as e2:
                    logger.error(f"Impossibile ricreare indice {idx_name} su {collection.name}: {e2}")
            else:
                logger.error(f"Errore creazione indice su {collection.name}: {e}")

    await safe_create_index(db.users, "user_id", unique=True)
    await safe_create_index(db.users, "email", unique=True)
    await safe_create_index(db.pdfs, "id", unique=True)
    await safe_create_index(db.pdf_pages, [("pdf_id", 1), ("page", 1)], unique=True)
    await safe_create_index(db.pdf_pages, "text")
    await safe_create_index(db.pdf_pages, "text_normalized")
    await safe_create_index(db.pdf_pages, "content_signature")
    await safe_create_index(db.pdfs, "title_normalized")
    await safe_create_index(db.upload_jobs, "id", unique=True)
    await safe_create_index(db.app_logs, "created_at")
    await safe_create_index(db.access_requests, "email")
    await safe_create_index(db.access_requests, "ip")
    await safe_create_index(db.shared_libraries, "id", unique=True)
    await safe_create_index(db.shared_libraries, "share_token", unique=True)
    await safe_create_index(db.login_otps, "email", unique=True)
    await safe_create_index(db.login_otps, "expires_at", expireAfterSeconds=0)

async def seed_admin():
    if not ADMIN_EMAIL:
        logger.warning("ADMIN_EMAIL non configurato: admin non creato. Imposta la variabile d'ambiente su Render e riavvia il servizio.")
        return
    admin = await db.users.find_one({"email": ADMIN_EMAIL})
    if not admin:
        pwd = get_admin_password()
        if not pwd:
            logger.error("Nessuna password admin configurata. Imposta ADMIN_PASS (o ADMIN_PASSWORD) su Render e riavvia il servizio.")
            return
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(pwd),
            "name": "Administrator",
            "is_admin": True,
            "created_at": iso_now(),
        })

async def migrate_single_owner():
    admin = await db.users.find_one({"email": ADMIN_EMAIL}, {"user_id": 1})
    if not admin: return
    admin_id = admin["user_id"]
    await db.pdfs.update_many({"owner_id": {"$ne": admin_id}}, {"$set": {"owner_id": admin_id}})

# ----------------- Models -----------------
class LoginIn(BaseModel):
    email: EmailStr
    password: Optional[str] = None

class AccessRequestIn(BaseModel):
    name: str
    email: EmailStr

class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str

class PdfPatchIn(BaseModel):
    title: Optional[str] = None
    is_favorite: Optional[bool] = None
    tags: Optional[List[str]] = None
    is_protected: Optional[bool] = None

class CreateLibraryIn(BaseModel):
    name: str
    description: Optional[str] = None

class AddPdfsIn(BaseModel):
    pdf_ids: List[str]

# ----------------- Auth -----------------
def user_public(u: dict) -> dict:
    is_admin = u.get("is_admin", False) or u.get("email", "").lower() == ADMIN_EMAIL
    return {
        "user_id": u["user_id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "is_admin": is_admin,
        "created_at": u.get("created_at"),
        "role": "admin" if is_admin else "user",
    }

async def require_admin(user_id: str = Depends(get_current_user_id)):
    u = await db.users.find_one({"user_id": user_id})
    if not u:
        raise HTTPException(status_code=401, detail="Non autenticato")
    is_admin = u.get("is_admin", False) or u.get("email", "").lower() == ADMIN_EMAIL
    if not is_admin:
        raise HTTPException(status_code=403, detail="Solo amministratori")
    return user_id

async def _get_active_user_id(user_id: Optional[str]) -> Optional[str]:
    """
    Re-validate a JWT's user_id against current DB state and return it only if the
    user still exists and is currently admin or approved. A JWT stays cryptographically
    valid for JWT_EXPIRE_DAYS regardless of what happens to the account afterwards, so
    any endpoint that returns data (not just the per-PDF access check) must call this
    instead of trusting a decoded token at face value - otherwise a revoked/banned user
    keeps read access to everything for as long as their old token remains unexpired.
    """
    if not user_id:
        return None
    u = await db.users.find_one({"user_id": user_id})
    if not u:
        return None
    if u.get("is_admin", False) or u.get("email", "").lower() == ADMIN_EMAIL:
        return user_id
    approved = await db.access_requests.find_one({"email": u.get("email", "").lower(), "status": "approved"})
    if approved:
        return user_id
    return None

async def require_active_user(user_id: str = Depends(get_current_user_id)) -> str:
    """Like get_current_user_id, but 401s if the account was since revoked/banned/deleted."""
    active_id = await _get_active_user_id(user_id)
    if not active_id:
        raise HTTPException(status_code=401, detail="Non autenticato")
    return active_id

@api.post("/auth/login")
@limiter.limit("5/minute")
async def login(payload: LoginIn, request: Request):
    ip = get_client_ip(request)
    email = payload.email.lower().strip()

    if email == ADMIN_EMAIL:
        if not payload.password:
            raise HTTPException(status_code=400, detail="Password richiesta")
        u = await db.users.find_one({"email": email})
        if not u:
            pwd = get_admin_password()
            if not pwd:
                await log_event("auth.login_failed", f"Tentativo login admin fallito: password admin non configurata", level="warn", meta={"email": email, "ip": ip})
                raise HTTPException(status_code=401, detail="Credenziali non valide")
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            u = {
                "user_id": user_id,
                "email": ADMIN_EMAIL,
                "password_hash": hash_password(pwd),
                "name": "Administrator",
                "is_admin": True,
                "created_at": iso_now(),
            }
            await db.users.insert_one(u)
        live_password = get_admin_password()
        if not live_password or not secrets.compare_digest(payload.password, live_password):
            await log_event("auth.login_failed", f"Tentativo login admin fallito", level="warn", meta={"email": email, "ip": ip})
            raise HTTPException(status_code=401, detail="Credenziali non valide")
        token = create_jwt(u["user_id"])
        await log_event("auth.login_admin", f"Admin login: {email}", user_id=u["user_id"], meta={"ip": ip})
        return {"token": token, "user": user_public(u)}

    req = await db.access_requests.find_one({"email": email})
    if req and req.get("status") == "banned":
        await log_event("auth.login_denied", f"Tentativo login da email bloccata: {email}", level="warn", meta={"email": email, "ip": ip, "status": "banned"})
        raise HTTPException(status_code=403, detail="Questo indirizzo email è stato bloccato.")
    if req and req.get("status") == "approved":
        # Regular accounts have no password: a one-time code sent to the
        # email on file is what proves the caller actually owns it, instead
        # of issuing a session token from the email address alone.
        sent = await issue_login_otp(email)
        await log_event("auth.login_otp_sent" if sent else "auth.login_otp_failed",
                         f"Codice di accesso {'inviato' if sent else 'NON inviato'} a {email}",
                         level="info" if sent else "error", meta={"ip": ip, "email": email})
        if not sent:
            raise HTTPException(status_code=503, detail="Impossibile inviare il codice di accesso. Riprova più tardi.")
        return {"otp_required": True, "email": email}

    # Provide clearer messages depending on access_request state
    status = req.get("status") if req else None
    await log_event("auth.login_denied", f"Tentativo login non approvato: {email}", level="warn", meta={"email": email, "ip": ip, "status": status or "missing"})
    if status == "pending":
        raise HTTPException(status_code=403, detail="Richiesta di accesso in attesa di approvazione.")
    if status == "rejected":
        raise HTTPException(status_code=403, detail="La richiesta di accesso è stata rifiutata.")
    if status == "banned":
        raise HTTPException(status_code=403, detail="Questo indirizzo email è stato bloccato.")
    # no request found
    raise HTTPException(status_code=403, detail="Nessuna richiesta trovata. Richiedi l'accesso.")

@api.post("/auth/login/verify-otp")
@limiter.limit("10/minute")
async def verify_otp_login(payload: VerifyOtpIn, request: Request):
    ip = get_client_ip(request)
    email = payload.email.lower().strip()

    req = await db.access_requests.find_one({"email": email})
    if not req or req.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Nessuna richiesta approvata trovata.")

    ok = await verify_login_otp(email, payload.code)
    if not ok:
        rec = await db.login_otps.find_one({"email": email})
        locked_until = rec.get("locked_until") if rec else None
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until and isinstance(locked_until, datetime):
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > datetime.now(timezone.utc):
                await log_event("auth.login_otp_locked", f"Codice di accesso bloccato temporaneamente per {email}", level="warn", meta={"ip": ip, "email": email})
                raise HTTPException(status_code=429, detail="Riprova più tardi.")
        await log_event("auth.login_otp_invalid", f"Codice di accesso errato o scaduto per {email}", level="warn", meta={"ip": ip, "email": email})
        raise HTTPException(status_code=401, detail="Codice non valido o scaduto.")

    user = await db.users.find_one({"email": email})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": req.get("name", ""),
            "is_admin": False,
            "created_at": iso_now(),
        }
        await db.users.insert_one(user)
    token = create_jwt(user["user_id"])
    await log_event("auth.login", f"Accesso utente approvato: {email}", user_id=user["user_id"], meta={"ip": ip, "email": email})
    return {"token": token, "user": user_public(user)}

@api.post("/auth/request-access")
@limiter.limit("3/hour")
async def request_access(payload: AccessRequestIn, request: Request):
    email = payload.email.lower().strip()
    ip = get_client_ip(request)
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="L'amministratore non può richiedere accesso.")
    existing = await db.access_requests.find_one({"email": email})
    if existing and existing.get("status") == "approved":
        raise HTTPException(status_code=409, detail="Hai già ottenuto l'accesso. Se necessario chiedi un reset all'amministratore.")
    if existing and existing.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Questo indirizzo email è stato bloccato.")
    await db.access_requests.update_one(
        {"email": email},
        {
            "$set": {"name": payload.name, "email": email, "ip": ip, "status": "pending", "created_at": iso_now()},
            "$unset": {"reminder_sent_at": ""}
        },
        upsert=True
    )
    return {"message": "Richiesta inviata."}

@api.get("/auth/me")
async def me(user_id: str = Depends(get_current_user_id)):
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u: raise HTTPException(status_code=404, detail="Utente non trovato")
    return user_public(u)

# ----------------- Backup / Drive -----------------
async def get_master_drive():
    return await db.config.find_one({"key": "master_drive"})


async def _resolve_drive_refresh_token(pdf_record: dict) -> Optional[str]:
    """Return the best available Google Drive refresh token for a PDF backup.

    Prefer the owner token, but fall back to the master Drive token when the
    owner token is missing or invalid, which helps recover PDFs after a revoked
    refresh token.
    """
    refresh = None

    if pdf_record.get("drive_owner") == "master":
        master = await get_master_drive()
        refresh = master.get("refresh_token") if master else None
        return refresh

    owner = await db.users.find_one({"user_id": pdf_record.get("owner_id")}, {"_id": 0})
    refresh = (owner or {}).get("google_refresh_token")

    if refresh:
        return refresh

    master = await get_master_drive()
    return master.get("refresh_token") if master else None


async def _download_from_drive_with_fallback(pdf_record: dict) -> bytes:
    """Download a PDF backup from Drive, trying the owner token first and then
    master Drive as a fallback if the owner token is invalid or revoked.
    """
    primary = await _resolve_drive_refresh_token(pdf_record)
    candidates = [primary] if primary else []

    master = await get_master_drive()
    master_token = master.get("refresh_token") if master else None
    if master_token and master_token not in candidates:
        candidates.append(master_token)

    if not candidates:
        message = "Nessun token Drive disponibile per il recupero: owner e master token mancanti o invalidi"
        await log_event(
            "pdf.error",
            message,
            user_id=pdf_record.get("owner_id"),
            level="error",
            meta={"pdf_id": pdf_record.get("id"), "drive_file_id": pdf_record.get("drive_file_id"), "stage": "drive_download_fallback", "reason": "no_tokens"},
        )
        raise RuntimeError(message)

    last_error = None
    for token in candidates:
        source = "primary_owner" if token == primary else "master"
        try:
            return await asyncio.to_thread(gi.download_from_drive, token, pdf_record["drive_file_id"])
        except Exception as exc:
            last_error = exc
            await log_event(
                "pdf.error",
                f"Drive download fallback failed ({source}) with {type(exc).__name__}: {exc}",
                user_id=pdf_record.get("owner_id"),
                level="error",
                meta={"pdf_id": pdf_record.get("id"), "drive_file_id": pdf_record.get("drive_file_id"), "stage": "drive_download_fallback", "source": source},
            )

    if last_error:
        raise last_error
    raise RuntimeError("Errore imprevisto nella procedura di recupero Drive")

@api.get("/backup/status")
async def backup_status(user_id: str = Depends(get_current_user_id)):
    master = await get_master_drive()
    has_master = bool(master and master.get("refresh_token"))
    total = await db.pdfs.count_documents({})
    backed = await db.pdfs.count_documents({"drive_file_id": {"$nin": [None, ""]}})
    return {
        "drive_connected": has_master,
        "total_pdfs": total,
        "backed_up_pdfs": backed,
        "pending_pdfs": max(0, total - backed),
    }

@api.post("/backup/run")
async def backup_run(user_id: str = Depends(require_admin)):
    master = await get_master_drive()
    if not master: raise HTTPException(status_code=400, detail="Master Drive non connesso")
    return {"ok": True, "pending": 0}

# ----------------- PDFs -----------------
def _serialize_pdf(p: dict) -> dict:
    return {
        "id": p["id"],
        "title": p.get("title", ""),
        "filename": p.get("filename", ""),
        "size": p.get("size", 0),
        "pages": p.get("pages", 0),
        "page_labels": p.get("page_labels", []),
        "status": p.get("status", "ready"),
        "is_protected": p.get("is_protected", False),
        "tags": p.get("tags", []),
        "is_favorite": p.get("is_favorite", False),
        "created_at": p.get("created_at"),
        "owner_id": p.get("owner_id"),
    }

@api.get("/users/approved")
async def approved_users(user_id: str = Depends(require_active_user)):
    reqs = await db.access_requests.find({"status": "approved"}).to_list(1000)
    return {"users": [{"email": r["email"], "name": r["name"], "created_at": r["created_at"]} for r in reqs]}

# ----------------- PDFs -----------------
@api.get("/pdfs")
async def list_pdfs(
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = None,
    user_id: str = Depends(require_active_user),
):
    query = {}
    if favorite is not None:
        query["is_favorite"] = favorite
    if tag:
        query["tags"] = {"$regex": f"^{re.escape(tag.strip())}$", "$options": "i"}
    sort_mapping = {
        "date_asc": [("created_at", 1)],
        "date_desc": [("created_at", -1)],
        "name_asc": [("title", 1)],
        "name_desc": [("title", -1)],
    }
    order = sort_mapping.get(sort, [("created_at", -1)])
    cursor = db.pdfs.find(query, {"_id": 0}).sort(order)
    items = await cursor.to_list(1000)
    return {"items": [_serialize_pdf(i) for i in items]}

@api.post("/pdfs/upload")
async def upload_pdf(
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    user_id: str = Depends(get_current_user_id)
):
    if not files:
        raise HTTPException(status_code=400, detail="Nessun file inviato")

    user = await db.users.find_one({"user_id": user_id})
    is_admin = _is_admin_user(user)
    limits = _upload_limits_for_user(is_admin)
    if len(files) > limits["files_per_request"]:
        raise HTTPException(status_code=413, detail=f"Solo {limits['files_per_request']} file possono essere caricati per volta")
    if not is_admin:
        active_user_jobs = await _count_active_upload_jobs(user_id)
        if active_user_jobs >= MAX_USER_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="Hai gia un PDF in elaborazione. Attendi che finisca prima di caricarne un altro.")
        active_global_jobs = await _count_active_upload_jobs()
        if active_global_jobs >= MAX_GLOBAL_PROCESSING_JOBS:
            raise HTTPException(status_code=429, detail="Il server sta gia elaborando un PDF. Riprova tra poco.")

    results = []
    total_uploaded_size = 0
    for file in files:
        recv_start = time.perf_counter()
        content = await file.read()
        filename = (file.filename or "").strip()
        recv_ms = (time.perf_counter() - recv_start) * 1000
        logger.info("PDF.UPLOAD_RECEIVED size=%d filename=%s recv_ms=%.1f", len(content), filename, recv_ms)
        
        total_uploaded_size += len(content)
        if total_uploaded_size > limits["file_size_bytes"] * limits["files_per_request"]:
            raise HTTPException(status_code=413, detail="Superata la dimensione massima totale per upload")
        if len(content) > limits["file_size_bytes"]:
            raise HTTPException(status_code=413, detail=f"File troppo grande: massimo {limits['file_size_bytes'] // (1024 * 1024)} MB")
        if not filename or Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Il file caricato non è un PDF valido")
        if len(content) < 5 or not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Il file caricato non è un PDF valido")
        preflight = _inspect_pdf_for_upload_limits(
            content,
            max_pages=limits["pdf_pages"],
            max_ocr_candidates=limits["ocr_candidate_pages"],
        )
        logger.info(
            "PDF.UPLOAD_PREFLIGHT pdf_filename=%s pages=%d ocr_candidates=%d is_admin=%s",
            filename,
            preflight["page_count"],
            preflight["ocr_candidate_pages"],
            is_admin,
        )

        if preflight["ocr_candidate_pages"] > 0 and not gemini_daily_quota_available():
            raise HTTPException(
                status_code=503,
                detail="Oggi puoi caricare solo PDF completamente testuali: le scansioni e le immagini richiedono OCR. Riprova più tardi o domani.",
            )
        # Save PDF without compression first (fast path for response)
        # Compression will happen in background job during OCR processing
        pdf_id = f"pdf_{uuid.uuid4().hex[:12]}"
        safe_filename = _sanitize_pdf_filename(filename)
        fpath = UPLOAD_DIR / f"{pdf_id}_{safe_filename}"
        save_start = time.perf_counter()
        fpath.write_bytes(content)
        save_ms = (time.perf_counter() - save_start) * 1000
        logger.info("PDF.UPLOAD_SAVED pdf=%s size=%d save_ms=%.1f", pdf_id, len(content), save_ms)

        await db.pdfs.insert_one({
            "id": pdf_id,
            "title": safe_filename,
            "title_normalized": normalize_pdf_text(safe_filename),
            "filename": safe_filename,
            "file_path": str(fpath),
            "size": len(content),
            "status": "pending",
            "owner_id": user_id,
            "compressed": False,  # Will compress in background
            "storage_type": "local",
            "drive_owner": None,
            "drive_file_id": None,
            "synced_at": None,
            "created_at": iso_now(),
        })

        job_id = str(uuid.uuid4())
        job_start = time.perf_counter()
        await db.upload_jobs.insert_one({
            "id": job_id,
            "pdf_id": pdf_id,
            "user_id": user_id,
            "status": "queued",
            "created_at": iso_now()
        })
        job_ms = (time.perf_counter() - job_start) * 1000
        logger.info("PDF.UPLOAD_JOB_CREATED pdf=%s job=%s job_ms=%.1f", pdf_id, job_id, job_ms)
        background_tasks.add_task(process_pdf_job, job_id)

        results.append({"ok": True, "pdf_id": pdf_id, "name": filename, "compressed": False})

    if results:
        await log_event("pdf.uploaded", f"Upload completato: {len(results)} file", user_id=user_id, meta={"count": len(results)})
    
    return {"results": results}


@api.get("/pdfs/upload-policy")
async def get_upload_policy(user_id: str = Depends(get_current_user_id)):
    user = await db.users.find_one({"user_id": user_id})
    is_admin = _is_admin_user(user)
    limits = _upload_limits_for_user(is_admin)
    active_user_jobs = await _count_active_upload_jobs(user_id)
    active_global_jobs = await _count_active_upload_jobs()
    can_upload = is_admin or (active_user_jobs < MAX_USER_ACTIVE_JOBS and active_global_jobs < MAX_GLOBAL_PROCESSING_JOBS)
    return {
        "is_admin": is_admin,
        "can_upload": can_upload,
        "active_user_jobs": active_user_jobs,
        "active_global_jobs": active_global_jobs,
        "limits": limits,
        "message": None if can_upload else "Attendi che finisca l'elaborazione in corso prima di caricare un altro PDF.",
    }

@api.get("/support/info")
async def support_info():
    return {"email": SUPPORT_EMAIL}


@api.get("/pdfs/{pdf_id}/status")
async def get_pdf_status(pdf_id: str, user_id: str = Depends(get_current_user_id)):
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0, "status": 1, "pages": 1})
    if not p: raise HTTPException(status_code=404, detail="Non trovato")
    # Check access
    can_access = await _user_can_access_pdf(user_id, pdf_id)
    if not can_access: raise HTTPException(status_code=403, detail="Accesso negato")
    return p

@api.get("/pdfs/{pdf_id}")
async def get_pdf(pdf_id: str, user_id: Optional[str] = Depends(get_optional_user_id), share_token: Optional[str] = Query(None)):
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="PDF non trovato")

    can_access = await _user_can_access_pdf(user_id, pdf_id, share_token)
    if not can_access:
        if p.get("is_protected") and not user_id:
            raise HTTPException(status_code=401, detail="Protetto")
        raise HTTPException(status_code=403, detail="Accesso negato")

    return _serialize_pdf(p)

@api.patch("/pdfs/{pdf_id}")
async def patch_pdf(pdf_id: str, payload: PdfPatchIn, user_id: str = Depends(get_current_user_id)):
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p: raise HTTPException(status_code=404, detail="PDF non trovato")
    can_access = await _user_can_access_pdf(user_id, pdf_id)
    if not can_access: raise HTTPException(status_code=403, detail="Accesso negato")
    u = await db.users.find_one({"user_id": user_id})
    is_admin = u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL)
    update = payload.model_dump(exclude_none=True)
    # protected PDFs: only allow tags and is_favorite
    if p.get("is_protected") and not is_admin:
        restricted_keys = {"title", "is_protected"}
        if any(key in update for key in restricted_keys):
            raise HTTPException(status_code=403, detail="Operazione non consentita su file protetto")
    if update.get("is_protected") and not is_admin:
        raise HTTPException(status_code=403, detail="Solo un amministratore può modificare lo stato protetto")
    if any(key in update for key in ["title"]):
        if not is_admin and p.get("owner_id") != user_id:
            raise HTTPException(status_code=403, detail="Solo il proprietario o un amministratore possono modificare questo file")
    if update:
        if "title" in update:
            update["title_normalized"] = normalize_pdf_text(update["title"])
        await db.pdfs.update_one({"id": pdf_id}, {"$set": update})
        if "title" in update and p.get("drive_file_id"):
            master = await get_master_drive()
            refresh_token = master.get("refresh_token") if master else None
            if refresh_token:
                renamed = await asyncio.to_thread(gi.rename_drive_file, refresh_token, p["drive_file_id"], _sanitize_pdf_filename(update["title"]))
                if not renamed:
                    await log_event("drive_backup_error", f"Rinomina Drive non riuscita per PDF {pdf_id}", user_id=user_id, level="error", meta={"pdf_id": pdf_id, "drive_file_id": p["drive_file_id"], "stage": "rename"})
            else:
                await log_event("drive_backup_error", f"Token Drive non disponibile per rinominare PDF {pdf_id}", user_id=user_id, level="error", meta={"pdf_id": pdf_id, "drive_file_id": p["drive_file_id"], "stage": "rename"})
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    return _serialize_pdf(p)

@api.delete("/pdfs/{pdf_id}")
async def delete_pdf(pdf_id: str, user_id: str = Depends(get_current_user_id)):
    p = await db.pdfs.find_one({"id": pdf_id})
    if not p: raise HTTPException(status_code=404, detail="PDF non trovato")
    u = await db.users.find_one({"user_id": user_id})
    is_admin = u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL)
    if p.get("is_protected") and not is_admin:
        raise HTTPException(status_code=403, detail="Operazione non consentita su file protetto")
    if p and os.path.exists(p["file_path"]):
        try:
            os.remove(p["file_path"])
        except Exception:
            pass
    await db.pdfs.delete_one({"id": pdf_id})
    await db.pdf_pages.delete_many({"pdf_id": pdf_id})
    await db.shared_libraries.update_many({}, {"$pull": {"pdf_ids": pdf_id}})
    await log_event("pdf.deleted", f"PDF eliminato: {pdf_id}", user_id=user_id, meta={"pdf_id": pdf_id})
    return {"ok": True}

@api.get("/pdfs/{pdf_id}/file")
async def get_pdf_file(pdf_id: str, user_id: Optional[str] = Depends(get_optional_user_id), share_token: Optional[str] = Query(None)):
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="PDF non trovato")

    can_access = await _user_can_access_pdf(user_id, pdf_id, share_token)
    if not can_access:
        if p.get("is_protected") and not user_id:
            raise HTTPException(status_code=401, detail="Protetto")
        raise HTTPException(status_code=403, detail="Accesso negato")
    # Diagnostic logging: capture metadata and whether local file exists
    file_path = p.get("file_path")
    try:
        fpath = Path(file_path) if file_path else Path("")
        file_exists = fpath.exists()
    except Exception:
        fpath = Path("")
        file_exists = False

    if file_exists:
        return FileResponse(fpath, media_type="application/pdf", filename=p["filename"])

    # Local file missing — attempt Drive fallback if available
    await log_event(
        "pdf.debug",
        "PDF_DEBUG",
        user_id=user_id,
        meta={
            "pdf_id": pdf_id,
            "file_path": str(file_path),
            "file_exists": file_exists,
            "drive_file_id": p.get("drive_file_id"),
            "drive_owner": p.get("drive_owner"),
            "storage_type": p.get("storage_type"),
        },
    )
    await log_event(
        "pdf.file_missing",
        "PDF locale mancante, provo fallback Drive",
        user_id=user_id,
        meta={"pdf_id": pdf_id, "file_path": str(file_path), "drive_file_id": p.get("drive_file_id"), "drive_owner": p.get("drive_owner")},
    )

    if p.get("drive_file_id"):
        try:
            data = await _download_from_drive_with_fallback(p)
            new_path = UPLOAD_DIR / Path(file_path).name
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(data)
            await db.pdfs.update_one({"id": pdf_id}, {"$set": {
                "file_path": str(new_path),
                "storage_type": "local",
                "synced_at": iso_now(),
            }})
            await log_event(
                "pdf.drive_restore",
                "PDF ripristinato da Drive",
                user_id=user_id,
                meta={"pdf_id": pdf_id, "drive_file_id": p["drive_file_id"], "file_path": str(new_path)},
            )
            return FileResponse(new_path, media_type="application/pdf", filename=p["filename"])
        except Exception as e:
                await log_event(
                    "pdf.debug",
                    "PDF_DRIVE_FALLBACK_ERROR",
                    user_id=user_id,
                    level="error",
                    meta={
                        "pdf_id": pdf_id,
                        "drive_file_id": p.get("drive_file_id"),
                        "exception_repr": repr(e),
                        "exception_str": str(e),
                        "stage": "get_pdf_file_fallback",
                    },
                )
                await log_event("pdf.error", f"Drive download fallito: {e}", user_id=user_id, level="error", meta={"pdf_id": pdf_id, "drive_file_id": p.get("drive_file_id"), "stage": "get_pdf_file_fallback"})

    raise HTTPException(status_code=404, detail="File non trovato")


@api.post("/pdfs/{pdf_id}/reload")
async def reload_pdf(pdf_id: str, user_id: str = Depends(get_current_user_id)):
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="PDF non trovato")
    if p.get("is_protected") and not user_id:
        raise HTTPException(status_code=401, detail="Protetto")
    can_access = await _user_can_access_pdf(user_id, pdf_id)
    if not can_access:
        raise HTTPException(status_code=403, detail="Accesso negato")
    drive_file_id = p.get("drive_file_id")
    if not drive_file_id:
        raise HTTPException(status_code=404, detail="Backup Drive non disponibile")

    try:
        data = await _download_from_drive_with_fallback(p)
        new_path = UPLOAD_DIR / Path(p["file_path"]).name
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(data)
        await db.pdfs.update_one({"id": pdf_id}, {"$set": {
            "file_path": str(new_path),
            "storage_type": "local",
            "synced_at": iso_now(),
        }})
        await log_event("pdf.drive_restore", "PDF ripristinato da Drive via reload endpoint", user_id=user_id, meta={"pdf_id": pdf_id, "drive_file_id": drive_file_id, "file_path": str(new_path)})
        return {"ok": True}
    except Exception as e:
        await log_event("pdf.error", f"Drive download reload fallito: {e}", user_id=user_id, level="error", meta={"pdf_id": pdf_id, "drive_file_id": drive_file_id, "stage": "reload"})
        raise HTTPException(status_code=502, detail="Recupero da Drive fallito")

# ----------------- Libraries -----------------
@api.post("/libraries")
async def create_library(payload: CreateLibraryIn, user_id: str = Depends(get_current_user_id)):
    lib_id = str(uuid.uuid4())
    share_token = secrets.token_urlsafe(16)
    doc = {
        "id": lib_id,
        "name": payload.name.strip() or "Libreria",
        "description": payload.description or "",
        "owner_id": user_id,
        "pdf_ids": [],
        "members": [],
        "share_token": share_token,
        "public": True,
        "created_at": iso_now(),
    }
    await db.shared_libraries.insert_one(doc)
    await log_event("library.create", f"Libreria creata: {doc['name']}", user_id=user_id)
    return clean_doc(doc)

@api.get("/libraries")
async def list_libraries(user_id: str = Depends(get_current_user_id)):
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    is_admin = bool(u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL))

    query = {"hidden_by_users": {"$ne": user_id}}
    if not is_admin:
        query["$or"] = [{"owner_id": user_id}, {"members": user_id}]

    cursor = db.shared_libraries.find(query, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(1000)
    return {"items": items}

@api.get("/libraries/hidden")
async def list_hidden_libraries(user_id: str = Depends(get_current_user_id)):
    cursor = db.shared_libraries.find({"hidden_by_users": user_id}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(1000)
    return {"items": items}

@api.get("/libraries/{lib_id}")
async def get_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id}, {"_id": 0})
    if not lib: raise HTTPException(status_code=404, detail="Libreria non trovata")
    pdfs = await db.pdfs.find({"id": {"$in": lib.get("pdf_ids", [])}}, {"_id": 0}).to_list(1000)
    lib["pdfs"] = [_serialize_pdf(p) for p in pdfs]
    lib["is_owner"] = lib["owner_id"] == user_id
    return lib

@api.post("/libraries/{lib_id}/pdfs")
async def add_to_library(lib_id: str, payload: AddPdfsIn, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id})
    if not lib: raise HTTPException(status_code=404, detail="Libreria non trovata")

    requester = await db.users.find_one({"user_id": user_id})
    is_admin = bool(requester and (requester.get("is_admin") or requester.get("email", "").lower() == ADMIN_EMAIL))

    added = []
    protected = []
    skipped = []
    existing_ids = set(lib.get("pdf_ids", []))

    for pdf_id in payload.pdf_ids:
        if pdf_id in existing_ids:
            skipped.append(pdf_id)
            continue
        p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0, "is_protected": 1, "owner_id": 1})
        if not p:
            skipped.append(pdf_id)
            continue
        can_add_protected = is_admin or p.get("owner_id") == user_id
        if p.get("is_protected") and not can_add_protected:
            protected.append(pdf_id)
            continue
        added.append(pdf_id)
        existing_ids.add(pdf_id)

    if added:
        await db.shared_libraries.update_one({"id": lib_id}, {"$addToSet": {"pdf_ids": {"$each": added}}})

    return {"added": added, "protected": protected, "skipped": skipped}

@api.delete("/libraries/{lib_id}/pdfs/{pdf_id}")
async def remove_from_library(lib_id: str, pdf_id: str, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id})
    if not lib: raise HTTPException(status_code=404, detail="Libreria non trovata")
    u = await db.users.find_one({"user_id": user_id})
    is_admin = u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL)
    is_member = user_id in lib.get("members", [])
    if not is_admin and lib.get("owner_id") != user_id and not is_member:
        raise HTTPException(status_code=403, detail="Solo il proprietario, un amministratore o un membro possono modificare questa libreria")
    await db.shared_libraries.update_one({"id": lib_id}, {"$pull": {"pdf_ids": pdf_id}})
    return {"ok": True}

@api.delete("/libraries/{lib_id}")
async def delete_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id})
    if not lib: raise HTTPException(status_code=404, detail="Libreria non trovata")
    u = await db.users.find_one({"user_id": user_id})
    is_admin = u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL)
    if not is_admin and lib.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Solo il proprietario o un amministratore possono eliminare questa libreria")
    await db.shared_libraries.delete_one({"id": lib_id})
    return {"ok": True}

@api.post("/libraries/{lib_id}/hide")
async def hide_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id}, {"_id": 0})
    if not lib:
        raise HTTPException(status_code=404, detail="Libreria non trovata")
    if lib.get("owner_id") == user_id:
        raise HTTPException(status_code=403, detail="Il proprietario non può nascondere la propria libreria")
    if user_id not in lib.get("members", []):
        raise HTTPException(status_code=403, detail="Solo i membri possono nascondere questa libreria")
    await db.shared_libraries.update_one({"id": lib_id}, {"$addToSet": {"hidden_by_users": user_id}})
    return {"ok": True}

@api.post("/libraries/{lib_id}/leave")
async def leave_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    return await hide_library(lib_id, user_id)

@api.delete("/libraries/{lib_id}/hide")
async def unhide_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    lib = await db.shared_libraries.find_one({"id": lib_id}, {"_id": 0})
    if not lib:
        raise HTTPException(status_code=404, detail="Libreria non trovata")
    await db.shared_libraries.update_one({"id": lib_id}, {"$pull": {"hidden_by_users": user_id}})
    return {"ok": True}

@api.delete("/libraries/{lib_id}/leave")
async def restore_library(lib_id: str, user_id: str = Depends(get_current_user_id)):
    return await unhide_library(lib_id, user_id)

# ----------------- Shared -----------------
@api.get("/shared/{token}")
async def view_shared(token: str, user_id: Optional[str] = Depends(get_optional_user_id)):
    # 1. Try as library share token
    lib = await db.shared_libraries.find_one({"share_token": token}, {"_id": 0})
    if not lib:
        raise HTTPException(status_code=404, detail="Link non valido o rimosso")
    if lib.get("is_protected") and not user_id:
        raise HTTPException(status_code=401, detail="Login richiesto per accedere alla libreria condivisa")
    # add as member if not owner and not yet member
    if lib["owner_id"] != user_id and user_id not in lib.get("members", []):
        await db.shared_libraries.update_one({"id": lib["id"]}, {"$addToSet": {"members": user_id}})
        await log_event("share.access", f"Accesso libreria condivisa: {lib['name']}", user_id=user_id)
        lib["members"].append(user_id)
    pdfs = await db.pdfs.find({"id": {"$in": lib.get("pdf_ids", [])}}, {"_id": 0}).to_list(10000)
    lib["pdfs"] = [_serialize_pdf(p) for p in pdfs]
    lib["is_owner"] = lib["owner_id"] == user_id
    return lib


@api.post("/pdfs/{pdf_id}/import")
async def import_shared_pdf(pdf_id: str, user_id: str = Depends(get_current_user_id)):
    """Import a shared PDF into user's personal library (creates a copy)."""
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="PDF non trovato")
    if p["owner_id"] == user_id:
        return {"ok": True, "pdf_id": pdf_id, "already_owned": True}
    accessible = await _user_can_access_pdf(user_id, pdf_id)
    if not accessible:
        raise HTTPException(status_code=403, detail="Accesso negato")
    if p.get("content_hash"):
        existing = await db.pdfs.find_one({"owner_id": user_id, "content_hash": p["content_hash"]}, {"_id": 0, "id": 1})
        if existing:
            return {"ok": True, "pdf_id": existing["id"], "already_owned": True}
    src = UPLOAD_DIR / p["owner_id"] / f"{pdf_id}.pdf"
    data = None
    if src.exists():
        data = src.read_bytes()
    elif p.get("drive_file_id"):
        try:
            data = await _download_from_drive_with_fallback(p)
        except Exception as e:
                await log_event("pdf.error", f"Import da Drive fallito: {e}", user_id=user_id, level="error", meta={"pdf_id": pdf_id, "drive_file_id": p.get("drive_file_id"), "stage": "import_drive_download"})
    if data is None:
        raise HTTPException(status_code=404, detail="File mancante")
    new_id = str(uuid.uuid4())
    user_dir = UPLOAD_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    dst = user_dir / f"{new_id}.pdf"
    dst.write_bytes(data)
    file_path_str = str(dst.resolve())
    new_doc = {
        **p,
        "id": new_id,
        "owner_id": user_id,
        "drive_file_id": None,
        "drive_owner": None,
        "storage_type": "local",
        "file_path": file_path_str,
        "synced_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title_normalized": p.get("title_normalized") or normalize_pdf_text(p.get("title", "")),
    }
    new_doc.pop("_id", None)
    await db.pdfs.insert_one(new_doc)
    pages = await db.pdf_pages.find({"pdf_id": pdf_id}, {"_id": 0}).to_list(10000)
    if pages:
        new_pages = [{**pg, "pdf_id": new_id, "owner_id": user_id} for pg in pages]
        await db.pdf_pages.insert_many(new_pages)
    await log_event("pdf.save", f"PDF condiviso importato su disco: {file_path_str}", user_id=user_id, meta={"pdf_id": new_id, "source_pdf_id": pdf_id, "path": file_path_str, "filename": p.get("filename")})
    await log_event("pdf.storage", f"Storage finale: LOCAL - path={file_path_str}", user_id=user_id, meta={"pdf_id": new_id, "storage_type": "local", "file_path": file_path_str})
    await log_event("pdf.import", f"Importato PDF condiviso: {p.get('title')}", user_id=user_id, meta={"pdf_id": new_id, "source_pdf_id": pdf_id})
    return {"ok": True, "pdf_id": new_id}


@api.post("/pdfs/{pdf_id}/share")
async def share_pdf(pdf_id: str, user_id: str = Depends(get_current_user_id)):
    """Create a simple one-off shared link for a single PDF."""
    p = await db.pdfs.find_one({"id": pdf_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="PDF non trovato")
    # Only owner or admin can create share
    u = await db.users.find_one({"user_id": user_id})
    is_admin = u and (u.get("is_admin") or u.get("email", "").lower() == ADMIN_EMAIL)
    if not is_admin and p.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Solo il proprietario o un amministratore possono condividere questo file")

    share_id = str(uuid.uuid4())
    share_token = secrets.token_urlsafe(16)
    doc = {
        "id": share_id,
        "name": f"Condivisione - {p.get('title', p.get('filename', pdf_id))}",
        "description": "Condivisione temporanea",
        "owner_id": user_id,
        "pdf_ids": [pdf_id],
        "share_token": share_token,
        "public": True,
        "created_at": iso_now(),
    }
    await db.shared_libraries.insert_one(doc)
    await log_event("pdf.share", f"PDF condiviso: {pdf_id}", user_id=user_id, meta={"pdf_id": pdf_id, "share_token": share_token})
    return {"ok": True, "share_token": share_token, "share_url": f"/shared/{share_token}"}


async def _user_can_access_pdf(user_id: Optional[str], pdf_id: str, share_token: Optional[str] = None) -> bool:
    """
    Access rules:
    - admin sees everything
    - approved users see everything
    - shared-link viewers may access the PDF if the share token belongs to that PDF
    - otherwise no access
    """
    if user_id and await _get_active_user_id(user_id):
        return True

    if share_token:
        lib = await db.shared_libraries.find_one({"share_token": share_token, "pdf_ids": pdf_id}, {"_id": 0})
        if lib:
            return True

    return False

# ----------------- Search -----------------

def _get_search_candidate_limit() -> int:
    raw_value = os.environ.get("SEARCH_CANDIDATE_PAGE_LIMIT", "500")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 500
    return max(50, min(value, 2000))


CONTENT_SIGNATURE_SIMILARITY_THRESHOLD = float(os.environ.get("CONTENT_SIGNATURE_SIMILARITY_THRESHOLD", "0.55"))


def _select_readable_snippet(raw_snippet: str, maxlen: int = 200) -> str:
    if not raw_snippet:
        return ""
    tmp = re.sub(r"[\u0000-\u001F\u007F-\u009F]+", " ", raw_snippet)
    tmp = re.sub(r"\s+", " ", tmp).strip()
    if not tmp:
        return ""

    def letter_density(s: str) -> float:
        letters = sum(1 for ch in s if ch.isalpha())
        return letters / len(s) if s else 0.0

    if len(tmp) <= maxlen:
        return tmp if letter_density(tmp) >= 0.35 else ""

    best_fragment = tmp[:maxlen]
    best_density = letter_density(best_fragment)
    step = max(1, maxlen // 4)
    for start in range(0, len(tmp) - 39, step):
        fragment = tmp[start : start + maxlen]
        density = letter_density(fragment)
        if density >= 0.6:
            return fragment.rstrip() + (" …" if start + maxlen < len(tmp) else "")
        if density > best_density:
            best_density = density
            best_fragment = fragment

    if best_density >= 0.45:
        return best_fragment.rstrip() + " …"
    return tmp[:maxlen].rstrip() + " …"


def _page_indexed_text(pg: dict) -> str:
    return str(pg.get("text") or pg.get("text_raw") or "").strip()


def _guaranteed_page_snippet(pg: dict, raw_snippet: str) -> str:
    source_text = _page_indexed_text(pg)
    if not source_text:
        return ""
    sanitized = __import__("pdf_processor").sanitize_snippet_for_api(raw_snippet) if raw_snippet else ""
    if sanitized:
        return sanitized
    readable = _select_readable_snippet(raw_snippet or source_text)
    if readable:
        return readable
    return re.sub(r"\s+", " ", source_text).strip()[:200]


def format_search_result(p: dict, pg: dict, q: str, score: int, snippet: Optional[str] = None, source: str = "personal", match_in: str = "content") -> dict:
    # Build raw snippet (prefer explicit snippet param, else generate from page text)
    indexed_text = _page_indexed_text(pg)
    raw_snippet = snippet if snippet is not None else make_snippet(indexed_text, q)
    # First try the aggressive sanitizer (removes chords/boilerplate)
    sanitized = __import__("pdf_processor").sanitize_snippet_for_api(raw_snippet) if raw_snippet else ""

    if sanitized:
        final_snippet = sanitized
    else:
        final_snippet = _select_readable_snippet(raw_snippet)
    if not final_snippet and indexed_text:
        final_snippet = _guaranteed_page_snippet(pg, raw_snippet)

    return {
        "pdf_id": p["id"],
        "title": p["title"],
        # `page` is the physical (file) page number 1-based — keep for backward compatibility
        "page": pg["page"],
        # `actual_page` mirrors `page` (some frontend code uses this name)
        "actual_page": pg["page"],
        # `viewer_page` is the canonical numeric page the viewer should open (physical page)
        "viewer_page": pg["page"],
        "page_label": pg.get("page_label", pg["page"]),
        # Provide sanitized snippet (or fallback light-clean preview)
        "snippet": final_snippet,
        "has_indexed_text": bool(indexed_text),
        "is_ocr_fallback_snippet": bool(indexed_text and raw_snippet and normalize_search_query(q) not in normalize_search_query(raw_snippet)),
        "query": q,
        "match_text": q,
        "score": score,
        "is_protected": p.get("is_protected", False),
        "source": source,
        "match_in": match_in,
    }


@api.get("/pdfs/{pdf_id}/search-context")
async def get_pdf_search_context(
    pdf_id: str,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    share_token: Optional[str] = Query(None),
    user_id: Optional[str] = Depends(get_optional_user_id),
):
    user_id = await _get_active_user_id(user_id)
    can_access = await _user_can_access_pdf(user_id, pdf_id, share_token)
    if not can_access:
        raise HTTPException(status_code=403, detail="Accesso negato")
    pg = await db.pdf_pages.find_one({"pdf_id": pdf_id, "page": page}, {"_id": 0})
    if not pg:
        return {"pdf_id": pdf_id, "page": page, "query": q, "snippet": "", "match_text": q, "has_indexed_text": False, "is_ocr_fallback_snippet": False}
    raw_q = normalize_search_query(q).strip()
    indexed_text = _page_indexed_text(pg)
    raw_snippet = make_snippet(indexed_text, raw_q)
    snippet = _guaranteed_page_snippet(pg, raw_snippet)
    if not snippet:
        snippet = _select_readable_snippet(raw_snippet) or _guaranteed_page_snippet(pg, indexed_text)
    return {
        "pdf_id": pdf_id,
        "page": pg.get("page", page),
        "page_label": pg.get("page_label", page),
        "query": raw_q,
        "match_text": raw_q,
        "snippet": snippet,
        "has_indexed_text": bool(indexed_text),
        "is_ocr_fallback_snippet": bool(indexed_text and raw_snippet and normalize_search_query(raw_q) not in normalize_search_query(raw_snippet)),
        "ocr_provider": pg.get("ocr_provider", ""),
    }

@api.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    pdf_ids: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    share_token: Optional[str] = Query(None),
    user_id: Optional[str] = Depends(get_optional_user_id),
    debug: bool = Query(False),
):
    raw_q = normalize_search_query(q).strip()
    if not raw_q:
        return {"results": []}

    # A decoded JWT alone isn't enough here: re-check the account is still admin/approved
    # so a revoked/banned user's still-unexpired token can't be used to full-text search
    # (and read snippets from) every PDF. Fall back to anonymous/share_token-only scope.
    user_id = await _get_active_user_id(user_id)

    if not user_id and not share_token:
        raise HTTPException(status_code=401, detail="Login richiesto")

    pdf_ids_list = [pid.strip() for pid in (pdf_ids or "").split(",") if pid.strip()] or None
    
    # Se tag è selezionato, filtra per PDF IDs che hanno quel tag
    if tag and tag.strip():
        tag_pattern = {"$regex": f"^{re.escape(tag.strip())}$", "$options": "i"}
        tag_pdfs = await db.pdfs.find({"tags": tag_pattern}, {"_id": 0, "id": 1}).to_list(1000)
        tag_pdf_ids = set(p["id"] for p in tag_pdfs)
        if pdf_ids_list:
            pdf_ids_list = [pid for pid in pdf_ids_list if pid in tag_pdf_ids]
        else:
            pdf_ids_list = list(tag_pdf_ids)
    
    if share_token:
        lib = await db.shared_libraries.find_one({"share_token": share_token}, {"_id": 0, "pdf_ids": 1})
        if not lib:
            raise HTTPException(status_code=404, detail="Link non valido o rimosso")
        allowed_pdf_ids = set(lib.get("pdf_ids", []))
        if pdf_ids_list:
            pdf_ids_list = [pid for pid in pdf_ids_list if pid in allowed_pdf_ids]
        else:
            pdf_ids_list = list(allowed_pdf_ids)

    results = []
    seen = set()  # Per evitare duplicati (stessa pagina trovata con logiche diverse)
    candidate_limit = _get_search_candidate_limit()
    search_debug = {
        "query": raw_q,
        "candidate_limit": candidate_limit,
        "candidate_count": 0,
        "initial_result_count": 0,
        "fallback_used": False,
        "fallback_candidate_count": 0,
        "final_result_count": 0,
    }

    if raw_q.isdigit():
        hymn_regex = rf"(?m)^\s*{re.escape(raw_q)}[.\s]"
        hymn_filter = {
            "$or": [
                {"text_normalized": {"$regex": hymn_regex, "$options": "im"}},
                {"text": {"$regex": hymn_regex, "$options": "im"}},
            ]
        }
        if pdf_ids_list:
            hymn_filter["pdf_id"] = {"$in": pdf_ids_list}
        cursor = db.pdf_pages.find(hymn_filter)
        async for pg in cursor:
            key = (pg["pdf_id"], pg["page"])
            if key in seen:
                continue
            seen.add(key)
            p = await db.pdfs.find_one({"id": pg["pdf_id"]})
            if p:
                results.append(format_search_result(p, pg, raw_q, score=100))

        if raw_q.isdigit():
            cantico_filter = {"cantico": int(raw_q)}
            if pdf_ids_list:
                cantico_filter["pdf_id"] = {"$in": pdf_ids_list}
            cantico_cursor = db.pdf_pages.find(cantico_filter)
            async for pg in cantico_cursor:
                key = (pg["pdf_id"], pg["page"])
                if key in seen:
                    continue
                seen.add(key)
                p = await db.pdfs.find_one({"id": pg["pdf_id"]})
                if p:
                    results.append(format_search_result(p, pg, raw_q, score=120, snippet=make_snippet(pg.get("text_raw", pg.get("text", "")), raw_q), match_in="cantico"))

        label_filter = {"page_label": raw_q}
        if pdf_ids_list:
            label_filter["pdf_id"] = {"$in": pdf_ids_list}
        label_cursor = db.pdf_pages.find(label_filter)
        async for pg in label_cursor:
            key = (pg["pdf_id"], pg["page"])
            if key in seen:
                continue
            seen.add(key)
            p = await db.pdfs.find_one({"id": pg["pdf_id"]})
            if p:
                results.append(format_search_result(p, pg, raw_q, score=50, snippet=f"Pagina {raw_q}"))

    safe_raw_q = rf"(?<!\d){re.escape(raw_q)}(?!\d)" if raw_q.isdigit() else re.escape(raw_q)
    safe_normalized_q = build_apostrophe_tolerant_regex(raw_q) if raw_q else safe_raw_q

    # 3. CERCA TITOLO PDF
    title_filter = {
        "$or": [
            {"title": {"$regex": safe_raw_q, "$options": "i"}},
            {"title": {"$regex": safe_normalized_q, "$options": "i"}},
            {"title_normalized": {"$regex": safe_normalized_q, "$options": "i"}},
        ]
    }
    if pdf_ids_list:
        title_filter["id"] = {"$in": pdf_ids_list}
    title_cursor = db.pdfs.find(title_filter, {"_id": 0})
    async for p in title_cursor:
        key = (p["id"], 1)
        if key in seen:
            continue
        seen.add(key)
        title_text = clean_pdf_text(p.get("title", ""))
        pg = {
            "page": 1,
            "page_label": (p.get("page_labels") or [1])[0] if p.get("page_labels") else 1,
            "text": p.get("title", ""),
        }
        results.append(
            format_search_result(
                p,
                pg,
                raw_q,
                score=30,
                snippet=make_snippet(title_text, raw_q),
                source="personal",
                match_in="title",
            )
        )

    def _token_tolerant_regex(s: str) -> str:
        r"""Build a token-tolerant regex allowing punctuation, chords or whitespace between tokens.
        Example: "amore grande profondo" -> "\bamore\b[\s\W]*\bgrande\b[\s\W]*\bprofondo\b"."""
        if not s:
            return ""
        parts = [p for p in re.split(r"\s+", s) if p]
        if not parts:
            return re.escape(s)
        pattern = r"\b" + re.escape(parts[0]) + r"\b"
        for p in parts[1:]:
            pattern += r"[\s\W]*" + r"\b" + re.escape(p) + r"\b"
        return pattern

    tokenized_raw_q = _token_tolerant_regex(raw_q)

    text_filter = {
        "$or": [
            {"text_normalized": {"$regex": safe_normalized_q, "$options": "i"}},
            {"text": {"$regex": tokenized_raw_q, "$options": "i"}},
        ]
    }

    # If the user query contains punctuation that splits the phrase (commas, semicolons,
    # colons, dashes, etc.), also include the primary segment that appears before the
    # first punctuation as candidate filter. This makes queries like
    # "dio ti protegga, ti benedica" still match pages containing "dio ti protegga".
    primary_split = re.split(r"[,\.;:—–\-]+", raw_q)[0].strip() if raw_q else ""
    if primary_split and primary_split != raw_q:
        primary_safe_norm = build_apostrophe_tolerant_regex(primary_split)
        primary_tokenized = _token_tolerant_regex(primary_split)
        # Prepend the primary checks so they are considered first in the candidate filter
        text_filter["$or"].insert(0, {"text_normalized": {"$regex": primary_safe_norm, "$options": "i"}})
        text_filter["$or"].insert(1, {"text": {"$regex": primary_tokenized, "$options": "i"}})

    if pdf_ids_list:
        text_filter["pdf_id"] = {"$in": pdf_ids_list}

    text_cursor = db.pdf_pages.find(text_filter)
    if pdf_ids_list:
        text_cursor = text_cursor.sort([("pdf_id", 1), ("page", 1)])
    else:
        text_cursor = text_cursor.sort([("pdf_id", 1), ("page", 1)]).limit(candidate_limit)
    signature_query = build_content_signature(raw_q)
    
    # First pass: collect all text pages to apply fuzzy token matching
    matched_pages = []
    async for pg in text_cursor:
        matched_pages.append(pg)

    async def _maybe_add_signature_match(pg: dict, base_score: int = 82) -> bool:
        if not signature_query:
            return False
        page_signature = pg.get("content_signature") or build_content_signature(pg.get("text", ""))
        if not page_signature:
            return False
        similarity = _content_signature_similarity(signature_query, page_signature)
        if similarity < CONTENT_SIGNATURE_SIMILARITY_THRESHOLD:
            return False
        key = (pg["pdf_id"], pg["page"])
        if key in seen:
            return False
        seen.add(key)
        p = await db.pdfs.find_one({"id": pg["pdf_id"]})
        if p:
            score = max(base_score, int(similarity * 90))
            results.append(format_search_result(p, pg, raw_q, score=score, source="personal", match_in="content_signature"))
            return True
        return False
    
    # Second pass: apply token-based fuzzy matching to the results
    for pg in matched_pages:
        key = (pg["pdf_id"], pg["page"])
        if key in seen:
            continue
        
        # Apply token-based matching to the actual text
        pg_text = pg.get("text", "")
        if pg_text and text_matches_query(pg_text, raw_q, use_fuzzy=True):
            seen.add(key)
            p = await db.pdfs.find_one({"id": pg["pdf_id"]})
            if p:
                # Calculate quality-based score with gradation
                # 1.0 (exact) → 100, 0.95 → 95, 0.90 → 90, 0.85 → 85
                quality = _calculate_match_quality(pg_text, raw_q)
                score = int(quality * 100) if quality > 0 else 10
                results.append(format_search_result(p, pg, raw_q, score=score, source="personal", match_in="content"))
        else:
            await _maybe_add_signature_match(pg)
    
    search_debug["candidate_count"] = len(matched_pages)
    search_debug["initial_result_count"] = len(results)

    # Also perform fallback fuzzy search on all pages if initial results are sparse
    fallback_used = False
    fallback_candidate_count = 0
    if len(results) < 3 and not raw_q.isdigit():
        fallback_used = True
        # Get all pages and apply fuzzy matching
        # Use a broader-but-bounded fallback to avoid blowing up the search path.
        fallback_limit = max(50, min(candidate_limit // 2, 200))
        all_pages = await db.pdf_pages.find({} if not pdf_ids_list else {"pdf_id": {"$in": pdf_ids_list}}).limit(fallback_limit).to_list(fallback_limit)
        fallback_candidate_count = len(all_pages)
        for pg in all_pages:
            key = (pg["pdf_id"], pg["page"])
            if key in seen:
                continue
            
            pg_text = pg.get("text", "")
            if pg_text and text_matches_query(pg_text, raw_q, use_fuzzy=True):
                seen.add(key)
                p = await db.pdfs.find_one({"id": pg["pdf_id"]})
                if p:
                    # Fallback results get lower base score with gradation
                    quality = _calculate_match_quality(pg_text, raw_q)
                    score = int(quality * 80) if quality > 0 else 8
                    results.append(format_search_result(p, pg, raw_q, score=score, source="personal", match_in="content"))
            else:
                await _maybe_add_signature_match(pg, base_score=74)

    search_debug["fallback_used"] = fallback_used
    search_debug["fallback_candidate_count"] = fallback_candidate_count
    search_debug["final_result_count"] = len(results)

    logger.info(
        "SEARCH_DEBUG query=%s candidate_limit=%d candidate_count=%d initial_results=%d fallback_used=%s fallback_candidates=%d final_results=%d",
        raw_q,
        candidate_limit,
        search_debug["candidate_count"],
        search_debug["initial_result_count"],
        fallback_used,
        fallback_candidate_count,
        len(results),
    )

    # Sort by score desc, then by physical page number (use actual_page if present, fall back to page)
    results.sort(key=lambda x: (-x["score"], x.get("actual_page", x.get("page", 0))))
    payload = {"results": results}
    if debug:
        payload["debug"] = search_debug
    return payload

# ----------------- Admin Logs -----------------
@api.get("/admin/logs")
async def get_admin_logs(event_type: str = Query("all"), q: str = Query(""), sort: str = Query("date_desc"), limit: int = Query(500), user_id: str = Depends(require_admin)):
    query = {}
    if event_type != "all":
        query["event_type"] = event_type
    if q:
        # Escape user input before it reaches $regex: an admin session (or anyone who
        # compromises one) could otherwise pass a catastrophic-backtracking pattern and
        # stall this query against Mongo.
        query["description"] = {"$regex": re.escape(q), "$options": "i"}
    
    sort_dir = -1 if "desc" in sort.lower() else 1
    cursor = db.app_logs.find(query, {"_id": 0}).sort("created_at", sort_dir).limit(limit)
    items = await cursor.to_list(limit)
    
    all_types = await db.app_logs.distinct("event_type")
    
    return {"items": items, "types": sorted(all_types or [])}


# ----------------- Admin -----------------
@api.get("/admin/stats")
async def admin_stats(_: str = Depends(require_admin)):
    return {
        "users_total": await db.access_requests.count_documents({"status": "approved"}),
        "pdfs_total": await db.pdfs.count_documents({}),
    }

@api.get("/admin/users")
async def admin_users(_: str = Depends(require_admin)):
    reqs = await db.access_requests.find({"status": "approved"}).to_list(1000)
    return {"users": [{"email": r["email"], "name": r["name"], "created_at": r["created_at"]} for r in reqs]}

@api.get("/admin/access-requests")
async def list_access_requests(_: str = Depends(require_admin)):
    reqs = await db.access_requests.find({}).sort("created_at", -1).to_list(100)
    return [clean_doc(r) for r in reqs]

@api.post("/admin/access-requests/approve")
async def approve_access(payload: dict, background_tasks: BackgroundTasks, user_id: str = Depends(require_admin)):
    email = payload["email"].lower().strip()
    req = await db.access_requests.find_one({"email": email})
    await db.access_requests.update_one({"email": email}, {"$set": {"status": "approved", "email": email}})
    await log_event("access.approved", f"Richiesta accesso approvata: {email}", user_id=user_id, meta={"email": email})
    background_tasks.add_task(send_access_request_outcome_email, email, "approved", req.get("name") if req else None)
    return {"ok": True}

@api.post("/admin/access-requests/reject")
async def reject_access(payload: dict, background_tasks: BackgroundTasks, user_id: str = Depends(require_admin)):
    email = payload["email"].lower().strip()
    req = await db.access_requests.find_one({"email": email})
    await db.access_requests.update_one({"email": email}, {"$set": {"status": "rejected", "email": email}})
    await log_event("access.rejected", f"Richiesta accesso rifiutata: {email}", user_id=user_id, meta={"email": email})
    background_tasks.add_task(send_access_request_outcome_email, email, "rejected", req.get("name") if req else None)
    return {"ok": True}

@api.post("/admin/access-requests/revoke")
async def revoke_access(payload: dict, user_id: str = Depends(require_admin)):
    email = (payload.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email richiesta")
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="L'amministratore non può essere revocato.")
    await db.access_requests.update_one({"email": email}, {"$set": {"status": "revoked", "email": email, "revoked_at": iso_now()}})
    await db.users.delete_many({"email": email})
    await log_event("access.revoked", f"Accesso revocato: {email}", user_id=user_id, meta={"email": email})
    return {"ok": True}

@api.post("/admin/access-requests/ban")
async def ban_access(payload: dict, user_id: str = Depends(require_admin)):
    email = (payload.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email richiesta")
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="L'amministratore non può essere bloccato.")
    await db.access_requests.update_one({"email": email}, {"$set": {"status": "banned", "email": email, "banned_at": iso_now()}})
    await db.users.delete_many({"email": email})
    await log_event("access.banned", f"Email bloccata: {email}", user_id=user_id, meta={"email": email})
    return {"ok": True}


@api.post("/admin/access-requests/unban")
async def unban_access(payload: dict, user_id: str = Depends(require_admin)):
    email = (payload.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email richiesta")
    await db.access_requests.update_one(
        {"email": email},
        {
            "$set": {"status": "pending", "email": email, "unbanned_at": iso_now()},
            "$unset": {"banned_at": "", "revoked_at": ""},
        },
        upsert=True,
    )
    await db.users.update_many(
        {"email": email},
        {"$unset": {"is_banned": "", "banned": "", "banned_at": ""}, "$set": {"updated_at": iso_now()}},
    )
    await log_event("access.unbanned", f"Email sbloccata: {email}", user_id=user_id, meta={"email": email})
    return {"ok": True}


@api.get("/admin/gemini/status")
async def admin_gemini_status(_: str = Depends(require_admin)):
    import pdf_processor

    return pdf_processor.get_gemini_admin_status()

@api.get("/admin/master-drive/status")
async def master_drive_status(_: str = Depends(require_admin)):
    m = await get_master_drive()
    return {"connected": bool(m), "email": m.get("email", "") if m else ""}

@api.post("/admin/master-drive/url")
async def master_drive_url(payload: dict, _: str = Depends(require_admin)):
    return {"url": gi.build_auth_url(payload["redirect_uri"], secrets.token_urlsafe(16))}

@api.post("/admin/master-drive/connect")
async def master_drive_connect(payload: dict, _: str = Depends(require_admin)):
    tokens = await gi.exchange_code(payload["code"], payload["redirect_uri"])
    info = await gi.fetch_userinfo(tokens["access_token"])
    root = await asyncio.to_thread(gi.ensure_master_root, tokens["refresh_token"])
    await db.config.update_one({"key": "master_drive"}, {"$set": {"refresh_token": tokens["refresh_token"], "email": info["email"], "folder_root_id": root, "updated_at": iso_now()}}, upsert=True)
    return {"connected": True, "email": info["email"]}

@api.post("/admin/master-drive/disconnect")
async def master_drive_disconnect(_: str = Depends(require_admin)):
    await db.config.delete_one({"key": "master_drive"})
    return {"ok": True}

def _job_waiting_for_gemini_quota_status() -> str:
    return "waiting_for_gemini_quota"


def _gemini_quota_resume_ranges(total_pages: int, quota_page: Optional[int] = None, completed_pages: Optional[List[int]] = None, pending_pages: Optional[List[int]] = None) -> Tuple[List[int], List[int]]:
    total_pages = max(0, int(total_pages or 0))

    if completed_pages is not None:
        completed = sorted({int(page) for page in completed_pages if 1 <= int(page) <= total_pages})
    else:
        completed = []

    if pending_pages is not None:
        pending = sorted({int(page) for page in pending_pages if 1 <= int(page) <= total_pages})
    elif quota_page is not None and total_pages:
        quota_page = max(1, min(int(quota_page), total_pages))
        pending = list(range(quota_page, total_pages + 1))
    else:
        pending = []

    if quota_page is not None and total_pages and not completed:
        quota_page = max(1, min(int(quota_page), total_pages))
        completed = list(range(1, quota_page))

    if pending and not completed:
        completed = [page for page in range(1, total_pages + 1) if page not in pending]

    if pending and completed:
        pending = sorted({page for page in pending if page not in completed})
        completed = sorted({page for page in completed if 1 <= page <= total_pages})

    if quota_page is not None and total_pages and not pending and completed:
        completed = sorted({page for page in range(1, total_pages + 1) if page not in pending})

    if quota_page is None and not pending and not completed:
        return [], []

    return completed, pending


async def _mark_job_waiting_for_gemini_quota(job_id: str, *, pdf_id: Optional[str], page_num: Optional[int], retry_after: Optional[float], pending_pages: Optional[List[int]] = None, completed_pages: Optional[List[int]] = None, model: Optional[str] = None, reason: str = "quota_exhausted") -> None:
    if not job_id:
        return
    payload = {
        "status": _job_waiting_for_gemini_quota_status(),
        "gemini_quota_waiting": True,
        "gemini_quota_waiting_since": iso_now(),
        "gemini_retry_after_seconds": retry_after,
        "gemini_model": model or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
        "gemini_quota_reason": reason,
        "updated_at": iso_now(),
    }
    if pdf_id is not None:
        payload["pdf_id"] = pdf_id
    if page_num is not None:
        payload["gemini_quota_page"] = int(page_num)
    if pending_pages is not None:
        payload["gemini_pending_pages"] = pending_pages
    if completed_pages is not None:
        payload["gemini_completed_pages"] = completed_pages
    await db.upload_jobs.update_one({"id": job_id}, {"$set": payload}, upsert=True)


async def _resume_waiting_gemini_jobs() -> None:
    pending_jobs = await db.upload_jobs.find({
        "status": _job_waiting_for_gemini_quota_status(),
    }).to_list(1000)
    for j in pending_jobs:
        safe_create_task(process_pdf_job(j["id"]))


async def _verify_expected_pdf_pages(pdf_id: str, expected_pages: List[int]) -> Tuple[bool, List[int], List[int], List[int], List[int]]:
    """Check that every expected page for this PDF really exists in MongoDB and no unexpected page is accepted."""
    normalized_expected = sorted({int(page) for page in expected_pages if page is not None})
    if not normalized_expected:
        return True, [], [], [], []

    try:
        saved_records = await db.pdf_pages.find(
            {"pdf_id": pdf_id, "page": {"$in": normalized_expected}},
            {"_id": 0, "page": 1},
        ).to_list(10000)
    except Exception as exc:
        logger.error("PDF.PAGES_WRITE_VERIFY_ERROR pdf=%s error=%s", pdf_id, repr(exc))
        return False, [], normalized_expected, normalized_expected, []

    saved_pages = sorted({int(record.get("page")) for record in saved_records if isinstance(record.get("page"), int)})
    missing_pages = sorted(set(normalized_expected) - set(saved_pages))
    unexpected_pages = sorted(set(saved_pages) - set(normalized_expected))
    logger.info(
        "PDF.PAGES_WRITE_VERIFY pdf=%s expected=%s saved=%s missing=%s unexpected=%s",
        pdf_id,
        normalized_expected,
        saved_pages,
        missing_pages,
        unexpected_pages,
    )
    return (not missing_pages and not unexpected_pages), saved_pages, missing_pages, unexpected_pages, normalized_expected


async def _set_job_status(job_id: str, status: str, **extra) -> None:
    patch = {"status": status, "updated_at": iso_now()}
    patch.update(extra)
    await db.upload_jobs.update_one({"id": job_id}, {"$set": patch}, upsert=True)


@api.post("/admin/reset-today")
async def reset_today_data(payload: dict, user_id: str = Depends(require_admin)):
    if not ADMIN_RESET_PASSWORD:
        raise HTTPException(status_code=503, detail="Funzione non configurata: impostare ADMIN_LOG_PASSWORD")
    provided = (payload.get("password") or "").strip()
    if not secrets.compare_digest(provided, ADMIN_RESET_PASSWORD):
        raise HTTPException(status_code=403, detail="Password non valida")

    access_deleted = await db.access_requests.delete_many({})
    users_deleted = await db.users.delete_many({"is_admin": {"$ne": True}})
    logs_deleted = await db.app_logs.delete_many({})

    await log_event(
        "admin.reset_today",
        "Reset dati amministrazione richiesto dall'amministratore",
        user_id=user_id,
        level="warn",
        meta={
            "access_requests_deleted": access_deleted.deleted_count,
            "users_deleted": users_deleted.deleted_count,
            "logs_deleted": logs_deleted.deleted_count,
        },
    )

    return {
        "ok": True,
        "deleted": {
            "access_requests": access_deleted.deleted_count,
            "users": users_deleted.deleted_count,
            "logs": logs_deleted.deleted_count,
        },
    }

@api.get("/system/status")
async def system_status():
    state = await _maintenance_state()
    return {"maintenance": bool(state.get("enabled")), "activated_by": state.get("activated_by"), "activated_at": state.get("activated_at")}

@api.post("/admin/maintenance")
async def set_maintenance(payload: dict, user_id: str = Depends(require_admin)):
    live_password = ADMIN_RESET_PASSWORD
    provided = (payload.get("password") or "").strip()
    if not live_password or not secrets.compare_digest(provided, live_password): raise HTTPException(status_code=403, detail="Password non valida")
    enabled = bool(payload.get("enabled"))
    state = {"key": "maintenance", "enabled": enabled, "activated_by": user_id if enabled else None, "activated_at": iso_now() if enabled else None, "updated_at": iso_now()}
    await db.config.update_one({"key": "maintenance"}, {"$set": state}, upsert=True)
    await log_event("admin.maintenance", "Modalità manutenzione " + ("attivata" if enabled else "disattivata"), user_id=user_id, level="warn" if enabled else "info", meta={"enabled": enabled})
    return {"maintenance": enabled, "activated_by": state["activated_by"], "activated_at": state["activated_at"]}

# Serve manifest.json
@app.get("/manifest.json")
async def get_manifest():
    return {
        "name": APP_NAME,
        "short_name": APP_NAME,
        "description": f"{APP_NAME} - Share and manage PDF scores",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#000000",
        "icons": [
            {"src": "/icon.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}

app.include_router(api)

# ----------------- Worker -----------------
def _extract_pages_sync(
    fpath_bytes: bytes,
    known_page_texts: Optional[List[str]] = None,
    known_page_records: Optional[List[Dict[str, Any]]] = None,
    timings: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Synchronous wrapper for extract_pages to run in thread pool."""
    return extract_pages(
        fpath_bytes,
        timings=timings,
        known_page_texts=known_page_texts,
        known_page_records=known_page_records,
    )


def _should_wait_for_gemini_quota(
    timings: Dict[str, Any],
    pending_pages: List[int],
    pages_text: List[str],
    page_map: List[int],
    original_total: int,
    completed_pages: List[int],
) -> bool:
    if not timings.get("gemini_quota_waiting"):
        return False
    extracted_page_numbers = {
        page_map[index]
        for index, text in enumerate(pages_text)
        if index < len(page_map) and text
    }
    processed_page_numbers = set(completed_pages) | extracted_page_numbers
    all_pages_processed = (
        not pending_pages
        and len(pages_text) == len(page_map)
        and set(range(1, original_total + 1)).issubset(processed_page_numbers)
    )
    return not all_pages_processed


async def process_pdf_job(job_id):
    async with _pdf_processing_semaphore:
        return await _process_pdf_job_locked(job_id)


async def _process_pdf_job_locked(job_id):
    job = await db.upload_jobs.find_one({"id": job_id})
    if not job: return

    if job.get("status") == _job_waiting_for_gemini_quota_status():
        logger.info("Gemini quota wait job resumed job_id=%s pdf_id=%s", job_id, job.get("pdf_id"))

    await db.upload_jobs.update_one({"id": job_id}, {"$set": {"status": "processing", "updated_at": iso_now()}})
    try:
        pdf = await db.pdfs.find_one({"id": job["pdf_id"]})
        fpath = Path(pdf["file_path"])
        if fpath.exists():
            pdf_bytes = fpath.read_bytes()
            
            # Log initial memory usage
            try:
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                logger.info("PDF.PROCESS_MEMORY rss_mb=%.1f stage=start pdf=%s", rss_mb, pdf["id"])
            except Exception:
                pass
            
            # Compress PDF in background if not already compressed
            if not pdf.get("compressed"):
                compress_start = time.perf_counter()
                compressed_bytes, was_compressed = await asyncio.to_thread(compress_pdf, pdf_bytes)
                compress_ms = (time.perf_counter() - compress_start) * 1000
                if was_compressed:
                    logger.info("PDF.COMPRESS_DONE pdf=%s original=%d compressed=%d ms=%.1f ratio=%.2f", 
                                pdf["id"], len(pdf_bytes), len(compressed_bytes), compress_ms, len(compressed_bytes) / len(pdf_bytes))
                    pdf_bytes = compressed_bytes
                    fpath.write_bytes(pdf_bytes)
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"compressed": True, "size": len(pdf_bytes), "updated_at": iso_now()}})
                else:
                    logger.info("PDF.COMPRESS_SKIP pdf=%s size=%d (no benefit) ms=%.1f", pdf["id"], len(pdf_bytes), compress_ms)
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"compressed": False, "updated_at": iso_now()}})
            
            with fitz.open(fpath) as source_doc:
                original_total = source_doc.page_count
                source_labels = source_doc.get_page_labels() or [str(page) for page in range(1, original_total + 1)]
                saved_records = await db.pdf_pages.find(
                    {"pdf_id": pdf["id"], "text": {"$ne": ""}},
                    {"_id": 0, "page": 1},
                ).to_list(10000)
                saved_pages = {
                    int(record["page"])
                    for record in saved_records
                    if isinstance(record.get("page"), int) and 1 <= record["page"] <= original_total
                }
                saved_pages.update(
                    int(page)
                    for page in (job.get("gemini_completed_pages") or [])
                    if isinstance(page, int) and 1 <= page <= original_total
                )
                pending_pages = [page for page in range(1, original_total + 1) if page not in saved_pages]
                logger.info(
                    "PDF.PROCESS_RESUME pdf=%s saved_pages=%s pending_pages=%s",
                    pdf["id"],
                    sorted(saved_pages),
                    pending_pages,
                )
                known_page_records = await db.pdf_pages.find(
                    {"text": {"$ne": ""}, "visual_signature": {"$exists": True}},
                    {"_id": 0, "text": 1, "visual_signature": 1},
                ).limit(200).to_list(200)
                known_page_texts = [page.get("text", "") for page in known_page_records if page.get("text")]
                failed_pages = []

                for page_num in pending_pages:
                    page_doc = fitz.open()
                    page_doc.insert_pdf(source_doc, from_page=page_num - 1, to_page=page_num - 1)
                    single_page_bytes = page_doc.tobytes()
                    page_doc.close()
                    timings: Dict[str, Any] = {"page_details": []}
                    pages_text, raw_texts, _, _, page_labels = await asyncio.to_thread(
                        _extract_pages_sync,
                        single_page_bytes,
                        known_page_texts,
                        known_page_records,
                        timings,
                    )
                    await _persist_gemini_daily_state()
                    if not pages_text:
                        raise RuntimeError(f"OCR extraction returned no page for pdf {pdf['id']} page={page_num}")
                    if timings.get("gemini_quota_waiting"):
                        remaining_pages = [page_num] + [page for page in pending_pages if page > page_num]
                        await db.upload_jobs.update_one(
                            {"id": job_id},
                            {"$set": {
                                "status": _job_waiting_for_gemini_quota_status(),
                                "gemini_quota_waiting": True,
                                "gemini_quota_page": page_num,
                                "gemini_pending_pages": remaining_pages,
                                "gemini_completed_pages": sorted(saved_pages),
                                "gemini_retry_after_seconds": timings.get("gemini_quota_retry_after"),
                                "updated_at": iso_now(),
                            }},
                        )
                        return

                    text = pages_text[0] if pages_text else ""
                    raw = raw_texts[0] if raw_texts else ""
                    page_detail = (timings.get("page_details") or [{}])[0]
                    normalized = normalize_pdf_text(text)
                    update_doc = {
                        "text": text,
                        "text_raw": raw,
                        "text_clean": text,
                        "text_normalized": normalized,
                        "page_label": source_labels[page_num - 1] if page_num <= len(source_labels) else str(page_num),
                        "content_signature": build_content_signature(text),
                        "visual_signature": page_detail.get("visual_signature"),
                        "ocr_provider": page_detail.get("ocr_provider", "native"),
                        **extract_page_metadata(normalized),
                    }
                    try:
                        result = await db.pdf_pages.update_one(
                            {"pdf_id": pdf["id"], "page": page_num},
                            {"$set": update_doc},
                            upsert=True,
                        )
                        if hasattr(result, "acknowledged") and result.acknowledged is False:
                            raise RuntimeError("Mongo update not acknowledged")
                    except Exception as exc:
                        logger.error("PDF.PAGE_WRITE_FAILED pdf=%s page=%d error=%s", pdf["id"], page_num, repr(exc))
                        logger.error("PDF.PAGES_WRITE_ERROR pdf=%s page=%d error=%s", pdf["id"], page_num, repr(exc))
                        failed_pages.append(page_num)
                        del pages_text, raw_texts, page_labels, page_detail, timings, single_page_bytes, text, raw, update_doc
                        gc.collect()
                        continue

                    saved_pages.add(page_num)
                    logger.info("PDF.PAGE_WRITE_OK pdf=%s page=%d", pdf["id"], page_num)
                    await db.upload_jobs.update_one(
                        {"id": job_id},
                        {"$set": {
                            "gemini_completed_pages": sorted(saved_pages),
                            "gemini_pending_pages": [page for page in pending_pages if page not in saved_pages],
                            "updated_at": iso_now(),
                        }},
                    )
                    del pages_text, raw_texts, page_labels, page_detail, timings, single_page_bytes, text, raw, update_doc
                    gc.collect()

                if failed_pages:
                    error = f"Mongo page write failed for pdf {pdf['id']} pages={failed_pages}"
                    await db.upload_jobs.update_one(
                        {"id": job_id},
                        {"$set": {"status": "failed", "error": error, "updated_at": iso_now()}},
                    )
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"status": "failed", "error": error, "updated_at": iso_now()}})
                    return

                expected_pages = list(range(1, original_total + 1))
                ok, verified_pages, missing_pages, unexpected_pages, _ = await _verify_expected_pdf_pages(pdf["id"], expected_pages)
                logger.info("PDF.PAGES_WRITE_RESULT pdf=%s expected=%s saved=%s missing=%s unexpected=%s", pdf["id"], expected_pages, verified_pages, missing_pages, unexpected_pages)
                if not ok:
                    logger.error("PDF.PAGE_WRITE_FAILED pdf=%s page=%s", pdf["id"], missing_pages or unexpected_pages)
                    await db.upload_jobs.update_one(
                        {"id": job_id},
                        {"$set": {"status": "failed", "error": f"Mongo page persistence verification failed for pdf {pdf['id']}", "updated_at": iso_now()}},
                    )
                    await db.pdfs.update_one(
                        {"id": pdf["id"]},
                        {"$set": {"status": "failed", "error": f"Mongo page persistence verification failed for pdf {pdf['id']}", "updated_at": iso_now()}},
                    )
                    return

                total = original_total
                page_labels = source_labels
            logger.info("PDF %s indexing complete", pdf["id"])
            await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"status": "ready", "pages": total, "page_labels": page_labels}})
            async def backup_drive():
                try:
                    master = await get_master_drive()
                    if not master or not master.get("refresh_token") or pdf.get("drive_file_id"):
                        return
                    folder_id = await asyncio.to_thread(gi.ensure_master_root, master["refresh_token"])
                    drive_id = await asyncio.to_thread(gi.upload_to_drive, master["refresh_token"], folder_id, pdf["filename"], pdf_bytes)
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {
                        "drive_file_id": drive_id,
                        "drive_owner": "master",
                        "storage_type": "drive",
                        "synced_at": iso_now(),
                        "drive_backup_error": "",
                    }})
                except Exception as exc:
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"drive_backup_error": str(exc)}})
            safe_create_task(backup_drive())
            await db.upload_jobs.update_one({"id": job_id}, {"$set": {"status": "completed", "updated_at": iso_now()}})
            return

            # Legacy batch implementation retained below only as historical context.
            try:
                saved_records = await db.pdf_pages.find(
                    {"pdf_id": pdf["id"], "text": {"$ne": ""}},
                    {"_id": 0, "page": 1},
                ).to_list(10000)
                saved_pages_set = {int(record.get("page")) for record in saved_records if isinstance(record.get("page"), int)}
            except Exception as exc:
                logger.warning("PDF.PROCESS_RESUME_CHECK_FAILED pdf=%s error=%s", pdf["id"], repr(exc))
                saved_pages_set = set()
            
            resume_completed_pages = job.get("gemini_completed_pages") or []
            resume_pending_pages = job.get("gemini_pending_pages") or []
            resume_quota_page = job.get("gemini_quota_page")
            
            # Merge with saved pages (in case of previous crashes)
            if saved_pages_set:
                resume_completed_pages = list(set(resume_completed_pages) | saved_pages_set)
                logger.info("PDF.PROCESS_RESUME pdf=%s saved_pages=%d pending_pages=%d", pdf["id"], len(saved_pages_set), len(resume_pending_pages))
            
            original_total = fitz.open(fpath).page_count if fpath.exists() else 0
            completed_pages, pending_pages = _gemini_quota_resume_ranges(
                total_pages=original_total,
                quota_page=resume_quota_page,
                completed_pages=resume_completed_pages,
                pending_pages=resume_pending_pages,
            )
            active_page_numbers = pending_pages if pending_pages else None
            active_pdf_bytes = pdf_bytes
            if active_page_numbers:
                with fitz.open(fpath) as doc:
                    subset = fitz.open()
                    for page_num in active_page_numbers:
                        page_index = max(0, min(page_num - 1, doc.page_count - 1))
                        subset.insert_pdf(doc, from_page=page_index, to_page=page_index)
                    active_pdf_bytes = subset.tobytes()
                    subset.close()
            known_page_records = await db.pdf_pages.find(
                {"text": {"$ne": ""}, "visual_signature": {"$exists": True}},
                {"_id": 0, "text": 1, "visual_signature": 1},
            ).limit(400).to_list(400)
            known_page_texts = [page.get("text", "") for page in known_page_records if page.get("text")]
            logger.info(
                "VISUAL_REUSE_CANDIDATES pdf=%s loaded=%d texts=%d resume_pages=%s",
                pdf["id"],
                len(known_page_records),
                len(known_page_texts),
                active_page_numbers,
            )
            timings: Dict[str, Any] = {"page_details": []}
            pages_text, raw_texts, total, used_ocr, page_labels = await asyncio.to_thread(
                _extract_pages_sync,
                active_pdf_bytes,
                known_page_texts,
                known_page_records,
                timings,
            )
            
            # Log memory after OCR extraction
            try:
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                logger.info("PDF.PROCESS_MEMORY rss_mb=%.1f stage=after_extract pdf=%s", rss_mb, pdf["id"])
            except Exception:
                pass
            
            if active_page_numbers:
                page_map = active_page_numbers
            else:
                page_map = list(range(1, total + 1))
            logger.info(f"PDF extraction for {pdf['id']}: {total} pages, OCR used: {used_ocr}, resume_pending={pending_pages}")
            if _should_wait_for_gemini_quota(
                timings,
                pending_pages,
                pages_text,
                page_map,
                original_total,
                completed_pages,
            ):
                quota_page = timings.get("gemini_quota_page")
                completed_pages, pending_pages = _gemini_quota_resume_ranges(
                    total_pages=total,
                    quota_page=quota_page,
                    completed_pages=completed_pages,
                    pending_pages=pending_pages,
                )
                scatter = {
                    "status": _job_waiting_for_gemini_quota_status(),
                    "gemini_quota_waiting": True,
                    "gemini_quota_waiting_since": iso_now(),
                    "gemini_retry_after_seconds": timings.get("gemini_quota_retry_after"),
                    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
                    "gemini_pending_pages": pending_pages,
                    "gemini_completed_pages": completed_pages,
                    "gemini_quota_page": quota_page,
                    "updated_at": iso_now(),
                    "error": "Gemini quota exhausted; waiting for quota reset",
                    "logger": "Gemini quota exhausted",
                }
                logger.warning(
                    "Gemini quota exhausted document_id=%s pending_pages=%s completed_pages=%s status=%s",
                    pdf["id"],
                    pending_pages,
                    completed_pages,
                    _job_waiting_for_gemini_quota_status(),
                )
                await db.upload_jobs.update_one({"id": job_id}, {"$set": scatter})
                return
            page_details = timings.get("page_details", [])
            logger.info(
                "VISUAL_REUSE_RESULT pdf=%s pages=%d used_ocr=%s",
                pdf["id"],
                len(page_details),
                used_ocr,
            )

            page_write_tasks = []
            for i, txt in enumerate(pages_text):
                page_num = page_map[i]
                if page_num in completed_pages:
                    continue
                raw = raw_texts[i] if i < len(raw_texts) else ""
                normalized = normalize_pdf_text(txt)
                metadata = extract_page_metadata(normalized)
                logger.info(f"  Page {page_num}: {len(txt)} chars, preview: {txt[:80] if txt else '(empty)'}")
                content_signature = build_content_signature(txt)
                visual_signature = page_details[i].get("visual_signature") if i < len(page_details) else None
                if i < len(page_details):
                    logger.info(
                        "VISUAL_REUSE_PAGE pdf=%s page=%d reason=%s reused_source=%s score=%s visual=%s",
                        pdf["id"],
                        page_num,
                        page_details[i].get("reason"),
                        page_details[i].get("reused_text_source"),
                        page_details[i].get("reused_text_similarity"),
                        bool(visual_signature),
                    )
                update_doc = {
                    "text": txt,
                    "text_raw": raw,
                    "text_clean": txt,
                    "text_normalized": normalized,
                    "page_label": page_labels[i],
                    "content_signature": content_signature,
                    "visual_signature": visual_signature,
                    "ocr_provider": page_details[i].get("ocr_provider", "native") if i < len(page_details) else "native",
                    **metadata,
                }
                page_write_tasks.append(
                    (
                        page_num,
                        db.pdf_pages.update_one(
                            {"pdf_id": pdf["id"], "page": page_num},
                            {"$set": update_doc},
                            upsert=True,
                        ),
                    )
                )

            expected_pages = sorted({
                int(page_num)
                for page_num in (page_map or list(range(1, total + 1)))
                if page_num not in completed_pages
            })
            if expected_pages:
                logger.info("PDF.PAGES_WRITE_START pdf=%s expected_pages=%s", pdf["id"], expected_pages)
                if page_write_tasks:
                    results = await asyncio.gather(
                        *(update_task for _, update_task in page_write_tasks),
                        return_exceptions=True,
                    )
                    failed_writes = []
                    successful_pages = []
                    for (page_num, _), result in zip(page_write_tasks, results):
                        if isinstance(result, Exception):
                            failed_writes.append((page_num, result))
                            logger.error(
                                "PDF.PAGES_WRITE_ERROR pdf=%s page=%s operation=pdf_pages.update_one error=%s",
                                pdf["id"],
                                page_num,
                                repr(result),
                            )
                        elif hasattr(result, "acknowledged") and result.acknowledged is False:
                            failed_writes.append((page_num, RuntimeError("Mongo update not acknowledged")))
                            logger.error(
                                "PDF.PAGES_WRITE_ERROR pdf=%s page=%s operation=pdf_pages.update_one error=%s",
                                pdf["id"],
                                page_num,
                                "Mongo update not acknowledged",
                            )
                        else:
                            successful_pages.append(page_num)
                            logger.info("PDF.PAGE_WRITE_OK pdf=%s page=%d", pdf["id"], page_num)
                    
                    # Free memory after page writes and garbage collection
                    del results
                    gc.collect()
                    try:
                        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                        logger.info("PDF.PROCESS_MEMORY rss_mb=%.1f stage=after_page_writes pdf=%s successful_pages=%d", rss_mb, pdf["id"], len(successful_pages))
                    except Exception:
                        pass
                    
                    if failed_writes:
                        logger.error(
                            "PDF.PAGES_WRITE_FAILED pdf=%s failed_pages=%s total_failed=%d",
                            pdf["id"],
                            [page_num for page_num, _ in failed_writes],
                            len(failed_writes),
                        )
                        await db.upload_jobs.update_one(
                            {"id": job_id},
                            {"$set": {"status": "failed", "error": f"Mongo page write failed for pdf {pdf['id']}", "updated_at": iso_now()}},
                        )
                        await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"status": "failed", "error": f"Mongo page write failed for pdf {pdf['id']}", "updated_at": iso_now()}})
                        return

                ok, saved_pages, missing_pages, unexpected_pages, _ = await _verify_expected_pdf_pages(pdf["id"], expected_pages)
                logger.info("PDF.PAGES_WRITE_RESULT pdf=%s expected=%s saved=%s missing=%s unexpected=%s", pdf["id"], expected_pages, saved_pages, missing_pages, unexpected_pages)
                if not ok:
                    logger.error(
                        "PDF.PAGES_WRITE_FAILED pdf=%s expected=%s saved=%s missing=%s unexpected=%s",
                        pdf["id"],
                        expected_pages,
                        saved_pages,
                        missing_pages,
                        unexpected_pages,
                    )
                    await db.upload_jobs.update_one(
                        {"id": job_id},
                        {"$set": {"status": "failed", "error": f"Mongo page persistence verification failed for pdf {pdf['id']} missing_pages={missing_pages} unexpected_pages={unexpected_pages}", "updated_at": iso_now()}},
                    )
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"status": "failed", "error": f"Mongo page persistence verification failed for pdf {pdf['id']} missing_pages={missing_pages} unexpected_pages={unexpected_pages}", "updated_at": iso_now()}})
                    return

            logger.info(f"PDF {pdf['id']} indexing complete")
            await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"status": "ready", "pages": total, "page_labels": page_labels}})
            
            # Final memory tracking
            try:
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                logger.info("PDF.PROCESS_MEMORY rss_mb=%.1f stage=complete pdf=%s", rss_mb, pdf["id"])
            except Exception:
                pass
            async def backup_drive():
                try:
                    master = await get_master_drive()
                    if not master or not master.get("refresh_token"):
                        message = "Drive backup skipped: master Drive non configurato o token mancante"
                        await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"drive_backup_error": message}})
                        await log_event("pdf.drive_error", message, user_id=pdf.get("owner_id"), level="warning", meta={"pdf_id": pdf["id"], "stage": "drive_backup", "reason": "no_master_token"})
                        return

                    if pdf.get("drive_file_id"):
                        await log_event("pdf.drive_backup", f"Drive backup skipped: PDF già salvato in Drive: {pdf['id']}", user_id=pdf.get("owner_id"), meta={"pdf_id": pdf["id"], "drive_file_id": pdf.get("drive_file_id"), "reason": "already_backed_up"})
                        return

                    folder_id = await asyncio.to_thread(gi.ensure_master_root, master["refresh_token"])
                    drive_id = await asyncio.to_thread(gi.upload_to_drive, master["refresh_token"], folder_id, pdf["filename"], pdf_bytes)
                    synced_at = iso_now()
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {
                        "drive_file_id": drive_id,
                        "drive_owner": "master",
                        "storage_type": "drive",
                        "synced_at": synced_at,
                        "drive_backup_error": "",
                    }})
                    await log_event("pdf.drive_backup", f"PDF caricato su Drive master: {pdf['id']}", user_id=pdf.get("owner_id"), meta={"pdf_id": pdf["id"], "drive_file_id": drive_id, "folder_id": folder_id})
                except Exception as e:
                    await db.pdfs.update_one({"id": pdf["id"]}, {"$set": {"drive_backup_error": str(e)}})
                    await log_event("pdf.drive_error", f"Drive backup fallito: {e}", user_id=pdf.get("owner_id"), level="error", meta={"pdf_id": pdf["id"], "stage": "drive_backup"})
            safe_create_task(backup_drive())
            await db.upload_jobs.update_one({"id": job_id}, {"$set": {"status": "completed", "updated_at": iso_now()}})
    except Exception as e:
        await db.upload_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": str(e), "updated_at": iso_now()}})
