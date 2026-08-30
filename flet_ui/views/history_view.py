import webbrowser
import flet as ft
from flet_ui.theme import ThemeColors, create_glass_card, create_secondary_button, create_input_field
from flet_ui.components.header import create_page_header
from flet_ui.components.status_chip import create_status_chip
from flet_ui.components.notification import show_snack

from database.db import db
from services.whatsapp_service import whatsapp_service
from core.logger import logger


class HistoryView(ft.Container):
    def __init__(self, page: ft.Page, on_navigate=None):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.on_navigate = on_navigate
        self.articles = []

        self.init_ui()

    def init_ui(self):
        btn_refresh = create_secondary_button(
            "🔄  تحديث السجل",
            icon=ft.Icons.REFRESH,
            on_click=lambda e: self.load_data()
        )

        header = create_page_header(
            title="أرشيف الأخبار المنشورة",
            subtitle="جميع الأخبار السابقة التي تم نشرها أو حفظها كمسودات، مع إمكانية إعادة مشاركة الواتساب",
            icon=ft.Icons.HISTORY,
            actions=[btn_refresh]
        )

        self.search_input = create_input_field(
            label="بحث في الأخبار...",
            hint_text="ابحث باسم العميل أو عنوان الخبر...",
            on_change=self.filter_data,
            prefix_icon=ft.Icons.SEARCH,
            expand=True
        )

        self.count_text = ft.Text("إجمالي: 0 خبر", size=13, color=ThemeColors.TEXT_MUTED)

        # DataTable
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("#", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("عنوان الخبر", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("العميل", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("الحالة", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("التاريخ", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("الإجراءات", weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            border_radius=10,
            border=ft.border.all(1, ThemeColors.BORDER_COLOR),
            horizontal_margin=12,
            column_spacing=15,
            expand=True
        )

        table_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Row([self.search_input, self.count_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ListView(
                        controls=[self.table],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO
                    )
                ],
                spacing=12,
                expand=True
            ),
            expand=True
        )

        self.content = ft.Column(
            controls=[
                header,
                table_card
            ],
            spacing=16,
            expand=True
        )

    def load_data(self):
        try:
            self.articles = db.get_all_articles()
            self.display_rows(self.articles)
        except Exception as ex:
            logger.error(f"خطأ في تحميل سجل الأخبار: {ex}")

    def filter_data(self, e):
        query = (self.search_input.value or "").strip().lower()
        if not query:
            self.display_rows(self.articles)
            return

        filtered = [
            a for a in self.articles
            if query in (a.get("title") or "").lower() or query in (a.get("client_name") or "").lower()
        ]
        self.display_rows(filtered)

    def display_rows(self, article_list):
        rows = []
        self.count_text.value = f"إجمالي: {len(article_list)} خبر"

        for article in article_list:
            post_url = article.get("post_url") or ""
            phone = article.get("client_phone") or ""
            name = article.get("client_name") or "—"
            status = article.get("blogger_status", "PENDING")

            actions = ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.OPEN_IN_NEW,
                        icon_color=ThemeColors.GOLD_PRIMARY,
                        tooltip="فتح رابط الخبر المنشور",
                        on_click=lambda e, url=post_url: webbrowser.open(url) if url else None,
                        visible=bool(post_url)
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHAT,
                        icon_color=ThemeColors.SUCCESS,
                        tooltip="فتح شات واتساب مباشر",
                        on_click=lambda e, a=article: self.open_wa(a)
                    ),
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        icon_color=ThemeColors.INDIGO_ACCENT,
                        tooltip="إعادة إرسال الواتساب تلقائياً عبر API",
                        on_click=lambda e, a=article: self.retry_api_wa(a)
                    )
                ],
                spacing=2
            )

            status_widget = create_status_chip(
                text="منشور" if status == "PUBLISHED" else "مسودة",
                is_ok=(status == "PUBLISHED")
            )

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(article["id"]), size=12, color=ThemeColors.TEXT_MUTED)),
                        ft.DataCell(ft.Text(article.get("title", ""), size=13, weight=ft.FontWeight.W_500, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                        ft.DataCell(ft.Text(name, size=13, color=ThemeColors.TEXT_SECONDARY)),
                        ft.DataCell(status_widget),
                        ft.DataCell(ft.Text(str(article.get("created_at", ""))[:16], size=12, color=ThemeColors.TEXT_MUTED)),
                        ft.DataCell(actions)
                    ]
                )
            )

        self.table.rows = rows
        self.update()

    def open_wa(self, article):
        phone = article.get("client_phone")
        if not phone:
            show_snack(self.app_page, "⚠️ لا يوجد رقم واتساب مسجل لهذا الخبر", is_error=True)
            return
        name = article.get("client_name") or "العميل"
        url = article.get("post_url") or "https://www.tahteldoo.com/"
        wa_link = whatsapp_service.generate_whatsapp_click_link(phone, name, url)
        webbrowser.open(wa_link)

    def retry_api_wa(self, article):
        phone = article.get("client_phone")
        post_url = article.get("post_url")
        if not post_url or not phone:
            show_snack(self.app_page, "⚠️ يلزم وجود رابط خبر ورقم هاتف للإرسال", is_error=True)
            return

        name = article.get("client_name", "")
        success = whatsapp_service.send_message(
            article_id=article["id"], phone=phone, name=name, post_url=post_url
        )
        if success:
            show_snack(self.app_page, f"✅ تم إرسال الواتساب تلقائياً لـ {name}", is_success=True)
        else:
            show_snack(self.app_page, f"❌ فشل إرسال الواتساب عبر API، يمكن فتح الشات المباشر", is_error=True)
            self.open_wa(article)
