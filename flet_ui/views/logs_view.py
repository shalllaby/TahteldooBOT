import flet as ft
from flet_ui.theme import ThemeColors, create_glass_card, create_secondary_button
from flet_ui.components.header import create_page_header
from flet_ui.components.notification import show_snack

from database.db import db
from core.logger import logger


class LogsView(ft.Container):
    def __init__(self, page: ft.Page, on_navigate=None):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.on_navigate = on_navigate

        self.init_ui()

    def init_ui(self):
        btn_refresh = create_secondary_button(
            "🔄  تحديث السجلات",
            icon=ft.Icons.REFRESH,
            on_click=lambda e: self.load_logs()
        )

        btn_copy = create_secondary_button(
            "📋 نسخ السجلات",
            icon=ft.Icons.COPY,
            on_click=self.copy_logs
        )

        btn_clear = create_secondary_button(
            "🗑️ مسح العرض",
            icon=ft.Icons.DELETE_OUTLINE,
            on_click=self.clear_logs
        )

        header = create_page_header(
            title="سجل أحداث النظام والعمليات",
            subtitle="جميع الأحداث والاستجابات التقنية والأخطاء مسجلة هنا للمراجعة والتشخيص اللحظي",
            icon=ft.Icons.RECEIPT_LONG,
            actions=[btn_refresh, btn_copy, btn_clear]
        )

        self.count_text = ft.Text("0 سجل", size=12, color=ThemeColors.TEXT_MUTED)

        self.logs_column = ft.Column(
            controls=[],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True
        )

        log_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Row([ft.Text("شاشة السجلات الحية", size=13, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY), self.count_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Container(
                        content=self.logs_column,
                        bgcolor="#050811",
                        border_radius=8,
                        padding=12,
                        border=ft.border.all(1, "#1E293B"),
                        expand=True
                    )
                ],
                spacing=10,
                expand=True
            ),
            expand=True
        )

        self.content = ft.Column(
            controls=[
                header,
                log_card
            ],
            spacing=16,
            expand=True
        )

    def load_logs(self):
        try:
            logs = db.get_system_logs(300)
            self.count_text.value = f"{len(logs)} سجل"
            controls = []

            for log in logs:
                time_str = log.get("created_at", "")[:19]
                level = log.get("level", "INFO")
                module = log.get("module", "APP")
                msg = log.get("message", "")

                level_color = ThemeColors.SUCCESS
                if level == "ERROR":
                    level_color = ThemeColors.ERROR
                elif level == "WARNING":
                    level_color = ThemeColors.GOLD_PRIMARY

                controls.append(
                    ft.Row(
                        controls=[
                            ft.Text(f"[{time_str}]", size=11, color=ThemeColors.TEXT_MUTED, selectable=True),
                            ft.Text(f"[{level}]", size=11, weight=ft.FontWeight.BOLD, color=level_color, selectable=True),
                            ft.Text(f"[{module}]", size=11, color=ThemeColors.TEXT_SECONDARY, selectable=True),
                            ft.Text(msg, size=12, color=ThemeColors.TEXT_PRIMARY, selectable=True, expand=True)
                        ],
                        spacing=8,
                        tight=True
                    )
                )

            if not controls:
                controls.append(ft.Text("لا توجد سجلات حالياً.", size=12, color=ThemeColors.TEXT_MUTED))

            self.logs_column.controls = controls
            self.update()
        except Exception as ex:
            logger.error(f"خطأ في تحميل سجلات النظام: {ex}")

    def copy_logs(self, e):
        text_lines = []
        for row in self.logs_column.controls:
            if isinstance(row, ft.Row):
                line = " ".join([c.value for c in row.controls if hasattr(c, "value")])
                text_lines.append(line)
        full_text = "\n".join(text_lines)
        if full_text:
            self.app_page.set_clipboard(full_text)
            show_snack(self.app_page, "📋 تم نسخ سجلات النظام بنجاح!", is_success=True)

    def clear_logs(self, e):
        self.logs_column.controls = [ft.Text("تم مسح السجلات من الشاشة.", size=12, color=ThemeColors.TEXT_MUTED)]
        self.count_text.value = "0 سجل"
        self.update()
