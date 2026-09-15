#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
أداة ربط حسابات بلوجر المتعددة لبوت جريدة تحت الضوء
تتيح تسجيل الدخول لـ 3 حسابات جوجل مختلفة لإنشاء ملفات التوكن:
- token_1.pickle (الحساب الأول)
- token_2.pickle (الحساب الثاني)
- token_3.pickle (الحساب الثالث)
"""

import os
import sys
import pickle
import argparse
from pathlib import Path

# Fix SSL verification if needed
os.environ["PYTHONHTTPSVERIFY"] = "0"

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from core.config import Config

SCOPES = ["https://www.googleapis.com/auth/blogger"]


def get_token_paths(slot: int):
    """Returns local and AppData paths for a token slot."""
    name = f"token_{slot}.pickle"
    app_data_path = Config.APP_DATA_DIR / name
    base_dir_path = Config.BASE_DIR / name
    return app_data_path, base_dir_path


def authenticate_slot(slot: int):
    """Performs Google OAuth authentication for a given slot (1, 2, or 3)."""
    creds_path = Config.CREDENTIALS_FILE
    if not os.path.exists(creds_path):
        print(f"❌ لم يتم العثور على ملف credentials.json في: {creds_path}")
        return False

    print(f"\n🚀 جاري بدء تسجيل الدخول لـ [حساب بلوجر رقم {slot}]...")
    print("🌐 سيتم فتح المتصفح الآن لتسجيل الدخول بحساب Google المطلوب...")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)

        # Save to both APP_DATA_DIR and BASE_DIR for maximum reliability
        app_data_path, base_dir_path = get_token_paths(slot)

        for p in [app_data_path, base_dir_path]:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "wb") as f:
                pickle.dump(creds, f)

        # If slot 1, also update standard token.pickle for backward compatibility
        if slot == 1:
            with open(Config.BASE_DIR / "token.pickle", "wb") as f:
                pickle.dump(creds, f)
            with open(Config.APP_DATA_DIR / "token.pickle", "wb") as f:
                pickle.dump(creds, f)

        # Query user info to confirm
        service = build("blogger", "v3", credentials=creds)
        user_info = service.users().get(userId="self").execute()
        display_name = user_info.get("displayName", "مستخدم Google")
        print(f"✅ تم ربط حساب بلوجر رقم {slot} بنجاح!")
        print(f"👤 اسم الحساب: {display_name}")
        print(f"💾 تم حفظ التوكن في: {base_dir_path.name}")
        return True

    except Exception as e:
        print(f"❌ حدث خطأ أثناء ربط الحساب رقم {slot}: {e}")
        return False


def check_status():
    """Displays the current status of all 3 Blogger account slots."""
    print("\n📊 فحص حالة حسابات بلوجر الثلاثة:")
    print("=" * 60)

    for slot in [1, 2, 3]:
        app_data_path, base_dir_path = get_token_paths(slot)
        exists = base_dir_path.exists() or app_data_path.exists()
        target_path = base_dir_path if base_dir_path.exists() else app_data_path
        if slot == 1 and not exists:
            if (Config.BASE_DIR / "token.pickle").exists():
                exists = True
                target_path = Config.BASE_DIR / "token.pickle"

        if exists:
            try:
                with open(target_path, "rb") as f:
                    creds = pickle.load(f)
                if creds and creds.valid:
                    status = "✅ متصل ونشط"
                elif creds and creds.refresh_token:
                    status = "🟡 يحتاج تحديث تلقائي (صالح)"
                else:
                    status = "⚠️ منتهي الصلاحية"
            except Exception:
                status = "❌ تالف أو غير صالح"
            print(f"• الحساب رقم {slot}: {status} ({target_path.name})")
        else:
            print(f"• الحساب رقم {slot}: ⚪ غير مسجل بعد")

    print("=" * 60)


def interactive_menu():
    """Runs interactive terminal menu."""
    while True:
        print("\n==================================================")
        print("  📰 مدير حسابات بلوجر - جريدة تحت الضوء")
        print("==================================================")
        print("1️⃣  تسجيل / تحديث الحساب الأول (Account 1)")
        print("2️⃣  تسجيل / تحديث الحساب الثاني (Account 2)")
        print("3️⃣  تسجيل / تحديث الحساب الثالث (Account 3)")
        print("4️⃣  عرض حالة جميع الحسابات المربوطة")
        print("5️⃣  خروج")
        print("--------------------------------------------------")

        choice = input("👉 اختر رقم العملية (1-5): ").strip()
        if choice == "1":
            authenticate_slot(1)
        elif choice == "2":
            authenticate_slot(2)
        elif choice == "3":
            authenticate_slot(3)
        elif choice == "4":
            check_status()
        elif choice == "5":
            print("👋 وداعاً!")
            break
        else:
            print("⚠️ اختيار غير صحيح، يرجى إدخال رقم بين 1 و 5.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="إدارة حسابات بلوجر المتعددة")
    parser.add_argument("--account", type=int, choices=[1, 2, 3], help="رقم الحساب المراد تسجيله (1 أو 2 أو 3)")
    parser.add_argument("--status", action="store_true", help="عرض حالة الحسابات المسجلة")
    args = parser.parse_args()

    if args.status:
        check_status()
    elif args.account:
        authenticate_slot(args.account)
    else:
        interactive_menu()
