import time
import asyncio
import threading
from typing import Optional
from core.logger import logger


class TelegramBotController:
    """Controls Telegram Bot lifecycle (start/stop) from Desktop UI and reports live status."""
    def __init__(self):
        self.is_running = False
        self.start_time = None
        self.thread: Optional[threading.Thread] = None
        self.app = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._started_event = threading.Event()
        self.last_error = ""

    def start(self, timeout: float = 15.0) -> bool:
        with self._lock:
            if self.is_running:
                return True
            self.last_error = ""
            self._started_event.clear()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            
            # Wait until bot application is successfully initialized or failed
            self._started_event.wait(timeout=timeout)
            return self.is_running

    def _run_loop(self):
        self._stop_requested = False
        retry_count = 0
        while not self._stop_requested:
            try:
                from telegram_bot.bot import create_bot_app
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self.app = create_bot_app()
                self.is_running = True
                if not self.start_time:
                    self.start_time = time.time()
                self._started_event.set()
                logger.info("⚡ تم تشغيل بوت تليجرام بنجاح من لوحة التحكم.")
                self.app.run_polling(close_loop=False, stop_signals=None)
                break
            except Exception as e:
                self.last_error = str(e)
                logger.warning(f"ملاحظة في حلقة تشغيل بوت تليجرام: {e}")
                if self._stop_requested:
                    break
                retry_count += 1
                if retry_count > 5:
                    self.is_running = False
                    self._started_event.set()
                    break
                time.sleep(3)
        self.is_running = False
        self.start_time = None
        self._started_event.clear()

    def stop(self) -> bool:
        with self._lock:
            self._stop_requested = True
            if not self.is_running:
                return True
            logger.info("⏹️ جاري إيقاف بوت تليجرام من لوحة التحكم...")
            try:
                if self.app:
                    if self._loop and self._loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
                        try:
                            fut.result(timeout=4.0)
                        except Exception:
                            pass
                    else:
                        if hasattr(self.app, "stop"):
                            res = self.app.stop()
                            if asyncio.iscoroutine(res):
                                res.close()
            except Exception as e:
                logger.warning(f"ملاحظة عند إيقاف البوت: {e}")
            self.is_running = False
            self.start_time = None
            self._started_event.clear()
            return True

    async def _async_stop(self):
        try:
            if self.app:
                if hasattr(self.app, "updater") and self.app.updater and getattr(self.app.updater, "running", False):
                    await self.app.updater.stop()
                if hasattr(self.app, "stop"):
                    await self.app.stop()
        except Exception:
            pass

    def restart(self, timeout: float = 15.0) -> bool:
        with self._lock:
            logger.info("🔄 جاري إعادة تشغيل بوت تليجرام من لوحة التحكم...")
            self.stop()
            time.sleep(1.5)
            return self.start(timeout=timeout)

    def broadcast_message(self, text: str) -> dict:
        """Sends an announcement message to all registered telegram reporters."""
        from database.db import db
        import requests
        from core.config import Config

        token = Config.TELEGRAM_BOT_TOKEN
        if not token:
            return {"success": False, "sent_count": 0, "failed_count": 0, "error": "لم يتم العثور على توكن البوت في الإعدادات"}

        reporters = db.get_all_reporters()
        if not reporters:
            return {"success": False, "sent_count": 0, "failed_count": 0, "error": "لا يوجد مراسلين مسجلين في قاعدة البيانات"}

        sent = 0
        failed = 0
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        for r in reporters:
            tid = str(r.get("telegram_id", "")).strip()
            if not tid:
                continue
            try:
                res = requests.post(
                    url,
                    json={"chat_id": tid, "text": text, "parse_mode": "Markdown"},
                    timeout=5
                )
                if res.status_code == 200 and res.json().get("ok"):
                    sent += 1
                else:
                    # Retry as plain text if markdown fails
                    res_plain = requests.post(
                        url,
                        json={"chat_id": tid, "text": text},
                        timeout=5
                    )
                    if res_plain.status_code == 200 and res_plain.json().get("ok"):
                        sent += 1
                    else:
                        failed += 1
            except Exception as e:
                logger.warning(f"فشل إرسال تعميم للصحفي {tid}: {e}")
                failed += 1

        return {
            "success": sent > 0,
            "sent_count": sent,
            "failed_count": failed,
            "total_reporters": len(reporters),
            "message": f"تم إرسال التعميم بنجاح إلى {sent} مراسل (فشل {failed})"
        }

    def get_status(self) -> dict:
        uptime = 0
        if self.is_running and self.start_time:
            uptime = int(time.time() - self.start_time)
        return {
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "last_error": self.last_error
        }

    def get_detailed_telemetry(self) -> dict:
        from database.db import db
        import psutil
        from datetime import datetime

        uptime = 0
        uptime_formatted = "--:--:--"
        start_iso = ""
        if self.is_running and self.start_time:
            uptime = int(time.time() - self.start_time)
            hrs = uptime // 3600
            mins = (uptime % 3600) // 60
            secs = uptime % 60
            uptime_formatted = f"{hrs:02d}:{mins:02d}:{secs:02d}"
            start_iso = datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S")

        reporters = db.get_reporters_with_stats()
        total_reporters = len(reporters)
        today_articles = sum(r.get("articles_today", 0) for r in reporters)
        total_articles = sum(r.get("articles_total", 0) for r in reporters)

        # Also fallback/check all articles in case some don't have reporter_telegram_id
        all_articles = db.get_all_articles()
        if len(all_articles) > total_articles:
            total_articles = len(all_articles)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        all_today = len([a for a in all_articles if (a.get("published_at") or "").startswith(today_str) and a.get("blogger_status") == "PUBLISHED"])
        if all_today > today_articles:
            today_articles = all_today

        active_sessions = 0
        try:
            from telegram_bot.bot import USER_SESSIONS
            active_sessions = len(USER_SESSIONS)
        except Exception:
            pass

        memory_mb = 0
        try:
            proc = psutil.Process()
            memory_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass

        return {
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "uptime_formatted": uptime_formatted,
            "start_time": start_iso,
            "started_at_iso": start_iso,
            "last_error": self.last_error,
            "total_reporters": total_reporters,
            "reporters_count": total_reporters,
            "today_articles": today_articles,
            "articles_today_count": today_articles,
            "total_articles": total_articles,
            "articles_total_count": total_articles,
            "active_sessions": active_sessions,
            "active_sessions_count": active_sessions,
            "memory_mb": memory_mb,
            "memory_rss_mb": memory_mb,
            "bot_name": "@TahteldooBOT",
            "bot_handle": "@TahteldooBOT"
        }


bot_controller = TelegramBotController()
