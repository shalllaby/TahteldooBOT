import os
import sys
import time
import asyncio
import threading
import ssl

# Fix SSL Certificate Verification failure for urllib & HTTPS connections
os.environ["PYTHONHTTPSVERIFY"] = "0"
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
except Exception:
    pass

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

import flet as ft

from core.config import Config
from core.logger import logger


def _safe_window_center(page: ft.Page):
    try:
        res = page.window.center()
        if asyncio.iscoroutine(res):
            res.close()
    except Exception:
        pass


def main(page: ft.Page):
    # ═══════════════════════════════════════════════════
    # SPLASH SCREEN — يظهر فوراً قبل أي تحميل
    # ═══════════════════════════════════════════════════
    page.title = "جريدة تحت الضوء الإخبارية"
    page.rtl = True
    page.padding = 0
    page.spacing = 0
    page.bgcolor = "#070A11"
    page.window.width = 480
    page.window.height = 320
    page.window.min_width = 480
    page.window.min_height = 320
    _safe_window_center(page)
    page.window.frameless = True

    splash_status = ft.Text(
        "جاري تهيئة النظام...",
        size=12,
        color="#8899AA",
        text_align=ft.TextAlign.CENTER
    )
    splash_bar = ft.ProgressBar(
        color="#C8A84B",
        bgcolor="#1A2035",
        width=320,
        height=4,
        value=0.0
    )

    icon_path = str(Config.BASE_DIR / "ico.ico")
    icon_ctrl = (
        ft.Image(src="ico.ico", width=72, height=72, fit="contain")
        if os.path.exists(icon_path)
        else ft.Icon(ft.Icons.NEWSPAPER, color="#C8A84B", size=64)
    )

    splash_content = ft.Column(
        controls=[
            ft.Container(height=20),
            icon_ctrl,
            ft.Container(height=12),
            ft.Text(
                "جريدة تحت الضوء الإخبارية",
                size=20,
                weight=ft.FontWeight.BOLD,
                color="#C8A84B",
                text_align=ft.TextAlign.CENTER
            ),
            ft.Text(
                "نظام نشر الأخبار الذكي  v3.0",
                size=12,
                color="#4A6080",
                text_align=ft.TextAlign.CENTER
            ),
            ft.Container(height=20),
            splash_bar,
            ft.Container(height=8),
            splash_status,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=4,
    )

    page.add(
        ft.Container(
            content=splash_content,
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor="#070A11",
        )
    )
    page.update()

    # ═══════════════════════════════════════════════════
    # تحميل باقي التطبيق في الخلفية
    # ═══════════════════════════════════════════════════
    def _load_app():
        try:
            # Step 1: DB
            from database.db import db
            db.init_db()
            logger.info("بدء تشغيل تطبيق نشر الأخبار — جريدة تحت الضوء الإخبارية v3.0...")
            splash_bar.value = 0.15
            splash_status.value = "تهيئة قاعدة البيانات..."
            page.update()
            time.sleep(0.1)

            # Step 2: Imports
            from flet_ui.theme import ThemeColors, theme_manager, THEMES, get_app_theme
            from flet_ui.components.status_chip import create_status_chip
            splash_bar.value = 0.40
            splash_status.value = "تحميل مكونات الواجهة..."
            page.update()
            time.sleep(0.1)

            # Step 3: Views
            from flet_ui.views.create_view import CreateView
            from flet_ui.views.preview_view import PreviewView
            from flet_ui.views.verification_view import VerificationView
            from flet_ui.views.history_view import HistoryView
            from flet_ui.views.settings_view import SettingsView
            from flet_ui.views.logs_view import LogsView

            # Auto-start Central Hub Server in background if configured for localhost and not already active
            try:
                from services.central_sync_service import central_sync_service
                hub_url = getattr(Config, "CENTRAL_HUB_URL", "http://127.0.0.1:8000")
                is_local = ("127.0.0.1" in hub_url) or ("localhost" in hub_url)
                if is_local and not central_sync_service.is_hub_available():
                    from services.central_hub import start_central_hub_background
                    start_central_hub_background()
                    logger.info("تم تشغيل السيرفر المركزي (Central Hub) بنجاح في الخلفية.")
            except Exception as hub_ex:
                logger.warning(f"ملاحظة حول تشغيل Central Hub: {hub_ex}")

            splash_bar.value = 0.75
            splash_status.value = "تهيئة نظام النشر والسيرفر المركزي..."
            page.update()
            time.sleep(0.1)

            splash_bar.value = 1.0
            splash_status.value = "✅ جاهز!"
            page.update()
            time.sleep(0.3)

            # ═══════════════════════════════════════════════
            # الآن نبني التطبيق الحقيقي
            # ═══════════════════════════════════════════════
            page.controls.clear()
            page.window.frameless = False
            page.window.width = 1360
            page.window.height = 860
            page.window.min_width = 1000
            page.window.min_height = 640
            _safe_window_center(page)

            # Theme Setup
            saved_theme = getattr(Config, "APP_THEME", "dark")
            if saved_theme not in THEMES:
                saved_theme = "dark"
            theme_manager.set_theme(saved_theme)
            page.theme = theme_manager.get_app_theme(saved_theme)
            page.bgcolor = theme_manager.get_palette()["BG_APP"]

            # Bind icon
            if os.path.exists(icon_path):
                page.window.icon = icon_path

            _build_main_ui(
                page, ThemeColors, get_app_theme, create_status_chip,
                CreateView, PreviewView, VerificationView, HistoryView, SettingsView, LogsView,
                initial_tab=0
            )
        except Exception as ex:
            import traceback
            err_details = traceback.format_exc()
            logger.error(f"فشل تشغيل التطبيق في _load_app: {ex}\n{err_details}")
            splash_status.value = f"❌ خطأ عند التشغيل: {ex}"
            splash_bar.value = 1.0
            page.update()

    threading.Thread(target=_load_app, daemon=True).start()


def _build_main_ui(page, ThemeColors, get_app_theme, create_status_chip,
                   CreateView, PreviewView, VerificationView, HistoryView, SettingsView, LogsView,
                   initial_tab=0):
    """بناء واجهة التطبيق الرئيسية بعد انتهاء الـ Splash ودعم التبديل اللحظي بين الثيمات الثلاثة."""
    from core.config import Config
    from core.logger import logger
    from flet_ui.theme import theme_manager, THEMES

    page.title = f"تطبيق نشر الأخبار الصحفية — {Config.NEWSPAPER_NAME}"

    # Current view index state
    current_index = [initial_tab]

    def change_theme(theme_name: str):
        if theme_name not in THEMES:
            return
        theme_manager.set_theme(theme_name)
        Config.update_env("APP_THEME", theme_name)
        Config.APP_THEME = theme_name
        p = theme_manager.get_palette(theme_name)
        page.theme = theme_manager.get_app_theme(theme_name)
        page.bgcolor = p["BG_APP"]
        page.controls.clear()
        _build_main_ui(
            page, ThemeColors, get_app_theme, create_status_chip,
            CreateView, PreviewView, VerificationView, HistoryView, SettingsView, LogsView,
            initial_tab=current_index[0]
        )
        page.update()

    # Instantiate Views
    create_view = CreateView(page)
    preview_view = PreviewView(page)
    verification_view = VerificationView(page)
    history_view = HistoryView(page)
    settings_view = SettingsView(page, on_theme_changed=change_theme)
    logs_view = LogsView(page, on_navigate=lambda idx: switch_tab(idx))

    views = [
        create_view,          # 0
        preview_view,         # 1
        verification_view,    # 2
        history_view,         # 3
        settings_view,        # 4
        logs_view             # 5
    ]

    # Content Container
    content_area = ft.Container(
        content=views[initial_tab],
        expand=True
    )

    palette = theme_manager.get_palette()

    def _style_nav_btn(btn, is_selected, p):
        btn.style = ft.ButtonStyle(
            color={
                ft.ControlState.DEFAULT: p["ACCENT"] if is_selected else p["TEXT_PRIMARY"],
                ft.ControlState.HOVERED: p["ACCENT"],
            },
            bgcolor={
                ft.ControlState.DEFAULT: p["BG_SURFACE_HOVER"] if is_selected else ft.Colors.TRANSPARENT,
                ft.ControlState.HOVERED: p["BG_SURFACE_HOVER"],
            },
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(1.5, p["ACCENT"]) if is_selected else ft.BorderSide(0, ft.Colors.TRANSPARENT),
            },
            padding=ft.Padding.symmetric(horizontal=14, vertical=11),
            alignment=ft.Alignment(1, 0),
            shape=ft.RoundedRectangleBorder(radius=8),
        )

    # Helper function to switch tabs
    def switch_tab(index: int):
        current_index[0] = index
        content_area.content = views[index]
        
        # Trigger data refresh on tab switch
        if index == 3 and hasattr(history_view, "load_data"):
            history_view.load_data()
        elif index == 5 and hasattr(logs_view, "load_logs"):
            logs_view.load_logs()

        # Update Navigation Buttons Style
        cur_p = theme_manager.get_palette()
        for i, btn in enumerate(nav_buttons):
            _style_nav_btn(btn, i == index, cur_p)
        
        page.update()

    # Callback when AI generates article -> Auto switch to Preview View
    def on_article_generated(client_id: int, ai_data: dict, selected_image_path: str):
        preview_view.load_article(client_id, ai_data, selected_image_path)
        switch_tab(1)

    create_view.on_article_generated = on_article_generated

    # Callback when user verifies client and wants to create article immediately
    def on_create_for_client(query):
        create_view.prefill_client(query)
        switch_tab(0)

    verification_view.on_create_for_client = on_create_for_client

    # Sidebar Navigation Items
    nav_items = [
        ("📝   إنشاء خبر جديد", ft.Icons.AUTO_AWESOME, 0),
        ("👁️   معاينة وتعديل ونشر", ft.Icons.PREVIEW, 1),
        ("🔍   التحقق من العملاء", ft.Icons.PERSON_SEARCH, 2),
        ("📊   أرشيف الأخبار", ft.Icons.HISTORY, 3),
        ("⚙️   إعدادات النظام", ft.Icons.SETTINGS, 4),
        ("📜   سجل العمليات", ft.Icons.RECEIPT_LONG, 5),
    ]

    nav_buttons = []
    for text, icon, idx in nav_items:
        btn = ft.TextButton(
            content=ft.Text(text),
            icon=icon,
            on_click=lambda e, i=idx: switch_tab(i),
        )
        _style_nav_btn(btn, idx == initial_tab, palette)
        nav_buttons.append(btn)

    # Blogger & Central Server Status Chips
    from services.blogger_service import blogger_service
    is_blogger_auth = blogger_service.is_authenticated()
    blogger_chip_text = "🟢 Blogger" if is_blogger_auth else "🔴 Blogger"
    blogger_chip = create_status_chip(blogger_chip_text, is_ok=is_blogger_auth)
    wa_chip = create_status_chip("💬 WhatsApp", is_ok=True)
    hub_chip = create_status_chip("🌐 سيرفر مركزي", is_ok=True)
    quota_chip = create_status_chip("📊 كوتا: ...", is_ok=True, icon=ft.Icons.ANALYTICS)

    def refresh_quota():
        try:
            from services.blogger_service import blogger_service
            q_info = blogger_service.get_quota_info()
            status_text = q_info.get("status_text", "📊 كوتا Blogger")
            status = q_info.get("status", "OK")
            is_ok = (status == "OK")
            is_warn = (status == "WARNING")

            bg_col = "#064E3B" if is_ok else ("#78350F" if is_warn else "#7F1D1D")
            text_col = palette["SUCCESS"] if is_ok else ("#FBBF24" if is_warn else palette["ERROR"])

            quota_chip.content.controls[1].value = status_text
            quota_chip.content.controls[1].color = text_col
            quota_chip.content.controls[0].color = text_col
            quota_chip.bgcolor = bg_col
            quota_chip.border = ft.border.all(1, text_col)
            quota_chip.tooltip = f"المستهلك: {q_info['used']:,} من {q_info['limit']:,} | المتبقي: {q_info['remaining']:,} طلب"
            page.update()
        except Exception as q_err:
            logger.warning(f"Error updating quota chip: {q_err}")

    threading.Thread(target=refresh_quota, daemon=True).start()

    def on_blogger_status_changed(blog_name, status_text):
        is_ok = ("🟢" in status_text)
        blogger_chip.content.controls[1].value = status_text
        blogger_chip.content.controls[1].color = palette["SUCCESS"] if is_ok else palette["ERROR"]
        page.update()
        threading.Thread(target=refresh_quota, daemon=True).start()

    settings_view.on_blogger_status_changed = on_blogger_status_changed

    # Callback when article is published from preview view -> Reset create view form & refresh quota
    def on_publish_success():
        create_view.reset_form()
        threading.Thread(target=refresh_quota, daemon=True).start()

    preview_view.on_publish_success = on_publish_success

    # Brand Avatar Header in Sidebar
    brand_avatar = ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Image(src="ico.ico", width=36, height=36, fit="contain") if os.path.exists("ico.ico") else ft.Icon(ft.Icons.NEWSPAPER_ROUNDED, color=palette["ACCENT"], size=30),
                    padding=3,
                    bgcolor=palette["HEADER_ICON_BG"],
                    border_radius=8,
                    border=ft.border.all(1, palette["BORDER"]),
                ),
                ft.Column(
                    controls=[
                        ft.Text(Config.NEWSPAPER_NAME or "تحت الضوء", size=15, weight=ft.FontWeight.BOLD, color=palette["TEXT_PRIMARY"]),
                        ft.Row(
                            controls=[
                                ft.Container(width=6, height=6, border_radius=3, bgcolor=palette["SUCCESS"]),
                                ft.Text("النظام الصحفي v3.0", size=10, color=palette["TEXT_MUTED"]),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER
                        )
                    ],
                    spacing=1
                )
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        ),
        padding=ft.Padding.only(bottom=6)
    )

    # Quick Tri-Theme Switcher in Sidebar
    current_theme = theme_manager.get_theme_name()
    theme_options = [
        ("dark", "أسود", ft.Icons.DARK_MODE_ROUNDED),
        ("gray", "رمادي", ft.Icons.CONTRAST_ROUNDED),
        ("light", "أبيض", ft.Icons.LIGHT_MODE_ROUNDED),
    ]

    theme_switch_btns = []
    for t_key, t_label, t_icon in theme_options:
        is_active = (t_key == current_theme)
        theme_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(t_icon, size=13, color=palette["ACCENT"] if is_active else palette["TEXT_MUTED"]),
                    ft.Text(
                        t_label,
                        size=10.5,
                        weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                        color=palette["ACCENT"] if is_active else palette["TEXT_MUTED"]
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=3
            ),
            padding=ft.padding.symmetric(horizontal=4, vertical=6),
            border_radius=6,
            bgcolor=palette["BG_SURFACE_HOVER"] if is_active else ft.Colors.TRANSPARENT,
            border=ft.border.all(1.5 if is_active else 1, palette["ACCENT"] if is_active else palette["BORDER"]),
            on_click=lambda e, k=t_key: change_theme(k),
            ink=True,
            expand=True,
            tooltip=THEMES[t_key]["title"]
        )
        theme_switch_btns.append(theme_btn)

    theme_dock = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PALETTE_OUTLINED, size=13, color=palette["TEXT_MUTED"]),
                        ft.Text("المظهر السريع", size=10.5, weight=ft.FontWeight.BOLD, color=palette["TEXT_MUTED"]),
                    ],
                    spacing=4
                ),
                ft.Row(controls=theme_switch_btns, spacing=4),
            ],
            spacing=4
        ),
        padding=6,
        border_radius=8,
        bgcolor=palette["BG_APP"],
        border=ft.border.all(1, palette["BORDER"])
    )

    # Status Dock in Sidebar
    status_dock = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row([blogger_chip, wa_chip], spacing=4),
                ft.Row([quota_chip, hub_chip], spacing=4),
            ],
            spacing=4
        ),
        padding=6,
        border_radius=8,
        bgcolor=palette["BG_APP"],
        border=ft.border.all(1, palette["BORDER"])
    )

    sidebar = ft.Container(
        content=ft.Column(
            controls=[
                brand_avatar,
                theme_dock,
                status_dock,
                ft.Divider(color=palette["BORDER"], height=1),
                ft.Text("القائمة الرئيسية", size=11, weight=ft.FontWeight.BOLD, color=palette["TEXT_MUTED"]),
                ft.Column(controls=nav_buttons, spacing=3),
                ft.Container(expand=True),
                ft.Text(
                    f"© {Config.NEWSPAPER_NAME or 'جريدة تحت الضوء'} 2026\nالإصدار الذكي v3.0",
                    size=10,
                    color=palette["TEXT_MUTED"],
                    text_align=ft.TextAlign.CENTER
                )
            ],
            spacing=8,
            expand=True
        ),
        width=260,
        padding=12,
        bgcolor=palette["BG_SIDEBAR"],
        border=ft.Border.only(left=ft.BorderSide(1, palette["BORDER"]))
    )

    # Main App Layout (Sidebar + Content Area)
    main_layout = ft.Row(
        controls=[
            sidebar,
            content_area
        ],
        spacing=0,
        expand=True
    )

    page.add(main_layout)


if __name__ == "__main__":
    if hasattr(ft, "run"):
        try:
            ft.run(main, assets_dir="assets")
        except Exception:
            ft.app(target=main, assets_dir="assets")
    else:
        ft.app(target=main, assets_dir="assets")
