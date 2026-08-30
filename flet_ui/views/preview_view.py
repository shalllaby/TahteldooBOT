import os
import json
import threading
import webbrowser
import flet as ft
from flet_ui.theme import ThemeColors, create_glass_card, create_gold_button, create_secondary_button, create_input_field
from flet_ui.components.header import create_page_header
from flet_ui.components.notification import show_snack, show_publish_success_dialog

from services.article_formatter import ArticleFormatter
from services.image_service import image_service
from services.blogger_service import blogger_service
from services.whatsapp_service import whatsapp_service
from database.db import db
from core.logger import logger


class PreviewView(ft.Container):
    def __init__(self, page: ft.Page, on_navigate=None):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.on_navigate = on_navigate
        self.client_id = None
        self.ai_data = {}
        self.selected_image_path = ""
        self.client_name = ""
        self.client_phone = ""
        self.is_loading = False

        self.init_ui()

    def init_ui(self):
        header = create_page_header(
            title="معاينة وتعديل ونشر الخبر الصحفي",
            subtitle="راجع صياغة المقال وعناوين التحرير، حدد نوع الكيان المخاطب، ثم انشر المقال بضغطة واحدة",
            icon=ft.Icons.PREVIEW
        )

        # HTML Content Preview Text Field
        self.html_preview_input = create_input_field(
            label="محتوى الخبر الصحفي (HTML)",
            multiline=True,
            rows=15,
            expand=True
        )

        btn_copy_html = create_secondary_button(
            "📋 نسخ كود HTML",
            icon=ft.Icons.COPY,
            on_click=self.copy_html_code
        )

        preview_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("المعاينة الحية والصياغة الصحفية", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                            btn_copy_html
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    self.html_preview_input
                ],
                spacing=10,
                expand=True
            ),
            expand=True
        )

        # Metadata Editor Controls
        self.title_input = create_input_field(label="عنوان الخبر الصحفي")
        self.slug_input = create_input_field(label="الرابط الثابت (Slug)")
        self.labels_input = create_input_field(
            label="التصنيف الرسمي (تعليم، صحة، شخصيات عامة، تطوير ذات، التغذية العلاجية، أعمال، خدمات)",
            hint_text="اختر تصنيفاً واحداً من الأقسام المعتمدة"
        )

        # Entity Type Selector (Radio Group)
        self.radio_entity = ft.RadioGroup(
            content=ft.Column(
                controls=[
                    ft.Radio(value="plural", label="🏢 كيان / عيادة / جهة (حضراتكم)", fill_color=ThemeColors.GOLD_PRIMARY),
                    ft.Radio(value="male", label="♂️ شخص مذكر (حضرتك)", fill_color=ThemeColors.GOLD_PRIMARY),
                    ft.Radio(value="female", label="♀️ شخص مؤنث (حضرتِك)", fill_color=ThemeColors.GOLD_PRIMARY),
                ],
                spacing=4
            ),
            value="plural"
        )

        entity_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Text("نوع الجهة المخاطبة في رسالة الواتساب", size=13, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_SECONDARY),
                    self.radio_entity
                ],
                spacing=8
            )
        )

        self.chk_auto_wa = ft.Checkbox(
            label="إرسال رسالة WhatsApp التفاعلية تلقائياً بعد النشر",
            value=True,
            fill_color=ThemeColors.GOLD_PRIMARY
        )

        # Loading Indicator
        self.loading_ring = ft.ProgressRing(color=ThemeColors.GOLD_PRIMARY, width=24, height=24, visible=False)
        self.loading_text = ft.Text("", size=13, color=ThemeColors.GOLD_PRIMARY, visible=False)
        loading_box = ft.Row([self.loading_ring, self.loading_text], spacing=10, alignment=ft.MainAxisAlignment.CENTER)

        # Action Buttons
        self.btn_publish = create_gold_button(
            "🚀   نشر الخبر الصحفي والواتساب الآن",
            on_click=lambda e: self.start_publish(is_draft=False),
            height=48,
            expand=True
        )

        self.btn_wa_direct = create_secondary_button(
            "💬 واتساب مباشر",
            icon=ft.Icons.CHAT,
            on_click=self.open_direct_wa,
            height=44,
            expand=True
        )

        self.btn_draft = create_secondary_button(
            "📝 حفظ مسودة",
            icon=ft.Icons.EDIT_DOCUMENT,
            on_click=lambda e: self.start_publish(is_draft=True),
            height=44,
            expand=True
        )

        controls_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Text("بيانات النشر والرسالة", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                    self.title_input,
                    self.slug_input,
                    self.labels_input,
                    entity_card,
                    self.chk_auto_wa,
                    loading_box,
                    self.btn_publish,
                    ft.Row([self.btn_wa_direct, self.btn_draft], spacing=10)
                ],
                spacing=12
            )
        )

        # Main Layout Content
        self.content = ft.Column(
            controls=[
                header,
                ft.ResponsiveRow(
                    controls=[
                        ft.Container(content=preview_card, col={"sm": 12, "md": 7}),
                        ft.Container(content=controls_card, col={"sm": 12, "md": 5})
                    ],
                    run_spacing=15
                )
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO
        )

    def load_article(self, client_id: int, ai_data: dict, selected_image_path: str):
        self.client_id = client_id
        self.ai_data = ai_data
        self.selected_image_path = selected_image_path

        with db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM clients WHERE id = ?", (self.client_id,))
            row = c.fetchone()
            self.client_name = row["name"] if row else ""
            self.client_phone = row["phone"] if row else ""

        self.title_input.value = ai_data.get("title", "")
        self.slug_input.value = ai_data.get("slug", "")
        self.labels_input.value = ", ".join(ai_data.get("labels", []))

        detected_entity = ai_data.get("entity_type", "plural")
        self.radio_entity.value = detected_entity if detected_entity in ["male", "female", "plural"] else "plural"

        formatted_html = ArticleFormatter.json_to_html(ai_data)
        self.html_preview_input.value = formatted_html
        self.update()

    def reset_form(self):
        self.client_id = None
        self.ai_data = {}
        self.selected_image_path = ""
        self.client_name = ""
        self.client_phone = ""
        self.title_input.value = ""
        self.slug_input.value = ""
        self.labels_input.value = ""
        self.html_preview_input.value = ""
        self.radio_entity.value = "plural"
        self.update()

    def copy_html_code(self, e):
        if self.html_preview_input.value:
            self.app_page.set_clipboard(self.html_preview_input.value)
            show_snack(self.app_page, "📋 تم نسخ كود HTML إلى الحافظة بنجاح!", is_success=True)

    def open_direct_wa(self, e):
        if not self.client_phone:
            show_snack(self.app_page, "⚠️ لا يوجد رقم واتساب مسجل لهذا العميل", is_error=True)
            return
        entity_type = self.radio_entity.value
        wa_link = whatsapp_service.generate_whatsapp_click_link(
            self.client_phone, self.client_name, "https://www.tahteldoo.com/", entity_type=entity_type
        )
        webbrowser.open(wa_link)

    def set_loading(self, loading: bool, message: str = ""):
        self.is_loading = loading
        self.loading_ring.visible = loading
        self.loading_text.visible = loading
        self.loading_text.value = message
        self.btn_publish.disabled = loading
        self.btn_wa_direct.disabled = loading
        self.btn_draft.disabled = loading
        self.update()

    def start_publish(self, is_draft: bool = False):
        title = self.title_input.value.strip() if self.title_input.value else ""
        if not title:
            show_snack(self.app_page, "⚠️ يرجى كتابة عنوان الخبر أولاً", is_error=True)
            return

        labels = [l.strip() for l in (self.labels_input.value or "").split(",") if l.strip()]

        article_data = {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "client_phone": self.client_phone,
            "title": title,
            "slug": self.slug_input.value.strip() if self.slug_input.value else "",
            "labels": labels,
            "final_html": self.html_preview_input.value or "",
            "local_image_path": self.selected_image_path,
            "ai_raw_json": self.ai_data,
            "entity_type": self.radio_entity.value
        }

        self.set_loading(True, "جاري رفع الصورة والنشر على المدونة...")

        def worker():
            try:
                image_path = article_data.get("local_image_path")
                remote_image_url = ""
                if image_path and os.path.exists(image_path):
                    remote_image_url = image_service.upload_image(image_path)

                final_html = article_data.get("final_html", "")
                if remote_image_url:
                    final_html = ArticleFormatter.replace_image_placeholder(final_html, remote_image_url)

                blogger_res = blogger_service.publish_post(
                    title=article_data["title"],
                    content_html=final_html,
                    labels=article_data["labels"],
                    is_draft=is_draft
                )

                post_id = blogger_res.get("post_id")
                post_url = blogger_res.get("post_url")

                db_payload = {
                    "client_id": article_data.get("client_id"),
                    "title": article_data["title"],
                    "slug": article_data.get("slug"),
                    "labels": ",".join(article_data.get("labels", [])),
                    "raw_ai_json": json.dumps(article_data.get("ai_raw_json", {}), ensure_ascii=False),
                    "final_html": final_html,
                    "local_image_path": image_path,
                    "remote_image_url": remote_image_url,
                    "blog_id": blogger_service.blog_id,
                    "post_id": post_id,
                    "post_url": post_url,
                    "is_draft": is_draft,
                    "blogger_status": "PUBLISHED" if not is_draft else "DRAFT"
                }
                article_id = db.save_article(db_payload)

                wa_sent = False
                client_name = article_data.get("client_name", "")
                client_phone = article_data.get("client_phone", "")
                entity_type = article_data.get("entity_type")

                if self.chk_auto_wa.value and post_url and client_phone:
                    wa_sent = whatsapp_service.send_message(
                        article_id=article_id,
                        phone=client_phone,
                        name=client_name,
                        post_url=post_url,
                        entity_type=entity_type
                    )

                wa_link = whatsapp_service.generate_whatsapp_click_link(client_phone, client_name, post_url, entity_type=entity_type) if client_phone else ""

                def ui_done():
                    self.set_loading(False)
                    self.reset_form()
                    if callable(getattr(self, "on_publish_success", None)):
                        self.on_publish_success()
                    show_publish_success_dialog(
                        self.app_page,
                        post_url=post_url,
                        client_name=client_name,
                        client_phone=client_phone,
                        wa_link=wa_link
                    )

                if hasattr(self.app_page, "run_thread"):
                    self.app_page.run_thread(ui_done)
                else:
                    ui_done()

            except Exception as ex:
                err_msg = str(ex)
                logger.error(f"خطأ أثناء النشر: {err_msg}")
                def ui_err():
                    self.set_loading(False)
                    show_snack(self.app_page, f"❌ فشل النشر: {err_msg}", is_error=True)
                if hasattr(self.app_page, "run_thread"):
                    self.app_page.run_thread(ui_err)
                else:
                    ui_err()

        threading.Thread(target=worker, daemon=True).start()
