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

import io
import csv
# Google OAuth removed — WordPress uses Application Passwords

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
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
from services.wordpress_service import wordpress_service as blogger_service
from services.whatsapp_service import (
    whatsapp_service,
    clean_egyptian_phone,
    extract_preferred_whatsapp_phone,
    extract_all_egyptian_phones
)
from services.central_sync_service import central_sync_service
from services.image_service import image_service
from services.lead_extractor import extract_lead_from_article
from telegram_bot.bot_controller import bot_controller
from services.facebook_service import fb_service
from press_automation.database import auto_db
from press_automation.browser_manager import browser_manager, BrowserManager
from press_automation.dispatchers.whatsapp_dispatcher import wa_dispatcher
from services.remote_automation_service import remote_auto_mgr

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

# AI Poster Generator Agent Router
from app.api.routes import router as poster_router
app.include_router(poster_router)

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
    # Auto-start Telegram Bot in background daemon thread if not disabled
    if os.getenv("DISABLE_TELEGRAM_BOT", "0").lower() not in ("true", "1", "yes"):
        try:
            threading.Thread(target=bot_controller.start, kwargs={"timeout": 20.0}, daemon=True).start()
        except Exception as be:
            logger.warning(f"Could not auto-start telegram bot on startup: {be}")
    else:
        logger.info("ℹ️ تم تعطيل تشغيل بوت تليجرام التلقائي (وضع تشغيل الأتمتة فقط لمنع التعارض).")


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
        "gender": user.get("gender", ""),
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
                session["gender"] = fresh.get("gender", session.get("gender", ""))
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

class UserIdentityUpdateRequest(BaseModel):
    full_name: str
    gender: str

class WhatsAppLinkGenerateRequest(BaseModel):
    raw_phone: str
    message: Optional[str] = ""
    client_name: Optional[str] = ""

class PromoteReviewArticleRequest(BaseModel):
    review_url: str
    generate_caption: Optional[bool] = False
    publish_to_facebook: Optional[bool] = False
    facebook_payment_status: Optional[str] = "EDITORIAL"
    facebook_amount: Optional[float] = 0.0

class FacebookQuickPublishRequest(BaseModel):
    message: str
    link: Optional[str] = ""
    image_url: Optional[str] = ""
    payment_status: Optional[str] = "EDITORIAL"
    amount: Optional[float] = 0.0
    currency: Optional[str] = "EGP"
    client_name: Optional[str] = ""
    payment_notes: Optional[str] = ""

class FacebookArticlePublishRequest(BaseModel):
    article_id: int
    custom_message: Optional[str] = None
    payment_status: Optional[str] = "EDITORIAL"
    amount: Optional[float] = 0.0
    client_name: Optional[str] = ""
    payment_notes: Optional[str] = ""

class FacebookPaymentUpdateRequest(BaseModel):
    payment_status: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    payment_notes: Optional[str] = None

class GenerateSocialCaptionRequest(BaseModel):
    title: Optional[str] = ""
    content: Optional[str] = ""
    main_url: str
    article_id: Optional[int] = None

class TransferPermissionsUpdateRequest(BaseModel):
    allowed_usernames: List[str]

class ReviewArticlesDeleteRequest(BaseModel):
    post_ids: Optional[List[str]] = []
    article_ids: Optional[List[int]] = []

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
    entity_type: Optional[str] = None
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
    entity_type: Optional[str] = None
    is_draft: Optional[bool] = False

class DirectPublishRequest(BaseModel):
    raw_notes: str
    image_url: Optional[str] = ""
    local_image_path: Optional[str] = ""
    entity_type: Optional[str] = None

class ReporterRegisterRequest(BaseModel):
    name: str
    telegram_id: str
    role: Optional[str] = "صحفي لدي"

class ReporterSaveRequest(BaseModel):
    telegram_id: str
    name: str
    role: Optional[str] = "صحفي لدي"
    api_key: Optional[str] = None

class BotBroadcastRequest(BaseModel):
    message: str

class ManualClientRegisterRequest(BaseModel):
    phone: str
    client_name: Optional[str] = ""
    contact_method: Optional[str] = "تواصل خارجي"
    notes: Optional[str] = ""

class UpdateCustomerLeadRequest(BaseModel):
    contact_status: Optional[str] = None
    notes: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    category: Optional[str] = None

class ExtractLeadFromUrlRequest(BaseModel):
    url: str

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

GOOGLE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]

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
    auth_url, state = flow.authorization_url(prompt="select_account consent", access_type="offline")
    
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
        
        # Save to personal token path for this specific journalist
        with open(personal_token_path, "wb") as f:
            pickle.dump(creds, f)
            
        # Only copy to master token.pickle and Config.TOKEN_FILE if this is master admin or if master token doesn't exist yet
        is_master_admin = (email == "shalllaby1@gmail.com") or (assigned_role == "admin" and not (PROJECT_ROOT / "token.pickle").exists())
        if is_master_admin or not (PROJECT_ROOT / "token.pickle").exists():
            with open(PROJECT_ROOT / "token.pickle", "wb") as f:
                pickle.dump(creds, f)
            if Config.TOKEN_FILE.parent.exists():
                with open(Config.TOKEN_FILE, "wb") as f:
                    pickle.dump(creds, f)
            try:
                blogger_service.authenticate()
                Config.GOOGLE_USER_EMAIL = email
                Config.update_env("GOOGLE_USER_EMAIL", email)
            except Exception:
                pass
        
        # If linking from Settings for an already logged-in session, attach token to that active user
        cookie_token = request.cookies.get("td_auth_token")
        sess = ACTIVE_SESSIONS.get(cookie_token) if cookie_token else None
        if is_blogger_link and sess and sess.get("user_id"):
            db.update_user_blogger_token(sess["user_id"], str(personal_token_path), avatar)
            sess["avatar"] = avatar or sess.get("avatar", "")
            logger.info(f"Attached personal Blogger token to active session user_id={sess['user_id']}")

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
        user["gender"] = fresh.get("gender", user.get("gender", ""))
    return {"success": True, "user": user}

@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    """Terminates active session."""
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        ACTIVE_SESSIONS.pop(token, None)
    return {"success": True, "message": "تم تسجيل الخروج بنجاح"}

