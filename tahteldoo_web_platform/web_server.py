import os
import sys
import re
import time
import json
import uuid
import secrets
import hashlib
import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import pickle
import logging

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
import uvicorn

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Project Modules
from database.db import db
from core.config import Config
from core.logger import logger
from services.ai_service import ai_service
from services.article_formatter import ArticleFormatter
from services.blogger_service import blogger_service
from services.whatsapp_service import (
    whatsapp_service,
    clean_egyptian_phone,
    extract_preferred_whatsapp_phone,
    extract_all_egyptian_phones
)
from services.central_sync_service import central_sync_service
from services.image_service import image_service
from telegram_bot.bot_controller import bot_controller

# Create FastAPI App
app = FastAPI(
    title="جريدة تحت الضوء الإخبارية — المنظومة السحابية v4.0",
    description="Enterprise AI Newsroom CMS & Central API Hub",
    version="4.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage directories
UPLOAD_DIR = PROJECT_ROOT / "storage" / "images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory Token Session Store
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_EXPIRY_HOURS = 72

# OAuth PKCE Code Verifier Store
OAUTH_FLOW_CACHE: Dict[str, str] = {}

# WebSocket Log Connections Pool
WS_CLIENTS: List[WebSocket] = []
WS_LOCK = asyncio.Lock()
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None

def broadcast_ws_event(event_dict: dict):
    """Safely broadcasts a JSON event dictionary to all connected WebSocket clients from any thread or sync code."""
    if not WS_CLIENTS:
        return
    payload = json.dumps(event_dict, ensure_ascii=False)
    try:
        loop = MAIN_LOOP
        if not loop or not loop.is_running():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast_to_ws_clients(payload), loop)
    except Exception:
        pass

async def _broadcast_to_ws_clients(payload: str):
    for ws in list(WS_CLIENTS):
        try:
            await ws.send_text(payload)
        except Exception:
            if ws in WS_CLIENTS:
                WS_CLIENTS.remove(ws)

def broadcast_publish_step(percent: int, text: str, stage: str = "PUBLISH"):
    """Emits a live publishing progress event to connected frontends."""
    broadcast_ws_event({
        "type": "publish_step",
        "percent": percent,
        "text": text,
        "stage": stage,
        "time": time.time()
    })

class WebSocketLogForwarder(logging.Handler):
    """Intercepts all backend Python logging events and streams them live to WebSockets."""
    def emit(self, record):
        try:
            msg = record.getMessage()
            broadcast_ws_event({
                "type": "log",
                "level": record.levelname,
                "module": record.name,
                "message": msg,
                "created_at": datetime.now().isoformat()
            })
        except Exception:
            pass

# Attach the live log streamer to the root publisher logger
ws_log_handler = WebSocketLogForwarder()
ws_log_handler.setLevel(logging.INFO)
logger.addHandler(ws_log_handler)

@app.on_event("startup")
async def on_app_startup():
    global MAIN_LOOP
    try:
        MAIN_LOOP = asyncio.get_running_loop()
    except Exception:
        pass
    # Auto-start Telegram Bot in background daemon thread
    try:
        threading.Thread(target=bot_controller.start, kwargs={"timeout": 20.0}, daemon=True).start()
    except Exception as be:
        logger.warning(f"Could not auto-start telegram bot on startup: {be}")


# =============================================================
# AUTHENTICATION & SECURITY UTILS
# =============================================================

def create_session_token(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    ACTIVE_SESSIONS[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "email": user.get("email", ""),
        "avatar": user.get("google_avatar", ""),
        "expires_at": datetime.now() + timedelta(hours=SESSION_EXPIRY_HOURS)
    }
    return token

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="يتطلب تسجيل الدخول للوصول لهذه العملية")
    
    token = authorization.replace("Bearer ", "").strip()
    session = ACTIVE_SESSIONS.get(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="الجلسة منتهية أو غير صالحة، يرجى تسجيل الدخول مجدداً")
    
    if datetime.now() > session["expires_at"]:
        ACTIVE_SESSIONS.pop(token, None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="انتهت صلاحية الجلسة، يرجى إعادة تسجيل الدخول")
    
    uid = session.get("user_id") or session.get("id")
    if uid:
        try:
            fresh = db.get_user_by_id(uid)
            if fresh:
                session["role"] = fresh.get("role", session.get("role"))
                session["full_name"] = fresh.get("full_name", session.get("full_name"))
        except Exception:
            pass

    return session

def require_role(allowed_roles: List[str]):
    def role_checker(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ليس لديك الصلاحيات الكافية لتنفيذ هذا الإجراء")
        return user
    return role_checker


# =============================================================
# PYDANTIC SCHEMAS
# =============================================================

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreateRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "journalist"
    email: Optional[str] = ""

class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None
    password: Optional[str] = None

class RoleUpdateRequest(BaseModel):
    role: str

class VerifyActivationRequest(BaseModel):
    code: str

class CreateActivationRequest(BaseModel):
    name: str
    phone: str
    role: str = "journalist"

class AIGenerateRequest(BaseModel):
    raw_notes: str

class UserAIKeyRequest(BaseModel):
    api_key: str

class ArticleSaveRequest(BaseModel):
    id: Optional[int] = None
    title: str
    focus_keyword: Optional[str] = ""
    meta_description: Optional[str] = ""
    slug: Optional[str] = ""
    labels: Optional[str] = ""
    client_name: Optional[str] = ""
    client_phone: Optional[str] = ""
    raw_notes: Optional[str] = ""
    raw_ai_json: Optional[str] = ""
    final_html: Optional[str] = ""
    local_image_path: Optional[str] = ""
    remote_image_url: Optional[str] = ""
    entity_type: Optional[str] = "plural"
    is_draft: Optional[bool] = False

class ArticlePublishRequest(BaseModel):
    article_id: Optional[int] = None
    title: str
    slug: Optional[str] = ""
    labels: Optional[str] = ""
    final_html: str
    local_image_path: Optional[str] = ""
    client_name: Optional[str] = ""
    client_phone: Optional[str] = ""
    entity_type: Optional[str] = "plural"
    is_draft: Optional[bool] = False

class DirectPublishRequest(BaseModel):
    raw_notes: str
    image_url: Optional[str] = ""
    local_image_path: Optional[str] = ""
    entity_type: Optional[str] = "plural"

class ReporterRegisterRequest(BaseModel):
    name: str
    telegram_id: str
    role: Optional[str] = "صحفي لدى"

class ReporterSaveRequest(BaseModel):
    telegram_id: str
    name: str
    role: Optional[str] = "صحفي لدى"
    api_key: Optional[str] = None

class BotBroadcastRequest(BaseModel):
    message: str

class ManualClientRegisterRequest(BaseModel):
    phone: str
    client_name: Optional[str] = ""
    contact_method: Optional[str] = "تواصل خارجي"
    notes: Optional[str] = ""

class CreateAccountingTransactionRequest(BaseModel):
    article_id: Optional[int] = None
    article_title: str
    article_url: Optional[str] = ""
    client_name: Optional[str] = ""
    client_phone: str
    amount_paid: float
    payment_method: str = "vodafone_cash"
    receipt_image_path: Optional[str] = ""
    notes: Optional[str] = ""

class UpdateFinancialSettingsRequest(BaseModel):
    official_article_price: Optional[float] = None
    cut_certified_journalist: Optional[float] = None
    cut_premium_editor: Optional[float] = None

class SetUserCustomCutRequest(BaseModel):
    user_id: int
    custom_cut: Optional[float] = None

class SettleTransactionsRequest(BaseModel):
    user_id: int

class CentralRegisterArticleRequest(BaseModel):
    client_name: Optional[str] = ""
    client_phone: Optional[str] = ""
    title: str
    slug: Optional[str] = ""
    labels: Optional[str] = ""
    post_url: Optional[str] = ""
    post_id: Optional[str] = ""
    reporter_telegram_id: Optional[str] = ""
    blogger_status: Optional[str] = "PUBLISHED"
    final_html: Optional[str] = ""


# =============================================================
# AUTHENTICATION ROUTER (GOOGLE OAUTH & CREDENTIALS)
# =============================================================

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/blogger"
]

@app.post("/api/auth/activation/verify")
def verify_activation_code_endpoint(payload: VerifyActivationRequest, response: Response):
    """
    Unified journalist login & onboarding gatekeeper:
    - If code is already linked/activated: logs in directly and issues JWT + 1-year cookie!
    - If code is new/pending: validates identity and prompts for first-time Google linking.
    """
    res = db.verify_activation_code(payload.code)
    if not res.get("valid"):
        raise HTTPException(status_code=400, detail=res.get("message", "كود الصحفي غير صالح"))
    
    if res.get("is_already_active"):
        # PERMANENT CODE RE-LOGIN: User already completed Google linking previously!
        email = res.get("user_email")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email.strip().lower(),))
            user_row = cursor.fetchone()
        
        if not user_row:
            # Fallback: create or link
            user_row = db.get_or_create_google_user(
                email=email,
                full_name=res.get("journalist_name") or "صحفي معتمد",
                role=res.get("role") or "journalist",
                phone=res.get("journalist_phone") or ""
            )
        else:
            user_row = dict(user_row)
            code_role = res.get("role")
            if code_role == "admin" and user_row.get("role") != "admin":
                with db.get_connection() as conn:
                    conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_row["id"],))
                    conn.commit()
                user_row["role"] = "admin"
            
        if not user_row.get("is_active", 1):
            raise HTTPException(status_code=403, detail="هذا الحساب معطل حالياً، يرجى مراجعة إدارة الجريدة")
            
        user = dict(user_row)
        user.pop("password_hash", None)
        token = create_session_token(user)
        
        # Set persistent 1-year cookie
        response.set_cookie(key="td_auth_token", value=token, max_age=86400*365, httponly=False, samesite="lax")
        
        db.log_system(
            "INFO", "Auth",
            f"تسجيل دخول بالكود الصحفي الدائم: {user['full_name']} ({user['role']}) - [{payload.code}]",
            user_id=str(user["id"]),
            user_name=user["full_name"]
        )
        
        return {
            "success": True,
            "action": "login",
            "token": token,
            "user": user,
            "message": f"مرحباً بك مجدداً، {user['full_name']} ✨"
        }
    else:
        # FIRST-TIME ONBOARDING: Show journalist details & prompt Google linking
        return {
            "success": True,
            "action": "first_time",
            "journalist": res
        }

