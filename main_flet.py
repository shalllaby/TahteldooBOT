import os
import sys
import time
import asyncio
import threading
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
        steps = [
            (0.15, "تهيئة قاعدة البيانات..."),
            (0.35, "تحميل خدمات الذكاء الاصطناعي..."),
            (0.55, "تهيئة خدمات النشر..."),
            (0.75, "بناء واجهة المستخدم..."),
            (0.95, "تجهيز كل شيء..."),
        ]

        # Step 1: DB
        from database.db import db
        db.init_db()
        logger.info("بدء تشغيل تطبيق نشر الأخبار — جريدة تحت الضوء الإخبارية v3.0...")
        splash_bar.value = 0.15
        splash_status.value = "تهيئة قاعدة البيانات..."
        page.update()
        time.sleep(0.1)

        # Step 2: Imports
        from flet_ui.theme import ThemeColors, get_app_theme
        from flet_ui.components.status_chip import create_status_chip
        splash_bar.value = 0.40
        splash_status.value = "تحميل مكونات الواجهة..."
        page.update()
        time.sleep(0.1)

        # Step 3: Views
        from flet_ui.views.create_view import CreateView
        from flet_ui.views.preview_view import PreviewView
        from flet_ui.views.history_view import HistoryView
        from flet_ui.views.settings_view import SettingsView
        from flet_ui.views.logs_view import LogsView
        splash_bar.value = 0.75
        splash_status.value = "تهيئة نظام النشر..."
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

        # Theme
        is_dark = (getattr(Config, "APP_THEME", "dark") == "dark")
        page.theme = get_app_theme(is_dark)
        page.bgcolor = ThemeColors.BG_DARK if is_dark else "#F1F5F9"

        # Bind icon
        if os.path.exists(icon_path):
            page.window.icon = icon_path

        _build_main_ui(
            page, ThemeColors, get_app_theme, create_status_chip,
            CreateView, PreviewView, HistoryView, SettingsView, LogsView,
            is_dark
        )

    threading.Thread(target=_load_app, daemon=True).start()


