#!/bin/bash
# ==============================================================================
# سكربت التثبيت والتشغيل التلقائي لمنظومة جريدة تحت الضوء على سيرفر VPS (Contabo)
# نظام التشغيل المدعوم: Ubuntu 20.04 / 22.04 / 24.04 LTS أو Debian 11 / 12
# ==============================================================================

set -e

echo "======================================================"
echo "   🚀 بدء إعداد وتثبيت منظومة جريدة تحت الضوء v4.0"
echo "======================================================"
echo ""

# 1. تحديث حزم النظام
echo "[1/6] تحديث حزم النظام وتثبيت المتطلبات الأساسية..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw

# 2. الانتقال إلى مجلد المشروع
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "[2/6] مسار المشروع الحالي: $APP_DIR"

# 3. إنشاء البيئة الافتراضية
echo "[3/6] إنشاء البيئة الافتراضية (Virtual Environment)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. فتح المنافذ في الجدار الناري
echo "[4/6] ضبط الجدار الناري (Firewall UFW)..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp
sudo ufw --force enable || true

# 5. إعداد خدمات Systemd للتشغيل الدائم في الخلفية
echo "[5/6] إعداد خدمات النظام (Systemd) لضمان العمل 24/7 وإعادة التشغيل التلقائي..."

CURRENT_USER="$(whoami)"

# أ) خدمة السيرفر المركزي والموقع (Web Server)
cat <<EOF | sudo tee /etc/systemd/system/tahteldoo-web.service > /dev/null
[Unit]
Description=Taht El Doo Newspaper Web Hub & CMS
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python web_server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# ب) خدمة بوت التليجرام (Telegram Bot)
cat <<EOF | sudo tee /etc/systemd/system/tahteldoo-bot.service > /dev/null
[Unit]
Description=Taht El Doo Telegram Publishing Bot
After=network.target tahteldoo-web.service

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m telegram_bot.bot
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 6. تفعيل وبدء تشغيل الخدمات
echo "[6/6] تشغيل الخدمات وتفعيلها عند إقلاع السيرفر..."
sudo systemctl daemon-reload
sudo systemctl enable tahteldoo-web.service
sudo systemctl restart tahteldoo-web.service

sudo systemctl enable tahteldoo-bot.service
sudo systemctl restart tahteldoo-bot.service

echo ""
echo "======================================================"
echo "   ✅ تم تثبيت وتشغيل منظومة جريدة تحت الضوء بنجاح!"
echo "======================================================"
echo ""
SERVER_IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')
echo "🌐 رابط لوحة التحكم والموقع: http://$SERVER_IP:8000"
echo "🤖 حالة بوت التليجرام: نشط ويعمل في الخلفية 24/7"
echo ""
echo "أوامر مفيدة لإدارة السيرفر:"
echo "  • فحص حالة السيرفر: sudo systemctl status tahteldoo-web"
echo "  • فحص حالة البوت:   sudo systemctl status tahteldoo-bot"
echo "  • متابعة سجل السيرفر: sudo journalctl -u tahteldoo-web -f"
echo "  • متابعة سجل البوت:   sudo journalctl -u tahteldoo-bot -f"
echo "======================================================"
