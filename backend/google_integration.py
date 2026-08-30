"""Google OAuth + Drive integration."""
import os
import io
import logging
from typing import Optional, Dict, Any
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]


def _client():
    """Read env lazily so that .env loaded by server.py is honored."""
    cid = os.environ.get("GOOGLE_CLIENT_ID", CLIENT_ID)
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    return cid, csec


def google_configured() -> bool:
    cid, csec = _client()
    return bool(cid and csec)


def build_auth_url(redirect_uri: str, state: str) -> str:
    """Construct the Google OAuth authorization URL."""
    from urllib.parse import urlencode
    cid, _ = _client()
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


async def exchange_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens."""
    cid, csec = _client()
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.post(TOKEN_URI, data={
            "code": code,
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if r.status_code != 200:
        logger.error(f"Google token exchange failed: {r.status_code} {r.text}")
        raise RuntimeError(f"Token exchange failed: {r.status_code} {r.text[:200]}")
    return r.json()


async def fetch_userinfo(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as cli:
        r = await cli.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise RuntimeError(f"userinfo failed: {r.status_code}")
    return r.json()


def _build_credentials(refresh_token: str, access_token: Optional[str] = None) -> Credentials:
    cid, csec = _client()
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=cid,
        client_secret=csec,
        scopes=SCOPES,
    )


def _drive_service(refresh_token: str):
    creds = _build_credentials(refresh_token)
    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError as e:
            logger.error("Drive auth broken - disable fallback")
            raise
        except Exception as e:
            logger.error(f"Drive credentials refresh failed: {e}")
            raise
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _access_token(refresh_token: str) -> str:
    creds = _build_credentials(refresh_token)
    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError as e:
            logger.error("Drive auth broken - disable fallback")
            raise
        except Exception as e:
            logger.error(f"Drive credentials refresh failed: {e}")
            raise
    if not creds.token:
        raise RuntimeError("Unable to refresh Google access token")
    return creds.token


def create_resumable_upload_session(refresh_token: str, folder_id: str, filename: str, size: int) -> str:
    """Create a Drive resumable-upload session URL for direct browser upload."""
    token = _access_token(refresh_token)
    metadata = {"name": filename, "parents": [folder_id]}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "application/pdf",
    }
    if size and size > 0:
        headers["X-Upload-Content-Length"] = str(size)
    with httpx.Client(timeout=20) as cli:
        r = cli.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id",
            json=metadata,
            headers=headers,
        )
    if r.status_code not in (200, 201):
        logger.error(f"Drive resumable session failed: {r.status_code} {r.text[:300]}")
        raise RuntimeError(f"Drive upload session failed: {r.status_code}")
    location = r.headers.get("Location")
    if not location:
        raise RuntimeError("Drive upload session missing Location header")
    return location


def ensure_master_root(refresh_token: str) -> str:
    """Get or create top-level 'ScoreLib' folder in master drive root."""
    svc = _drive_service(refresh_token)
    q = "mimeType='application/vnd.google-apps.folder' and name='ScoreLib' and trashed=false and 'root' in parents"
    res = svc.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    if res.get("files"):
        return res["files"][0]["id"]
    meta = {"name": "ScoreLib", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]}
    return svc.files().create(body=meta, fields="id").execute()["id"]


def ensure_subfolder(refresh_token: str, parent_id: str, name: str) -> str:
    """Get or create subfolder by name under parent_id."""
    svc = _drive_service(refresh_token)
    safe = name.replace("'", "")
    q = f"mimeType='application/vnd.google-apps.folder' and name='{safe}' and trashed=false and '{parent_id}' in parents"
    res = svc.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    if res.get("files"):
        return res["files"][0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    return svc.files().create(body=meta, fields="id").execute()["id"]


def ensure_user_folder(refresh_token: str, user_id: str) -> str:
    """Get or create /ScoreLib/{user_id} folder in user's Drive. Returns folder ID."""
    svc = _drive_service(refresh_token)
    # find or create root "ScoreLib"
    q = "mimeType='application/vnd.google-apps.folder' and name='ScoreLib' and trashed=false and 'root' in parents"
    res = svc.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    if res.get("files"):
        root_id = res["files"][0]["id"]
    else:
        meta = {"name": "ScoreLib", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]}
        root_id = svc.files().create(body=meta, fields="id").execute()["id"]
    # find or create user folder
    q2 = f"mimeType='application/vnd.google-apps.folder' and name='{user_id}' and trashed=false and '{root_id}' in parents"
    res2 = svc.files().list(q=q2, fields="files(id,name)", spaces="drive").execute()
    if res2.get("files"):
        return res2["files"][0]["id"]
    meta2 = {"name": user_id, "mimeType": "application/vnd.google-apps.folder", "parents": [root_id]}
    return svc.files().create(body=meta2, fields="id").execute()["id"]


def upload_to_drive(refresh_token: str, folder_id: str, filename: str, data: bytes) -> str:
    """Upload PDF bytes to Drive folder. Returns Drive file ID."""
    svc = _drive_service(refresh_token)
    meta = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/pdf", resumable=False)
    f = svc.files().create(body=meta, media_body=media, fields="id").execute()
    return f["id"]


def download_from_drive(refresh_token: str, file_id: str) -> bytes:
    """Download a Drive file by ID. Returns bytes."""
    svc = _drive_service(refresh_token)
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def delete_from_drive(refresh_token: str, file_id: str) -> bool:
    try:
        svc = _drive_service(refresh_token)
        svc.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        logger.warning(f"Drive delete failed for {file_id}: {e}")
        return False


def list_drive_files(refresh_token: str, folder_id: str) -> list:
    svc = _drive_service(refresh_token)
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,size,modifiedTime)",
        pageSize=1000,
    ).execute()
    return res.get("files", [])
