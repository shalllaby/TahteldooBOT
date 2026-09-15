#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
جريدة تحت الضوء الإخبارية — لوحة تحكم بوت التليجرام والمحررين المستقلة
تطبيق مكتبي متكامل (Standalone Desktop App) للتحكم الكامل في:
- تشغيل وإيقاف بوت تليجرام ومراقبة حالته اللحظية
- إدارة الصحفيين وأكواد التفعيل (API Keys) وتتبع إنتاجيتهم
- حوض حسابات بلوجر المتعددة (3 حسابات) وتوثيقها بضغطة زر
- سجل الأخطاء والأنشطة اللحظي
"""

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Fix SSL verification
os.environ["PYTHONHTTPSVERIFY"] = "0"
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
except Exception:
    pass

import flet as ft

from flet_ui.theme import (
    ThemeColors,
    get_app_theme,
    create_glass_card,
    create_gold_button,
    create_secondary_button,
    create_input_field
)
from flet_ui.components.notification import show_snack, copy_to_clipboard
from database.db import db
from services.blogger_service import blogger_service
from telegram_bot.bot_controller import bot_controller
from core.logger import logger

# Background warm-up of bot runtime without delaying window startup
def _warmup_bot_runtime():
    try:
        import telegram_bot.bot
    except Exception:
        pass
threading.Thread(target=_warmup_bot_runtime, daemon=True).start()


def create_stat_card(icon, title: str, value_ref: ft.Text, border_color=None):
    return ft.Container(
        content=ft.Row([
            ft.Container(
                content=ft.Icon(icon, color=ThemeColors.GOLD_PRIMARY, size=24),
                padding=10,
                border_radius=10,
                bgcolor="#F59E0B15"
            ),
            ft.Column([
                ft.Text(title, size=11, color=ThemeColors.TEXT_MUTED),
                value_ref
            ], spacing=2)
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border_radius=12,
        bgcolor=ThemeColors.SURFACE_DARK,
        border=ft.border.all(1, border_color or ThemeColors.BORDER_COLOR),
        expand=True
    )


class BotManagerView(ft.Container):
    def __init__(self, page: ft.Page):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.reporters = []
        self.bot_logs = []
        self.active_tab_idx = 0
        self.reveal_keys = {}
        self.is_dialog_open = False
        self.live_sync_enabled = True
        self._is_refreshing = False
        self._last_reporters_sig = None
        self._last_logs_sig = None
        self._last_pool_sig = None

        self.init_ui()
        self.load_all_data()
        self._start_status_poller()

    def _start_status_poller(self):
        def _poll():
            while True:
                time.sleep(2.5)
                try:
                    self.live_refresh_data()
                except Exception as ex:
                    logger.debug(f"Status poller exception: {ex}")
        threading.Thread(target=_poll, daemon=True).start()

    def live_refresh_data(self):
        if getattr(self, "_is_refreshing", False):
            return
        self._is_refreshing = True
        try:
            # 1. Update bot status UI (running/stopped/uptime)
            if hasattr(self, "status_chip"):
                self.update_bot_status_ui()

            # If user has an active dialog open or sync is disabled, pause table updates
            if self.is_dialog_open or not self.live_sync_enabled:
                return

            # 2. Fetch fresh reporters & stats from DB
            fresh_reporters = db.get_reporters_with_stats()
            fresh_logs = db.get_bot_logs(limit=150)
            pool_status = blogger_service.get_pool_status()

            # Update Stat Cards
            rep_count_str = str(len(fresh_reporters))
            if self.stat_reporters.value != rep_count_str:
                self.stat_reporters.value = rep_count_str

            today_total_str = str(sum(r.get("articles_today", 0) for r in fresh_reporters))
            if self.stat_articles_today.value != today_total_str:
                self.stat_articles_today.value = today_total_str

            active_slots_str = f"{sum(1 for a in pool_status if a.get('is_valid'))}/3"
            if self.stat_blogger_accounts.value != active_slots_str:
                self.stat_blogger_accounts.value = active_slots_str

            err_count_str = str(sum(1 for l in fresh_logs if l.get("level") == "ERROR"))
            if self.stat_errors.value != err_count_str:
                self.stat_errors.value = err_count_str

            # 3. Tab-specific live update
            if self.active_tab_idx == 0:
                self.reporters = fresh_reporters
                search_term = (getattr(self, "search_reporter_input", None) and self.search_reporter_input.value or "").strip().lower()
                if search_term:
                    display_list = [
                        r for r in self.reporters
                        if search_term in str(r.get("name", "")).lower()
                        or search_term in str(r.get("telegram_id", "")).lower()
                        or search_term in str(r.get("api_key", "")).lower()
                    ]
                else:
                    display_list = self.reporters

                rep_sig = [
                    (r.get("telegram_id"), r.get("name"), r.get("api_key"), r.get("articles_today"), r.get("total_articles"), self.reveal_keys.get(str(r.get("telegram_id", "")), False))
                    for r in display_list
                ]
                if rep_sig != self._last_reporters_sig:
                    self._last_reporters_sig = rep_sig
                    if hasattr(self, "reporters_table"):
                        self._populate_reporters_table(display_list)

            elif self.active_tab_idx == 1:
                pool_sig = [(a.get("account_id"), a.get("is_valid"), a.get("status_text")) for a in pool_status]
                if pool_sig != self._last_pool_sig:
                    self._last_pool_sig = pool_sig
                    if hasattr(self, "blogger_cards_row"):
                        self.blogger_cards_row.controls = [self._build_account_card(a) for a in pool_status]

            elif self.active_tab_idx == 2:
                self.bot_logs = fresh_logs
                logs_sig = [(l.get("id"), l.get("created_at"), l.get("message"), l.get("level")) for l in self.bot_logs]
                if logs_sig != self._last_logs_sig:
                    self._last_logs_sig = logs_sig
                    if hasattr(self, "logs_table"):
                        self._populate_logs_table(self.bot_logs)

            self.safe_update()
        except Exception as ex:
            logger.debug(f"live_refresh_data error: {ex}")
        finally:
            self._is_refreshing = False

    def safe_update(self):
        try:
            self.update()
        except Exception:
            pass

    def _open_dialog(self, dlg):
        try:
            self.is_dialog_open = True
            orig_dismiss = getattr(dlg, "on_dismiss", None)
            def _dismiss_wrapper(e):
                self.is_dialog_open = False
                if orig_dismiss:
                    try:
                        orig_dismiss(e)
                    except Exception:
                        pass
            dlg.on_dismiss = _dismiss_wrapper

            if hasattr(self.app_page, "open"):
                self.app_page.open(dlg)
            else:
                self.app_page.dialog = dlg
                dlg.open = True
                self.app_page.update()
        except Exception as ex:
            logger.error(f"Error opening dialog: {ex}")

    def _close_dialog(self, dlg):
        try:
            self.is_dialog_open = False
            if hasattr(self.app_page, "close"):
                self.app_page.close(dlg)
            else:
                dlg.open = False
                self.app_page.update()
        except Exception:
            pass

    def init_ui(self):
        # 1. Header with Bot Controls
        self.status_chip = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.RADIO_BUTTON_CHECKED, color=ThemeColors.SUCCESS, size=14),
                ft.Text("جاري الفحص...", size=12, weight=ft.FontWeight.BOLD, color=ThemeColors.SUCCESS)
            ], spacing=6, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            border_radius=20,
            bgcolor="#10B98120",
            border=ft.border.all(1, ThemeColors.SUCCESS)
        )

        self.btn_start = ft.ElevatedButton(
            "▶️  تشغيل البوت",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self.handle_start_bot,
            style=ft.ButtonStyle(
                bgcolor=ThemeColors.SUCCESS,
                color="#FFFFFF",
                padding=ft.padding.symmetric(horizontal=18, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=10)
            )
        )

        self.btn_stop = ft.ElevatedButton(
            "⏹️  إيقاف البوت",
            icon=ft.Icons.STOP,
            on_click=self.handle_stop_bot,
            style=ft.ButtonStyle(
                bgcolor="#EF444425",
                color=ThemeColors.ERROR,
                padding=ft.padding.symmetric(horizontal=18, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=10),
                side=ft.BorderSide(1, ThemeColors.ERROR)
            ),
            disabled=True
        )

        self.live_indicator = ft.Container(
            content=ft.Row([
                ft.Container(
                    width=8,
                    height=8,
                    border_radius=4,
                    bgcolor=ThemeColors.SUCCESS
                ),
                ft.Text("تحديث لحظي مباشر ⚡", size=11, weight=ft.FontWeight.BOLD, color=ThemeColors.SUCCESS)
            ], spacing=6, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=10, vertical=7),
            border_radius=15,
            bgcolor="#10B98118",
            border=ft.border.all(1, "#10B98150"),
            tooltip="البيانات وقائمة الصحفيين وسجل البوت تتحدث تلقائياً وفورياً كل ثانيتين ونصف"
        )

        header_row = ft.Row([
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SMART_TOY, color=ThemeColors.GOLD_PRIMARY, size=32),
                    padding=10,
                    border_radius=12,
                    bgcolor="#F59E0B20",
                    border=ft.border.all(1, ThemeColors.GOLD_PRIMARY)
                ),
                ft.Column([
                    ft.Text("لوحة إدارة بوت التليجرام والمحررين", size=20, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                    ft.Text("التحكم الكامل في تشغيل البوت، أكواد التفعيل للصحفيين، وتدوير حسابات بلوجر", size=12, color=ThemeColors.TEXT_MUTED)
                ], spacing=2)
            ], spacing=12),
            ft.Row([
                self.live_indicator,
                self.status_chip,
                self.btn_start,
                self.btn_stop,
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="تحديث يدوي فوري",
                    icon_color=ThemeColors.GOLD_PRIMARY,
                    on_click=lambda e: self.load_all_data()
                )
            ], spacing=10)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        # 2. Stat summary cards
        self.stat_reporters = ft.Text("0", size=18, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_PRIMARY)
        self.stat_articles_today = ft.Text("0", size=18, weight=ft.FontWeight.BOLD, color=ThemeColors.SUCCESS)
        self.stat_blogger_accounts = ft.Text("0/3", size=18, weight=ft.FontWeight.BOLD, color=ThemeColors.INFO)
        self.stat_errors = ft.Text("0", size=18, weight=ft.FontWeight.BOLD, color=ThemeColors.ERROR)

        stats_row = ft.Row([
            create_stat_card(ft.Icons.PEOPLE, "الصحفيين المسجلين", self.stat_reporters),
            create_stat_card(ft.Icons.TODAY, "أخبار اليوم عبر البوت", self.stat_articles_today, ThemeColors.SUCCESS),
            create_stat_card(ft.Icons.CLOUD_SYNC, "حسابات بلوجر النشطة", self.stat_blogger_accounts, ThemeColors.INFO),
            create_stat_card(ft.Icons.BUG_REPORT, "أخطاء مسجلة", self.stat_errors, ThemeColors.ERROR),
        ], spacing=15)

        # 3. Navigation Tabs
        self.tab_btn_reporters = self._build_tab_button("👥 الصحفيين وأكواد التفعيل", 0)
        self.tab_btn_blogger = self._build_tab_button("🌐 حوض حسابات بلوجر (3)", 1)
        self.tab_btn_logs = self._build_tab_button("📜 سجل الأخطاء والنشاط المباشر", 2)

        tabs_bar = ft.Container(
            content=ft.Row([
                self.tab_btn_reporters,
                self.tab_btn_blogger,
                self.tab_btn_logs
            ], spacing=10),
            padding=ft.padding.only(bottom=10)
        )

        # 4. Content Area for active tab
        self.tab_content_area = ft.Container(expand=True)

        self.content = ft.Column([
            header_row,
            ft.Divider(color=ThemeColors.BORDER_COLOR, height=1),
            stats_row,
            ft.Divider(color=ThemeColors.BORDER_COLOR, height=1),
            tabs_bar,
            self.tab_content_area
        ], spacing=15, expand=True)

        self.switch_tab(0)

    def _build_tab_button(self, text: str, index: int):
        is_active = (index == self.active_tab_idx)
        return ft.ElevatedButton(
            text,
            on_click=lambda e, idx=index: self.switch_tab(idx),
            style=ft.ButtonStyle(
                bgcolor=ThemeColors.GOLD_PRIMARY if is_active else ThemeColors.SURFACE_DARK,
                color="#000000" if is_active else ThemeColors.TEXT_PRIMARY,
                padding=ft.padding.symmetric(horizontal=18, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=8),
                side=ft.BorderSide(1, ThemeColors.BORDER_COLOR)
            )
        )

    def switch_tab(self, index: int):
        self.active_tab_idx = index
        buttons = [self.tab_btn_reporters, self.tab_btn_blogger, self.tab_btn_logs]
        for i, btn in enumerate(buttons):
            is_active = (i == index)
            btn.style.bgcolor = ThemeColors.GOLD_PRIMARY if is_active else ThemeColors.SURFACE_DARK
            btn.style.color = "#000000" if is_active else ThemeColors.TEXT_PRIMARY

        if index == 0:
            self.tab_content_area.content = self._build_reporters_tab()
        elif index == 1:
            self.tab_content_area.content = self._build_blogger_tab()
        elif index == 2:
            self.tab_content_area.content = self._build_logs_tab()

        self.safe_update()

    # ══════════════════════════════════════════════════════════════
    # TAB 1: REPORTERS & ACTIVATION CODES
    # ══════════════════════════════════════════════════════════════
    def _build_reporters_tab(self):
        self.search_reporter_input = create_input_field(
            label="بحث في الصحفيين...",
            hint_text="ابحث بالاسم أو بمعرف تليجرام أو الكود...",
            on_change=self.filter_reporters,
            prefix_icon=ft.Icons.SEARCH,
            expand=True
        )

        top_actions = ft.Row([
            self.search_reporter_input,
            create_gold_button(
                "➕ إضافة صحفي جديد",
                icon=ft.Icons.PERSON_ADD,
                on_click=self.open_add_reporter_dialog
            ),
        ], spacing=15)

        self.reporters_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("#", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("اسم الصحفي", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("معرف تليجرام", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("كود التفعيل (API Key)", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("أخبار اليوم", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("الإجمالي", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("تاريخ التسجيل", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("إجراءات", weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            heading_row_color="#1E293B",
            data_row_min_height=52,
            border=ft.border.all(1, ThemeColors.BORDER_COLOR),
            border_radius=10,
            column_spacing=20,
            expand=True
        )

        table_card = create_glass_card(
            content=ft.ListView(
                controls=[self.reporters_table],
                expand=True,
                spacing=0
            ),
            expand=True,
            padding=10
        )

        self._populate_reporters_table(self.reporters)

        return ft.Column([
            top_actions,
            table_card
        ], spacing=12, expand=True)

    def _populate_reporters_table(self, reporters_list):
        rows = []
        for idx, r in enumerate(reporters_list, 1):
            tid = str(r.get("telegram_id", ""))
            name = str(r.get("name", "غير محدد"))
            role = str(r.get("role", "صحفي"))
            api_key = str(r.get("api_key", "") or "").strip()
            articles_today = r.get("articles_today", 0)
            total_cnt = r.get("total_articles", 0)
            created = str(r.get("created_at", ""))[:10]

            is_revealed = self.reveal_keys.get(tid, False)
            if api_key:
                if is_revealed:
                    masked_key = api_key
                else:
                    masked_key = api_key[:7] + "..." + api_key[-4:] if len(api_key) > 12 else "••••••••••••"
                key_color = ThemeColors.SUCCESS
            else:
                masked_key = "غير مفعل ⚠️"
                key_color = ThemeColors.WARNING

            def toggle_reveal(e, target_tid=tid):
                self.reveal_keys[target_tid] = not self.reveal_keys.get(target_tid, False)
                self._populate_reporters_table(self.reporters)

            key_cell = ft.Row([
                ft.Text(masked_key, font_family="monospace", size=11, color=key_color, selectable=True),
                ft.IconButton(
                    icon=ft.Icons.VISIBILITY_OFF if is_revealed else ft.Icons.VISIBILITY,
                    icon_size=16,
                    icon_color=ThemeColors.TEXT_MUTED,
                    tooltip="إظهار / إخفاء الكود",
                    on_click=toggle_reveal
                ) if api_key else ft.Container(),
                ft.IconButton(
                    icon=ft.Icons.COPY,
                    icon_size=16,
                    icon_color=ThemeColors.GOLD_PRIMARY,
                    tooltip="نسخ كود التفعيل",
                    on_click=lambda e, k=api_key: self.copy_key(k)
                ) if api_key else ft.Container()
            ], spacing=2, alignment=ft.MainAxisAlignment.START)

            today_badge = ft.Container(
                content=ft.Text(f"{articles_today} خبر", size=11, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border_radius=8,
                bgcolor=ThemeColors.SUCCESS if articles_today > 0 else "#334155"
            )

            actions = ft.Row([
                ft.IconButton(
                    icon=ft.Icons.KEY,
                    icon_color=ThemeColors.GOLD_PRIMARY,
                    icon_size=18,
                    tooltip="تعديل كود التفعيل",
                    on_click=lambda e, rep=r: self.open_edit_key_dialog(rep)
                ),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=ThemeColors.ERROR,
                    icon_size=18,
                    tooltip="حذف الصحفي",
                    on_click=lambda e, target_tid=tid, rname=name: self.confirm_delete_reporter(target_tid, rname)
                )
            ], spacing=2)

            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(idx), color=ThemeColors.TEXT_MUTED)),
                ft.DataCell(ft.Column([
                    ft.Text(name, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_PRIMARY),
                    ft.Text(role, size=11, color=ThemeColors.TEXT_MUTED)
                ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)),
                ft.DataCell(ft.Text(tid, color=ThemeColors.INFO, font_family="monospace")),
                ft.DataCell(key_cell),
                ft.DataCell(today_badge),
                ft.DataCell(ft.Text(str(total_cnt), weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(created, size=12, color=ThemeColors.TEXT_MUTED)),
                ft.DataCell(actions)
            ]))

        self.reporters_table.rows = rows
        self.safe_update()

    def filter_reporters(self, e):
        q = (self.search_reporter_input.value or "").strip().lower()
        if not q:
            self._populate_reporters_table(self.reporters)
            return
        filtered = [
            r for r in self.reporters
            if q in str(r.get("name", "")).lower()
            or q in str(r.get("telegram_id", "")).lower()
            or q in str(r.get("api_key", "")).lower()
        ]
        self._populate_reporters_table(filtered)

    def copy_key(self, key_text: str):
        if not key_text:
            return
        copy_to_clipboard(self.app_page, key_text)
        show_snack(self.app_page, "📋 تم نسخ كود التفعيل إلى الحافظة بنجاح!", is_success=True)

    def open_add_reporter_dialog(self, e):
        txt_tid = create_input_field("معرف تليجرام (Telegram ID)", hint_text="مثال: 123456789")
        txt_name = create_input_field("اسم الصحفي الكامل", hint_text="مثال: أحمد محمود")
        txt_key = create_input_field("كود التفعيل (Z.AI API Key)", hint_text="ألصق المفتاح هنا...")

        def save_new_reporter(ev):
            tid = (txt_tid.value or "").strip()
            name = (txt_name.value or "").strip()
            key = (txt_key.value or "").strip()
            if not tid or not name:
                show_snack(self.app_page, "⚠️ يرجى إدخال اسم الصحفي ومعرف تليجرام!", is_error=True)
                return

            db.save_reporter(tid, name, "صحفي لدى", key or None)
            self._close_dialog(dlg)
            show_snack(self.app_page, f"✅ تم تسجيل وتفعيل الصحفي {name} بنجاح!", is_success=True)
            self.load_all_data()

        dlg = ft.AlertDialog(
            title=ft.Text("إضافة أو تفعيل صحفي جديد", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("أدخل بيانات الصحفي وكود التفعيل الخاص به لربطه بالبوت مباشرة:", size=12, color=ThemeColors.TEXT_MUTED),
                    txt_tid,
                    txt_name,
                    txt_key
                ], spacing=12),
                width=450,
                height=260
            ),
            actions=[
                ft.TextButton("إلغاء", on_click=lambda ev: self._close_dialog(dlg)),
                create_gold_button("💾 حفظ الصحفي", on_click=save_new_reporter)
            ]
        )
        self._open_dialog(dlg)

    def open_edit_key_dialog(self, reporter):
        tid = str(reporter.get("telegram_id", ""))
        name = str(reporter.get("name", "الصحفي"))
        curr_key = str(reporter.get("api_key", "") or "")

        txt_new_key = create_input_field(
            "كود التفعيل الجديد (API Key)",
            value=curr_key,
            hint_text="ألصق كود Z.AI الجديد هنا...",
            multiline=True,
            rows=3
        )

        def save_key(ev):
            new_val = (txt_new_key.value or "").strip()
            db.update_reporter_key(tid, new_val)
            self._close_dialog(dlg)
            show_snack(self.app_page, f"✅ تم تحديث كود التفعيل للصحفي {name} بنجاح!", is_success=True)
            self.load_all_data()

        dlg = ft.AlertDialog(
            title=ft.Text(f"تعديل كود تفعيل: {name}", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"معرف تليجرام: {tid}", size=12, color=ThemeColors.INFO),
                    txt_new_key
                ], spacing=10),
                width=460,
                height=180
            ),
            actions=[
                ft.TextButton("إلغاء", on_click=lambda ev: self._close_dialog(dlg)),
                create_gold_button("💾 حفظ التحديث", on_click=save_key)
            ]
        )
        self._open_dialog(dlg)

    def confirm_delete_reporter(self, tid, name):
        def do_delete(ev):
            db.delete_reporter(tid)
            self._close_dialog(dlg)
            show_snack(self.app_page, f"🗑️ تم حذف الصحفي {name} بنجاح!", is_error=True)
            self.load_all_data()

        dlg = ft.AlertDialog(
            title=ft.Text("تأكيد الحذف", weight=ft.FontWeight.BOLD, color=ThemeColors.ERROR),
            content=ft.Text(f"هل أنت متأكد من رغبتك في حذف الصحفي ({name} - ID: {tid})؟\nلن يتمكن من استخدام البوت إلا بعد إعادة تسجيله."),
            actions=[
                ft.TextButton("تراجع", on_click=lambda ev: self._close_dialog(dlg)),
                ft.ElevatedButton("نعم، احذف", bgcolor=ThemeColors.ERROR, color="#FFFFFF", on_click=do_delete)
            ]
        )
        self._open_dialog(dlg)

    # ══════════════════════════════════════════════════════════════
    # TAB 2: BLOGGER MULTI-ACCOUNT POOL
    # ══════════════════════════════════════════════════════════════
    def _build_blogger_tab(self):
        pool_status = blogger_service.get_pool_status()

        banner = create_glass_card(
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ThemeColors.GOLD_PRIMARY, size=24),
                ft.Column([
                    ft.Text("نظام توزيع أحمال بلوجر التناوبي (Round-Robin Multi-Account Pool)", weight=ft.FontWeight.BOLD),
                    ft.Text("يقوم البوت بتوزيع عمليات النشر بين الحسابات الثلاثة تلقائياً لتفادي استنزاف كوتا جوجل وتفادي أخطاء التزامن.\nتأكد فقط من دعوة الحسابات الثلاثة كـ Authors أو Admins على نفس المدونة في Blogger.", size=12, color=ThemeColors.TEXT_MUTED)
                ], expand=True, spacing=3)
            ], spacing=15),
            padding=15
        )

        cards = []
        for a in pool_status:
            cards.append(self._build_account_card(a))

        self.blogger_cards_row = ft.Row(controls=cards, spacing=15, expand=True)

        return ft.Column([
            banner,
            self.blogger_cards_row
        ], spacing=15, expand=True)

    def _build_account_card(self, acc_info: dict):
        slot = acc_info["account_id"]
        token_name = acc_info["token_file"]
        is_valid = acc_info["is_valid"]
        status_text = acc_info["status_text"]
        disp_name = acc_info.get("display_name", f"حساب بلوجر {slot}")

        if is_valid:
            badge_bg = "#10B98125"
            badge_border = ThemeColors.SUCCESS
            badge_color = ThemeColors.SUCCESS
            status_icon = ft.Icons.CHECK_CIRCLE
        elif acc_info.get("exists"):
            badge_bg = "#F59E0B25"
            badge_border = ThemeColors.GOLD_PRIMARY
            badge_color = ThemeColors.GOLD_PRIMARY
            status_icon = ft.Icons.UPDATE
        else:
            badge_bg = "#33415525"
            badge_border = ThemeColors.BORDER_COLOR
            badge_color = ThemeColors.TEXT_MUTED
            status_icon = ft.Icons.HELP_OUTLINE

        return create_glass_card(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=ThemeColors.GOLD_PRIMARY, size=28),
                        padding=8,
                        border_radius=10,
                        bgcolor="#F59E0B15"
                    ),
                    ft.Column([
                        ft.Text(f"حساب بلوجر رقم {slot}", weight=ft.FontWeight.BOLD, size=15),
                        ft.Text(token_name, size=11, color=ThemeColors.TEXT_MUTED, font_family="monospace")
                    ], spacing=2, expand=True)
                ], spacing=10),
                ft.Divider(color=ThemeColors.BORDER_COLOR, height=1),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(status_icon, color=badge_color, size=16),
                        ft.Text(status_text, size=12, weight=ft.FontWeight.BOLD, color=badge_color)
                    ], spacing=6, alignment=ft.MainAxisAlignment.CENTER),
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    border_radius=8,
                    bgcolor=badge_bg,
                    border=ft.border.all(1, badge_border)
                ),
                ft.Text(f"الاسم المكتشف: {disp_name}", size=12, color=ThemeColors.TEXT_PRIMARY),
                ft.Container(expand=True),
                create_gold_button(
                    f"🌐 تسجيل دخول وتوثيق (حساب {slot})",
                    icon=ft.Icons.LOGIN,
                    on_click=lambda e, s=slot: self.handle_auth_account(s)
                )
            ], spacing=12, expand=True),
            expand=True,
            padding=16
        )

    def handle_auth_account(self, slot: int):
        show_snack(self.app_page, f"🌐 جاري فتح المتصفح لتسجيل الدخول للحساب {slot}...", is_success=True)
        threading.Thread(target=self._run_browser_auth, args=(slot,), daemon=True).start()

    def _run_browser_auth(self, slot: int):
        success, res = blogger_service.authenticate_slot_browser(slot)
        if success:
            show_snack(self.app_page, f"✅ تم ربط حساب بلوجر رقم {slot} بنجاح ({res})!", is_success=True)
        else:
            show_snack(self.app_page, f"❌ فشل ربط الحساب رقم {slot}: {res}", is_error=True)
        self.load_all_data()

    # ══════════════════════════════════════════════════════════════
    # TAB 3: LIVE ERROR & ACTIVITY LOG
    # ══════════════════════════════════════════════════════════════
    def _build_logs_tab(self):
        actions_bar = ft.Row([
            ft.Text("سجل أحداث وأخطاء البوت المباشرة لحظة بلحظة:", size=13, color=ThemeColors.TEXT_MUTED, expand=True),
            create_secondary_button(
                "🔄 تحديث السجل",
                icon=ft.Icons.REFRESH,
                on_click=lambda e: self.load_all_data()
            ),
            ft.ElevatedButton(
                "🗑️ تفريغ السجل",
                icon=ft.Icons.DELETE_SWEEP,
                style=ft.ButtonStyle(
                    bgcolor="#EF444420",
                    color=ThemeColors.ERROR,
                    side=ft.BorderSide(1, ThemeColors.ERROR),
                    shape=ft.RoundedRectangleBorder(radius=8)
                ),
                on_click=self.clear_logs
            )
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.logs_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("التاريخ والوقت", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("النوع", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("الصحفي / المعرف", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("تفاصيل الحدث أو الخطأ", weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            heading_row_color="#1E293B",
            data_row_min_height=48,
            border=ft.border.all(1, ThemeColors.BORDER_COLOR),
            border_radius=10,
            column_spacing=20,
            expand=True
        )

        table_card = create_glass_card(
            content=ft.ListView(
                controls=[self.logs_table],
                expand=True,
                spacing=0
            ),
            expand=True,
            padding=10
        )

        self._populate_logs_table(self.bot_logs)

        return ft.Column([
            actions_bar,
            table_card
        ], spacing=12, expand=True)

    def _populate_logs_table(self, logs_list):
        rows = []
        for l in logs_list:
            ts = str(l.get("created_at", ""))
            level = str(l.get("level", "INFO")).upper()
            msg = str(l.get("message", ""))
            reporter_id = l.get("reporter_id") or ""
            reporter_name = l.get("reporter_name") or ""

            is_err = level == "ERROR"
            badge_color = ThemeColors.ERROR if is_err else ThemeColors.SUCCESS
            badge_txt = "🔴 خطأ" if is_err else "🔵 نشاط"

            type_badge = ft.Container(
                content=ft.Text(badge_txt, size=11, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border_radius=10,
                bgcolor=badge_color
            )

            rep_label = f"{reporter_name} ({reporter_id})" if reporter_name else (str(reporter_id) if reporter_id else "النظام")

            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(ts, size=11, color=ThemeColors.TEXT_MUTED)),
                ft.DataCell(type_badge),
                ft.DataCell(ft.Text(rep_label, size=12, color=ThemeColors.INFO, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(msg, size=12, color=ThemeColors.ERROR if is_err else ThemeColors.TEXT_PRIMARY, selectable=True))
            ]))

        self.logs_table.rows = rows
        self.safe_update()

    def clear_logs(self, e):
        with db.get_connection() as conn:
            conn.cursor().execute("DELETE FROM system_logs WHERE module = 'TelegramBot'")
            conn.commit()
        show_snack(self.app_page, "🗑️ تم تفريغ سجلات البوت بنجاح!", is_success=True)
        self.load_all_data()

    # ══════════════════════════════════════════════════════════════
    # BOT SERVICE CONTROL (START / STOP)
    # ══════════════════════════════════════════════════════════════
    def handle_start_bot(self, e):
        self.btn_start.disabled = True
        self.status_chip.content.controls[0].color = ThemeColors.GOLD_PRIMARY
        self.status_chip.content.controls[1].value = "جاري التشغيل 🟡..."
        self.status_chip.content.controls[1].color = ThemeColors.GOLD_PRIMARY
        self.status_chip.bgcolor = "#F59E0B20"
        self.status_chip.border = ft.border.all(1, ThemeColors.GOLD_PRIMARY)
        self.safe_update()
        show_snack(self.app_page, "⚡ جاري بدء تهيئة وتشغيل البوت في الخلفية...", is_success=True)
        threading.Thread(target=self._run_start_bot, daemon=True).start()

    def _run_start_bot(self):
        success = bot_controller.start(timeout=15.0)
        self.update_bot_status_ui()
        if success:
            show_snack(self.app_page, "✅ تم تشغيل بوت تليجرام بنجاح وهو جاهز لاستقبال الرسائل!", is_success=True)
        else:
            err = bot_controller.last_error or "انتهت مهلة بدء التشغيل"
            show_snack(self.app_page, f"❌ تعذر تشغيل البوت: {err}", is_error=True)

    def handle_stop_bot(self, e):
        bot_controller.stop()
        self.update_bot_status_ui()
        show_snack(self.app_page, "⏹️ تم إيقاف بوت تليجرام بنجاح.", is_error=False)

    def update_bot_status_ui(self):
        status = bot_controller.get_status()
        is_running = status.get("is_running", False)
        uptime = status.get("uptime_seconds", 0)

        if is_running:
            mins = uptime // 60
            hrs = mins // 60
            uptime_txt = f"{hrs}h {mins % 60}m" if hrs > 0 else f"{mins}m"
            self.status_chip.content.controls[0].color = ThemeColors.SUCCESS
            self.status_chip.content.controls[1].value = f"يعمل بنجاح 🟢 ({uptime_txt})"
            self.status_chip.content.controls[1].color = ThemeColors.SUCCESS
            self.status_chip.bgcolor = "#10B98120"
            self.status_chip.border = ft.border.all(1, ThemeColors.SUCCESS)
            self.btn_start.disabled = True
            self.btn_stop.disabled = False
        else:
            self.status_chip.content.controls[0].color = ThemeColors.TEXT_MUTED
            self.status_chip.content.controls[1].value = "متوقف ⚪"
            self.status_chip.content.controls[1].color = ThemeColors.TEXT_MUTED
            self.status_chip.bgcolor = "#33415520"
            self.status_chip.border = ft.border.all(1, ThemeColors.BORDER_COLOR)
            self.btn_start.disabled = False
            self.btn_stop.disabled = True

        self.safe_update()

    # ══════════════════════════════════════════════════════════════
    # DATA LOADING & REFRESH
    # ══════════════════════════════════════════════════════════════
    def load_all_data(self):
        try:
            self._last_reporters_sig = None
            self._last_logs_sig = None
            self._last_pool_sig = None
            self.reporters = db.get_reporters_with_stats()
            self.bot_logs = db.get_bot_logs(limit=150)
            pool_status = blogger_service.get_pool_status()

            # Update stats
            self.stat_reporters.value = str(len(self.reporters))
            today_total = sum(r.get("articles_today", 0) for r in self.reporters)
            self.stat_articles_today.value = str(today_total)

            active_slots = sum(1 for a in pool_status if a["is_valid"])
            self.stat_blogger_accounts.value = f"{active_slots}/3"

            err_count = sum(1 for l in self.bot_logs if l.get("level") == "ERROR")
            self.stat_errors.value = str(err_count)

            self.update_bot_status_ui()
            self.switch_tab(self.active_tab_idx)
        except Exception as e:
            logger.error(f"Error loading bot panel data: {e}")
            show_snack(self.app_page, f"خطأ في تحميل بيانات اللوحة: {e}", is_error=True)


def main(page: ft.Page):
    page.title = "جريدة تحت الضوء — لوحة إدارة بوت التليجرام والمحررين"
    page.window_width = 1100
    page.window_height = 780
    page.window_min_width = 900
    page.window_min_height = 650
    page.bgcolor = ThemeColors.BG_DARK
    page.theme = get_app_theme(True)
    page.padding = 0
    page.rtl = True

    view = BotManagerView(page)
    page.add(view)


if __name__ == "__main__":
    if hasattr(ft, "run"):
        try:
            ft.run(main, assets_dir="assets")
        except Exception:
            ft.app(target=main, assets_dir="assets")
    else:
        ft.app(target=main, assets_dir="assets")