@app.get("/api/auth/google/login")
def google_oauth_login(request: Request, activation_code: Optional[str] = Query(None)):
    """Initiates Google OAuth flow for journalist authentication."""
    if not Config.CREDENTIALS_FILE.exists():
        raise HTTPException(status_code=500, detail="ملف credentials.json غير موجود في السيرفر")
    
    if activation_code and activation_code.strip():
        v = db.verify_activation_code(activation_code)
        if not v.get("valid"):
            raise HTTPException(status_code=400, detail=v.get("message", "كود التفعيل غير صالح"))

    host = request.headers.get("host", f"localhost:{getattr(Config, 'CENTRAL_HUB_PORT', 8000)}")
    scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else request.url.scheme or "http"
    redirect_uri = f"{scheme}://{host}/api/auth/google/callback"
    
    flow = Flow.from_client_secrets_file(
        str(Config.CREDENTIALS_FILE),
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    
    # Store PKCE code_verifier to match during token exchange
    if flow.code_verifier:
        OAUTH_FLOW_CACHE[state] = flow.code_verifier
        OAUTH_FLOW_CACHE["_latest"] = flow.code_verifier
        if activation_code and activation_code.strip():
            clean_c = activation_code.strip().upper()
            OAUTH_FLOW_CACHE[state + "_code"] = clean_c
            OAUTH_FLOW_CACHE["_latest_code"] = clean_c
        
    return JSONResponse({"success": True, "auth_url": auth_url})

@app.get("/api/auth/google/callback")
def google_oauth_callback(request: Request, code: str = Query(...), state: Optional[str] = Query(None)):
    """
    Handles Google OAuth redirect callback:
    - Exchanges authorization code for credentials with PKCE code_verifier
    - Fetches Google profile (Email, Name, Avatar)
    - Enforces journalist activation code for new accounts
    - Saves personal Blogger token for this journalist
    - Registers/updates user in database
    - Issues session token and redirects to frontend dashboard
    """
    try:
        host = request.headers.get("host", f"localhost:{getattr(Config, 'CENTRAL_HUB_PORT', 8000)}")
        scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else request.url.scheme or "http"
        redirect_uri = f"{scheme}://{host}/api/auth/google/callback"
        
        flow = Flow.from_client_secrets_file(
            str(Config.CREDENTIALS_FILE),
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
            state=state
        )
        
        # Retrieve the PKCE code_verifier generated during authorization
        code_verifier = None
        if state and state in OAUTH_FLOW_CACHE:
            code_verifier = OAUTH_FLOW_CACHE.pop(state)
        elif "_latest" in OAUTH_FLOW_CACHE:
            code_verifier = OAUTH_FLOW_CACHE.get("_latest")
            
        act_code = None
        if state and (state + "_code") in OAUTH_FLOW_CACHE:
            act_code = OAUTH_FLOW_CACHE.pop(state + "_code")
        elif "_latest_code" in OAUTH_FLOW_CACHE:
            act_code = OAUTH_FLOW_CACHE.get("_latest_code")

        is_blogger_link = False
        if state and (state + "_is_blogger_link") in OAUTH_FLOW_CACHE:
            is_blogger_link = bool(OAUTH_FLOW_CACHE.pop(state + "_is_blogger_link"))
        elif "_latest_is_blogger_link" in OAUTH_FLOW_CACHE:
            is_blogger_link = bool(OAUTH_FLOW_CACHE.pop("_latest_is_blogger_link", False))
            
        logger.info(f"OAuth Callback: state={state}, verifier_found={bool(code_verifier)}, act_code={act_code}, is_blogger_link={is_blogger_link}")
        
        if code_verifier:
            flow.code_verifier = code_verifier
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
            
        creds = flow.credentials
        
        # 1. Fetch user identity from Google
        user_info_service = build("oauth2", "v2", credentials=creds)
        user_info = user_info_service.userinfo().get().execute()
        email = user_info.get("email", "").strip().lower()
        full_name = user_info.get("name", "") or email.split("@")[0]
        avatar = user_info.get("picture", "")
        
        # Check existing user in database
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            existing_user = cursor.fetchone()

        assigned_role = "journalist"
        assigned_phone = ""
        assigned_name = full_name

        if not existing_user:
            if is_blogger_link:
                # Linking Google account from Settings: inherit admin or active user privileges
                cookie_token = request.cookies.get("td_auth_token")
                sess = ACTIVE_SESSIONS.get(cookie_token) if cookie_token else None
                assigned_role = sess.get("role", "admin") if sess else "admin"
                assigned_name = full_name
            elif not act_code:
                # New user without activation code: reject
                return HTMLResponse(content=f"""
                <!DOCTYPE html>
                <html lang="ar" dir="rtl">
                <head><meta charset="utf-8"><title>تنبيه: حساب غير مصرح</title></head>
                <body style="background: #090D16; color: #F3F4F6; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0;">
                    <div style="max-width: 500px; width: 90%; background: #121826; border: 1px solid #EF4444; border-radius: 16px; padding: 36px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.8);">
                        <div style="font-size: 48px; margin-bottom: 14px;">⛔</div>
                        <h2 style="color: #EF4444; margin: 0 0 12px 0;">عذراً! هذا الحساب غير مفعل في الجريدة</h2>
                        <p style="color: #94A3B8; font-size: 14px; line-height: 1.6; margin: 0 0 16px 0;">
                            البريد الإلكتروني <strong>({email})</strong> غير مسجل في ملفات الصحفيين المعتمدين لدى المنظومة.
                        </p>
                        <div style="background: rgba(245, 158, 11, 0.1); border: 1px dashed #F59E0B; border-radius: 8px; padding: 14px; color: #F59E0B; font-size: 13px; line-height: 1.5; margin-bottom: 24px;">
                            💡 للانضمام إلى فريق الجريدة: يرجى التواصل مع رئيس التحرير للحصول على <strong>كود التفعيل الصحفي</strong> الخاص بك ثم إدخاله في صفحة البداية.
                        </div>
                        <a href="/" style="display: block; width: 100%; box-sizing: border-box; padding: 12px; background: #F59E0B; color: #090D16; border-radius: 8px; font-weight: bold; text-decoration: none;">العودة لصفحة التفعيل</a>
                    </div>
                </body>
                </html>
                """, status_code=403)

            # Validate and burn the activation code
            code_info = db.verify_activation_code(act_code)
            if not code_info.get("valid"):
                return HTMLResponse(content=f"""
                <body style="background: #090D16; color: #EF4444; font-family: sans-serif; text-align: center; padding-top: 100px;" dir="rtl">
                    <h2>❌ فشل تفعيل الحساب الصحفي</h2>
                    <p>{code_info.get('message', 'كود التفعيل غير صالح')}</p>
                    <a href="/" style="color: #F59E0B;">العودة لصفحة التفعيل</a>
                </body>
                """, status_code=400)

            assigned_role = code_info.get("role", "journalist")
            assigned_phone = code_info.get("journalist_phone", "")
            assigned_name = code_info.get("journalist_name", full_name)
            db.consume_activation_code(act_code, email)
        else:
            # Existing user logging in
            assigned_role = existing_user["role"]
            assigned_phone = existing_user["phone"] if "phone" in existing_user.keys() and existing_user["phone"] else ""
            assigned_name = existing_user["full_name"] or full_name
            if act_code:
                code_info = db.verify_activation_code(act_code)
                if code_info.get("valid"):
                    assigned_role = code_info.get("role", assigned_role)
                    assigned_phone = code_info.get("journalist_phone", assigned_phone)
                    db.consume_activation_code(act_code, email)
        
        # 2. Save Blogger token for this journalist
        token_dir = PROJECT_ROOT / "storage" / "tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        safe_email = re.sub(r'[^a-zA-Z0-9_\-]', '_', email)
        personal_token_path = token_dir / f"token_{safe_email}.pickle"
        
        with open(personal_token_path, "wb") as f:
            pickle.dump(creds, f)
            
        # Also copy to root token.pickle and Config.TOKEN_FILE so BloggerService uses it immediately
        with open(PROJECT_ROOT / "token.pickle", "wb") as f:
            pickle.dump(creds, f)
        if Config.TOKEN_FILE.parent.exists():
            with open(Config.TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
            
        # Re-authenticate blogger_service with new credentials
        try:
            blogger_service.authenticate()
            Config.GOOGLE_USER_EMAIL = email
            Config.update_env("GOOGLE_USER_EMAIL", email)
        except Exception:
            pass
        
        # 3. Create or update user in database
        user = db.get_or_create_google_user(
            email=email,
            full_name=assigned_name,
            avatar=avatar,
            token_path=str(personal_token_path),
            role=assigned_role,
            phone=assigned_phone
        )
        
        # 4. Create web session
        session_token = create_session_token(user)
        
        db.log_system(
            "INFO", "Auth",
            f"تسجيل دخول ناجح عبر Google للصحفي: {full_name} ({email}) - تم ربط صلاحية Blogger بنجاح",
            user_id=str(user["id"]),
            user_name=full_name
        )
        
        user_json = json.dumps(user)
        target_redirect = "/?view=settings" if is_blogger_link else "/"
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="utf-8">
            <title>جاري تحويلك للمنظومة...</title>
            <script>
                localStorage.setItem('td_auth_token', '{session_token}');
                localStorage.setItem('td_user', JSON.stringify({user_json}));
                document.cookie = "td_auth_token={session_token}; path=/; max-age=31536000; SameSite=Lax";
                window.location.href = '{target_redirect}';
            </script>
        </head>
        <body style="background: #090D16; color: #F59E0B; font-family: sans-serif; text-align: center; padding-top: 100px;">
            <h2>✅ تم ربط حساب Google بنجاح ({email})!</h2>
            <p>جاري فتح لوحة التحكم الخاصة بك...</p>
        </body>
        </html>
        """
        resp = HTMLResponse(content=html_content)
        resp.set_cookie(key="td_auth_token", value=session_token, max_age=86400*365, httponly=False, samesite="lax")
        return resp
        
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return HTMLResponse(content=f"""
        <body style="background: #090D16; color: #EF4444; font-family: sans-serif; text-align: center; padding-top: 100px;">
            <h2>❌ فشل تسجيل الدخول عبر Google</h2>
            <p>{str(e)}</p>
            <a href="/" style="color: #F59E0B; text-decoration: underline;">العودة لصفحة الدخول</a>
        </body>
        """, status_code=500)

@app.post("/api/auth/login")
def login(payload: LoginRequest):
    """Authenticates user credentials and returns session token and role."""
    user = db.authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=400, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    
    token = create_session_token(user)
    db.log_system("INFO", "Auth", f"تسجيل دخول ناجح للمستخدم: {user['full_name']} ({user['username']})", user_id=str(user["id"]), user_name=user["full_name"])
    
    return {
        "success": True,
        "token": token,
        "user": user
    }

@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """Returns current active user session profile with live database updates."""
    fresh = db.get_user_by_id(user["user_id"])
    if fresh:
        user["role"] = fresh.get("role", user.get("role", "journalist"))
        user["full_name"] = fresh.get("full_name", user.get("full_name", ""))
        user["email"] = fresh.get("email", user.get("email", ""))
        user["avatar"] = fresh.get("google_avatar", user.get("avatar", ""))
    return {"success": True, "user": user}

@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    """Terminates active session."""
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        ACTIVE_SESSIONS.pop(token, None)
    return {"success": True, "message": "تم تسجيل الخروج بنجاح"}

@app.get("/api/auth/users", dependencies=[Depends(require_role(["admin"]))])
def list_users():
    """Admin-only: lists all registered system users."""
    users = db.get_all_users()
    return {"success": True, "users": users}

@app.post("/api/auth/users/{user_id}/role", dependencies=[Depends(require_role(["admin"]))])
def update_user_role(user_id: int, payload: RoleUpdateRequest, admin_user: dict = Depends(get_current_user)):
    """Admin-only: updates a journalist or user role (admin, editor, journalist)."""
    if payload.role not in ["admin", "editor", "journalist"]:
        raise HTTPException(status_code=400, detail="الرتبة غير صالحة. الرتب المتاحة: admin, editor, journalist")
    db.update_user(user_id, role=payload.role)
    for token, sess in list(ACTIVE_SESSIONS.items()):
        if sess.get("user_id") == user_id:
            sess["role"] = payload.role
    role_arabic = {"admin": "رئيس التحرير (Admin)", "editor": "صحفي مميز (مدير تحرير)", "journalist": "صحفي معتمد"}.get(payload.role, payload.role)
    db.log_system("INFO", "Auth", f"تم تعديل رتبة المستخدم #{user_id} إلى {role_arabic}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "message": f"تم ترقية وتعيين رتبة الصحفي إلى: {role_arabic}"}

@app.get("/api/admin/activation-codes", dependencies=[Depends(require_role(["admin"]))])
def list_activation_codes():
    """Admin-only: lists all generated invitation/activation codes."""
    codes = db.get_all_activation_codes()
    return {"success": True, "codes": codes}

@app.post("/api/admin/activation-codes", dependencies=[Depends(require_role(["admin"]))])
def create_new_activation_code(payload: CreateActivationRequest, admin_user: dict = Depends(get_current_user)):
    """Admin-only: issues a new one-time activation code for onboarding a journalist."""
    code = db.create_activation_code(
        journalist_name=payload.name,
        journalist_phone=payload.phone,
        role=payload.role,
        created_by=admin_user.get("full_name") or admin_user.get("username")
    )
    db.log_system("INFO", "Auth", f"تم إصدار كود تفعيل صحفي جديد: {code} للصحفي {payload.name} برتبة {payload.role}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "code": code, "message": "تم توليد كود التفعيل الصحفي بنجاح"}

@app.delete("/api/admin/activation-codes/{code}", dependencies=[Depends(require_role(["admin"]))])
def revoke_activation_code_endpoint(code: str, admin_user: dict = Depends(get_current_user)):
    """Admin-only: revokes an unused activation code."""
    db.revoke_activation_code(code)
    db.log_system("INFO", "Auth", f"تم إيقاف كود التفعيل {code}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "message": f"تم إيقاف كود التفعيل: {code}"}

@app.post("/api/auth/users", dependencies=[Depends(require_role(["admin"]))])
def create_user(payload: UserCreateRequest):
    """Admin-only: creates a new system user."""
    existing = db.get_user_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="اسم المستخدم مسجل مسبقاً في النظام")
    
    user_id = db.create_user(
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
        email=payload.email or ""
    )
    return {"success": True, "user_id": user_id, "message": "تم إنشاء حساب المستخدم بنجاح"}

@app.put("/api/auth/users/{user_id}", dependencies=[Depends(require_role(["admin"]))])
def update_user_profile(user_id: int, payload: UserUpdateRequest):
    """Admin-only: updates user role, status or resets password."""
    db.update_user(
        user_id=user_id,
        full_name=payload.full_name,
        role=payload.role,
        is_active=payload.is_active,
        password=payload.password
    )
    return {"success": True, "message": "تم تحديث بيانات المستخدم بنجاح"}

@app.delete("/api/auth/users/{user_id}", dependencies=[Depends(require_role(["admin"]))])
def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """Admin-only: deletes a system user."""
    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="لا يمكنك حذف حسابك الشخصي الحالي")
    db.delete_user(user_id)
    return {"success": True, "message": "تم حذف الحساب بنجاح"}


# =============================================================
# AI GENERATION ROUTER
# =============================================================
# AI GENERATION & PERSONAL API KEY ROUTER
# =============================================================

@app.get("/api/user/ai-key")
def get_user_ai_key(user: dict = Depends(get_current_user)):
    """Returns whether the logged-in journalist has configured their personal Z.AI API key."""
    key = db.get_user_zai_key(user["user_id"])
    has_key = bool(key and len(key.strip()) >= 10)
    masked = ""
    if has_key:
        k = key.strip()
        masked = f"{k[:4]}••••••••{k[-4:]}" if len(k) > 10 else "••••••••"
    return {
        "success": True,
        "has_key": has_key,
        "masked_key": masked
    }

@app.post("/api/user/ai-key")
def set_user_ai_key(payload: UserAIKeyRequest, user: dict = Depends(get_current_user)):
    """Saves and activates the journalist's personal Z.AI API key."""
    clean_key = (payload.api_key or "").strip()
    if not clean_key or len(clean_key) < 10:
        raise HTTPException(status_code=400, detail="يرجى إدخال مفتاح Z.AI API صالح وكامل")
    
    db.set_user_zai_key(user["user_id"], clean_key)
    db.log_system("INFO", "AIService", f"تم حفظ وتفعيل مفتاح Z.AI الشخصي بواسطة: {user.get('full_name')}", user_id=str(user.get("user_id")))
    
    masked = f"{clean_key[:4]}••••••••{clean_key[-4:]}" if len(clean_key) > 10 else "••••••••"
    return {
        "success": True,
        "message": "تم حفظ وتفعيل مفتاح الذكاء الاصطناعي بنجاح! 🔑✨",
        "has_key": True,
        "masked_key": masked
    }

@app.delete("/api/user/ai-key")
def delete_user_ai_key(user: dict = Depends(get_current_user)):
    """Clears the journalist's personal Z.AI API key."""
    db.set_user_zai_key(user["user_id"], "")
    db.log_system("WARNING", "AIService", f"تم إزالة مفتاح Z.AI الشخصي للصحفي: {user.get('full_name')}", user_id=str(user.get("user_id")))
    return {
        "success": True,
        "message": "تم حذف مفتاح الذكاء الاصطناعي بنجاح",
        "has_key": False,
        "masked_key": ""
    }

@app.post("/api/ai/generate")
def generate_article_ai(payload: AIGenerateRequest, user: dict = Depends(get_current_user)):
    """
    Generates a full professional Egyptian journalistic article using the journalist's
    personal Z.AI (GLM) key with strict adherence to allowed categories and Schema.org standards.
    """
    if not payload.raw_notes or not payload.raw_notes.strip():
        raise HTTPException(status_code=400, detail="يرجى إدخال تفاصيل ومعلومات الخبر الخام")
    
    # Enforce personal Z.AI API key
    user_key = db.get_user_zai_key(user["user_id"])
    if not user_key:
        raise HTTPException(
            status_code=400,
            detail="⚠️ تنبيه إجباري: لم تقم بإدخال مفتاح الذكاء الاصطناعي (Z.AI API Key) الخاص بك. يرجى التوجه لصفحة الإعدادات وحفظ مفتاحك الشخصي أولاً قبل البدء في الصياغة."
        )
    
    t_start = time.time()
    try:
        ai_data = ai_service.generate_article(payload.raw_notes, api_key=user_key)
        if not ai_data or not isinstance(ai_data, dict):
            raise ValueError("فشل محرك الذكاء الاصطناعي في إرجاع بيانات المقال بصيغة صحيحة")
        
        final_html = ArticleFormatter.format_full_article(ai_data)
        ai_data["final_html"] = final_html
        
        elapsed = round(time.time() - t_start, 2)
        db.log_system("INFO", "AIService", f"تمت صياغة خبر بنجاح: '{ai_data.get('title', '')}' في {elapsed} ثانية", user_id=str(user["user_id"]), user_name=user["full_name"])
        
        return {
            "success": True,
            "elapsed_seconds": elapsed,
            "data": ai_data
        }
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")
        db.log_system("ERROR", "AIService", f"فشل توليد الخبر: {e}", user_id=str(user["user_id"]), user_name=user["full_name"])
        raise HTTPException(status_code=500, detail=f"حدث خطأ أثناء الصياغة بالذكاء الاصطناعي: {str(e)}")


# =============================================================
# VERIFICATION & DUPLICATE PROTECTION ROUTER
# =============================================================

@app.get("/api/verification/check")
def check_duplicate_client(q: str = Query(..., description="رقم الهاتف أو اسم العميل للتحقق")):
    """
    Real-time duplicate lookup across all Telegram Bot & Desktop archives.
    Cleans Egyptian phone format automatically and checks for exact and partial matches.
    """
    q_clean = q.strip()
    if not q_clean:
        return {"exists": False}
    
    # If multiple phone numbers or raw text were provided, check all extracted numbers
    all_extracted = extract_all_egyptian_phones(q_clean)
    if all_extracted:
        for ph in all_extracted:
            res = db.find_article_by_phone(ph)
            if res.get("exists"):
                res["query_type"] = "phone"
                res["cleaned_phone"] = ph
                c_phone = res.get("client_phone") or ph
                c_name = res.get("client_name") or ""
                p_url = res.get("post_url") or ""
                res["article_title"] = res.get("title") or ""
                if c_phone:
                    res["clean_chat_url"] = f"https://wa.me/{c_phone}"
                    if p_url:
                        try:
                            res["whatsapp_direct_url"] = whatsapp_service.generate_whatsapp_click_link(
                                phone=c_phone,
                                name=c_name,
                                post_url=p_url
                            )
                        except Exception as we:
                            logger.warning(f"Could not generate whatsapp direct link in verification: {we}")
                            res["whatsapp_direct_url"] = f"https://wa.me/{c_phone}"
                return res

    clean_phone = clean_egyptian_phone(q_clean)
    digits = "".join(filter(str.isdigit, q_clean))
    
    res = {"exists": False}
    if len(digits) >= 8 or clean_phone:
        res = db.find_article_by_phone(q_clean)
        if res.get("exists"):
            res["query_type"] = "phone"
            res["cleaned_phone"] = clean_phone
    
    if not res.get("exists"):
        res = db.check_client_duplicate(name=q_clean)
        res["query_type"] = "name"
        res["cleaned_phone"] = clean_phone

    if res.get("exists"):
        c_phone = res.get("client_phone") or clean_phone or ""
        c_name = res.get("client_name") or ""
        p_url = res.get("post_url") or ""
        res["article_title"] = res.get("title") or ""
        if c_phone:
            res["clean_chat_url"] = f"https://wa.me/{c_phone}"
            if p_url:
                try:
                    res["whatsapp_direct_url"] = whatsapp_service.generate_whatsapp_click_link(
                        phone=c_phone,
                        name=c_name,
                        post_url=p_url
                    )
                except Exception as we:
                    logger.warning(f"Could not generate whatsapp direct link in verification: {we}")
                    res["whatsapp_direct_url"] = f"https://wa.me/{c_phone}"
        return res
    
    return {"exists": False, "cleaned_phone": clean_phone, "query": q_clean}

@app.get("/api/check-phone")
def check_phone_legacy(phone: str = Query(...)):
    if not phone or not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required")
    return db.find_article_by_phone(phone)

@app.get("/api/search")
def search_legacy(q: str = Query(...)):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query is required")
    digits = "".join(filter(str.isdigit, q))
    if len(digits) >= 8:
        res = db.find_article_by_phone(q)
        if res.get("exists"):
            return res
    return db.check_client_duplicate(name=q)


@app.post("/api/verification/manual-register")
def manual_register_client(payload: ManualClientRegisterRequest, user: dict = Depends(get_current_user)):
    """
    Manually registers a client phone number into the central database.
    Marks them as already contacted/registered to prevent duplicate contact by reporters/editors.
    """
    phone_raw = (payload.phone or "").strip()
    if not phone_raw:
        raise HTTPException(status_code=400, detail="يرجى إدخال رقم هاتف العميل.")

    clean_phone = clean_egyptian_phone(phone_raw)
    digits = "".join(filter(str.isdigit, phone_raw))
    if len(digits) < 9 and not clean_phone:
        raise HTTPException(status_code=400, detail="رقم الهاتف غير صالح. يرجى إدخال رقم هاتف صحيح.")

    final_phone = clean_phone or digits

    # Check if this phone already exists in the system
    dup = db.find_article_by_phone(final_phone)
    if dup.get("exists"):
        prev_title = dup.get("title") or dup.get("article_title") or "خبر مسجل مسبقاً"
        prev_author = dup.get("author_name") or dup.get("reporter_name") or "محرر بالجريدة"
        prev_date = (dup.get("published_at") or dup.get("created_at") or "")[:10]
        raise HTTPException(
            status_code=409,
            detail=f"⚠️ هذا الرقم مسجل بالفعل في قاعدة البيانات مسبقاً!\nالعنوان: {prev_title}\nبواسطة: {prev_author} ({prev_date})"
        )

    client_name = (payload.client_name or "").strip() or "عميل مسجل يدوياً"
    contact_method = (payload.contact_method or "").strip() or "تواصل خارجي"
    notes = (payload.notes or "").strip()

    author_name = user.get("full_name") or user.get("email") or "محرر الجريدة"
    author_email = user.get("email") or ""
    reporter_id = str(user.get("user_id", ""))

    try:
        client_id = db.save_client(name=client_name, phone=final_phone, raw_data=notes)
    except Exception as ce:
        logger.warning(f"save_client failed in manual register: {ce}")
        client_id = None

    now_iso = datetime.now().isoformat()
    title = f"عميل مسجل يدوياً ({contact_method}) — {client_name}"
    final_html = f"""<div class="manual-client-card">
        <h3>تم تسجيل هذا العميل يدوياً لمنع التكرار وحجز التواصل</h3>
        <p><strong>اسم العميل:</strong> {client_name}</p>
        <p><strong>رقم الهاتف:</strong> {final_phone}</p>
        <p><strong>طريقة التواصل:</strong> {contact_method}</p>
        <p><strong>المحرر المسئول:</strong> {author_name}</p>
        <p><strong>تاريخ التسجيل:</strong> {now_iso[:10]}</p>
        {f'<p><strong>ملاحظات:</strong> {notes}</p>' if notes else ''}
    </div>"""

    article_id = db.save_article({
        "client_id": client_id,
        "client_name": client_name,
        "client_phone": final_phone,
        "title": title,
        "slug": f"manual-{final_phone}",
        "labels": "تواصل خارجي, مسجل يدوياً",
        "final_html": final_html,
        "blogger_status": "REGISTERED_MANUAL",
        "published_at": now_iso,
        "author_name": author_name,
        "author_email": author_email,
        "reporter_telegram_id": reporter_id
    })

    # Log to system activity
    db.log_system(
        "INFO",
        "Verification",
        f"تسجيل عميل يدوياً: {final_phone} ({client_name}) بواسطة {author_name} [{contact_method}]",
        user_id=reporter_id,
        user_name=author_name
    )

    # Sync to Central Server Hub if available
    try:
        central_sync_service.register_published_post({
            "client_name": client_name,
            "client_phone": final_phone,
            "title": title,
            "slug": f"manual-{final_phone}",
            "labels": "تواصل خارجي",
            "post_url": "",
            "post_id": f"MANUAL_{article_id}",
            "reporter_telegram_id": reporter_id,
            "blogger_status": "REGISTERED_MANUAL"
        })
    except Exception as se:
        logger.debug(f"Central hub sync info: {se}")

    return {
        "success": True,
        "message": f"تم تسجيل العميل {client_name} ({final_phone}) بنجاح وحمايته من التكرار.",
        "article_id": article_id,
        "client_phone": final_phone,
        "client_name": client_name,
        "contact_method": contact_method
    }


# =============================================================
# RATE LIMITING & COOLDOWN ROUTER
# =============================================================

@app.get("/api/publish-cooldown")
def get_cooldown(cooldown: int = 60):
    """Returns the remaining seconds for the 60-second newspaper rate limit."""
    remaining = db.get_publish_cooldown_remaining(cooldown_seconds=cooldown)
    return {
        "can_publish": remaining == 0,
        "wait_seconds": remaining,
        "cooldown": cooldown,
        "message": "يمكن النشر الآن." if remaining == 0 else f"يوجد خبر تم نشره مؤخراً. يرجى الانتظار {remaining} ثانية لتنظيم تدفق النشر."
    }

@app.post("/api/record-publish")
def record_publish_event():
    db.record_publish_event()
    return {"success": True, "timestamp": time.time()}


# =============================================================
# ARTICLES & PUBLISHING ROUTER
# =============================================================

@app.get("/api/articles")
def list_articles(
    search: Optional[str] = "",
    category: Optional[str] = "",
    status: Optional[str] = "",
    author: Optional[str] = "",
    page: int = 1,
    limit: int = 25,
    user: dict = Depends(get_current_user)
):
    is_admin = user.get("role") == "admin"
    if is_admin:
        articles = db.get_all_articles(author_email=author if author else None)
    else:
        articles = db.get_all_articles(
            author_email=user.get("email"),
            author_name=user.get("full_name"),
            user_id=user.get("user_id")
        )
    
    filtered = []
    for a in articles:
        if search:
            s = search.lower()
            t = (a.get("title") or "").lower()
            c = (a.get("client_name") or "").lower()
            p = (a.get("client_phone") or "")
            if s not in t and s not in c and s not in p:
                continue
        if category and category != "الكل":
            if category not in (a.get("labels") or ""):
                continue
        if status and status != "الكل":
            if a.get("blogger_status") != status:
                continue
        filtered.append(a)
    
    total = len(filtered)
    start_idx = (page - 1) * limit
    paginated = filtered[start_idx:start_idx + limit]
    
    return {
        "success": True,
        "total": total,
        "page": page,
        "limit": limit,
        "articles": paginated,
        "is_admin": is_admin
    }

@app.get("/api/articles/{article_id}")
def get_article(article_id: int, user: dict = Depends(get_current_user)):
    article = db.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="المقال غير موجود")
    if user.get("role") != "admin":
        is_own = (
            (article.get("author_email") and article["author_email"].strip().lower() == (user.get("email") or "").strip().lower()) or
            (article.get("author_name") and article["author_name"].strip() == (user.get("full_name") or "").strip()) or
            (article.get("reporter_telegram_id") and str(article["reporter_telegram_id"]) == str(user.get("user_id")))
        )
        if not is_own:
            raise HTTPException(status_code=403, detail="لا يمكنك استعراض هذا المقال")
    return {"success": True, "article": article}

@app.post("/api/articles")
def save_article(payload: ArticleSaveRequest, user: dict = Depends(get_current_user)):
    article_dict = {
        "title": payload.title,
        "slug": payload.slug,
        "labels": payload.labels,
        "client_name": payload.client_name,
        "client_phone": payload.client_phone,
        "raw_ai_json": payload.raw_ai_json,
        "final_html": payload.final_html,
        "local_image_path": payload.local_image_path,
        "remote_image_url": payload.remote_image_url,
        "is_draft": 1 if payload.is_draft else 0,
        "blogger_status": "DRAFT" if payload.is_draft else "PENDING",
        "reporter_telegram_id": str(user.get("user_id", "")),
        "author_email": user.get("email") or "",
        "author_name": user.get("full_name") or ""
    }
    
    if payload.id:
        existing = db.get_article(payload.id)
        if existing and user.get("role") != "admin":
            is_own = (
                (existing.get("author_email") and existing["author_email"].strip().lower() == (user.get("email") or "").strip().lower()) or
                (existing.get("author_name") and existing["author_name"].strip() == (user.get("full_name") or "").strip()) or
                (existing.get("reporter_telegram_id") and str(existing["reporter_telegram_id"]) == str(user.get("user_id")))
            )
            if not is_own:
                raise HTTPException(status_code=403, detail="لا يمكنك تعديل مقال يخص صحفياً آخر")
        db.update_article(payload.id, article_dict)
        art_id = payload.id
        msg = f"تم تحديث المقال #{art_id}: {payload.title}"
    else:
        art_id = db.save_article(article_dict)
        msg = f"تم حفظ المقال الجديد #{art_id}: {payload.title}"
        
    db.log_system("INFO", "Articles", msg, user_id=str(user["user_id"]), user_name=user["full_name"])
    return {"success": True, "article_id": art_id, "message": msg}

@app.post("/api/articles/{article_id}/publish")
def publish_article_to_blogger(article_id: int, payload: ArticlePublishRequest, user: dict = Depends(get_current_user)):
    # Admins and Featured Journalists (Editors) have direct publishing privilege without waiting
    is_privileged = user.get("role") in ["admin", "editor"]
    if not is_privileged:
        cooldown_rem = db.get_publish_cooldown_remaining(60)
        if cooldown_rem > 0:
            raise HTTPException(status_code=429, detail=f"⚠️ برجاء الانتظار {cooldown_rem} ثانية لضبط تدفق نشر الجريدة قبل النشر مجدداً.")
    
    if not blogger_service.is_authenticated():
        raise HTTPException(status_code=400, detail="خدمة Blogger غير متصلة. يرجى توثيق حساب Google أولاً في الإعدادات.")
    
    broadcast_publish_step(15, "⚡ [1/4] فحص بيانات المقال وصلاحيات النشر السحابي...")
    
    remote_img_url = ""
    local_img = payload.local_image_path or ""
    if local_img and os.path.exists(local_img):
        broadcast_publish_step(30, "📸 [2/4] جاري رفع الصورة المرفقة إلى السحابة...")
        try:
            remote_img_url = image_service.upload_image(local_img)
        except Exception as img_err:
            logger.warning(f"Could not upload image: {img_err}")
    
    final_html_to_publish = payload.final_html
    if remote_img_url:
        alt_text = f"{payload.client_name or payload.title} | جريدة تحت الضوء"
        final_html_to_publish = ArticleFormatter.replace_image_placeholder(final_html_to_publish, remote_img_url, alt_text=alt_text)

    try:
        broadcast_publish_step(60, "🚀 [3/4] إرسال المقال والبث المباشر إلى خوادم Google Blogger...")
        labels_list = [l.strip() for l in (payload.labels or "").split(",") if l.strip()] if isinstance(payload.labels, str) else (payload.labels or [])
        pub_res = blogger_service.publish_post(
            title=payload.title,
            content_html=final_html_to_publish,
            labels=labels_list,
            is_draft=payload.is_draft,
            meta_description=payload.slug
        )
        
        post_url = pub_res.get("post_url") or pub_res.get("url", "")
        post_id = pub_res.get("post_id") or pub_res.get("id", "")
        
        db.record_publish_event()
        
        db.update_article(article_id, {
            "title": payload.title,
            "slug": payload.slug,
            "labels": payload.labels,
            "final_html": final_html_to_publish,
            "post_id": post_id,
            "post_url": post_url,
            "remote_image_url": remote_img_url,
            "blogger_status": "DRAFT" if payload.is_draft else "PUBLISHED",
            "published_at": datetime.now().isoformat()
        })
        
        broadcast_publish_step(92, "📲 [4/4] تم النشر في بلوجر! جاري تجهيز رسالة الواتساب للعميل...")
        wa_text = ""
        wa_url = ""
        if payload.client_phone:
            c_name = payload.client_name or "العميل"
            e_type = payload.entity_type
            if not e_type or e_type not in ["male", "female", "plural"]:
                e_type = whatsapp_service.detect_entity_type(c_name)
            wa_text = whatsapp_service.format_message(
                name=c_name,
                post_url=post_url,
                entity_type=e_type
            )
            wa_url = whatsapp_service.generate_whatsapp_click_link(
                phone=payload.client_phone,
                name=c_name,
                post_url=post_url,
                entity_type=e_type
            )
            
            db.save_whatsapp_log(
                article_id=article_id,
                recipient_phone=payload.client_phone,
                recipient_name=payload.client_name or "",
                message_body=wa_text,
                status="READY"
            )
        
        # Register any secondary phone numbers under the same organization
        secondary_phones = []
        try:
            art_record = db.get_article(article_id) or {}
            combined_text = f"{art_record.get('raw_notes', '')} {art_record.get('final_html', '')} {payload.final_html} {payload.title}"
            all_phones = extract_all_egyptian_phones(combined_text)
            if all_phones and payload.client_phone:
                secondary_phones = db.register_secondary_client_phones(
                    primary_phone=payload.client_phone,
                    all_phones=all_phones,
                    client_name=payload.client_name or "",
                    article_data={
                        "title": payload.title,
                        "slug": payload.slug,
                        "labels": payload.labels,
                        "post_id": post_id,
                        "post_url": post_url,
                        "author_name": user.get("full_name") or "",
                        "author_email": user.get("email") or "",
                        "reporter_telegram_id": str(user.get("user_id", ""))
                    }
                )
        except Exception as spe:
            logger.warning(f"Error registering secondary phones in publish_article: {spe}")

        broadcast_publish_step(100, "✅ تم النشر والاعتماد بنجاح!")
        db.log_system("INFO", "BloggerService", f"تم نشر المقال #{article_id} بنجاح: {payload.title} -> {post_url}", user_id=str(user["user_id"]), user_name=user["full_name"])
        
        return {
            "success": True,
            "post_url": post_url,
            "post_id": post_id,
            "whatsapp_url": wa_url,
            "whatsapp_text": wa_text,
            "secondary_phones": secondary_phones,
            "message": "تم نشر المقال في بلوجر وتجهيز رسالة الواتساب بنجاح!"
        }
    except Exception as e:
        logger.error(f"Publish failed: {e}")
        db.log_system("ERROR", "BloggerService", f"فشل نشر المقال #{article_id}: {e}", user_id=str(user["user_id"]), user_name=user["full_name"])
        raise HTTPException(status_code=500, detail=f"فشل النشر على Blogger: {str(e)}")

@app.post("/api/articles/direct-publish")
def direct_one_click_publish(payload: DirectPublishRequest, user: dict = Depends(get_current_user)):
    # Admins and Featured Journalists (Editors) publish directly without waiting
    is_privileged = user.get("role") in ["admin", "editor"]
    if not is_privileged:
        rem = db.get_publish_cooldown_remaining(60)
        if rem > 0:
            raise HTTPException(status_code=429, detail=f"⚠️ ليمت الجريدة مفعل: يرجى الانتظار {rem} ثانية قبل نشر هذا المقال.")
    
    if not blogger_service.is_authenticated():
        raise HTTPException(status_code=400, detail="خدمة Blogger غير متصلة. يرجى توثيق حساب Google أولاً.")
    
    # Enforce personal Z.AI API key (with admin fallback to system key)
    user_key = db.get_user_zai_key(user["user_id"])
    if not user_key and user.get("role") == "admin" and Config.ZAI_API_KEY:
        user_key = Config.ZAI_API_KEY
    if not user_key:
        raise HTTPException(
            status_code=400,
            detail="⚠️ تنبيه إجباري: لم تقم بإدخال مفتاح الذكاء الاصطناعي (Z.AI API Key) الخاص بك. يرجى التوجه لصفحة الإعدادات وحفظ مفتاحك الشخصي أولاً قبل النشر."
        )
    
    try:
        broadcast_publish_step(10, "⚡ [1/5] استلام البيانات وبدء فحص التفاصيل الصحفية...")
        
        remote_img_url = ""
        local_img = payload.local_image_path or ""
        if local_img and os.path.exists(local_img):
            broadcast_publish_step(25, "📸 [2/5] جاري رفع الصورة المرفقة سحابياً إلى الخادم...")
            try:
                remote_img_url = image_service.upload_image(local_img)
            except Exception as img_err:
                logger.warning(f"Could not upload image in direct publish: {img_err}")

        broadcast_publish_step(40, "🤖 [3/5] إرسال البيانات وصياغة الخبر عبر نموذج الذكاء الاصطناعي Z.AI (GLM)...")
        ai_data = ai_service.generate_article(payload.raw_notes, api_key=user_key)
        final_html = ArticleFormatter.format_full_article(ai_data, image_url=remote_img_url if remote_img_url else None)
        
        title = ai_data.get("title", "خبر صحفي — جريدة تحت الضوء")
        client_name = ai_data.get("client_name", "")
        client_phone = extract_preferred_whatsapp_phone(payload.raw_notes) or ai_data.get("client_phone", "")
        all_extracted_phones = extract_all_egyptian_phones(payload.raw_notes)
        labels_raw = ai_data.get("labels", "أخبار")
        if isinstance(labels_raw, list):
            labels_str = ", ".join([str(l).strip() for l in labels_raw if l])
            labels_list = [str(l).strip() for l in labels_raw if l]
        else:
            labels_str = str(labels_raw)
            labels_list = [l.strip() for l in labels_str.split(",") if l.strip()]
        slug = ai_data.get("slug", "")
        
        broadcast_publish_step(68, f"📝 [4/5] تم اعتماد الصياغة التحريرية والـ SEO ({len(final_html)} حرف)...")
        art_id = db.save_article({
            "title": title,
            "slug": slug,
            "labels": labels_str,
            "client_name": client_name,
            "client_phone": client_phone,
            "raw_notes": payload.raw_notes,
            "raw_ai_json": json.dumps(ai_data, ensure_ascii=False),
            "final_html": final_html,
            "local_image_path": payload.local_image_path or "",
            "remote_image_url": remote_img_url,
            "blogger_status": "PUBLISHED",
            "reporter_telegram_id": str(user.get("user_id", "")),
            "author_email": user.get("email") or "",
            "author_name": user.get("full_name") or ""
        })
        
        broadcast_publish_step(84, "🚀 [5/5] إرسال المقال والبث السحابي المباشر إلى Google Blogger...")
        pub_res = blogger_service.publish_post(
            title=title,
            content_html=final_html,
            labels=labels_list,
            is_draft=False,
            meta_description=slug
        )
        post_url = pub_res.get("post_url") or pub_res.get("url", "")
        post_id = pub_res.get("post_id") or pub_res.get("id", "")
        
        db.record_publish_event()
        db.update_article(art_id, {
            "post_id": post_id,
            "post_url": post_url,
            "published_at": datetime.now().isoformat()
        })
        
        # Register any secondary phone numbers under the same organization
        secondary_phones = []
        if all_extracted_phones:
            try:
                secondary_phones = db.register_secondary_client_phones(
                    primary_phone=client_phone,
                    all_phones=all_extracted_phones,
                    client_name=client_name,
                    article_data={
                        "title": title,
                        "slug": slug,
                        "labels": labels_str,
                        "post_id": post_id,
                        "post_url": post_url,
                        "author_name": user.get("full_name") or "",
                        "author_email": user.get("email") or "",
                        "reporter_telegram_id": str(user.get("user_id", ""))
                    }
                )
            except Exception as se:
                logger.warning(f"Error registering secondary phones in direct publish: {se}")

        broadcast_publish_step(96, "📲 تم النشر في بلوجر بنجاح! جاري تحضير رسالة الواتساب للعميل...")
        wa_text = ""
        wa_url = ""
        if client_phone:
            c_name = client_name or "العميل"
            e_type = payload.entity_type
            if not e_type or e_type not in ["male", "female", "plural"]:
                e_type = whatsapp_service.detect_entity_type(c_name)
            wa_text = whatsapp_service.format_message(name=c_name, post_url=post_url, entity_type=e_type)
            wa_url = whatsapp_service.generate_whatsapp_click_link(phone=client_phone, name=c_name, post_url=post_url, entity_type=e_type)
            db.save_whatsapp_log(art_id, client_phone, client_name, wa_text, "READY")
            
        broadcast_publish_step(100, "✅ اكتملت عملية النشر والاعتماد بالكامل!")
        db.log_system("INFO", "Pipeline", f"نشر سريع بنجاح للمقال #{art_id}: {title}", user_id=str(user["user_id"]), user_name=user["full_name"])
        
        return {
            "success": True,
            "article_id": art_id,
            "title": title,
            "post_url": post_url,
            "whatsapp_url": wa_url,
            "whatsapp_text": wa_text,
            "client_name": client_name,
            "client_phone": client_phone,
            "secondary_phones": secondary_phones
        }
    except Exception as e:
        logger.error(f"Direct publish failed: {e}")
        db.log_system("ERROR", "Pipeline", f"فشل النشر السريع: {e}", user_id=str(user["user_id"]), user_name=user["full_name"])
        raise HTTPException(status_code=500, detail=f"فشل النشر المباشر: {str(e)}")

@app.delete("/api/articles/{article_id}", dependencies=[Depends(require_role(["admin", "editor", "journalist"]))])
def delete_article(article_id: int, user: dict = Depends(get_current_user)):
    with db.get_connection() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(status_code=404, detail="المقال غير موجود")
        art = dict(art)
        if user.get("role") != "admin":
            is_own = (
                (art.get("author_email") and art["author_email"].strip().lower() == (user.get("email") or "").strip().lower()) or
                (art.get("author_name") and art["author_name"].strip() == (user.get("full_name") or "").strip()) or
                (art.get("reporter_telegram_id") and str(art["reporter_telegram_id"]) == str(user.get("user_id")))
            )
            if not is_own:
                raise HTTPException(status_code=403, detail="لا يمكنك حذف مقال يخص صحفياً آخر")
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.commit()
    db.log_system("INFO", "Articles", f"تم حذف المقال #{article_id}", user_id=str(user["user_id"]), user_name=user["full_name"])
    return {"success": True, "message": "تم حذف المقال بنجاح"}

@app.post("/api/register-article")
def register_article_legacy(payload: CentralRegisterArticleRequest):
    article_id = db.save_article(
        client_name=payload.client_name,
        client_phone=payload.client_phone,
        title=payload.title,
        slug=payload.slug,
        labels=payload.labels,
        post_url=payload.post_url,
        post_id=payload.post_id,
        reporter_telegram_id=payload.reporter_telegram_id,
        blogger_status=payload.blogger_status,
        final_html=payload.final_html
    )
    db.record_publish_event()
    return {"success": True, "article_id": article_id}


# =============================================================
# REPORTERS & TELEGRAM BOT MANAGEMENT ROUTER (ADMIN CONTROL)
# =============================================================

@app.get("/api/admin/bot/status", dependencies=[Depends(require_role(["admin"]))])
def get_bot_status():
    telemetry = bot_controller.get_detailed_telemetry()
    return {"success": True, "telemetry": telemetry}

@app.post("/api/admin/bot/start", dependencies=[Depends(require_role(["admin"]))])
def start_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.start(timeout=10.0)
    db.log_system("INFO", "BotAdmin", f"تشغيل بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    if not success:
        return {"success": False, "error": bot_controller.last_error or "تعذر بدء تشغيل البوت"}
    return {"success": True, "message": "تم إطلاق بوت التليجرام وتشغيله بنجاح ⚡"}

@app.post("/api/admin/bot/stop", dependencies=[Depends(require_role(["admin"]))])
def stop_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.stop()
    db.log_system("WARNING", "BotAdmin", f"إيقاف بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    return {"success": success, "message": "تم إيقاف بوت التليجرام بنجاح ⏹️"}

@app.post("/api/admin/bot/restart", dependencies=[Depends(require_role(["admin"]))])
def restart_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.restart(timeout=15.0)
    db.log_system("INFO", "BotAdmin", f"إعادة تشغيل بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    if not success:
        return {"success": False, "error": bot_controller.last_error or "تعذر إعادة تشغيل البوت"}
    return {"success": True, "message": "تمت إعادة تشغيل بوت التليجرام وتنشيطه بنجاح 🔄"}

@app.post("/api/admin/bot/broadcast", dependencies=[Depends(require_role(["admin"]))])
def broadcast_bot(payload: BotBroadcastRequest, user: dict = Depends(get_current_user)):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="لا يمكن إرسال رسالة تعميم فارغة")
    res = bot_controller.broadcast_message(msg)
    db.log_system("INFO", "BotAdmin", f"إرسال تعميم للصحفيين عبر البوت: '{msg[:40]}...' إلى {res.get('sent_count', 0)} صحفي", user_id=str(user.get("user_id")))
    return res

@app.get("/api/admin/bot/logs", dependencies=[Depends(require_role(["admin"]))])
def get_bot_logs(limit: int = 100):
    logs = db.get_bot_logs(limit=limit)
    return {"success": True, "logs": logs}

@app.get("/api/reporters", dependencies=[Depends(require_role(["admin"]))])
def list_reporters():
    reporters = db.get_reporters_with_stats()
    return {"success": True, "reporters": reporters}

@app.post("/api/reporters", dependencies=[Depends(require_role(["admin"]))])
def register_reporter(payload: ReporterSaveRequest, user: dict = Depends(get_current_user)):
    api_key = payload.api_key.strip() if payload.api_key else f"TD-{secrets.token_hex(8).upper()}"
    db.save_reporter(
        telegram_id=payload.telegram_id.strip(),
        name=payload.name.strip(),
        role=payload.role.strip() if payload.role else "صحفي لدى",
        api_key=api_key
    )
    db.log_system("INFO", "Reporters", f"تسجيل/تحديث المراسل {payload.name} ({payload.telegram_id})", user_id=str(user.get("user_id")))
    return {"success": True, "api_key": api_key, "message": "تم حفظ بيانات الصحفي واعتماد المفتاح بنجاح"}

@app.delete("/api/reporters/{telegram_id}", dependencies=[Depends(require_role(["admin"]))])
def delete_reporter(telegram_id: str, user: dict = Depends(get_current_user)):
    ok = db.delete_reporter(telegram_id)
    if ok:
        db.log_system("WARNING", "Reporters", f"حذف الصحفي ذو المعرف {telegram_id}", user_id=str(user.get("user_id")))
        return {"success": True, "message": "تم حذف المراسل بنجاح"}
    return {"success": False, "message": "تعذر العثور على المراسل"}


# =============================================================
# JOURNALIST ACCOUNTING & FINANCIAL VAULT ROUTER
# =============================================================

@app.get("/api/accounting/settings")
def get_accounting_settings_endpoint(user: dict = Depends(get_current_user)):
    settings = db.get_financial_settings()
    effective_cut = db.calculate_effective_cut(user["user_id"], user["role"])
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT custom_deduction, is_active FROM users WHERE id = ?", (user["user_id"],))
        user_row = cursor.fetchone()
        custom_cut = user_row["custom_deduction"] if user_row else None
        is_active = user_row["is_active"] if user_row else 1

    return {
        "success": True,
        "settings": settings,
        "effective_cut": effective_cut,
        "user_role": user["role"],
        "user_custom_cut": custom_cut,
        "is_active": is_active
    }

@app.post("/api/accounting/transactions")
def create_accounting_transaction_endpoint(payload: CreateAccountingTransactionRequest, user: dict = Depends(get_current_user)):
    if not payload.article_title.strip():
        raise HTTPException(status_code=400, detail="يرجى إدخال عنوان الخبر الصحفي")
    if not payload.client_phone.strip():
        raise HTTPException(status_code=400, detail="يرجى إدخال رقم هاتف العميل")
    if payload.amount_paid <= 0:
        raise HTTPException(status_code=400, detail="يرجى إدخال مبلغ تحصيل صحيح أكبر من صفر")
    if payload.payment_method not in ["vodafone_cash", "instapay"]:
        raise HTTPException(status_code=400, detail="طرق الدفع المعتمدة هي (فودافون كاش أو إنستاباي) فقط")

    tx_id = db.save_accounting_transaction({
        "user_id": user["user_id"],
        "author_name": user.get("full_name") or user.get("username"),
        "author_email": user.get("email") or "",
        "user_role": user.get("role") or "journalist",
        "article_id": payload.article_id,
        "article_title": payload.article_title.strip(),
        "article_url": payload.article_url.strip() if payload.article_url else "",
        "client_name": payload.client_name.strip() if payload.client_name else "",
        "client_phone": payload.client_phone.strip(),
        "amount_paid": payload.amount_paid,
        "payment_method": payload.payment_method,
        "receipt_image_path": payload.receipt_image_path or "",
        "notes": payload.notes or ""
    })

    db.log_system("INFO", "Accounting", f"تسجيل عملية تحصيل مالي للخبر '{payload.article_title[:30]}' بمبلغ {payload.amount_paid} ج.م", user_id=str(user["user_id"]), user_name=user.get("full_name"))
    return {"success": True, "transaction_id": tx_id, "message": "تم اعتماد وتسجيل عملية التحصيل المالي بنجاح 💰"}

@app.get("/api/accounting/my-transactions")
def get_my_accounting_transactions_endpoint(range: str = "all", start_date: Optional[str] = None, end_date: Optional[str] = None, user: dict = Depends(get_current_user)):
    user_id = None if user.get("role") == "admin" else user["user_id"]
    txs = db.get_accounting_transactions(user_id=user_id, time_range=range, start_date=start_date, end_date=end_date)
    return {"success": True, "transactions": txs}

@app.get("/api/accounting/my-stats")
def get_my_accounting_stats_endpoint(range: str = "all", start_date: Optional[str] = None, end_date: Optional[str] = None, user: dict = Depends(get_current_user)):
    user_id = None if user.get("role") == "admin" else user["user_id"]
    stats = db.get_user_financial_stats(user_id=user_id, time_range=range, start_date=start_date, end_date=end_date, user_role=user.get("role", "journalist"))
    return {"success": True, "stats": stats}

@app.get("/api/accounting/unbilled-articles")
def get_unbilled_articles_endpoint(user: dict = Depends(get_current_user)):
    email = user.get("email") if user.get("role") != "admin" else None
    articles = db.get_unbilled_articles(author_email=email)
    return {"success": True, "articles": articles}

@app.delete("/api/accounting/transactions/{tx_id}")
def delete_accounting_transaction_endpoint(tx_id: int, user: dict = Depends(get_current_user)):
    is_admin = (user.get("role") == "admin")
    ok = db.delete_accounting_transaction(tx_id, user_id=user["user_id"], is_admin=is_admin)
    if ok:
        db.log_system("WARNING", "Accounting", f"حذف معاملة مالية رقم {tx_id}", user_id=str(user["user_id"]), user_name=user.get("full_name"))
        return {"success": True, "message": "تم حذف المعاملة المالية بنجاح"}
    raise HTTPException(status_code=400, detail="تعذر حذف المعاملة (ربما تمت تسويتها بالفعل أو لا تملك الصلاحية)")

# --- Admin Exclusives ---
@app.get("/api/admin/accounting/overview", dependencies=[Depends(require_role(["admin"]))])
def get_admin_accounting_overview_endpoint(range: str = "all", start_date: Optional[str] = None, end_date: Optional[str] = None):
    overview = db.get_admin_financial_overview(time_range=range, start_date=start_date, end_date=end_date)
    return {"success": True, "overview": overview}

@app.get("/api/admin/accounting/reporters-ledger", dependencies=[Depends(require_role(["admin"]))])
def get_admin_reporters_ledger_endpoint(range: str = "all", start_date: Optional[str] = None, end_date: Optional[str] = None):
    ledger = db.get_reporters_financial_ledger(time_range=range, start_date=start_date, end_date=end_date)
    return {"success": True, "ledger": ledger}

@app.post("/api/admin/accounting/settings", dependencies=[Depends(require_role(["admin"]))])
def update_financial_settings_endpoint(payload: UpdateFinancialSettingsRequest, user: dict = Depends(get_current_user)):
    update_dict = {}
    if payload.official_article_price is not None:
        update_dict["official_article_price"] = payload.official_article_price
    if payload.cut_certified_journalist is not None:
        update_dict["cut_certified_journalist"] = payload.cut_certified_journalist
    if payload.cut_premium_editor is not None:
        update_dict["cut_premium_editor"] = payload.cut_premium_editor

    db.update_financial_settings(update_dict)
    db.log_system("INFO", "Accounting", f"تعديل إعدادات الأسعار والنسب الرسمية بواسطة {user.get('full_name')}", user_id=str(user["user_id"]))
    return {"success": True, "message": "تم تحديث إعدادات الأسعار والنسب بنجاح ✅"}

@app.post("/api/admin/accounting/user-cut", dependencies=[Depends(require_role(["admin"]))])
def set_user_custom_cut_endpoint(payload: SetUserCustomCutRequest, user: dict = Depends(get_current_user)):
    db.set_user_custom_cut(payload.user_id, payload.custom_cut)
    cut_desc = f"{payload.custom_cut} ج.م" if payload.custom_cut is not None else "النسبة الافتراضية للرتبة"
    db.log_system("INFO", "Accounting", f"تعديل نسبة الاستقطاع الخاصة بالمستخدم {payload.user_id} لتكون: {cut_desc}", user_id=str(user["user_id"]))
    return {"success": True, "message": f"تم اعتماد نسبة الاستقطاع ({cut_desc}) بنجاح"}

@app.post("/api/admin/accounting/settle", dependencies=[Depends(require_role(["admin"]))])
def settle_transactions_endpoint(payload: SettleTransactionsRequest, user: dict = Depends(get_current_user)):
    count = db.settle_user_transactions(payload.user_id, admin_name=user.get("full_name") or "رئيس التحرير")
    db.log_system("INFO", "Accounting", f"تسوية وتصفير مستحقات المستخدم {payload.user_id} لعدد {count} معاملة", user_id=str(user["user_id"]))
    return {"success": True, "settled_count": count, "message": f"تمت تسوية وتصفية {count} معاملة بنجاح 💵"}


# =============================================================
# SETTINGS & BLOGGER POOL ROUTER
# =============================================================

@app.get("/api/settings")
def get_system_settings(authorization: Optional[str] = Header(None)):
    q_info = blogger_service.get_quota_info()
    is_auth = blogger_service.is_authenticated()
    google_account = blogger_service.get_google_account_details()
    
    user_ai_key = {"has_key": False, "masked_key": ""}
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        sess = ACTIVE_SESSIONS.get(token)
        if sess:
            key = db.get_user_zai_key(sess["user_id"])
            if key and len(key.strip()) >= 10:
                k = key.strip()
                masked = f"{k[:4]}••••••••{k[-4:]}" if len(k) > 10 else "••••••••"
                user_ai_key = {"has_key": True, "masked_key": masked}
    
    return {
        "success": True,
        "newspaper_name": Config.NEWSPAPER_NAME,
        "blog_id": Config.BLOGGER_BLOG_ID,
        "is_blogger_auth": is_auth,
        "google_account": google_account,
        "user_ai_key": user_ai_key,
        "quota": q_info,
        "zai_model": getattr(Config, "ZAI_MODEL", "glm-4.7-flash"),
        "theme": getattr(Config, "APP_THEME", "dark"),
        "wa_editor_name": getattr(Config, "WHATSAPP_EDITOR_NAME", "محرر الجريدة")
    }

@app.get("/api/blogger/quota")
def get_quota_details():
    return blogger_service.get_quota_info()

@app.post("/api/blogger/disconnect")
def disconnect_blogger_endpoint(user: dict = Depends(get_current_user)):
    """Disconnects the current Google account from Blogger and deletes local credentials."""
    blogger_service.disconnect(clear_blog_id=False)
    db.log_system("WARNING", "BloggerService", f"تم فك ربط وتسجيل خروج حساب Google بواسطة: {user.get('full_name')}", user_id=str(user.get("user_id")))
    return {"success": True, "message": "تم تسجيل الخروج من حساب Google وفك الربط بنجاح 🚪"}

@app.get("/api/blogger/auth-url")
def get_blogger_auth_url(request: Request):
    """Generates Google OAuth URL with prompt=select_account for switching or connecting a new Blogger Google account."""
    if not Config.CREDENTIALS_FILE.exists():
        raise HTTPException(status_code=500, detail="ملف credentials.json غير موجود في السيرفر")
    
    host = request.headers.get("host", f"localhost:{getattr(Config, 'CENTRAL_HUB_PORT', 8000)}")
    scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else request.url.scheme or "http"
    redirect_uri = f"{scheme}://{host}/api/auth/google/callback"
    
    flow = Flow.from_client_secrets_file(
        str(Config.CREDENTIALS_FILE),
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(prompt="select_account consent", access_type="offline")
    
    if flow.code_verifier:
        OAUTH_FLOW_CACHE[state] = flow.code_verifier
        OAUTH_FLOW_CACHE["_latest"] = flow.code_verifier
        OAUTH_FLOW_CACHE[state + "_is_blogger_link"] = True
        OAUTH_FLOW_CACHE["_latest_is_blogger_link"] = True
        
    accept = request.headers.get("accept", "")
    if "application/json" in accept or request.query_params.get("format") == "json":
        return JSONResponse({"success": True, "auth_url": auth_url})
    
    return RedirectResponse(url=auth_url, status_code=302)

@app.get("/api/stats")
def get_dashboard_stats():
    articles = db.get_all_articles()
    reporters = db.get_all_reporters()
    quota = blogger_service.get_quota_info()
    
    total_articles = len(articles)
    published_count = len([a for a in articles if a.get("blogger_status") == "PUBLISHED"])
    drafts_count = len([a for a in articles if a.get("blogger_status") == "DRAFT" or a.get("is_draft") == 1])
    unique_clients = len({a.get("client_name") for a in articles if a.get("client_name")})
    
    return {
        "success": True,
        "total_articles": total_articles,
        "published_count": published_count,
        "drafts_count": drafts_count,
        "unique_clients": unique_clients,
        "reporters_count": len(reporters),
        "quota_remaining": quota.get("remaining", 0),
        "quota_percent": round((quota.get("used", 0) / max(quota.get("limit", 1), 1)) * 100, 1)
    }


# =============================================================
# FILE & IMAGE UPLOADER ROUTER
# =============================================================

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="صيغة الملف غير مدعومة. يرجى رفع صورة بصيغة JPG أو PNG أو WEBP.")
    
    unique_name = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    dest_path = UPLOAD_DIR / unique_name
    
    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)
        
    return {
        "success": True,
        "filename": unique_name,
        "local_path": str(dest_path),
        "url": f"/storage/images/{unique_name}"
    }


# =============================================================
# LOGS & WEBSOCKETS ROUTER
# =============================================================

@app.get("/api/logs")
def get_system_logs(
    level: Optional[str] = "",
    module: Optional[str] = "",
    limit: int = 150,
    user: dict = Depends(get_current_user)
):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM system_logs"
        params = []
        conds = []
        
        # Non-admins only see their own operations
        if user.get("role") != "admin":
            user_conds = []
            if user.get("user_id"):
                user_conds.append("user_id = ?")
                params.append(str(user["user_id"]))
            if user.get("full_name"):
                user_conds.append("user_name = ?")
                params.append(user["full_name"])
            if user_conds:
                conds.append("(" + " OR ".join(user_conds) + ")")
            else:
                conds.append("1 = 0")
                
        if level and level != "ALL":
            conds.append("level = ?")
            params.append(level)
        if module and module != "ALL":
            conds.append("module = ?")
            params.append(module)
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return {"success": True, "logs": rows}

@app.websocket("/api/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket):
    global MAIN_LOOP
    if not MAIN_LOOP:
        try:
            MAIN_LOOP = asyncio.get_running_loop()
        except Exception:
            pass
    await websocket.accept()
    async with WS_LOCK:
        WS_CLIENTS.append(websocket)
    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_text(json.dumps({"type": "ping", "time": time.time()}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with WS_LOCK:
            if websocket in WS_CLIENTS:
                WS_CLIENTS.remove(websocket)

@app.post("/api/ws/test-broadcast")
def test_ws_broadcast(message: str = "اختبار الربط المباشر", percent: int = 50):
    broadcast_publish_step(percent, message)
    return {"success": True, "clients_count": len(WS_CLIENTS)}


# =============================================================
# STATIC FILES & FRONTEND SPA SERVING
# =============================================================

# Mount storage for images
app.mount("/storage/images", StaticFiles(directory=str(UPLOAD_DIR)), name="storage_images")

# Mount Web Directory
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIR.mkdir(parents=True, exist_ok=True)
(WEB_DIR / "css").mkdir(parents=True, exist_ok=True)
(WEB_DIR / "js").mkdir(parents=True, exist_ok=True)

if (WEB_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
if (WEB_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")
if (WEB_DIR / "img").exists():
    app.mount("/img", StaticFiles(directory=str(WEB_DIR / "img")), name="img")
if (PROJECT_ROOT / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(PROJECT_ROOT / "assets")), name="assets")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>جاري تجهيز الواجهة الأمامية...</h1>")

@app.get("/favicon.ico")
def serve_favicon():
    for candidate in [WEB_DIR / "favicon.ico", PROJECT_ROOT / "ico.ico"]:
        if candidate.exists():
            return FileResponse(candidate)
    return Response(status_code=204)

@app.get("/{full_path:path}", response_class=HTMLResponse)
def serve_spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("storage/"):
        raise HTTPException(status_code=404, detail="API route not found")
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)


# =============================================================
# SERVER RUNNER
# =============================================================

def run_web_server(host: str = "0.0.0.0", port: int = None):
    if port is None:
        port = int(os.getenv("CENTRAL_HUB_PORT", str(getattr(Config, "CENTRAL_HUB_PORT", 8000))))
    logger.info(f"🚀 بدء تشغيل منظومة جريدة تحت الضوء السحابية على: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    port = int(os.getenv("CENTRAL_HUB_PORT", str(getattr(Config, "CENTRAL_HUB_PORT", 8000))))
    run_web_server(host="0.0.0.0", port=port)
