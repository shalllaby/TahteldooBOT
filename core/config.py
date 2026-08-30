import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

class Config:
    """Application Configuration Manager"""
    BASE_DIR = BASE_DIR
    STORAGE_DIR = BASE_DIR / "storage"
    DB_PATH = STORAGE_DIR / "app.db"
    LOGS_DIR = STORAGE_DIR / "logs"

    # Ensure directories exist
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Z.AI / GLM Settings
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
    ZAI_API_KEY_2 = os.getenv("ZAI_API_KEY_2", "")
    ZAI_API_KEY_3 = os.getenv("ZAI_API_KEY_3", "")
    ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    ZAI_MODEL = os.getenv("ZAI_MODEL", "glm-4.7-flash")

    # Groq AI Settings
    GROQ_API_KEY = os.getenv("groq-api-kay") or os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL") or os.getenv("Model", "openai/gpt-oss-120b")

    # ZenMux / OpenAI Compatible AI Settings
    ZENMUX_API_KEY = os.getenv("ZENMUX_API_KEY", "")
    ZENMUX_BASE_URL = os.getenv("ZENMUX_BASE_URL", "https://zenmux.ai/api/v1")
    ZENMUX_MODEL = os.getenv("ZENMUX_MODEL", "")

    # Google Gemini AI Settings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # OpenRouter AI Settings
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    # Blogger Settings
    BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "")
    BLOGGER_BLOG_NAME = os.getenv("BLOGGER_BLOG_NAME", "")
    GOOGLE_USER_EMAIL = os.getenv("GOOGLE_USER_EMAIL", "")
    CREDENTIALS_FILE = BASE_DIR / "credentials.json"
    TOKEN_FILE = BASE_DIR / "token.pickle"

    # Image Hosting (ImgBB)
    IMGBB_API_KEY = os.getenv("ImgBB API") or os.getenv("IMGBB_API_KEY", "")

    # WhatsApp API (wpsenderx / direct gateway)
    WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://backendapi.wpsenderx.com/api/messages/send")
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_API_URL", "")
    WHATSAPP_SESSION_ID = os.getenv("WHATSAPP_SESSION_ID", "user_396_8be6e549-4034-4357-ba17-4ddd5c28d507")
    WHATSAPP_DELAY_SECONDS = int(os.getenv("WHATSAPP_DELAY_SECONDS", "5"))

    # Theme Setting (dark / light)
    APP_THEME = os.getenv("APP_THEME", "dark")

    # Newspaper Branding
    NEWSPAPER_NAME = os.getenv("NEWSPAPER_NAME", "جريدة تحت الضوء الإخبارية")
    NEWSPAPER_URL = os.getenv("NEWSPAPER_URL", "https://www.tahteldoo.com/")
    FACEBOOK_URL = os.getenv("FACEBOOK_URL", "https://www.facebook.com/tahteldoo/")

    # Editor / Staff Settings (المحرر المسؤول عن رسائل الواتساب)
    EDITOR_NAME = os.getenv("EDITOR_NAME", "محمد شلبي")
    EDITOR_ROLE = os.getenv("EDITOR_ROLE", "رئيس تحرير")
    EDITOR_PHONE = os.getenv("EDITOR_PHONE", "")

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

