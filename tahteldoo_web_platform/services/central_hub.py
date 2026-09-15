import os
import time
import threading
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from database.db import db
from core.config import Config
from core.logger import logger
from services.whatsapp_service import clean_egyptian_phone

# FastAPI Application for Central Server
app = FastAPI(
    title="Taht El Doo Central Hub API",
    description="Central Server for Client Verification and Multi-Channel Publish Sync (Telegram & Desktop)",
    version="1.0.0"
)

# Allow all origins for local network & desktop communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ArticleRegisterRequest(BaseModel):
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


@app.get("/api/health")
def health_check():
    """Returns operational health status of Central Hub."""
    return {
        "status": "ok",
        "service": "TahtElDoo-Central-Hub",
        "newspaper": Config.NEWSPAPER_NAME
    }


@app.get("/api/check-phone")
def check_phone(phone: str = Query(..., description="رقم هاتف العميل المراد التحقق منه")):
    """
    Checks if a phone number already has a published article in the master database.
    Used by both Telegram Bot and Desktop App as Layer-1 duplicate protection.
    """
    if not phone or not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required")

    clean_p = clean_egyptian_phone(phone)
    res = db.find_article_by_phone(phone)
    logger.info(f"[Central Hub] Check phone query '{phone}' (Clean: {clean_p}) -> Exists: {res.get('exists', False)}")
    return res


@app.get("/api/search")
def search_client(q: str = Query(..., description="البحث برقم الهاتف أو اسم العميل")):
    """Searches master records by phone or client name."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query is required")

    # If numeric, prioritize phone search
    digits = "".join(filter(str.isdigit, q))
    if len(digits) >= 8:
        res = db.find_article_by_phone(q)
        if res.get("exists"):
            return res

    # Check by name or partial query
    res = db.check_client_duplicate(name=q)
    return res


GLOBAL_LAST_PUBLISH_TIME: float = 0.0
PUBLISH_LOCK = threading.Lock()


@app.get("/api/publish-cooldown")
def get_publish_cooldown(cooldown: int = 60):
    """
    Returns the remaining seconds for the 60-second newspaper rate limit across all journalists.
    """
    now = time.time()
    latest_db = db.get_latest_published_timestamp()
    latest_t = max(GLOBAL_LAST_PUBLISH_TIME, latest_db)
    elapsed = now - latest_t
    if latest_t > 0 and 0 <= elapsed < cooldown:
        wait_sec = int(cooldown - elapsed) + 1
        return {
            "can_publish": False,
            "wait_seconds": wait_sec,
            "cooldown": cooldown,
            "message": f"يوجد خبر تم نشره مؤخراً. يرجى الانتظار {wait_sec} ثانية لتنظيم تدفق النشر."
        }
    return {
        "can_publish": True,
        "wait_seconds": 0,
        "cooldown": cooldown,
        "message": "يمكن النشر الآن."
    }


@app.post("/api/record-publish")
def record_publish():
    """Records that an article was published right now to synchronize rate limits across all devices."""
    global GLOBAL_LAST_PUBLISH_TIME
    with PUBLISH_LOCK:
        GLOBAL_LAST_PUBLISH_TIME = time.time()
        db.record_publish_event()
    return {"success": True, "timestamp": GLOBAL_LAST_PUBLISH_TIME}


@app.post("/api/register-article")
def register_article(payload: ArticleRegisterRequest):
    """Registers a published article in the central master database and updates the rate limiter."""
    global GLOBAL_LAST_PUBLISH_TIME
    try:
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
        with PUBLISH_LOCK:
            GLOBAL_LAST_PUBLISH_TIME = time.time()
            db.record_publish_event()

        logger.info(f"[Central Hub] Registered article #{article_id} for client: {payload.client_name} ({payload.client_phone}) - Rate limiter updated.")
        return {"success": True, "article_id": article_id}
    except Exception as e:
        logger.error(f"[Central Hub] Failed to register article: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
def get_stats():
    """Returns high-level statistics from central database."""
    articles = db.get_all_articles()
    return {
        "total_articles": len(articles),
        "total_clients": len({a.get("client_name") for a in articles if a.get("client_name")})
    }


def run_server(host: str = "0.0.0.0", port: int = None):
    """Runs uvicorn server synchronously."""
    if port is None:
        port = int(os.getenv("CENTRAL_HUB_PORT", str(getattr(Config, "CENTRAL_HUB_PORT", 8000))))
    logger.info(f"🚀 بدء تشغيل السيرفر المركزي (TahtElDoo Central Hub) على: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_central_hub_background(host: str = "0.0.0.0", port: int = None):
    """Starts Central Hub server in a background daemon thread."""
    if port is None:
        port = int(os.getenv("CENTRAL_HUB_PORT", str(getattr(Config, "CENTRAL_HUB_PORT", 8000))))
    t = threading.Thread(target=run_server, args=(host, port), daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    port = int(os.getenv("CENTRAL_HUB_PORT", str(getattr(Config, "CENTRAL_HUB_PORT", 8000))))
    run_server(host="0.0.0.0", port=port)