def _build_main_ui(page, ThemeColors, get_app_theme, create_status_chip,
                   CreateView, PreviewView, HistoryView, SettingsView, LogsView,
                   is_dark):
    """بناء واجهة التطبيق الرئيسية بعد انتهاء الـ Splash."""
    from core.config import Config
    from core.logger import logger

    page.title = f"تطبيق نشر الأخبار الصحفية — {Config.NEWSPAPER_NAME}"

    # Current view index state
    current_index = [0]

    # Instantiate Views
    create_view = CreateView(page)
    preview_view = PreviewView(page)
    history_view = HistoryView(page)

    settings_view = SettingsView(page)
    logs_view = LogsView(page)

    views = [
        create_view,
        preview_view,
        history_view,
        settings_view,
        logs_view
    ]

    # Content Container
    content_area = ft.Container(
        content=views[0],
        expand=True
    )

    # Helper function to switch tabs
    def switch_tab(index: int):
        current_index[0] = index
        content_area.content = views[index]
        
        # Trigger data refresh on tab switch
        if index == 2 and hasattr(history_view, "load_data"):
            history_view.load_data()
        elif index == 4 and hasattr(logs_view, "load_logs"):
            logs_view.load_logs()

        # Update Navigation Buttons Style
        for i, btn in enumerate(nav_buttons):
            is_selected = (i == index)
            btn.style.bgcolor = {
                ft.ControlState.DEFAULT: ThemeColors.SURFACE_HOVER if is_selected else ft.Colors.TRANSPARENT,
                ft.ControlState.HOVERED: ThemeColors.SURFACE_HOVER
            }
            btn.style.color = {
                ft.ControlState.DEFAULT: ThemeColors.GOLD_PRIMARY if is_selected else ThemeColors.TEXT_PRIMARY
            }
        
        page.update()

    # Callback when AI generates article -> Auto switch to Preview View
    def on_article_generated(client_id: int, ai_data: dict, selected_image_path: str):
        preview_view.load_article(client_id, ai_data, selected_image_path)
        switch_tab(1)

    create_view.on_article_generated = on_article_generated

    # Callback when article is published from preview view -> Reset create view form
    def on_publish_success():
        create_view.reset_form()

    preview_view.on_publish_success = on_publish_success

    # Sidebar Navigation Items
    nav_items = [
        ("📝   إنشاء خبر جديد", ft.Icons.AUTO_AWESOME, 0),
        ("👁️   معاينة وتعديل ونشر", ft.Icons.PREVIEW, 1),
        ("📊   أرشيف الأخبار", ft.Icons.HISTORY, 2),
        ("⚙️   إعدادات النظام", ft.Icons.SETTINGS, 3),
        ("📜   سجل العمليات", ft.Icons.RECEIPT_LONG, 4),
    ]

    nav_buttons = []
    for text, icon, idx in nav_items:
        btn = ft.TextButton(
            content=ft.Text(text),
            icon=icon,
            on_click=lambda e, i=idx: switch_tab(i),
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.DEFAULT: ThemeColors.GOLD_PRIMARY if idx == 0 else ThemeColors.TEXT_PRIMARY,
                    ft.ControlState.HOVERED: ThemeColors.GOLD_PRIMARY
                },
                bgcolor={
                    ft.ControlState.DEFAULT: ThemeColors.SURFACE_HOVER if idx == 0 else ft.Colors.TRANSPARENT,
                    ft.ControlState.HOVERED: ThemeColors.SURFACE_HOVER
                },
                padding=ft.Padding.symmetric(horizontal=15, vertical=12),
                alignment=ft.Alignment(1, 0),
                shape=ft.RoundedRectangleBorder(radius=8)
            )
        )
        nav_buttons.append(btn)

    # Blogger Status Chip
    blogger_chip_text = "🟢 Blogger" if Config.BLOGGER_BLOG_ID else "🔴 غير متصل"
    blogger_chip = create_status_chip(blogger_chip_text, is_ok=bool(Config.BLOGGER_BLOG_ID))
    wa_chip = create_status_chip("💬 WhatsApp", is_ok=True)

    def on_blogger_status_changed(blog_name, status_text):
        is_ok = ("🟢" in status_text)
        blogger_chip.content.controls[1].value = status_text
        blogger_chip.content.controls[1].color = ThemeColors.SUCCESS if is_ok else ThemeColors.ERROR
        page.update()

    settings_view.on_blogger_status_changed = on_blogger_status_changed

    # Brand Avatar Header in Sidebar
    brand_avatar = ft.Container(
        content=ft.Row(
            controls=[
                ft.Image(src="ico.ico", width=36, height=36) if os.path.exists("ico.ico") else ft.Icon(ft.Icons.NEWSPAPER, color=ThemeColors.GOLD_PRIMARY, size=32),
                ft.Column(
                    controls=[
                        ft.Text("تحت الضوء", size=16, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_PRIMARY),
                        ft.Text("أتمتة النشر والواتساب 2.0", size=10, color=ThemeColors.TEXT_MUTED)
                    ],
                    spacing=1
                )
            ],
            spacing=10
        ),
        padding=ft.Padding.only(bottom=10)
    )

    sidebar = ft.Container(
        content=ft.Column(
            controls=[
                brand_avatar,
                ft.Row([blogger_chip, wa_chip], spacing=5),
                ft.Divider(color=ThemeColors.BORDER_COLOR, height=1),
                ft.Text("القائمة الرئيسية", size=11, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_MUTED),
                ft.Column(controls=nav_buttons, spacing=4),
                ft.Container(expand=True),
                ft.Text("© جريدة تحت الضوء 2026\nالإصدار الذكي v3.0", size=10, color=ThemeColors.TEXT_MUTED, text_align=ft.TextAlign.CENTER)
            ],
            spacing=10,
            expand=True
        ),
        width=250,
        padding=15,
        bgcolor="#070A11",
        border=ft.Border.only(left=ft.BorderSide(1, ThemeColors.BORDER_COLOR))
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