@app.get("/api/auth/users", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def list_users():
    """Admin-only: lists all registered system users."""
    users = db.get_all_users()
    return {"success": True, "users": users}

@app.post("/api/auth/users/{user_id}/role", dependencies=[Depends(require_role(["admin"]))])
def update_user_role(user_id: int, payload: RoleUpdateRequest, admin_user: dict = Depends(get_current_user)):
    """Admin-only: updates a journalist or user role (admin, editor, journalist)."""
    if payload.role not in ["admin", "deputy_editor", "editor", "journalist"]:
        raise HTTPException(status_code=400, detail="الرتبة غير صالحة. الرتب المتاحة: admin, deputy_editor, editor, journalist")
    db.update_user(user_id, role=payload.role)
    for token, sess in list(ACTIVE_SESSIONS.items()):
        if sess.get("user_id") == user_id:
            sess["role"] = payload.role
    role_arabic = {"admin": "رئيس التحرير (Admin)", "deputy_editor": "نائب رئيس التحرير", "editor": "صحفي مميز (مدير تحرير)", "journalist": "صحفي معتمد"}.get(payload.role, payload.role)
    db.log_system("INFO", "Auth", f"تم تعديل رتبة المستخدم #{user_id} إلى {role_arabic}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "message": f"تم ترقية وتعيين رتبة الصحفي إلى: {role_arabic}"}

@app.get("/api/admin/activation-codes", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def list_activation_codes():
    """Admin & Deputy: lists all generated invitation/activation codes."""
    codes = db.get_all_activation_codes()
    return {"success": True, "codes": codes}

@app.post("/api/admin/activation-codes", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def create_new_activation_code(payload: CreateActivationRequest, admin_user: dict = Depends(get_current_user)):
    """Admin & Deputy: issues a new one-time activation code for onboarding a journalist."""
    assigned_role = payload.role
    if admin_user.get("role") != "admin":
        if payload.role != "journalist":
            raise HTTPException(status_code=403, detail="عفواً، لا تملك صلاحية منح رتب إدارية؛ منح الرتب والترقيات مقتصر على رئيس التحرير فقط 🔒")
        assigned_role = "journalist"
    code = db.create_activation_code(
        journalist_name=payload.name,
        journalist_phone=payload.phone,
        role=assigned_role,
        created_by=admin_user.get("full_name") or admin_user.get("username")
    )
    db.log_system("INFO", "Auth", f"تم إصدار كود تفعيل صحفي جديد: {code} للصحفي {payload.name} برتبة {assigned_role}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "code": code, "message": "تم توليد كود التفعيل الصحفي بنجاح"}

@app.delete("/api/admin/activation-codes/{code}", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def revoke_activation_code_endpoint(code: str, admin_user: dict = Depends(get_current_user)):
    """Admin & Deputy: revokes an unused activation code."""
    db.revoke_activation_code(code)
    db.log_system("INFO", "Auth", f"تم إيقاف كود التفعيل {code}", user_id=str(admin_user["user_id"]), user_name=admin_user["full_name"])
    return {"success": True, "message": f"تم إيقاف كود التفعيل: {code}"}

@app.post("/api/auth/users", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def create_user(payload: UserCreateRequest, current_user: dict = Depends(get_current_user)):
    """Creates a new system user."""
    existing = db.get_user_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="اسم المستخدم مسجل مسبقاً في النظام")
    
    assigned_role = payload.role
    if current_user.get("role") != "admin":
        assigned_role = "journalist"
    
    user_id = db.create_user(
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role=assigned_role,
        email=payload.email or ""
    )
    return {"success": True, "user_id": user_id, "message": "تم إنشاء حساب المستخدم بنجاح"}

@app.put("/api/auth/users/{user_id}", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def update_user_profile(user_id: int, payload: UserUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Updates user profile or password."""
    target_role = payload.role
    if current_user.get("role") != "admin":
        existing = db.get_user_by_id(user_id)
        if existing:
            target_role = existing.get("role", "journalist")
    db.update_user(
        user_id=user_id,
        full_name=payload.full_name,
        role=target_role,
        is_active=payload.is_active,
        password=payload.password
    )
    return {"success": True, "message": "تم تحديث بيانات المستخدم بنجاح"}

@app.delete("/api/auth/users/{user_id}", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """Admin-only: deletes a system user."""
    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="لا يمكنك حذف حسابك الشخصي الحالي")
    db.delete_user(user_id)
    return {"success": True, "message": "تم حذف الحساب بنجاح"}

@app.post("/api/user/identity")
def update_user_identity_endpoint(payload: UserIdentityUpdateRequest, user: dict = Depends(get_current_user)):
    """Updates user's official two-part full name and gender/identity in the platform."""
    name = (payload.full_name or "").strip()
    gender = (payload.gender or "").strip().lower()
    
    words = [w for w in name.split() if w.strip()]
    if len(words) < 2:
        raise HTTPException(status_code=400, detail="يرجى إدخال اسمك ثنائياً على الأقل (مثال: محمد ابراهيم أو هدى أحمد).")
        
    if gender not in ["male", "female"]:
        raise HTTPException(status_code=400, detail="يرجى تحديد الجنس بشكل صحيح (ذكر أو أنثى).")
        
    updated_user = db.update_user_identity(user["user_id"], name, gender)
    
    # Update active session immediately
    for token, sess in list(ACTIVE_SESSIONS.items()):
        if sess.get("user_id") == user["user_id"]:
            sess["full_name"] = name
            sess["gender"] = gender
            
    db.log_system(
        "INFO", "Auth",
        f"تحديث الهوية الصحفية للمستخدم: {name} ({gender})",
        user_id=str(user["user_id"]),
        user_name=name
    )
    
    return {
        "success": True,
        "message": f"أهلاً بك يا {name}، تم اعتماد هويتك الصحفية بنجاح!",
        "user": updated_user
    }

@app.get("/api/user/identity")
def get_user_identity_endpoint(user: dict = Depends(get_current_user)):
    """Returns current user identity configuration."""
    fresh = db.get_user_by_id(user["user_id"]) or {}
    return {
        "success": True,
        "full_name": fresh.get("full_name", user.get("full_name", "")),
        "gender": fresh.get("gender", user.get("gender", "")),
        "is_configured": bool(fresh.get("gender") and len((fresh.get("full_name") or "").split()) >= 2)
    }


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

@app.get("/api/ai/health")
def get_ai_health_status(user: dict = Depends(get_current_user)):
    """
    Live Health & Load Monitor for Z.AI / GLM model.
    Sends a minimal probe (1-2 tokens) and evaluates:
    - Latency (in seconds & ms)
    - Status (healthy / rate_limited / quota_exhausted / server_overload / missing_key)
    """
    user_key = db.get_user_zai_key(user["user_id"])
    active_key = user_key if (user_key and len(user_key.strip()) >= 10) else (getattr(Config, "ZAI_API_KEY", "") or getattr(Config, "TELEGRAM_ZAI_API_KEY", ""))
    active_model = getattr(Config, "ZAI_MODEL", "") or getattr(ai_service, "model", "glm-4.7-flash")

    if not active_key:
        return {
            "success": False,
            "status": "missing_key",
            "model": active_model,
            "latency_ms": 0,
            "latency_sec": 0,
            "has_personal_key": False,
            "message": "لم تقم بضبط مفتاح Z.AI الخاص بك بعد. يرجى إدخاله في الخانة أعلاه وحفظه لتفعيل الذكاء الاصطناعي."
        }

    t0 = time.time()
    try:
        from openai import OpenAI
        base_url = getattr(Config, "ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        client = OpenAI(api_key=active_key.strip(), base_url=base_url, timeout=10.0)
        resp = client.chat.completions.create(
            model=active_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=2,
            temperature=0.1
        )
        latency_sec = round(time.time() - t0, 2)
        latency_ms = int(latency_sec * 1000)

        speed_rating = "فائق السرعة ⚡" if latency_sec < 1.0 else ("سريع وطبيعي ✅" if latency_sec < 2.5 else "استجابة متوسطة ⏳")
        return {
            "success": True,
            "status": "healthy",
            "model": active_model,
            "latency_ms": latency_ms,
            "latency_sec": latency_sec,
            "speed_rating": speed_rating,
            "has_personal_key": bool(user_key),
            "message": f"السيرفر مستقر وسريع، لا يوجد ضغط وجاهز لتوليد المقالات واعتماد الأخبار فوراً ({speed_rating})."
        }

    except Exception as e:
        latency_sec = round(time.time() - t0, 2)
        latency_ms = int(latency_sec * 1000)
        err_str = str(e)
        logger.warning(f"AI Health ping test error: {err_str}")

        # Check for Rate Limit (Code 1302 or HTTP 429)
        if "1302" in err_str or "速率限制" in err_str or "rate limit" in err_str.lower() or "429" in err_str:
            return {
                "success": False,
                "status": "rate_limited",
                "code": 1302,
                "model": active_model,
                "latency_ms": latency_ms,
                "latency_sec": latency_sec,
                "has_personal_key": bool(user_key),
                "message": "يوجد ضغط مؤقت في معدل الطلبات بالدقيقة الحالية (Rate Limit). يرجى الانتظار 15-30 ثانية ثم إعادة المحاولة."
            }

        # Check for Quota exhausted (Code 1308, 1310)
        if "1308" in err_str or "1310" in err_str or "quota" in err_str.lower() or "余额" in err_str:
            return {
                "success": False,
                "status": "quota_exhausted",
                "code": 1308,
                "model": active_model,
                "latency_ms": latency_ms,
                "latency_sec": latency_sec,
                "has_personal_key": bool(user_key),
                "message": "انتهت الحصة الشهرية المجانية لهذا المفتاح. يرجى توليد مفتاح API جديد من موقع BigModel وتحديثه."
            }

        # Check for Server Overload / Timeout / 500 / 503
        if "500" in err_str or "502" in err_str or "503" in err_str or "504" in err_str or "timeout" in err_str.lower():
            return {
                "success": False,
                "status": "server_overload",
                "model": active_model,
                "latency_ms": latency_ms,
                "latency_sec": latency_sec,
                "has_personal_key": bool(user_key),
                "message": "خوادم Z.AI العالمية تواجه ضغطاً كبيراً أو صيانة خوادم لحظية. جرب بعد دقيقة أو دقيقتين."
            }

        # Authentication / Key error
        if "auth" in err_str.lower() or "key" in err_str.lower() or "401" in err_str:
            return {
                "success": False,
                "status": "auth_error",
                "model": active_model,
                "latency_ms": latency_ms,
                "latency_sec": latency_sec,
                "has_personal_key": bool(user_key),
                "message": "المفتاح المدخل غير صحيح أو تم إلغاؤه من المنصة. تأكد من نسخ المفتاح بدقة."
            }

        return {
            "success": False,
            "status": "error",
            "model": active_model,
            "latency_ms": latency_ms,
            "latency_sec": latency_sec,
            "has_personal_key": bool(user_key),
            "message": f"حدث خطأ أثناء فحص الاتصال: {err_str[:120]}"
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
        ai_data = ai_service.generate_article(
            payload.raw_notes,
            api_key=user_key,
            reporter_name=user.get("full_name", ""),
            reporter_id=str(user.get("user_id", ""))
        )
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
        err_str = str(e)
        if "1113" in err_str or "余额不足" in err_str or "无可用资源包" in err_str or "请充值" in err_str or "يوجد ضغط حاليا" in err_str or "حاول مرة أخرى" in err_str or "1302" in err_str:
            raise HTTPException(status_code=503, detail="حاول مرة أخرى.. يوجد ضغط حالياً ⏳")
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

@app.post("/api/publish-cooldown/reset")
def reset_cooldown(user: dict = Depends(get_current_user)):
    """Allows administrators and deputy editors to reset the publish cooldown immediately."""
    if user.get("role") not in ["admin", "deputy_editor", "editor"]:
        raise HTTPException(status_code=403, detail="غير مصرح")
    db.reset_publish_cooldown()
    return {"success": True, "message": "تم تصفير عداد ليمت الجريدة بنجاح."}


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

    user_gender = (user.get("gender") or "").strip().lower()
    editor_role = "صحفية لدي" if user_gender == "female" else "صحفي لدي"

    for a in paginated:
        c_phone = (a.get("client_phone") or "").strip()
        c_name = (a.get("client_name") or a.get("title") or "العميل الكريم").strip()
        post_url = (a.get("post_url") or "").strip()

        if not c_phone:
            combined = (a.get("raw_notes") or "") + " " + (a.get("final_html") or "")
            extracted = extract_preferred_whatsapp_phone(combined)
            if extracted:
                c_phone = extracted
                a["client_phone"] = c_phone

        e_type = whatsapp_service.detect_entity_type(c_name)

        art_author = (a.get("author_name") or "").strip()
        current_user_name = (user.get("full_name") or "").strip()
        if current_user_name and current_user_name not in ["محرر الجريدة", "Admin", "المشرف العام"]:
            editor_display_name = current_user_name
        elif art_author:
            editor_display_name = art_author
        elif current_user_name:
            editor_display_name = current_user_name
        else:
            editor_display_name = "محمد شلبي"

        wa_text = ""
        wa_url = ""
        if post_url:
            wa_text = whatsapp_service.format_message(
                name=c_name,
                post_url=post_url,
                editor_name=editor_display_name,
                editor_role=editor_role,
                entity_type=e_type
            )
            if c_phone:
                wa_url = whatsapp_service.generate_whatsapp_click_link(
                    phone=c_phone,
                    name=c_name,
                    post_url=post_url,
                    entity_type=e_type,
                    editor_name=editor_display_name,
                    editor_role=editor_role
                )

        a["whatsapp_text"] = wa_text
        a["whatsapp_url"] = wa_url

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
    if user.get("role") not in ["admin", "deputy_editor"]:
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
        if existing and user.get("role") not in ["admin", "deputy_editor"]:
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
    # Admins, Deputy Editors, and Editors have direct publishing privilege without waiting
    is_privileged = user.get("role") in ["admin", "deputy_editor", "editor"]
    if not is_privileged:
        cooldown_rem = db.get_publish_cooldown_remaining(60)
        if cooldown_rem > 0:
            raise HTTPException(status_code=429, detail=f"⚠️ برجاء الانتظار {cooldown_rem} ثانية لضبط تدفق نشر الجريدة قبل النشر مجدداً.")
    
    # WordPress service is always authenticated via App Passwords
    if False:
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
            title=payload.title if 'payload' in locals() and hasattr(payload, 'title') else title,
            content_html=final_html_to_publish if 'final_html_to_publish' in locals() else final_html,
            labels=labels_list,
            is_draft=getattr(payload, 'is_draft', False),
            meta_description=getattr(payload, 'meta_description', '') or getattr(payload, 'slug', ''),
            slug=getattr(payload, 'slug', None),
            image_url=remote_img_url or None
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
            
            user_gender = (user.get("gender") or "").strip().lower()
            editor_name = user.get("full_name") or "محرر الجريدة"
            editor_role = "صحفية لدي" if user_gender == "female" else "صحفي لدي"

            wa_text = whatsapp_service.format_message(
                name=c_name,
                post_url=post_url,
                entity_type=e_type,
                editor_name=editor_name,
                editor_role=editor_role
            )
            wa_url = whatsapp_service.generate_whatsapp_click_link(
                phone=payload.client_phone,
                name=c_name,
                post_url=post_url,
                entity_type=e_type,
                editor_name=editor_name,
                editor_role=editor_role
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Publish failed: {e}")
        db.log_system("ERROR", "BloggerService", f"فشل نشر المقال #{article_id}: {e}", user_id=str(user["user_id"]), user_name=user["full_name"])
        raise HTTPException(status_code=500, detail=f"فشل النشر على Blogger: {str(e)}")

@app.post("/api/articles/direct-publish")
def direct_one_click_publish(payload: DirectPublishRequest, user: dict = Depends(get_current_user)):
    # Admins, Deputy Editors, and Editors publish directly without waiting
    is_privileged = user.get("role") in ["admin", "deputy_editor", "editor"]
    if not is_privileged:
        rem = db.get_publish_cooldown_remaining(60)
        if rem > 0:
            raise HTTPException(status_code=429, detail=f"⚠️ ليمت الجريدة مفعل: يرجى الانتظار {rem} ثانية قبل نشر هذا المقال.")
    
    # WordPress service is always authenticated via App Passwords
    if False:
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
        ai_data = ai_service.generate_article(
            payload.raw_notes,
            api_key=user_key,
            reporter_name=user.get("full_name", ""),
            reporter_id=str(user.get("user_id", ""))
        )
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
            "blogger_status": "PROCESSING",
            "reporter_telegram_id": str(user.get("user_id", "")),
            "author_email": user.get("email") or "",
            "author_name": user.get("full_name") or ""
        })
        
        broadcast_publish_step(84, "🚀 [5/5] إرسال المقال والبث السحابي المباشر إلى Google Blogger...")
        pub_res = blogger_service.publish_post(
            title=payload.title if 'payload' in locals() and hasattr(payload, 'title') else title,
            content_html=final_html_to_publish if 'final_html_to_publish' in locals() else final_html,
            labels=labels_list,
            is_draft=getattr(payload, 'is_draft', False),
            meta_description=getattr(payload, 'meta_description', '') or getattr(payload, 'slug', ''),
            slug=getattr(payload, 'slug', None),
            image_url=remote_img_url or None
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
            # Auto-detect entity type from LLM output (with rule-based fallback)
            e_type = ai_data.get("entity_type") or getattr(payload, "entity_type", None)
            if not e_type or e_type not in ["male", "female", "plural"]:
                e_type = whatsapp_service.detect_entity_type(c_name or payload.raw_notes)
            if e_type in ["group", "plural"]:
                e_type = "plural"

            user_gender = (user.get("gender") or "").strip().lower()
            editor_name = user.get("full_name") or "محرر الجريدة"
            editor_role = "صحفية لدي" if user_gender == "female" else "صحفي لدي"

            wa_text = whatsapp_service.format_message(
                name=c_name,
                post_url=post_url,
                entity_type=e_type,
                editor_name=editor_name,
                editor_role=editor_role
            )
            wa_url = whatsapp_service.generate_whatsapp_click_link(
                phone=client_phone,
                name=c_name,
                post_url=post_url,
                entity_type=e_type,
                editor_name=editor_name,
                editor_role=editor_role
            )
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Direct publish failed: {e}")
        if 'art_id' in locals() and art_id:
            try:
                db.update_article(art_id, {"blogger_status": "FAILED"})
            except Exception:
                pass
        db.log_system("ERROR", "Pipeline", f"فشل النشر السريع: {e}", user_id=str(user["user_id"]), user_name=user["full_name"])
        err_str = str(e)
        if "1113" in err_str or "余额不足" in err_str or "无可用资源包" in err_str or "请充值" in err_str or "يوجد ضغط حاليا" in err_str or "حاول مرة أخرى" in err_str or "1302" in err_str:
            raise HTTPException(status_code=503, detail="حاول مرة أخرى.. يوجد ضغط حالياً ⏳")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.delete("/api/articles/{article_id}", dependencies=[Depends(require_role(["admin", "editor", "journalist"]))])
def delete_article(article_id: int, user: dict = Depends(get_current_user)):
    with db.get_connection() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(status_code=404, detail="المقال غير موجود")
        art = dict(art)
        if user.get("role") not in ["admin", "deputy_editor"]:
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
# SMART AI SURGICAL ARTICLE EDITOR (GEMINI)
# =============================================================

class SmartEditFetchRequest(BaseModel):
    url: str

class SmartEditApplyRequest(BaseModel):
    url: str
    client_notes: str
    auto_publish: bool = True
    sync_both_sites: bool = True

@app.post("/api/articles/smart-edit/fetch")
def smart_edit_fetch_article_endpoint(payload: SmartEditFetchRequest, user: dict = Depends(get_current_user)):
    """
    Fetches article details from either Review site or Main site via URL.
    Returns title, content snippet, post_id, site_type, and categories.
    """
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="يرجى إدخال رابط المقال")
    
    res = blogger_service.fetch_post_by_url(url)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "تعذر جلب المقال من الرابط"))
    
    clean_text = re.sub(r"<[^>]+>", " ", res.get("content_html", ""))
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    
    return {
        "success": True,
        "site_type": res.get("site_type"),
        "site_url": res.get("site_url"),
        "post_id": res.get("post_id"),
        "title": res.get("title"),
        "link": res.get("link"),
        "slug": res.get("slug"),
        "content_length": len(res.get("content_html", "")),
        "preview_text": clean_text[:400] + "..." if len(clean_text) > 400 else clean_text
    }

@app.post("/api/articles/smart-edit/apply")
def smart_edit_apply_article_endpoint(payload: SmartEditApplyRequest, user: dict = Depends(get_current_user)):
    """
    Surgically applies client modifications to the article using Google Gemini (with fallbacks).
    Strictly preserves untouched content, structure, and newspaper guidelines.
    Optionally auto-updates WordPress immediately and syncs across Review and Main sites.
    """
    url = (payload.url or "").strip()
    notes = (payload.client_notes or "").strip()
    
    if not url:
        raise HTTPException(status_code=400, detail="يرجى إدخال رابط المقال")
    if not notes:
        raise HTTPException(status_code=400, detail="يرجى إدخال ملاحظات أو تعديلات العميل")
        
    # 1. Fetch current article from site
    fetch_res = blogger_service.fetch_post_by_url(url)
    if not fetch_res.get("success"):
        raise HTTPException(status_code=404, detail=fetch_res.get("error", "تعذر جلب المقال من الرابط للتعديل"))
        
    orig_title = fetch_res.get("title", "")
    orig_content = fetch_res.get("content_html", "")
    site_type = fetch_res.get("site_type", "review")
    post_id = fetch_res.get("post_id")
    post_link = fetch_res.get("link", url)
    
    # 2. Run surgical edit with Gemini
    edit_res = ai_service.apply_surgical_client_edits(
        original_title=orig_title,
        original_content=orig_content,
        client_notes=notes
    )
    
    if not edit_res.get("success"):
        raise HTTPException(status_code=500, detail=edit_res.get("error", "فشلت عملية التعديل بالذكاء الاصطناعي"))
        
    new_title = edit_res.get("title", orig_title)
    new_content = edit_res.get("content", orig_content)
    changes_summary = edit_res.get("changes_summary", "")
    engine = edit_res.get("engine", "Gemini")
    
    # 3. Auto-publish if requested
    publish_result = None
    synced_sister = False
    
    if payload.auto_publish and post_id and str(post_id) != "0":
        up_res = blogger_service.update_post(
            site_type=site_type,
            post_id=str(post_id),
            title=new_title,
            content_html=new_content
        )
        publish_result = up_res
        
        # Sync to sister site if requested
        if payload.sync_both_sites:
            sister_site = "main" if site_type == "review" else "review"
            sister_url = blogger_service.MAIN_SITE_URL if sister_site == "main" else blogger_service.REVIEW_SITE_URL
            sister_headers = blogger_service.main_account.get_headers() if sister_site == "main" else blogger_service.platform_account.get_headers()
            raw_slug = fetch_res.get("slug")
            if raw_slug:
                try:
                    sr = requests.get(
                        f"{sister_url}/wp-json/wp/v2/posts",
                        params={"slug": raw_slug, "_fields": "id"},
                        headers=sister_headers,
                        timeout=8
                    )
                    if sr.status_code == 200 and sr.json():
                        sister_post_id = str(sr.json()[0].get("id"))
                        blogger_service.update_post(
                            site_type=sister_site,
                            post_id=sister_post_id,
                            title=new_title,
                            content_html=new_content
                        )
                        synced_sister = True
                except Exception as sync_e:
                    logger.warning(f"[SmartEdit] Could not sync to sister site {sister_site}: {sync_e}")

    # Save backup snapshot for 1-click Undo / Recovery
    backup_id = None
    if post_id and str(post_id) != "0":
        try:
            backup_id = db.save_article_edit_backup(
                post_id=str(post_id),
                site_type=site_type,
                article_url=post_link,
                original_title=orig_title,
                original_content=orig_content,
                modified_title=new_title,
                modified_content=new_content,
                client_notes=notes,
                user_id=str(user.get("user_id", "")),
                user_name=str(user.get("full_name", ""))
            )
        except Exception as be:
            logger.warning(f"[SmartEdit] Failed to save backup snapshot: {be}")

    # Log in system logs
    log_msg = f"تعديل جراحي بالذكاء ({engine}) للمقال: '{new_title}' (ID: {post_id} - {site_type}). التعديلات: {changes_summary[:120]}"
    db.log_system("INFO", "SmartEdit", log_msg, user_id=str(user.get("user_id")), user_name=user.get("full_name"))

    return {
        "success": True,
        "message": "تم تطبيق تعديلات العميل وتحديث المقال بنجاح! 🚀",
        "engine": engine,
        "site_type": site_type,
        "post_id": post_id,
        "backup_id": backup_id,
        "article_url": post_link,
        "original_title": orig_title,
        "original_content": orig_content,
        "new_title": new_title,
        "changes_summary": changes_summary,
        "published": bool(payload.auto_publish),
        "synced_sister_site": synced_sister,
        "preview_html": new_content
    }


class SmartEditUndoRequest(BaseModel):
    url: str
    post_id: str
    site_type: str = "review"
    backup_title: Optional[str] = None
    backup_content: Optional[str] = None
    backup_id: Optional[int] = None
    sync_both_sites: bool = False

@app.post("/api/articles/smart-edit/undo")
def smart_edit_undo_article_endpoint(payload: SmartEditUndoRequest, user: dict = Depends(get_current_user)):
    """
    Restores the original article title and content in-place if client edits need to be rolled back.
    """
    import urllib.parse
    post_id = str(payload.post_id).strip()
    site_type = payload.site_type or "review"
    url = (payload.url or "").strip()

    orig_title = payload.backup_title
    orig_content = payload.backup_content
    backup_rec = None

    if not orig_title or not orig_content:
        backup_rec = db.get_latest_article_edit_backup(post_id, site_type)
        if backup_rec:
            orig_title = orig_title or backup_rec.get("original_title")
            orig_content = orig_content or backup_rec.get("original_content")

    if not orig_title or not orig_content:
        raise HTTPException(status_code=400, detail="لم يتم العثور على نسخة أصلية محفوظة لهذا المقال للتراجع عنها.")

    # Revert post in-place on WordPress
    up_res = blogger_service.update_post(
        site_type=site_type,
        post_id=post_id,
        title=orig_title,
        content_html=orig_content
    )
    if not up_res.get("success"):
        raise HTTPException(status_code=500, detail=up_res.get("error", "فشلت استعادة المقال الأصلي على ووردبريس"))

    # Revert sister site if sync_both_sites was enabled
    synced_sister = False
    if payload.sync_both_sites:
        sister_site = "main" if site_type == "review" else "review"
        sister_url = blogger_service.MAIN_SITE_URL if sister_site == "main" else blogger_service.REVIEW_SITE_URL
        sister_headers = blogger_service.main_account.get_headers() if sister_site == "main" else blogger_service.platform_account.get_headers()

        parsed_slug = ""
        if url:
            parsed = urllib.parse.urlparse(url)
            slug_parts = [p for p in parsed.path.strip("/").split("/") if p]
            parsed_slug = slug_parts[-1].replace(".html", "") if slug_parts else ""

        if parsed_slug:
            try:
                sr = requests.get(
                    f"{sister_url}/wp-json/wp/v2/posts",
                    params={"slug": parsed_slug, "_fields": "id"},
                    headers=sister_headers,
                    timeout=8
                )
                if sr.status_code == 200 and sr.json():
                    sister_post_id = str(sr.json()[0].get("id"))
                    blogger_service.update_post(
                        site_type=sister_site,
                        post_id=sister_post_id,
                        title=orig_title,
                        content_html=orig_content
                    )
                    synced_sister = True
            except Exception as se:
                logger.warning(f"[SmartEditUndo] Could not sync undo to sister site: {se}")

    if backup_rec and backup_rec.get("id"):
        db.mark_article_edit_backup_restored(backup_rec["id"])
    elif payload.backup_id:
        db.mark_article_edit_backup_restored(payload.backup_id)

    # Log in system logs
    log_msg = f"تم التراجع واستعادة المقال الأصلي (Undo): '{orig_title}' (ID: {post_id} - {site_type}) بنجاح."
    db.log_system("INFO", "SmartEditUndo", log_msg, user_id=str(user.get("user_id")), user_name=user.get("full_name"))

    return {
        "success": True,
        "message": "تم التراجع عن التعديل واستعادة المقال الأصلي كما كان بنجاح! ↩️",
        "post_id": post_id,
        "site_type": site_type,
        "article_url": up_res.get("post_url", url),
        "title": orig_title,
        "preview_html": orig_content,
        "synced_sister_site": synced_sister
    }


# =============================================================
# REPORTERS & TELEGRAM BOT MANAGEMENT ROUTER (ADMIN CONTROL)
# =============================================================

@app.get("/api/admin/bot/status", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_bot_status():
    telemetry = bot_controller.get_detailed_telemetry()
    return {"success": True, "telemetry": telemetry}

@app.post("/api/admin/bot/start", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def start_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.start(timeout=10.0)
    db.log_system("INFO", "BotAdmin", f"تشغيل بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    if not success:
        return {"success": False, "error": bot_controller.last_error or "تعذر بدء تشغيل البوت"}
    return {"success": True, "message": "تم إطلاق بوت التليجرام وتشغيله بنجاح ⚡"}

@app.post("/api/admin/bot/stop", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def stop_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.stop()
    db.log_system("WARNING", "BotAdmin", f"إيقاف بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    return {"success": success, "message": "تم إيقاف بوت التليجرام بنجاح ⏹️"}

@app.post("/api/admin/bot/restart", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def restart_bot(user: dict = Depends(get_current_user)):
    success = bot_controller.restart(timeout=15.0)
    db.log_system("INFO", "BotAdmin", f"إعادة تشغيل بوت التليجرام بواسطة المسؤول: {user.get('full_name')} ({user.get('role')})", user_id=str(user.get("user_id")))
    if not success:
        return {"success": False, "error": bot_controller.last_error or "تعذر إعادة تشغيل البوت"}
    return {"success": True, "message": "تمت إعادة تشغيل بوت التليجرام وتنشيطه بنجاح 🔄"}

@app.post("/api/admin/bot/broadcast", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def broadcast_bot(payload: BotBroadcastRequest, user: dict = Depends(get_current_user)):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="لا يمكن إرسال رسالة تعميم فارغة")
    res = bot_controller.broadcast_message(msg)
    db.log_system("INFO", "BotAdmin", f"إرسال تعميم للصحفيين عبر البوت: '{msg[:40]}...' إلى {res.get('sent_count', 0)} صحفي", user_id=str(user.get("user_id")))
    return res

@app.get("/api/admin/bot/logs", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_bot_logs(limit: int = 100):
    logs = db.get_bot_logs(limit=limit)
    return {"success": True, "logs": logs}

@app.get("/api/reporters", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def list_reporters():
    reporters = db.get_reporters_with_stats()
    return {"success": True, "reporters": reporters}

@app.post("/api/reporters", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def register_reporter(payload: ReporterSaveRequest, user: dict = Depends(get_current_user)):
    api_key = payload.api_key.strip() if payload.api_key else f"TD-{secrets.token_hex(8).upper()}"
    db.save_reporter(
        telegram_id=payload.telegram_id.strip(),
        name=payload.name.strip(),
        role=payload.role.strip() if payload.role else "صحفي لدي",
        api_key=api_key
    )
    db.log_system("INFO", "Reporters", f"تسجيل/تحديث المراسل {payload.name} ({payload.telegram_id})", user_id=str(user.get("user_id")))
    return {"success": True, "api_key": api_key, "message": "تم حفظ بيانات الصحفي واعتماد المفتاح بنجاح"}

@app.delete("/api/reporters/{telegram_id}", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
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
# WHATSAPP TOOLS & PHONE NORMALIZER ROUTER
# =============================================================

@app.post("/api/tools/whatsapp-link")
def generate_whatsapp_link_endpoint(payload: WhatsAppLinkGenerateRequest, authorization: Optional[str] = Header(None)):
    """
    Normalizes any raw phone number string in any format, detects telecom operator,
    and returns ready-to-use WhatsApp direct links and formatted numbers.
    """
    res = whatsapp_service.normalize_phone_and_generate_link(
        raw_input=payload.raw_phone,
        message=payload.message or "",
        client_name=payload.client_name or ""
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "تعذر معالجة رقم الهاتف المدخل"))
    
    return res


# =============================================================
# REVIEW TO MAIN NEWSPAPER PROMOTION ROUTER
# =============================================================

@app.get("/api/transfer/permissions")
def get_transfer_permissions(user: dict = Depends(get_current_user)):
    """
    Checks if current user has permission to transfer articles from Review to Main blog.
    Returns permission status, and for Admins/Chief Editors, returns full list of users and allowed usernames.
    """
    is_allowed = db.is_user_allowed_transfer(user)
    is_admin = (user.get("role") or "").strip().lower() in ["admin", "deputy_editor", "editor"]
    
    allowed_list = []
    all_users = []
    if is_admin:
        allowed_list = db.get_allowed_transfer_usernames()
        all_users = [
            {
                "id": u.get("id"),
                "username": u.get("username"),
                "full_name": u.get("full_name") or u.get("username"),
                "role": u.get("role"),
                "is_allowed": (u.get("role") in ["admin", "deputy_editor", "editor"]) or (u.get("username", "").lower() in allowed_list)
            }
            for u in db.get_all_users()
        ]

    return {
        "success": True,
        "is_allowed": is_allowed,
        "is_admin": is_admin,
        "allowed_usernames": allowed_list,
        "users": all_users,
        "all_users": all_users
    }

@app.post("/api/transfer/permissions")
def update_transfer_permissions(payload: TransferPermissionsUpdateRequest, user: dict = Depends(require_role(["admin", "editor"]))):
    """
    Only for Chief Editor / Admin:
    Updates the list of usernames explicitly allowed to use the Review -> Main promote tool.
    """
    db.set_allowed_transfer_usernames(payload.allowed_usernames)
    updated_list = db.get_allowed_transfer_usernames()
    db.log_system("INFO", "Permissions", f"تم تحديث صلاحيات نقل الأخبار للحسابات: {', '.join(updated_list)}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
    return {
        "success": True,
        "allowed_usernames": updated_list
    }

@app.post("/api/articles/promote-review")
def promote_review_article_endpoint(payload: PromoteReviewArticleRequest, user: dict = Depends(get_current_user)):
    """
    Transfers an article from the Review WordPress site (review.tahteldoo.com)
    to the Primary / Main WordPress site (www.tahteldoo.com).
    Uses WordPress REST API with Application Password authentication.
    Strictly enforces permission: Editor-in-Chief / Admin or specifically allowed username.
    """
    if not db.is_user_allowed_transfer(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="⚠️ عذراً، هذه الميزة مخصصة لرئيس التحرير أو الحسابات المصرح لها بالاسم فقط."
        )

    clean_url = (payload.review_url or "").strip()
    if not clean_url or ("http://" not in clean_url and "https://" not in clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يرجى إدخال رابط صالح لخبر الريفيو (مثال: https://review.tahteldoo.com/...)"
        )

    try:
        # WordPress Application Password auth — token_path not needed
        res = blogger_service.transfer_review_to_main(clean_url)
        
        title = res.get("title", "")
        main_url = res.get("main_url", "")
        main_post_id = res.get("main_post_id", "")
        labels_list = res.get("labels", ["أخبار"])
        labels_str = ", ".join(labels_list) if isinstance(labels_list, list) else str(labels_list)

        art_id = db.save_article({
            "title": title,
            "slug": title,
            "labels": labels_str,
            "raw_notes": f"منقول تلقائياً من جريدة الريفيو: {clean_url}",
            "final_html": res.get("content_html", ""),
            "post_id": main_post_id,
            "post_url": main_url,
            "blogger_status": "PUBLISHED",
            "author_email": user.get("email") or "",
            "author_name": user.get("full_name") or "",
            "reporter_telegram_id": str(user.get("user_id", ""))
        })

        db.log_system("INFO", "Promotion", f"تم نقل واعتماد الخبر بنجاح إلى الجريدة الأساسية: '{title}' -> {main_url}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))

        content_html = res.get("content_html", "")

        # 🔒 العملية الخلفية السرية: سحب وتحليل بيانات العميل تلقائياً لرئيس التحرير (مخفية 100% عن الصحفيين)
        try:
            lead_info = extract_lead_from_article(
                title=title,
                content_html=content_html,
                labels=labels_str
            )
            final_live_url = (main_url or "").strip()
            if not final_live_url or not final_live_url.startswith("http"):
                final_live_url = clean_url
            if final_live_url.startswith("http://"):
                final_live_url = final_live_url.replace("http://", "https://", 1)

            lead_record = {
                "client_name": lead_info.get("client_name") or "عميل كريم",
                "client_phone": lead_info.get("client_phone") or "",
                "category": lead_info.get("category") or "عام",
                "article_title": title,
                "article_url": final_live_url,
                "article_id": art_id,
                "promoted_by_name": user.get("full_name") or user.get("username") or "صحفي",
                "promoted_by_email": user.get("email") or "",
                "contact_status": "NEW"
            }
            lead_id = db.save_customer_lead(lead_record)
            logger.info(f"✅ تم سحب بيانات العميل تلقائياً للـ CRM #{lead_id}: {lead_record['client_name']} ({lead_record['client_phone']})")
        except Exception as lead_err:
            logger.warning(f"تنبيه صامت (غير مؤثر على النشر) أثناء سحب العميل: {lead_err}")

        # 📢 نشر تلقائي اختياري على صفحة فيسبوك للجريدة
        fb_post_info = None
        if getattr(payload, "publish_to_facebook", False):
            try:
                fb_post_info = fb_service.publish_article(
                    article_data={
                        "id": art_id,
                        "title": title,
                        "post_url": main_url,
                        "summary": title,
                        "category": labels_str,
                        "client_name": lead_info.get("client_name") if 'lead_info' in locals() else "",
                        "image_url": res.get("image_url") or ""
                    },
                    payment_status=getattr(payload, "facebook_payment_status", "EDITORIAL") or "EDITORIAL",
                    amount=getattr(payload, "facebook_amount", 0.0) or 0.0,
                    db=db,
                    published_by_name=user.get("full_name") or user.get("username") or "رئيس التحرير"
                )
                logger.info(f"✅ تم النشر التلقائي للخبر #{art_id} على فيسبوك بنجاح: {fb_post_info.get('post_url')}")
            except Exception as fb_err:
                logger.warning(f"تنبيه صامت: تعذر النشر على فيسبوك أثناء الترقية: {fb_err}")

        # If no caption requested (default behavior: only save data and promote article), return immediately
        if not getattr(payload, "generate_caption", False):
            return {
                "success": True,
                "article_id": art_id,
                "title": title,
                "main_url": main_url,
                "main_post_id": main_post_id,
                "original_review_url": clean_url,
                "content_html": content_html,
                "caption": "",
                "facebook": fb_post_info
            }

        # Generate Social Media Caption with AI (for single-step callers)
        caption = ""
        try:
            caption = ai_service.generate_social_caption(
                article_title=title,
                article_content=content_html,
                main_url=main_url
            )
        except Exception as cap_err:
            logger.warning(f"Error generating social caption: {cap_err}")
            caption = f"تسلّط «تحت الضوء الإخبارية» الضوء على {title}..\n\n📰 رابط الخبر كاملًا:\n{main_url}\n📞 للتواصل مع جريدة تحت الضوء الإخبارية:\n01094775924\nتحت الضوء الإخبارية.. نسلط الضوء على كل ما يهمك."

        return {
            "success": True,
            "article_id": art_id,
            "title": title,
            "main_url": main_url,
            "main_post_id": main_post_id,
            "original_review_url": clean_url,
            "content_html": content_html,
            "caption": caption,
            "facebook": fb_post_info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to promote review article: {e}")
        db.log_system("ERROR", "Promotion", f"فشل نقل خبر الريفيو: {e}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/api/articles/generate-caption")
def generate_article_caption_endpoint(payload: GenerateSocialCaptionRequest, user: dict = Depends(get_current_user)):
    """
    Progressive Step 2: Generates professional social media caption for an article
    using AI with structured newspaper template and direct plain URL.
    """
    title = (payload.title or "").strip()
    content = (payload.content or "").strip()
    main_url = (payload.main_url or "").strip()

    if not content and payload.article_id:
        art = db.get_article(payload.article_id)
        if art:
            if not title:
                title = art.get("title", "")
            content = art.get("final_html", "") or art.get("raw_notes", "")
            if not main_url:
                main_url = art.get("post_url", "")

    if not main_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="رابط المقال المنشور مطلوب لتوليد الكابشن."
        )

    try:
        caption = ai_service.generate_social_caption(
            article_title=title,
            article_content=content,
            main_url=main_url
        )
        return {
            "success": True,
            "caption": caption
        }
    except Exception as e:
        logger.error(f"Failed to generate caption: {e}")
        fallback_caption = f"تسلّط «تحت الضوء الإخبارية» الضوء على {title}..\n\n📰 رابط الخبر كاملًا:\n{main_url}\n📞 للتواصل مع جريدة تحت الضوء الإخبارية:\n01094775924\nتحت الضوء الإخبارية.. نسلط الضوء على كل ما يهمك."
        return {
            "success": True,
            "caption": fallback_caption
        }


# =============================================================
# REVIEW ARTICLES CLEANUP ENDPOINTS (CHIEF & DEPUTY EDITOR)
# =============================================================

@app.get("/api/admin/review-cleanup/dates")
def get_review_cleanup_dates_endpoint(user: dict = Depends(require_role(["admin", "deputy_editor"]))):
    """
    Returns a summary list of dates with review articles count.
    Exclusively accessible to Chief Editor ('admin') and Deputy Editor ('deputy_editor').
    """
    dates = db.get_review_dates_summary()
    return {
        "success": True,
        "dates": dates
    }

@app.get("/api/admin/review-cleanup/day-details")
def get_review_cleanup_day_details_endpoint(date: str, user: dict = Depends(require_role(["admin", "deputy_editor"]))):
    """
    Returns review articles for a given day with real-time comparison against Main newspaper articles.
    Articles present on the Main blog are marked is_on_main = True (Approved/Kept).
    Articles absent from Main blog are marked is_on_main = False (Targeted for Deletion).
    """
    if not date or not re.match(r"^\d{4}-\d{2}-\d{2}$", date.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="تاريخ غير صالح. الصيغة المطلوبة: YYYY-MM-DD"
        )
    
    user_tok = user.get("blogger_token_path")
    details = db.get_review_day_articles_with_main_match(date.strip(), blogger_service=blogger_service, token_path=user_tok)
    return {
        "success": True,
        **details
    }

@app.post("/api/admin/review-cleanup/delete")
def delete_review_cleanup_articles_endpoint(payload: ReviewArticlesDeleteRequest, user: dict = Depends(require_role(["admin", "deputy_editor"]))):
    """
    Deletes review articles from both Blogger and the database.
    Can be used for:
    - Only unapproved articles
    - All articles of a day
    - Selected articles
    """
    post_ids = [str(p).strip() for p in (payload.post_ids or []) if str(p).strip()]
    article_ids = [int(a) for a in (payload.article_ids or []) if a]

    if not post_ids and not article_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لم يتم تحديد أي مقالات للحذف"
        )

    # 1. Delete from Blogger Review Blog
    user_tok = user.get("blogger_token_path")
    blogger_res = blogger_service.delete_review_posts(post_ids, token_path=user_tok)

    # 2. Delete from local database
    db_deleted = db.bulk_delete_review_articles(post_ids=post_ids, article_ids=article_ids)

    # Log action
    db.log_system(
        "INFO",
        "ReviewCleanup",
        f"تم حذف {blogger_res.get('deleted_count', 0)} مقال ريفيو من بلوجر و {db_deleted} من قاعدة البيانات بواسطة {user.get('full_name')} ({user.get('role')})",
        user_id=str(user.get("user_id")),
        user_name=user.get("full_name")
    )

    return {
        "success": True,
        "blogger_deleted_count": blogger_res.get("deleted_count", 0),
        "blogger_deleted_ids": blogger_res.get("deleted_ids", []),
        "db_deleted_count": db_deleted,
        "failed_count": blogger_res.get("failed_count", 0),
        "failed": blogger_res.get("failed", [])
    }


# =============================================================
# CHIEF EDITOR EXCLUSIVE CRM: CUSTOMER LEADS ENDPOINTS
# =============================================================

@app.get("/api/admin/customer-leads", dependencies=[Depends(require_role(["admin"]))])
def get_customer_leads_endpoint(
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 50
):
    """
    Exclusive for Chief Editor (Admin):
    Retrieves paginated customer leads extracted automatically during article promotions.
    """
    res = db.get_customer_leads(search=search, category=category, status=status, page=page, limit=limit)
    return {
        "success": True,
        **res
    }

@app.put("/api/admin/customer-leads/{lead_id}", dependencies=[Depends(require_role(["admin"]))])
def update_customer_lead_endpoint(lead_id: int, payload: UpdateCustomerLeadRequest):
    """
    Exclusive for Chief Editor (Admin):
    Updates lead contact status (NEW, CONTACTED, VIP, NOT_INTERESTED), notes, or contact info.
    """
    ok = db.update_customer_lead(
        lead_id=lead_id,
        status=payload.contact_status,
        notes=payload.notes,
        client_name=payload.client_name,
        client_phone=payload.client_phone,
        category=payload.category
    )
    if not ok:
        raise HTTPException(status_code=404, detail="تعذر العثور على العميل أو تعديل بياناته")
    return {"success": True, "message": "تم تحديث بيانات وملاحظات العميل بنجاح"}

@app.delete("/api/admin/customer-leads/{lead_id}", dependencies=[Depends(require_role(["admin"]))])
def delete_customer_lead_endpoint(lead_id: int, user: dict = Depends(require_role(["admin"]))):
    """
    Exclusive for Chief Editor (Admin):
    Deletes a customer lead record permanently.
    """
    ok = db.delete_customer_lead(lead_id)
    if not ok:
        raise HTTPException(status_code=404, detail="تعذر العثور على سجل العميل للحذف")
    db.log_system("INFO", "CustomerLeads", f"تم حذف سجل العميل #{lead_id} بواسطة رئيس التحرير", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
    return {"success": True, "message": "تم حذف سجل العميل بنجاح"}

@app.get("/api/admin/customer-leads/export", dependencies=[Depends(require_role(["admin"]))])
def export_customer_leads_endpoint():
    """
    Exclusive for Chief Editor (Admin):
    Exports all extracted customer leads into an Excel-friendly CSV with UTF-8 BOM encoding.
    """
    leads = db.get_all_customer_leads_for_export()
    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Microsoft Excel Arabic compatibility
    writer = csv.writer(output)
    writer.writerow([
        "ID", "اسم العميل / الجهة", "رقم الهاتف", "القسم / المجال", 
        "عنوان الخبر", "رابط الخبر المنشور", "معرف المقال", "اعتمد بواسطة (الصحفي)", 
        "إيميل الصحفي", "حالة التواصل", "ملاحظات رئيس التحرير", "تاريخ الاعتماد والسحب"
    ])
    for l in leads:
        writer.writerow([
            l.get("id", ""),
            l.get("client_name", ""),
            l.get("client_phone", ""),
            l.get("category", ""),
            l.get("article_title", ""),
            l.get("article_url", ""),
            l.get("article_id", ""),
            l.get("promoted_by_name", ""),
            l.get("promoted_by_email", ""),
            l.get("contact_status", ""),
            l.get("notes", ""),
            l.get("created_at", "")
        ])
    
    csv_bytes = output.getvalue().encode('utf-8-sig')
    filename = f"customer_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/admin/customer-leads/extract-from-url", dependencies=[Depends(require_role(["admin"]))])
def extract_customer_lead_from_url_endpoint(payload: ExtractLeadFromUrlRequest, user: dict = Depends(get_current_user)):
    """
    Exclusive for Chief Editor (Admin):
    Extracts customer lead data automatically from a news article URL and saves it to CRM.
    """
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="يرجى إدخال رابط الخبر")
    
    try:
        from services.lead_extractor import extract_lead_from_url
        res = extract_lead_from_url(url=url, db=db, admin_user=user)
        db.log_system(
            "INFO",
            "CustomerLeads",
            f"تم استخراج بيانات العميل بنجاح من الرابط: {url} بواسطة {user.get('full_name')}",
            user_id=str(user.get("user_id")),
            user_name=user.get("full_name")
        )
        return res
    except Exception as e:
        logger.error(f"Failed to extract customer lead from URL {url}: {e}")
        raise HTTPException(status_code=400, detail=f"تعذر استخراج بيانات العميل من الرابط: {str(e)}")


# =============================================================
# FACEBOOK HUB & COMMERCIAL POSTS MANAGEMENT
# =============================================================

@app.get("/api/admin/facebook/overview", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_facebook_overview_endpoint(user: dict = Depends(get_current_user)):
    """Fetches Facebook Page live details and local executive financial/performance statistics."""
    page_info = fb_service.get_page_info()
    stats = db.get_facebook_overview_stats()
    return {
        "success": True,
        "page": page_info,
        "stats": stats
    }

@app.get("/api/admin/facebook/posts", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_facebook_posts_endpoint(
    payment_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    """Retrieves paginated Facebook posts with financial filters."""
    result = db.get_facebook_posts(payment_status=payment_status, search=search, page=page, limit=limit)
    return {
        "success": True,
        **result
    }

@app.post("/api/admin/facebook/publish", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def publish_facebook_quick_post_endpoint(payload: FacebookQuickPublishRequest, user: dict = Depends(get_current_user)):
    """Publishes a direct post or photo to the Facebook page and records its financial state."""
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="نص المنشور مطلوب")
    
    try:
        author_name = user.get("full_name") or user.get("username") or "رئيس التحرير"
        res = fb_service.publish_quick_post(
            message=payload.message.strip(),
            image_url=payload.image_url.strip() if payload.image_url else None,
            link=payload.link.strip() if payload.link else None,
            payment_status=payload.payment_status or "EDITORIAL",
            client_name=payload.client_name or "",
            amount=payload.amount or 0.0,
            payment_notes=payload.payment_notes or "",
            published_by_name=author_name,
            db=db
        )
        db.log_system("INFO", "Facebook", f"تم نشر منشور جديد على فيسبوك: {res.get('post_url')}", user_id=str(user.get("user_id")), user_name=author_name)
        return res
    except Exception as e:
        logger.error(f"Failed to publish quick post to Facebook: {e}")
        db.log_system("ERROR", "Facebook", f"فشل نشر منشور على فيسبوك: {e}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/admin/facebook/publish-article", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def publish_facebook_article_endpoint(payload: FacebookArticlePublishRequest, user: dict = Depends(get_current_user)):
    """Publishes an existing database article to the Facebook page."""
    art = db.get_article(payload.article_id)
    if not art:
        raise HTTPException(status_code=404, detail="الخبر غير موجود في قاعدة البيانات")
    
    try:
        author_name = user.get("full_name") or user.get("username") or "رئيس التحرير"
        res = fb_service.publish_article(
            article_data={
                "id": art.get("id"),
                "title": art.get("title", ""),
                "post_url": art.get("post_url", ""),
                "summary": payload.custom_message or art.get("title", ""),
                "category": art.get("labels", ""),
                "client_name": payload.client_name or art.get("client_name", ""),
                "image_url": art.get("remote_image_url") or art.get("image_url") or ""
            },
            payment_status=payload.payment_status or "EDITORIAL",
            amount=payload.amount or 0.0,
            payment_notes=payload.payment_notes or "",
            db=db,
            published_by_name=author_name
        )
        db.log_system("INFO", "Facebook", f"تم نشر الخبر #{payload.article_id} على فيسبوك: {res.get('post_url')}", user_id=str(user.get("user_id")), user_name=author_name)
        return res
    except Exception as e:
        logger.error(f"Failed to publish article to Facebook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/admin/facebook/posts/{post_id}/payment", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def update_facebook_post_payment_endpoint(post_id: str, payload: FacebookPaymentUpdateRequest, user: dict = Depends(get_current_user)):
    """Updates the commercial/payment status of a Facebook post (PAID / UNPAID / EDITORIAL / FREE)."""
    success = db.update_facebook_post_payment(
        post_id=post_id,
        payment_status=payload.payment_status,
        payment_notes=payload.payment_notes,
        amount=payload.amount
    )
    if not success:
        raise HTTPException(status_code=404, detail="المنشور غير موجود أو لم يتم تحديث أي بيانات")
    
    db.log_system("INFO", "Facebook", f"تم تحديث الحالة المالية للمنشور {post_id} إلى {payload.payment_status}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
    return {
        "success": True,
        "message": f"تم تحديث الحالة المالية إلى {payload.payment_status} بنجاح"
    }

@app.delete("/api/admin/facebook/posts/{post_id}", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def delete_facebook_post_endpoint(post_id: str, delete_from_fb: bool = Query(True), user: dict = Depends(get_current_user)):
    """Deletes post from Facebook page (if requested) and removes from local database."""
    if delete_from_fb:
        try:
            fb_service.delete_post(post_id, db=db)
        except Exception as e:
            logger.warning(f"Failed deleting post from FB (deleting from DB anyway): {e}")
            db.delete_facebook_post_record(post_id)
    else:
        db.delete_facebook_post_record(post_id)
        
    db.log_system("WARNING", "Facebook", f"تم حذف المنشور {post_id}", user_id=str(user.get("user_id")), user_name=user.get("full_name"))
    return {"success": True, "message": "تم حذف المنشور بنجاح"}

@app.post("/api/admin/facebook/sync", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def sync_facebook_posts_endpoint(limit: int = Query(30, ge=5, le=100), user: dict = Depends(get_current_user)):
    """Syncs live engagement counts (likes, comments, shares) and recent posts from Facebook."""
    synced = fb_service.sync_live_posts(limit=limit, db=db)
    stats = db.get_facebook_overview_stats()
    return {
        "success": True,
        "synced_count": len(synced),
        "posts": synced,
        "stats": stats
    }


# =============================================================
# GEMINI FALLBACK MONITORING (CHIEF EDITOR & DEPUTY)
# =============================================================

@app.get("/api/admin/gemini-fallback/logs", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_gemini_fallback_logs_endpoint(
    search: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 25
):
    """
    Exclusive for Chief Editor & Deputy Editor:
    Retrieves detailed logs of all Google Gemini fallback invocations when GLM fails.
    """
    res = db.get_gemini_fallback_logs(page=page, limit=limit, search=search, status=status)
    return {
        "success": True,
        **res
    }

@app.get("/api/admin/gemini-fallback/stats", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def get_gemini_fallback_stats_endpoint():
    """
    Exclusive for Chief Editor & Deputy Editor:
    Retrieves live executive HUD statistics for Gemini Fallback operations.
    """
    stats = db.get_gemini_fallback_stats()
    return {
        "success": True,
        "stats": stats
    }

@app.post("/api/admin/gemini-fallback/test", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def test_gemini_fallback_connection_endpoint():
    """
    Exclusive for Chief Editor & Deputy Editor:
    Performs an immediate live ping to Google Gemini 3.6 Flash to test connectivity and response latency.
    """
    if not getattr(ai_service, "gemini_client", None):
        return {
            "success": False,
            "message": "محرك Google Gemini غير مهيأ أو ينقصه المفتاح في ملف الإعدادات."
        }
    
    t0 = time.time()
    try:
        resp = ai_service.gemini_client.chat.completions.create(
            model=ai_service.gemini_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=30
        )
        latency = round(time.time() - t0, 2)
        return {
            "success": True,
            "latency_seconds": latency,
            "model": ai_service.gemini_model,
            "message": f"اتصال فائق السرعة وجاهزية تامة بنسبة 100% ({latency} ثانية)"
        }
    except Exception as e:
        latency = round(time.time() - t0, 2)
        return {
            "success": False,
            "latency_seconds": latency,
            "message": f"تعذر الاتصال بـ Google Gemini: {str(e)[:150]}"
        }


@app.post("/api/admin/groq-fallback/test", dependencies=[Depends(require_role(["admin", "deputy_editor"]))])
def test_groq_fallback_connection_endpoint():
    """
    Exclusive for Chief Editor & Deputy Editor:
    Performs an immediate live ping to Groq Cloud (openai/gpt-oss-120b) to test connectivity and response latency.
    """
    if not getattr(ai_service, "groq_client", None):
        return {
            "success": False,
            "message": "محرك Groq Cloud غير مهيأ أو ينقصه المفتاح في ملف الإعدادات."
        }
    
    t0 = time.time()
    try:
        resp = ai_service.groq_client.chat.completions.create(
            model=ai_service.groq_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=20
        )
        latency = round(time.time() - t0, 2)
        return {
            "success": True,
            "latency_seconds": latency,
            "model": ai_service.groq_model,
            "message": f"اتصال فائق السرعة وجاهزية تامة عبر Groq Cloud ({latency} ثانية)"
        }
    except Exception as e:
        latency = round(time.time() - t0, 2)
        return {
            "success": False,
            "latency_seconds": latency,
            "message": f"تعذر الاتصال بـ Groq Cloud: {str(e)[:150]}"
        }


# =============================================================
# WHATSAPP FARM MULTI-SESSION & ANTI-BAN ROUTER (1 to 100)
# =============================================================

class AddWhatsAppSessionRequest(BaseModel):
    session_number: int
    phone_number: str = ""
    label: str = ""
    daily_limit: int = 20

@app.get("/api/admin/whatsapp/sessions")
def get_whatsapp_sessions_endpoint():
    """Returns all configured WhatsApp sessions and farm overview stats."""
    sessions = auto_db.get_all_whatsapp_sessions()
    ban_logs = auto_db.get_whatsapp_ban_logs(limit=20)
    active_count = sum(1 for s in sessions if s.get("is_active") and s.get("status") == "ACTIVE")
    total_today = sum(s.get("messages_sent_today", 0) for s in sessions)
    banned_count = sum(1 for s in sessions if s.get("status") == "BANNED")
    return {
        "success": True,
        "sessions": sessions,
        "ban_logs": ban_logs,
        "stats": {
            "total_configured": len(sessions),
            "active_count": active_count,
            "banned_count": banned_count,
            "total_sent_today": total_today
        }
    }

@app.post("/api/admin/whatsapp/sessions/add")
def add_whatsapp_session_endpoint(payload: AddWhatsAppSessionRequest):
    """Adds or updates a WhatsApp session profile."""
    if payload.session_number < 1 or payload.session_number > 100:
        raise HTTPException(status_code=400, detail="رقم الجلسة يجب أن يكون بين 1 و 100.")
    row_id = auto_db.add_whatsapp_session(
        session_number=payload.session_number,
        phone_number=payload.phone_number,
        label=payload.label or f"خط واتساب {payload.session_number}",
        daily_limit=payload.daily_limit
    )
    return {"success": True, "message": f"تمت إضافة الجلسة #{payload.session_number} بنجاح", "id": row_id}

@app.post("/api/admin/whatsapp/sessions/{session_num}/toggle")
def toggle_whatsapp_session_endpoint(session_num: int):
    """Toggles session active/pause state."""
    sess = auto_db.get_whatsapp_session(session_num)
    if not sess:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة.")
    new_active = 0 if sess.get("is_active") == 1 else 1
    new_status = sess.get("status")
    if new_active == 1 and new_status in ("DISABLED", "PAUSED"):
        new_status = "ACTIVE"
    elif new_active == 0:
        new_status = "PAUSED"
    auto_db.update_whatsapp_session(session_num, is_active=new_active, status=new_status)
    return {"success": True, "is_active": new_active, "status": new_status}

class UpdateWhatsAppLimitRequest(BaseModel):
    daily_limit: int

@app.post("/api/admin/whatsapp/sessions/{session_num}/limit")
def update_whatsapp_limit_endpoint(session_num: int, payload: UpdateWhatsAppLimitRequest):
    """Updates the individual daily message quota for a specific session."""
    sess = auto_db.get_whatsapp_session(session_num)
    if not sess:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة.")
    if payload.daily_limit < 1 or payload.daily_limit > 5000:
        raise HTTPException(status_code=400, detail="الحد اليومي يجب أن يكون بين 1 و 5000 رسالة.")
    auto_db.update_whatsapp_session(session_num, daily_limit=payload.daily_limit, is_custom_limit=1)
    return {
        "success": True,
        "message": f"تم تحديد سقف الخط #{session_num} إلى {payload.daily_limit} رسالة يومياً بنجاح.",
        "session_number": session_num,
        "daily_limit": payload.daily_limit
    }

class SetGlobalWhatsAppLimitRequest(BaseModel):
    daily_limit: int

@app.post("/api/admin/whatsapp/sessions/global-limit")
def set_global_whatsapp_limit_endpoint(payload: SetGlobalWhatsAppLimitRequest):
    """Updates the daily message quota for all sessions in the WhatsApp farm."""
    if payload.daily_limit < 1 or payload.daily_limit > 5000:
        raise HTTPException(status_code=400, detail="الحد اليومي يجب أن يكون بين 1 و 5000 رسالة.")
    auto_db.set_global_whatsapp_daily_limit(payload.daily_limit)
    return {
        "success": True,
        "message": f"تم تطبيق سقف {payload.daily_limit} رسالة يومياً على جميع خطوط المزرعة بنجاح.",
        "daily_limit": payload.daily_limit
    }

@app.post("/api/admin/whatsapp/sessions/{session_num}/connect")
def connect_whatsapp_session_endpoint(session_num: int):
    """
    Launches WhatsApp Web in visible browser window for session pairing (QR scan or link with phone number).
    """
    def _run_connect():
        try:
            profile_dir = AutomationConfig.get_wa_session_profile_dir(session_num)
            BrowserManager._clean_profile_locks(profile_dir)
            page = browser_manager.get_whatsapp_page(session_number=session_num, headless=False)
            page.goto("https://web.whatsapp.com", timeout=60000)
            # Give user up to 180s to scan QR / link code
            for _ in range(60):
                time.sleep(3.0)
                if page.is_closed():
                    break
                st = wa_dispatcher.check_session_status(page)
                if st == "READY":
                    extracted_phone = wa_dispatcher.extract_logged_in_phone(page, session_number=session_num)
                    auto_db.update_whatsapp_session(session_num, status="ACTIVE", is_active=1)
                    time.sleep(3.0)
                    break
        except Exception as e:
            logger.warning(f"Connect error on session #{session_num}: {e}")
        finally:
            browser_manager.close_whatsapp_context(session_number=session_num)
            browser_manager.close_all()

    threading.Thread(target=_run_connect, daemon=True).start()
    return {
        "success": True,
        "message": f"تم تشغيل متصفح الجلسة #{session_num} على شاشتك. يمكنك مسح الـ QR أو الربط برقم الهاتف مباشرة."
    }

@app.post("/api/admin/whatsapp/sessions/{session_num}/check")
def check_whatsapp_session_endpoint(session_num: int):
    """Probes if a specific session is logged in and ready."""
    try:
        page = browser_manager.get_whatsapp_page(session_number=session_num, headless=True)
        page.goto("https://web.whatsapp.com", timeout=45000)

        final_status = "LOADING"
        for _ in range(8):
            time.sleep(2.0)
            if page.is_closed():
                break
            st = wa_dispatcher.check_session_status(page)
            if st == "READY":
                final_status = "READY"
                break
            elif st == "NEEDS_QR":
                final_status = "NEEDS_QR"
                break

        ban_text = wa_dispatcher._check_ban_or_logout_dialog(page)
        if ban_text:
            auto_db.update_whatsapp_session(session_num, status="BANNED", is_active=0)
            return {"success": False, "status": "BANNED", "message": ban_text}

        if final_status == "READY":
            extracted_phone = wa_dispatcher.extract_logged_in_phone(page, session_number=session_num)
            auto_db.update_whatsapp_session(session_num, status="ACTIVE", is_active=1)
            phone_tag = f" (+{extracted_phone})" if extracted_phone else ""
            return {"success": True, "status": "ACTIVE", "phone": extracted_phone, "message": f"الجلسة نشطة ومتصلة وجاهزة للإرسال{phone_tag} ✅"}
        elif final_status == "NEEDS_QR":
            auto_db.update_whatsapp_session(session_num, status="NEEDS_AUTH")
            return {"success": False, "status": "NEEDS_AUTH", "message": "الجلسة بحاجة إلى تسجيل الدخول (QR أو كود)"}
        else:
            return {"success": False, "status": "LOADING", "message": "واتساب قيد تحميل المحادثات، يرجى المحاولة ثانية ⏳"}
    except Exception as e:
        return {"success": False, "status": "ERROR", "message": str(e)[:150]}
    finally:
        browser_manager.close_whatsapp_context(session_number=session_num)
        browser_manager.close_all()

@app.delete("/api/admin/whatsapp/sessions/{session_num}")
def delete_whatsapp_session_endpoint(session_num: int):
    """Deletes session from database and closes its browser context."""
    browser_manager.close_whatsapp_context(session_number=session_num)
    auto_db.delete_whatsapp_session(session_num)
    return {"success": True, "message": f"تم حذف الجلسة #{session_num} بنجاح."}

@app.post("/api/admin/whatsapp/sessions/reset-daily")
def reset_whatsapp_daily_counters_endpoint():
    """Resets daily counters and progresses warm-up limits."""
    auto_db.reset_daily_whatsapp_counters()
    return {"success": True, "message": "تم تصفير عدادات رسائل اليوم وترقية سقف التسخين بنجاح."}

@app.get("/api/admin/whatsapp/ban-logs")
def get_whatsapp_ban_logs_endpoint():
    """Returns recent ban and failover audit events."""
    logs = auto_db.get_whatsapp_ban_logs(limit=50)
    return {"success": True, "logs": logs}


# =============================================================
# SETTINGS & BLOGGER POOL ROUTER
# =============================================================

@app.get("/api/settings")
def get_system_settings(authorization: Optional[str] = Header(None)):
    q_info = blogger_service.get_quota_info()
    # Default to False; only True if the specific logged-in user has their own valid token
    is_auth = False
    google_account = {"is_connected": False, "email": "", "name": "", "picture": ""}
    
    user_ai_key = {"has_key": False, "masked_key": ""}
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        sess = ACTIVE_SESSIONS.get(token)
        if sess:
            uid = sess.get("user_id") or sess.get("id")
            user_rec = db.get_user_by_id(uid) if uid else None
            if user_rec:
                u_email = user_rec.get("email") or ""
                u_token = user_rec.get("blogger_token_path") or ""
                u_avatar = user_rec.get("google_avatar") or ""
                u_name = user_rec.get("full_name") or ""
                
                # Check user's personal Google/Blogger account
                if u_token and os.path.exists(u_token):
                    tok_details = blogger_service.get_token_details(u_token)
                    if tok_details.get("is_connected"):
                        google_account = {
                            "is_connected": True,
                            "email": tok_details.get("email") or u_email,
                            "name": tok_details.get("name") or u_name,
                            "picture": tok_details.get("picture") or u_avatar
                        }
                        is_auth = True
                    else:
                        google_account = {
                            "is_connected": False,
                            "email": u_email,
                            "name": u_name,
                            "picture": u_avatar
                        }
                elif u_token and os.path.exists(u_token):
                    # Token file exists but expired or details unreadable
                    is_auth = False
                    google_account = {
                        "is_connected": False,
                        "email": u_email,
                        "name": u_name,
                        "picture": u_avatar
                    }
                else:
                    if user_rec.get("role") != "admin":
                        google_account = {
                            "is_connected": False,
                            "email": "",
                            "name": "",
                            "picture": ""
                        }
                        is_auth = False

            if uid:
                key = db.get_user_zai_key(uid)
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

class UploadUrlRequest(BaseModel):
    url: str

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    raw_name = file.filename or "image.png"
    ext = Path(raw_name).suffix.lower()
    
    # Infer extension from Content-Type if missing or generic
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if not ext or ext == ".tmp" or raw_name == "blob":
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif "gif" in content_type:
            ext = ".gif"
        elif "bmp" in content_type:
            ext = ".bmp"
        elif "avif" in content_type:
            ext = ".avif"
        else:
            ext = ".jpg"

    allowed = [".jpg", ".jpeg", ".png", ".webp", ".jfif", ".bmp", ".avif", ".gif"]
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="صيغة الملف غير مدعومة. يرجى رفع صورة بصيغة JPG أو PNG أو WEBP أو GIF.")

    contents = await file.read()
    
    # Save target file name
    save_ext = ext if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else ".jpg"
    unique_name = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{save_ext}"
    dest_path = UPLOAD_DIR / unique_name

    # Try PIL for sanitizing/converting esoteric image formats (jfif, bmp, avif) to standard
    saved_with_pil = False
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(contents))
        fmt = "PNG" if save_ext == ".png" else ("WEBP" if save_ext == ".webp" else ("GIF" if save_ext == ".gif" else "JPEG"))
        if fmt == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(dest_path, format=fmt, quality=92)
        saved_with_pil = True
    except Exception as pil_err:
        logger.debug(f"PIL save fallback to raw binary: {pil_err}")

    if not saved_with_pil:
        with open(dest_path, "wb") as f:
            f.write(contents)

    return {
        "success": True,
        "filename": unique_name,
        "local_path": str(dest_path),
        "url": f"/storage/images/{unique_name}"
    }

@app.post("/api/upload-url")
def upload_image_from_url(payload: UploadUrlRequest):
    img_url = (payload.url or "").strip()
    if not img_url or not img_url.startswith("http"):
        raise HTTPException(status_code=400, detail="رابط الصورة غير صالح")
    try:
        resp = requests.get(img_url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"تعذر تحميل الصورة من الرابط (HTTP {resp.status_code})")
        
        content_type = resp.headers.get("content-type", "").lower()
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif "gif" in content_type:
            ext = ".gif"
        
        unique_name = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
        dest_path = UPLOAD_DIR / unique_name
        with open(dest_path, "wb") as f:
            f.write(resp.content)
            
        return {
            "success": True,
            "filename": unique_name,
            "local_path": str(dest_path),
            "url": f"/storage/images/{unique_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"فشل استيراد الصورة من الرابط: {str(e)}")


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
        if user.get("role") not in ["admin", "deputy_editor"]:
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
# REMOTE AUTOMATION CONTROLLER & API ENDPOINTS
# =============================================================

class StartAutomationPayload(BaseModel):
    urls: List[str]
    is_test_mode: bool = True
    rest_enabled: bool = False
    rest_batch_size: int = 50
    rest_duration_minutes: float = 60.0
    target_phone: Optional[str] = "01094775924"

class RestConfigPayload(BaseModel):
    enabled: bool
    batch_size: int = 50
    duration_minutes: float = 60.0

class FacebookCookiesPayload(BaseModel):
    cookies: str

class TestSingleArticlePayload(BaseModel):
    url: str
    phone: Optional[str] = "01094775924"

class TestScreenshotPayload(BaseModel):
    article_url: str

class TestWhatsAppPayload(BaseModel):
    phone: str = "01094775924"
    message: str = "تجربة إرسال مباشر من منظومة أتمتة جريدة تحت الضوء 🗞️"

AUTO_WS_CLIENTS: List[WebSocket] = []
AUTO_WS_LOCK = asyncio.Lock()

def auto_log_subscriber(entry: dict):
    if not AUTO_WS_CLIENTS:
        return
    try:
        loop = MAIN_LOOP
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_auto_ws(entry), loop)
    except Exception:
        pass

async def broadcast_auto_ws(entry: dict):
    text = json.dumps(entry, ensure_ascii=False)
    async with AUTO_WS_LOCK:
        dead = []
        for ws in AUTO_WS_CLIENTS:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for d in dead:
            if d in AUTO_WS_CLIENTS:
                AUTO_WS_CLIENTS.remove(d)

remote_auto_mgr._log_subscribers.append(auto_log_subscriber)

@app.websocket("/api/automation/ws/logs")
async def websocket_automation_logs(websocket: WebSocket):
    await websocket.accept()
    async with AUTO_WS_LOCK:
        AUTO_WS_CLIENTS.append(websocket)
    try:
        recent = remote_auto_mgr.get_logs(limit=50)
        for item in recent:
            await websocket.send_text(json.dumps(item, ensure_ascii=False))
        while True:
            await asyncio.sleep(15)
            await websocket.send_text(json.dumps({"time": datetime.now().strftime("%I:%M:%S %p"), "level": "PING", "message": "heartbeat"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with AUTO_WS_LOCK:
            if websocket in AUTO_WS_CLIENTS:
                AUTO_WS_CLIENTS.remove(websocket)

# --- Local PC Agent Bridge Routes ---

class AgentPollPayload(BaseModel):
    agent_token: Optional[str] = "TD_AGENT_DEFAULT"
    node_name: Optional[str] = "جهاز الصحافة المحلي"
    state: Optional[Dict[str, Any]] = None
    new_logs: Optional[List[Dict[str, Any]]] = None

class AgentResultPayload(BaseModel):
    command_id: str
    result: Dict[str, Any]

@app.post("/api/automation/agent/poll")
def agent_poll_endpoint(payload: AgentPollPayload):
    return remote_auto_mgr.handle_agent_poll(payload.dict())

@app.post("/api/automation/agent/result")
def agent_result_endpoint(payload: AgentResultPayload):
    return remote_auto_mgr.handle_agent_result(payload.dict())

@app.get("/api/automation/node/status")
def get_node_status_endpoint():
    return remote_auto_mgr.get_node_info()

@app.get("/api/automation/status")
def get_automation_status():
    return remote_auto_mgr.get_status()

@app.post("/api/automation/start")
def start_automation_endpoint(payload: StartAutomationPayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("START", payload.dict(), timeout=12.0)
    return {
        "success": False,
        "message": "جهاز الكمبيوتر المحلي غير متصل حالياً بالسيرفر! يرجى تشغيل Run_Remote_Automation_Agent.bat على جهازك الشخصي أولاً."
    }

@app.post("/api/automation/stop")
def stop_automation_endpoint():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("STOP", {}, timeout=10.0)
    return remote_auto_mgr.stop_automation()

@app.post("/api/automation/skip-rest")
def skip_rest_endpoint():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("SKIP_REST", {}, timeout=10.0)
    return remote_auto_mgr.skip_rest()

@app.post("/api/automation/configure-rest")
def configure_rest_endpoint(payload: RestConfigPayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("CONFIGURE_REST", payload.dict(), timeout=10.0)
    return remote_auto_mgr.configure_rest_settings(
        enabled=payload.enabled,
        batch_size=payload.batch_size,
        duration_minutes=payload.duration_minutes
    )

@app.get("/api/automation/logs")
def get_automation_logs_endpoint(limit: int = 150):
    return remote_auto_mgr.get_logs(limit=limit)

# --- Account Health & Session Control Endpoints ---
@app.get("/api/automation/accounts/overview")
def get_accounts_overview():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("ACCOUNTS_OVERVIEW", {}, timeout=10.0)
    fb_status = "OFFLINE"
    wa_status = "OFFLINE"
    blogger_status = "UNKNOWN"
    try:
        from services.wordpress_service import wordpress_service as blogger_service
        blogger_status = "READY" if blogger_service.personal_account.token_exists() else "NO_TOKEN"
    except Exception:
        pass
    return {
        "facebook": fb_status,
        "whatsapp": wa_status,
        "blogger": blogger_status,
        "node": remote_auto_mgr.get_node_info()
    }

@app.get("/api/automation/accounts/facebook/status")
def check_facebook_endpoint():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("CHECK_FACEBOOK", {}, timeout=30.0)
    return {"status": "OFFLINE", "message": "جهاز الكمبيوتر المحلي غير متصل بالسيرفر. يرجى تشغيل البرنامج على جهازك أولاً."}

@app.post("/api/automation/accounts/facebook/logout")
def logout_facebook_endpoint():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("LOGOUT_FACEBOOK", {}, timeout=15.0)
    return remote_auto_mgr.logout_facebook()

@app.post("/api/automation/accounts/facebook/login")
def login_facebook_endpoint(payload: FacebookCookiesPayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("LOGIN_FACEBOOK", {"cookies": payload.cookies}, timeout=30.0)
    return remote_auto_mgr.login_facebook_cookies(payload.cookies)

@app.get("/api/automation/accounts/whatsapp/status")
def check_whatsapp_endpoint(session: int = 1):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("CHECK_WHATSAPP", {"session": session}, timeout=30.0)
    return remote_auto_mgr.check_whatsapp_status(session_number=session)

@app.post("/api/automation/accounts/whatsapp/logout")
def logout_whatsapp_endpoint(session: int = 1):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("LOGOUT_WHATSAPP", {"session": session}, timeout=15.0)
    return remote_auto_mgr.logout_whatsapp(session_number=session)

@app.get("/api/automation/accounts/blogger/status")
def check_blogger_endpoint():
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("CHECK_BLOGGER", {}, timeout=15.0)
    return remote_auto_mgr.check_blogger_status()

@app.post("/api/automation/accounts/blogger/test")
def test_blogger_endpoint(account_id: int = 1):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("TEST_BLOGGER", {"account_id": account_id}, timeout=20.0)
    return remote_auto_mgr.test_blogger_connection(account_id=account_id)

# --- Testing & Diagnostic Tools ---
@app.post("/api/automation/test/single")
def test_single_article_endpoint(payload: TestSingleArticlePayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("TEST_SINGLE", payload.dict(), timeout=90.0)
    return {"success": False, "message": "جهاز الكمبيوتر المحلي غير متصل."}

@app.post("/api/automation/test/screenshot")
def test_screenshot_endpoint(payload: TestScreenshotPayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("TEST_SCREENSHOT", payload.dict(), timeout=40.0)
    return {"success": False, "message": "جهاز الكمبيوتر المحلي غير متصل."}

@app.post("/api/automation/test/whatsapp")
def test_whatsapp_endpoint(payload: TestWhatsAppPayload):
    if remote_auto_mgr.is_local_node_online():
        return remote_auto_mgr.dispatch_agent_command("TEST_WHATSAPP", payload.dict(), timeout=25.0)
    return {"success": False, "message": "جهاز الكمبيوتر المحلي غير متصل."}


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

@app.get("/automation", response_class=HTMLResponse)
def serve_automation_page():
    auto_path = WEB_DIR / "automation.html"
    if auto_path.exists():
        return FileResponse(auto_path)
    parent_auto = PROJECT_ROOT.parent / "web" / "automation.html"
    if parent_auto.exists():
        return FileResponse(parent_auto)
    return HTMLResponse("<h1>لوحة الأتمتة قيد التجهيز...</h1>")

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

