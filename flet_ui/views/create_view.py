import os
import json
import time
import uuid
import threading
import flet as ft
from flet_ui.theme import ThemeColors, create_glass_card, create_gold_button, create_secondary_button, create_input_field
from flet_ui.components.header import create_page_header
from flet_ui.components.notification import show_snack, show_publish_success_dialog

from services.ai_service import ai_service
from services.article_formatter import ArticleFormatter
from services.image_service import image_service
from services.blogger_service import blogger_service
from services.whatsapp_service import whatsapp_service
from database.db import db
from core.config import Config
from core.logger import logger


class CreateView(ft.Container):
    def __init__(self, page: ft.Page, on_navigate=None, on_article_generated=None):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.on_navigate = on_navigate
        self.on_article_generated = on_article_generated
        self.selected_image_path = ""
        self.is_loading = False

        self.init_ui()

    def init_ui(self):
        # Header
        header = create_page_header(
            title="إنشاء ونشر خبر صحفي بالذكاء الاصطناعي",
            subtitle="أدخل التفاصيل والمعلومات الخام، وسيحدد النظام الكيانات وينشر الخبر ويرسل الواتساب تلقائياً",
            icon=ft.Icons.AUTO_AWESOME
        )

        # Raw Notes Input Field
        self.notes_input = create_input_field(
            label="المعلومات والتفاصيل الخام للخبر الصحفي",
            hint_text="ضع هنا كافة البيانات والمعلومات الخام دون تنسيق:\nمثال: دكتور ناصر عبدالكريم - استشاري الجلدية والتجميل - عيادة الدقي - تقديم خدمات الفيلر والبوتكس وأحدث تقنيات الليزر - تليفون 01012345678...",
            multiline=True,
            rows=8,
            expand=True
        )

        # Image Selection & Preview Section
        self.img_status_text = ft.Text(
            "لم يتم اختيار صورة بعد (يمكن إضافة صورة لاحقاً)",
            size=12,
            color=ThemeColors.TEXT_MUTED,
            weight=ft.FontWeight.W_500
        )

        self.img_preview = ft.Image(
            src="",
            width=160,
            height=100,
            fit="cover",
            border_radius=10,
            visible=False
        )

        self.img_placeholder_box = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.ADD_A_PHOTO, size=28, color=ThemeColors.TEXT_MUTED),
                    ft.Text("لا توجد صورة مرفقة", size=11, color=ThemeColors.TEXT_MUTED)
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4
            ),
            width=160,
            height=100,
            bgcolor="#0F172A",
            border=ft.border.all(1, ThemeColors.BORDER_COLOR),
            border_radius=10,
            alignment=ft.Alignment(0, 0)
        )

        self.btn_remove_img = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE,
            icon_color=ThemeColors.ERROR,
            tooltip="حذف الصورة المرفقة",
            on_click=self.remove_image,
            visible=False
        )

        img_card = create_glass_card(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.IMAGE, color=ThemeColors.GOLD_PRIMARY, size=20),
                            ft.Text("صورة الخبر الرئيسية (اختياري)", size=15, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                        ],
                        spacing=8
                    ),
                    ft.Row(
                        controls=[
                            ft.Stack(
                                controls=[
                                    self.img_placeholder_box,
                                    self.img_preview,
                                ]
                            ),
                            ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            create_secondary_button(
                                                "📁 اختيار صورة من الجهاز",
                                                icon=ft.Icons.FOLDER_OPEN,
                                                on_click=self.pick_image
                                            ),
                                            create_secondary_button(
                                                "📋 لصق صورة من الحافظة",
                                                icon=ft.Icons.CONTENT_PASTE,
                                                on_click=self.paste_image
                                            ),
                                            self.btn_remove_img
                                        ],
                                        spacing=10
                                    ),
                                    self.img_status_text
                                ],
                                spacing=10,
                                expand=True
                            )
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=16
                    )
                ],
                spacing=12
            )
        )

        # File picker control (Service in Flet 0.80+)
        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.on_image_picked
        if self.file_picker not in self.app_page.services:
            self.app_page.services.append(self.file_picker)

        # Loading Progress Indicator
        self.loading_ring = ft.ProgressRing(color=ThemeColors.GOLD_PRIMARY, width=24, height=24, visible=False)
        self.loading_text = ft.Text("", size=13, color=ThemeColors.GOLD_PRIMARY, visible=False)
        
        loading_box = ft.Row(
            controls=[self.loading_ring, self.loading_text],
            spacing=10,
            alignment=ft.MainAxisAlignment.CENTER
        )

        # Action Buttons Centered
        self.btn_direct_publish = create_gold_button(
            "🚀   صياغة ونشر الخبر والواتساب مباشرة (ضغطة واحدة)",
            on_click=self.start_direct_publish,
            height=52
        )

        self.btn_generate_preview = create_secondary_button(
            "✨   صياغة وتجهيز للمعاينة والتعديل أولاً",
            icon=ft.Icons.EDIT_DOCUMENT,
            on_click=self.start_generation_preview,
            height=46
        )

        action_buttons_box = ft.Container(
            content=ft.Column(
                controls=[
                    self.btn_direct_publish,
                    self.btn_generate_preview
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH
            ),
            width=580,
            alignment=ft.Alignment(0, 0)
        )

        centered_actions_row = ft.Row(
            controls=[action_buttons_box],
            alignment=ft.MainAxisAlignment.CENTER
        )

        # Main Layout Content
        self.content = ft.Column(
            controls=[
                header,
                create_glass_card(self.notes_input),
                img_card,
                loading_box,
                centered_actions_row
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO
        )

    async def pick_image(self, e):
        try:
            file_type = ft.FilePickerFileType.CUSTOM if hasattr(ft, "FilePickerFileType") else None
            res = await self.file_picker.pick_files(
                dialog_title="اختر صورة الخبر",
                file_type=file_type,
                allowed_extensions=["png", "jpg", "jpeg", "webp"]
            )
            if res and len(res) > 0:
                file_path = res[0].path
                self.set_selected_image(file_path, f"✓ تم إرفاق: {os.path.basename(file_path)}")
        except Exception as ex:
            logger.error(f"خطأ في نافذة اختيار الملفات: {ex}")

    def paste_image(self, e):
        try:
            from PIL import Image, ImageGrab
            import tempfile

            clip = ImageGrab.grabclipboard()
            if isinstance(clip, Image.Image):
                temp_dir = tempfile.gettempdir()
                filename = f"pasted_news_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
                save_path = os.path.join(temp_dir, filename)
                clip.save(save_path, "PNG")
                self.set_selected_image(save_path, "✓ تم لصق صورة من الحافظة")
                show_snack(self.app_page, "📋 تم لصق الصورة من الحافظة بنجاح!", is_success=True)
                return
            elif isinstance(clip, list) and len(clip) > 0:
                file_path = clip[0]
                if os.path.isfile(file_path) and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                    self.set_selected_image(file_path, f"✓ تم لصق ملف: {os.path.basename(file_path)}")
                    show_snack(self.app_page, "📋 تم لصق ملف الصورة بنجاح!", is_success=True)
                    return
        except Exception as ex:
            logger.error(f"خطأ في لصق الصورة: {ex}")

        show_snack(self.app_page, "⚠️ لا توجد صورة أو ملف صورة متوافق في الحافظة للصقها", is_error=True)

    def remove_image(self, e=None):
        self.selected_image_path = ""
        self.img_status_text.value = "لم يتم اختيار صورة بعد (يمكن إضافة صورة لاحقاً)"
        self.img_status_text.color = ThemeColors.TEXT_MUTED
        self.img_preview.src = ""
        self.img_preview.visible = False
        self.img_placeholder_box.visible = True
        self.btn_remove_img.visible = False
        self.update()

    def reset_form(self, e=None):
        self.notes_input.value = ""
        self.remove_image(None)

    def set_selected_image(self, file_path: str, msg: str):
        self.selected_image_path = file_path
        self.img_status_text.value = msg
        self.img_status_text.color = ThemeColors.SUCCESS
        self.img_preview.src = file_path
        self.img_preview.visible = True
        self.img_placeholder_box.visible = False
        self.btn_remove_img.visible = True
        self.update()

    def on_image_picked(self, e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            file_path = e.files[0].path
            self.set_selected_image(file_path, f"✓ تم إرفاق: {os.path.basename(file_path)}")

    def set_loading(self, loading: bool, message: str = ""):
        self.is_loading = loading
        self.loading_ring.visible = loading
        self.loading_text.visible = loading
        self.loading_text.value = message
        self.btn_direct_publish.disabled = loading
        self.btn_generate_preview.disabled = loading
        self.update()

    def start_direct_publish(self, e):
        raw_notes = self.notes_input.value.strip() if self.notes_input.value else ""
        if not raw_notes:
            show_snack(self.app_page, "⚠️ يرجى إدخال التفاصيل الخام للخبر أولاً", is_error=True)
            return

        self.set_loading(True, "جاري الصياغة والنشر وإرسال الواتساب بالذكاء الاصطناعي...")

        def worker():
            try:
                from concurrent.futures import ThreadPoolExecutor

                remote_image_url = ""
                with ThreadPoolExecutor(max_workers=2) as executor:
                    ai_future = executor.submit(ai_service.generate_article, raw_notes)
                    img_future = None
                    if self.selected_image_path and os.path.exists(self.selected_image_path):
                        img_future = executor.submit(image_service.upload_image, self.selected_image_path)
                    
                    if img_future:
                        remote_image_url = img_future.result()
                    ai_data = ai_future.result()

                client_name = ai_data.get("client_name") or ""
                if not client_name:
                    title = ai_data.get("title", "")
                    client_name = title.split("..")[0].strip() if ".." in title else (title or "خبر صحفي")

                client_phone = ai_data.get("client_phone") or ""
                client_id = db.save_client(client_name, client_phone, raw_notes)

                entity_type = ai_data.get("entity_type")
                if not entity_type or entity_type not in ["male", "female", "plural"]:
                    entity_type = whatsapp_service.detect_entity_type(client_name)

                formatted_html = ArticleFormatter.json_to_html(ai_data)
                if remote_image_url:
                    formatted_html = ArticleFormatter.replace_image_placeholder(formatted_html, remote_image_url)

                title = ai_data.get("title", "خبر صحفي")
                labels = ai_data.get("labels", [])

                blogger_res = blogger_service.publish_post(
                    title=title,
                    content_html=formatted_html,
                    labels=labels,
                    is_draft=False
                )

                post_id = blogger_res.get("post_id")
                post_url = blogger_res.get("post_url")

                db_payload = {
                    "client_id": client_id,
                    "title": title,
                    "slug": ai_data.get("slug", ""),
                    "labels": ",".join(labels),
                    "raw_ai_json": json.dumps(ai_data, ensure_ascii=False),
                    "final_html": formatted_html,
                    "local_image_path": self.selected_image_path,
                    "remote_image_url": remote_image_url,
                    "blog_id": blogger_service.blog_id,
                    "post_id": post_id,
                    "post_url": post_url,
                    "is_draft": False,
                    "blogger_status": "PUBLISHED"
                }
                article_id = db.save_article(db_payload)

                wa_sent = False
                if post_url and client_phone:
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
                logger.error(f"خطأ في النشر المباشر: {err_msg}")
                def ui_err():
                    self.set_loading(False)
                    show_snack(self.app_page, f"❌ فشل النشر: {err_msg}", is_error=True)
                if hasattr(self.app_page, "run_thread"):
                    self.app_page.run_thread(ui_err)
                else:
                    ui_err()

        threading.Thread(target=worker, daemon=True).start()

    def start_generation_preview(self, e):
        raw_notes = self.notes_input.value.strip() if self.notes_input.value else ""
        if not raw_notes:
            show_snack(self.app_page, "⚠️ يرجى إدخال التفاصيل الخام للخبر أولاً", is_error=True)
            return

        self.set_loading(True, "جاري صياغة وتنسيق الخبر بالذكاء الاصطناعي...")

        def worker():
            try:
                ai_data = ai_service.generate_article(raw_notes)
                client_name = ai_data.get("client_name") or ""
                if not client_name:
                    title = ai_data.get("title", "")
                    client_name = title.split("..")[0].strip() if ".." in title else (title or "خبر صحفي")

                client_phone = ai_data.get("client_phone") or ""
                client_id = db.save_client(client_name, client_phone, raw_notes)

                def ui_done():
                    self.set_loading(False)
                    show_snack(self.app_page, "✨ تم صياغة الخبر بنجاح! جاري الانتقال للمعاينة...", is_success=True)
                    if callable(self.on_article_generated):
                        self.on_article_generated(client_id, ai_data, self.selected_image_path)

                if hasattr(self.app_page, "run_thread"):
                    self.app_page.run_thread(ui_done)
                else:
                    ui_done()

            except Exception as ex:
                err_msg = str(ex)
                logger.error(f"خطأ في صياغة الخبر للمعاينة: {err_msg}")
                def ui_err():
                    self.set_loading(False)
                    show_snack(self.app_page, f"❌ فشل صياغة الخبر: {err_msg}", is_error=True)
                if hasattr(self.app_page, "run_thread"):
                    self.app_page.run_thread(ui_err)
                else:
                    ui_err()

        threading.Thread(target=worker, daemon=True).start()
