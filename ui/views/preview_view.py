import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QTextEdit, QPushButton, QMessageBox, QGroupBox, QCheckBox,
    QProgressBar, QSplitter, QRadioButton, QButtonGroup, QApplication
)
from PySide6.QtCore import Signal, Qt, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from services.article_formatter import ArticleFormatter
from services.image_service import image_service
from services.blogger_service import blogger_service
from services.whatsapp_service import whatsapp_service
from database.db import db
from core.logger import logger


class PublishWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, article_data, is_draft, send_wa_auto):
        super().__init__()
        self.article_data = article_data
        self.is_draft = is_draft
        self.send_wa_auto = send_wa_auto

    def run(self):
        try:
            image_path = self.article_data.get("local_image_path")
            remote_image_url = ""

            if image_path:
                remote_image_url = image_service.upload_image(image_path)

            final_html = self.article_data.get("final_html", "")
            if remote_image_url:
                final_html = ArticleFormatter.replace_image_placeholder(final_html, remote_image_url)

            blogger_res = blogger_service.publish_post(
                title=self.article_data["title"],
                content_html=final_html,
                labels=self.article_data["labels"],
                is_draft=self.is_draft
            )

            post_id = blogger_res.get("post_id")
            post_url = blogger_res.get("post_url")

            db_payload = {
                "client_id": self.article_data.get("client_id"),
                "title": self.article_data["title"],
                "slug": self.article_data.get("slug"),
                "labels": ",".join(self.article_data.get("labels", [])),
                "raw_ai_json": json.dumps(self.article_data.get("ai_raw_json", {}), ensure_ascii=False),
                "final_html": final_html,
                "local_image_path": image_path,
                "remote_image_url": remote_image_url,
                "blog_id": blogger_service.blog_id,
                "post_id": post_id,
                "post_url": post_url,
                "is_draft": self.is_draft,
                "blogger_status": "PUBLISHED" if not self.is_draft else "DRAFT"
            }
            article_id = db.save_article(db_payload)

            wa_sent = False
            client_name = self.article_data.get("client_name", "")
            client_phone = self.article_data.get("client_phone", "")
            entity_type = self.article_data.get("entity_type")

            if self.send_wa_auto and post_url and client_phone:
                wa_sent = whatsapp_service.send_message(
                    article_id=article_id,
                    phone=client_phone,
                    name=client_name,
                    post_url=post_url,
                    entity_type=entity_type
                )

            self.finished.emit({
                "article_id": article_id,
                "post_id": post_id,
                "post_url": post_url,
                "wa_sent": wa_sent,
                "client_name": client_name,
                "client_phone": client_phone,
                "entity_type": entity_type
            })

        except Exception as e:
            self.error.emit(str(e))


