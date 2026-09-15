import urllib.parse
import time
import requests
from core.config import Config
from core.logger import logger
from database.db import db
from services.whatsapp_service import clean_egyptian_phone


class CentralSyncService:
    """
    Client service providing seamless communication with the Central Hub server.
    Features automated sub-second lookup with automatic fallback to local database
    if the central server is temporarily offline.
    """

    def __init__(self, base_url: str = None):
        self._custom_url = base_url

    @property
    def base_url(self) -> str:
        url = self._custom_url or getattr(Config, "CENTRAL_HUB_URL", "http://127.0.0.1:8000")
        return url.rstrip("/")

    def is_server_online(self) -> bool:
        """Checks if the Central Hub server is reachable."""
        try:
            res = requests.get(f"{self.base_url}/api/health", timeout=1.0)
            return res.status_code == 200
        except Exception:
            return False

    is_hub_available = is_server_online

    def check_phone(self, phone: str) -> dict:
        """
        Queries the central server to check whether this phone number already has a published article.
        Falls back to the local database if the central server is unreachable.
        """
        if not phone or not str(phone).strip():
            return {"exists": False}

        clean_p = clean_egyptian_phone(phone) or str(phone).strip()

        # 1. Try Central Server
        try:
            encoded_phone = urllib.parse.quote(clean_p)
            url = f"{self.base_url}/api/check-phone?phone={encoded_phone}"
            res = requests.get(url, timeout=1.8)
            if res.status_code == 200:
                data = res.json()
                data["source"] = "central_hub"
                return data
        except Exception as e:
            logger.debug(f"[CentralSyncService] Central Hub unreachable ({e}). Using local database fallback.")

        # 2. Local DB Fallback
        local_res = db.find_article_by_phone(phone)
        local_res["source"] = "local_db"
        return local_res

    def search_client(self, query: str) -> dict:
        """
        Searches central server for existing article by phone or client name.
        Falls back to local database if the central server is unreachable.
        """
        if not query or not str(query).strip():
            return {"exists": False}

        q = str(query).strip()

        # 1. Try Central Server
        try:
            encoded_q = urllib.parse.quote(q)
            url = f"{self.base_url}/api/search?q={encoded_q}"
            res = requests.get(url, timeout=1.8)
            if res.status_code == 200:
                data = res.json()
                data["source"] = "central_hub"
                return data
        except Exception as e:
            logger.debug(f"[CentralSyncService] Central Hub search unreachable ({e}). Using local fallback.")

        # 2. Local DB Fallback
        digits = "".join(filter(str.isdigit, q))
        if len(digits) >= 8:
            local_res = db.find_article_by_phone(q)
            if local_res.get("exists"):
                local_res["source"] = "local_db"
                return local_res

        local_res = db.find_article_by_name(q)
        local_res["source"] = "local_db"
        return local_res

    def register_published_post(self, article_data: dict) -> bool:
        """
        Notifies Central Hub of a newly published article to update the master record.
        """
        try:
            url = f"{self.base_url}/api/register-article"
            payload = {
                "client_name": article_data.get("client_name", ""),
                "client_phone": article_data.get("client_phone", ""),
                "title": article_data.get("title", ""),
                "slug": article_data.get("slug", ""),
                "labels": article_data.get("labels", ""),
                "post_url": article_data.get("post_url", ""),
                "post_id": article_data.get("post_id", ""),
                "reporter_telegram_id": str(article_data.get("reporter_telegram_id", "")),
                "blogger_status": article_data.get("blogger_status", "PUBLISHED"),
                "final_html": article_data.get("final_html", "")
            }
            res = requests.post(url, json=payload, timeout=2.5)
            return res.status_code == 200
        except Exception as e:
            logger.warning(f"[CentralSyncService] Could not sync new post to Central Hub ({e}).")
            return False

    def get_publish_cooldown(self, cooldown_seconds: int = 60) -> int:
        """
        Queries Central Hub for the remaining rate-limit cooldown in seconds.
        Falls back to local database if Central Hub is unavailable.
        """
        try:
            url = f"{self.base_url}/api/publish-cooldown?cooldown={cooldown_seconds}"
            res = requests.get(url, timeout=1.5)
            if res.status_code == 200:
                data = res.json()
                return int(data.get("wait_seconds", 0))
        except Exception:
            pass
        return db.get_publish_cooldown_remaining(cooldown_seconds)

    def record_publish_event(self):
        """Notifies both local DB and Central Hub that an article has been published."""
        db.record_publish_event()
        try:
            requests.post(f"{self.base_url}/api/record-publish", timeout=1.0)
        except Exception:
            pass

    def wait_for_publish_slot(self, on_tick=None, cooldown_seconds: int = 60):
        """
        Enforces the 1 article per minute newspaper rate limit.
        If a cooldown is active, waits and invokes on_tick(remaining_seconds) every second.
        Once the slot is clear, marks the slot as claimed and returns.
        """
        while True:
            remaining = self.get_publish_cooldown(cooldown_seconds)
            if remaining <= 0:
                break
            if callable(on_tick):
                on_tick(remaining)
            time.sleep(1)
        # Mark local & central publish time to claim slot
        self.record_publish_event()


# Global singleton instance
central_sync_service = CentralSyncService()
