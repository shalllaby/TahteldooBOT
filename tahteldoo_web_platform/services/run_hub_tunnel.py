#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تشغيل خادم التحقق المركزي (Central Hub) مع نفق Cloudflare Tunnel العالمي
يقوم هذا السكربت بـ:
1. تشغيل سيرفر FastAPI المركزي على البورت 8765
2. تشغيل نفق Cloudflare Quick Tunnel العام (cloudflared)
3. استخراج الرابط العام المشفر (https://xxxx.trycloudflare.com)
4. حفظ الرابط في ملف central_hub_url.txt لنسخه بسهولة وإرساله للصحفيين
"""

import os
import sys
import time
import re
import signal
import subprocess
import threading
from pathlib import Path

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Enable line buffering on stdout/stderr
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

from core.config import Config
from core.logger import logger
import uvicorn
from services.central_hub import start_central_hub_background

HUB_PORT = int(getattr(Config, "CENTRAL_HUB_PORT", 8000))
URL_FILE = project_root / "central_hub_url.txt"
APP_DATA_URL_FILE = Config.APP_DATA_DIR / "central_hub_url.txt"

_cloudflared_proc = None


def run_cloudflare_tunnel():
    """Runs cloudflared tunnel and captures the public HTTPS URL."""
    global _cloudflared_proc

    cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{HUB_PORT}"]

    try:
        _cloudflared_proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
    except FileNotFoundError:
        print("\n❌ لم يتم العثور على أداة cloudflared في النظام.")
        print("💡 يرجى التأكد من تثبيت cloudflared أو إضافتها لـ PATH.\n")
        return None

    public_url = None
    start_time = time.time()

    # Cloudflare outputs its status and URL to stderr line by line
    while True:
        line = _cloudflared_proc.stderr.readline()
        if not line:
            if _cloudflared_proc.poll() is not None:
                break
            time.sleep(0.1)
            continue

        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if match:
            public_url = match.group(0)
            break
        if time.time() - start_time > 35:
            break

    return public_url


def main():
    print("=" * 72)
    print("      🌐 تشغيل السيرفر المركزي الموحد + نفق Cloudflare العالمي")
    print("             جريدة تحت الضوء الإخبارية - نظام التحقق الموحد")
    print("=" * 72)
    print(f"\n⏳ 1. جاري تشغيل خادم FastAPI المركزي على البورت {HUB_PORT}...")
    start_central_hub_background(host="0.0.0.0", port=HUB_PORT)
    time.sleep(1.5)

    print("⏳ 2. جاري إنشاء نفق Cloudflare المشفر وربطه بسيرفر جهازك...")
    public_url = run_cloudflare_tunnel()

    if not public_url:
        print("\n⚠️ تعذر التقاط رابط Cloudflare تلقائياً. تأكد من اتصال الإنترنت.")
        print(f"📌 السيرفر المحلي يعمل حالياً على: http://127.0.0.1:{HUB_PORT}\n")
    else:
        # Save URL to root and AppData for easy copying
        try:
            with open(URL_FILE, "w", encoding="utf-8") as f:
                f.write(public_url + "\n")
            with open(APP_DATA_URL_FILE, "w", encoding="utf-8") as f:
                f.write(public_url + "\n")
        except Exception as e:
            logger.warning(f"Could not save url file: {e}")

        # Update .env dynamically for the current user
        try:
            Config.update_env("PUBLIC_CENTRAL_HUB_URL", public_url)
        except Exception:
            pass

        print("\n" + "═" * 72)
        print("  🎉 تم إنشاء النفق والسيرفر المركزي بنجاح وبات متاحاً للعالم!")
        print("═" * 72)
        print(f"\n  🔗 الرابط العام لسيرفر الأرقام (Public Central Hub URL):")
        print(f"     👉  {public_url}")
        print("\n" + "─" * 72)
        print("  📋 تعليمات ربط برنامج الصحفي الخارجي:")
        print("  1. انسخ الرابط أعلاه وأرسله للصحفي.")
        print("  2. يفتح الصحفي برنامجه المكتبي ⬅️ يدخل على (⚙️ إعدادات النظام).")
        print("  3. في تبويب (🎨 المظهر والنظام) يضع هذا الرابط في خانة (Central Hub URL).")
        print("  4. يضغط 'فحص الاتصال' ⬅️ ستظهر علامة 🟢 متصل فوراً!")
        print("  5. الآن أي خبر أو رقم يفحصه الصحفي، سيصل إلى قاعدة بيانات جهازك مباشرة!")
        print("─" * 72)
        print(f"  💾 تم حفظ الرابط أيضاً في ملف: {URL_FILE.name}")
        print("═" * 72)
        print("\n[ ملاحظة: اترك هذه النافذة مفتوحة طوال فترة عمل الصحفيين ]")
        print("اضغط Ctrl+C لإيقاف السيرفر والنفق في أي وقت.\n")

    def handle_exit(signum, frame):
        print("\n🛑 جاري إيقاف السيرفر المركزي ونفق Cloudflare...")
        global _cloudflared_proc, _server
        if _cloudflared_proc:
            try:
                _cloudflared_proc.terminate()
            except Exception:
                pass
        if _server:
            _server.should_exit = True
        print("✅ تم الإيقاف بنجاح. مع السلامة!")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_exit(None, None)


if __name__ == "__main__":
    main()
