import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Base Directory (Application bundle directory)
BASE_DIR = Path(__file__).resolve().parent.parent

# User Writable Data Directory (AppData/Local/TahtElDooPublisher)
if sys.platform == "win32":
    APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "TahtElDooPublisher"
else:
    # Unified VPS Linux Path: Always point to the central production storage
    _vps_platform = BASE_DIR / "tahteldoo_web_platform"
    if _vps_platform.exists() and (_vps_platform / "storage").exists():
        APP_DATA_DIR = _vps_platform
    else:
        APP_DATA_DIR = BASE_DIR

APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

# User Writable .env File
ENV_FILE = APP_DATA_DIR / ".env"

# Copy default .env from bundle if user .env doesn't exist yet
if not ENV_FILE.exists():
    bundle_env = BASE_DIR / ".env"
    if bundle_env.exists():
        try:
            shutil.copy2(bundle_env, ENV_FILE)
        except Exception:
            pass

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)
else:
    bundle_env = BASE_DIR / ".env"
    if bundle_env.exists():
        load_dotenv(bundle_env, override=True)

class Config:
    """Application Configuration Manager"""
    BASE_DIR = BASE_DIR
    APP_DATA_DIR = APP_DATA_DIR
    STORAGE_DIR = APP_DATA_DIR / "storage"
    DB_PATH = STORAGE_DIR / "app.db"
    LOGS_DIR = STORAGE_DIR / "logs"

    # Ensure directories exist
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Z.AI / GLM Settings (Primary LLM Provider)
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
    ZAI_API_KEY_2 = os.getenv("ZAI_API_KEY_2", "")
    ZAI_API_KEY_3 = os.getenv("ZAI_API_KEY_3", "")
    TELEGRAM_ZAI_API_KEY = os.getenv("TELEGRAM_ZAI_API_KEY", "")
    ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    ZAI_MODEL = os.getenv("ZAI_MODEL", "glm-4.7-flash")

    # Groq Cloud Settings (Primary Fallback Engine - Fallback 1)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # Google Gemini Settings (Secondary High-Performance Fallback - Fallback 2)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Blogger Settings
    BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "3967122067465937059")
    BLOGGER_BLOG_NAME = os.getenv("BLOGGER_BLOG_NAME", "تحت الضوء الإخبارية (review)")
    BLOGGER_FALLBACK_BLOG_ID = os.getenv("BLOGGER_FALLBACK_BLOG_ID", "5932774642958705278")
    BLOGGER_FALLBACK_BLOG_NAME = os.getenv("BLOGGER_FALLBACK_BLOG_NAME", "تحت الضوء الإخبارية (1review)")
    BLOGGER_FALLBACK_BLOG_URL = os.getenv("BLOGGER_FALLBACK_BLOG_URL", "https://review2.tahteldoo.com")
    BLOGGER_FALLBACK_EMAIL = os.getenv("BLOGGER_FALLBACK_EMAIL", "shalllaby1@gmail.com")
    GOOGLE_USER_EMAIL = os.getenv("GOOGLE_USER_EMAIL", "")
    CREDENTIALS_FILE = APP_DATA_DIR / "credentials.json" if (APP_DATA_DIR / "credentials.json").exists() else BASE_DIR / "credentials.json"
    TOKEN_FILE = APP_DATA_DIR / "token.pickle"

    # Image Hosting (ImgBB)
    IMGBB_API_KEY = os.getenv("ImgBB API") or os.getenv("IMGBB_API_KEY", "")
    IMGBB_API_KEY_2 = os.getenv("IMGBB_API_KEY_2", "")

    # WhatsApp API (wpsenderx / direct gateway)
    WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://backendapi.wpsenderx.com/api/messages/send")
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_API_URL", "")
    WHATSAPP_SESSION_ID = os.getenv("WHATSAPP_SESSION_ID", "user_396_8be6e549-4034-4357-ba17-4ddd5c28d507")
    WHATSAPP_DELAY_SECONDS = int(os.getenv("WHATSAPP_DELAY_SECONDS", "5"))
    REMOVE_WHATSAPP_EMOJIS = os.getenv("REMOVE_WHATSAPP_EMOJIS", "true").lower() in ("true", "1", "yes")

    # Theme Setting (dark / light)
    APP_THEME = os.getenv("APP_THEME", "dark")

    # Newspaper Branding
    NEWSPAPER_NAME = os.getenv("NEWSPAPER_NAME", "جريدة تحت الضوء الإخبارية")
    NEWSPAPER_URL = os.getenv("NEWSPAPER_URL", "https://www.tahteldoo.com/")
    FACEBOOK_URL = os.getenv("FACEBOOK_URL", "https://www.facebook.com/tahteldoo/")

    # Facebook Graph API (Meta Pages API)
    FB_APP_ID = os.getenv("FB_APP_ID", "2485887625231882")
    FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")
    FB_PAGE_ID = os.getenv("FB_PAGE_ID", "200604629806605")
    FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "تحت الضوء")
    FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

    # Editor / Staff Settings (المحرر المسؤول عن رسائل الواتساب)
    EDITOR_NAME = os.getenv("EDITOR_NAME", "محمد شلبي")
    EDITOR_ROLE = os.getenv("EDITOR_ROLE", "صحفي لدي")
    EDITOR_PHONE = os.getenv("EDITOR_PHONE", "")

    # Central Hub Server (Local / Network Hub for Telegram & Desktop)
    CENTRAL_HUB_URL = os.getenv("CENTRAL_HUB_URL", "http://127.0.0.1:8000")
    CENTRAL_HUB_PORT = int(os.getenv("CENTRAL_HUB_PORT", "8000"))

    @classmethod
    def update_env(cls, key: str, value: str):
        """Update a key in .env file dynamically"""
        os.environ[key] = value
        lines = []
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
                new_lines.append(f"{key}={value}\n")
                updated = True
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"{key}={value}\n")
            
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    @classmethod
    def clear_blogger_config(cls):
        """Clear local Blogger blog ID, blog name, and Google user email"""
        cls.BLOGGER_BLOG_ID = ""
        cls.BLOGGER_BLOG_NAME = ""
        cls.GOOGLE_USER_EMAIL = ""
        cls.update_env("BLOGGER_BLOG_ID", "")
        cls.update_env("BLOGGER_BLOG_NAME", "")
        cls.update_env("GOOGLE_USER_EMAIL", "")