class PreviewArticleView(QWidget):
    published_success = Signal(int, str, dict)

    def __init__(self):
        super().__init__()
        self.client_id = None
        self.ai_data = {}
        self.selected_image_path = ""
        self.client_name = ""
        self.client_phone = ""
        self.selected_entity_type = "plural"
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        # ─── Page Header ───
        header_box = QVBoxLayout()
        header_box.setSpacing(4)

        header = QLabel("معاينة وتعديل ونشر الخبر الصحفي")
        header.setProperty("class", "section-title")
        header_box.addWidget(header)

        subtitle = QLabel("راجع صياغة المقال وعناوين التحرير، حدد نوع الجهة المخاطبة، ثم انشر المقال وأرسل رسالة الواتساب بنقرة واحدة.")
        subtitle.setProperty("class", "section-subtitle")
        subtitle.setWordWrap(True)
        header_box.addWidget(subtitle)

        layout.addLayout(header_box)

        # ─── Splitter: HTML Preview | Metadata Controls ───
        splitter = QSplitter(Qt.Horizontal)

        # Left: Live Article HTML Preview Card
        preview_group = QGroupBox("المعاينة الحية للمقال الصحفي")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(14, 18, 14, 14)
        preview_layout.setSpacing(10)

        preview_toolbar = QHBoxLayout()
        preview_toolbar.addStretch()

        self.btn_copy_html = QPushButton("📋 نسخ كود HTML")
        self.btn_copy_html.setProperty("class", "secondary-btn")
        self.btn_copy_html.clicked.connect(self.copy_html_code)
        preview_toolbar.addWidget(self.btn_copy_html)

        preview_layout.addLayout(preview_toolbar)

        self.html_previewer = QTextEdit()
        self.html_previewer.setReadOnly(False)
        self.html_previewer.setMinimumWidth(440)
        preview_layout.addWidget(self.html_previewer)
        splitter.addWidget(preview_group)

        # Right: Controls Card
        controls_group = QGroupBox("بيانات النشر والرسالة")
        controls_layout = QVBoxLayout(controls_group)
        controls_layout.setContentsMargins(16, 20, 16, 16)
        controls_layout.setSpacing(12)

        # Article Title
        controls_layout.addWidget(QLabel("عنوان الخبر الصحفي:"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("أدخل عنوان الخبر...")
        controls_layout.addWidget(self.title_input)

        # Slug
        controls_layout.addWidget(QLabel("الرابط الثابت (Slug):"))
        self.slug_input = QLineEdit()
        self.slug_input.setPlaceholderText("blog-post_1234")
        controls_layout.addWidget(self.slug_input)

        # Category Labels
        controls_layout.addWidget(QLabel("التصنيفات (Labels):"))
        self.labels_input = QLineEdit()
        self.labels_input.setPlaceholderText("تعليم, عيادات, تجميل")
        controls_layout.addWidget(self.labels_input)

        # Entity Type Selector Box (♂️ / ♀️ / 🏢)
        entity_box = QGroupBox("نوع الجهة المخاطبة في رسالة الواتساب")
        entity_layout = QHBoxLayout(entity_box)
        entity_layout.setContentsMargins(10, 12, 10, 10)
        entity_layout.setSpacing(8)

        self.entity_button_group = QButtonGroup(self)

        self.radio_plural = QRadioButton("🏢 كيان / عيادة (حضراتكم)")
        self.radio_plural.setProperty("class", "entity-pill")
        self.radio_male = QRadioButton("♂️ شخص مذكر (حضرتك)")
        self.radio_male.setProperty("class", "entity-pill")
        self.radio_female = QRadioButton("♀️ شخص مؤنث (حضرتِك)")
        self.radio_female.setProperty("class", "entity-pill")

        self.entity_button_group.addButton(self.radio_plural, 1)
        self.entity_button_group.addButton(self.radio_male, 2)
        self.entity_button_group.addButton(self.radio_female, 3)

        self.radio_plural.setChecked(True)

        entity_layout.addWidget(self.radio_plural)
        entity_layout.addWidget(self.radio_male)
        entity_layout.addWidget(self.radio_female)

        controls_layout.addWidget(entity_box)

        # Auto WhatsApp Checkbox
        self.chk_auto_wa = QCheckBox("إرسال رسالة WhatsApp التفاعلية تلقائياً بعد النشر")
        self.chk_auto_wa.setChecked(True)
        controls_layout.addWidget(self.chk_auto_wa)

        # Action Buttons Layout
        btn_box = QVBoxLayout()
        btn_box.setSpacing(10)

        self.btn_publish = QPushButton("🚀   نشر الخبر الصحفي والواتساب الآن")
        self.btn_publish.setProperty("class", "primary-btn")
        self.btn_publish.setMinimumHeight(46)
        self.btn_publish.setCursor(Qt.PointingHandCursor)
        self.btn_publish.clicked.connect(lambda: self.start_publish(is_draft=False))
        btn_box.addWidget(self.btn_publish)

        sub_btn_row = QHBoxLayout()
        sub_btn_row.setSpacing(8)

        self.btn_wa_direct = QPushButton("💬  واتساب مباشر")
        self.btn_wa_direct.setProperty("class", "success-btn")
        self.btn_wa_direct.setMinimumHeight(38)
        self.btn_wa_direct.setCursor(Qt.PointingHandCursor)
        self.btn_wa_direct.clicked.connect(self.open_direct_wa)
        sub_btn_row.addWidget(self.btn_wa_direct)

        self.btn_draft = QPushButton("📝  حفظ مسودة")
        self.btn_draft.setProperty("class", "secondary-btn")
        self.btn_draft.setMinimumHeight(38)
        self.btn_draft.setCursor(Qt.PointingHandCursor)
        self.btn_draft.clicked.connect(lambda: self.start_publish(is_draft=True))
        sub_btn_row.addWidget(self.btn_draft)

        btn_box.addLayout(sub_btn_row)
        controls_layout.addLayout(btn_box)

        controls_layout.addStretch()
        splitter.addWidget(controls_group)
        splitter.setSizes([560, 420])

        layout.addWidget(splitter)

        # Progress Indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("جاري رفع الصورة والنشر على مدونة تحت الضوء وإرسال الواتساب...")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

    def get_selected_entity_type(self) -> str:
        if self.radio_female.isChecked():
            return "female"
        elif self.radio_male.isChecked():
            return "male"
        return "plural"

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

        self.title_input.setText(ai_data.get("title", ""))
        self.slug_input.setText(ai_data.get("slug", ""))
        self.labels_input.setText(", ".join(ai_data.get("labels", [])))

        # Set default radio button based on AI detected entity_type
        detected_entity = ai_data.get("entity_type", "plural")
        if detected_entity == "female":
            self.radio_female.setChecked(True)
        elif detected_entity == "male":
            self.radio_male.setChecked(True)
        else:
            self.radio_plural.setChecked(True)

        formatted_html = ArticleFormatter.json_to_html(ai_data)
        self.html_previewer.setHtml(formatted_html)

    def copy_html_code(self):
        html_code = self.html_previewer.toHtml()
        QApplication.clipboard().setText(html_code)
        QMessageBox.information(self, "نجاح", "تم نسخ كود HTML الكامل إلى الحافظة بنجاح!")

    def open_direct_wa(self):
        import webbrowser
        if not self.client_phone:
            QMessageBox.warning(self, "تنبيه", "لا يوجد رقم واتساب مسجل لهذا العميل.")
            return
        entity_type = self.get_selected_entity_type()
        wa_link = whatsapp_service.generate_whatsapp_click_link(
            self.client_phone, self.client_name, "https://www.tahteldoo.com/", entity_type=entity_type
        )
        webbrowser.open(wa_link)

    def start_publish(self, is_draft: bool = False):
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "تنبيه", "يرجى كتابة عنوان الخبر.")
            return

        labels = [l.strip() for l in self.labels_input.text().split(",") if l.strip()]

        article_data = {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "client_phone": self.client_phone,
            "title": title,
            "slug": self.slug_input.text().strip(),
            "labels": labels,
            "final_html": self.html_previewer.toHtml(),
            "local_image_path": self.selected_image_path,
            "ai_raw_json": self.ai_data,
            "entity_type": self.get_selected_entity_type()
        }

        self.btn_publish.setEnabled(False)
        self.btn_draft.setEnabled(False)
        self.btn_wa_direct.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.worker = PublishWorker(article_data, is_draft, self.chk_auto_wa.isChecked())
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, result):
        self.btn_publish.setEnabled(True)
        self.btn_draft.setEnabled(True)
        self.btn_wa_direct.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.info(f"تم النشر بنجاح. Article ID: {result['article_id']}")
        self.published_success.emit(result["article_id"], result["post_url"], result)

    def _on_error(self, error_msg):
        self.btn_publish.setEnabled(True)
        self.btn_draft.setEnabled(True)
        self.btn_wa_direct.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.error(f"خطأ أثناء النشر: {error_msg}")
        QMessageBox.critical(self, "خطأ", f"فشل النشر:\n{error_msg}")
