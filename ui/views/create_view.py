import os
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFileDialog, QMessageBox, QGroupBox, 
    QProgressBar, QApplication
)
from PySide6.QtCore import Signal, Qt, QThread
from PySide6.QtGui import QPixmap
from services.ai_service import ai_service
from services.article_formatter import ArticleFormatter
from services.image_service import image_service
from services.blogger_service import blogger_service
from services.whatsapp_service import whatsapp_service
from database.db import db
from core.config import Config
from core.logger import logger


class AIGeneratorWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, raw_notes):
        super().__init__()
        self.raw_notes = raw_notes

    def run(self):
        try:
            ai_data = ai_service.generate_article(self.raw_notes)
            self.finished.emit(ai_data)
        except Exception as e:
            self.error.emit(str(e))


class DirectPublishWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, raw_notes, image_path):
        super().__init__()
        self.raw_notes = raw_notes
        self.image_path = image_path

    def run(self):
        try:
            from concurrent.futures import ThreadPoolExecutor

            # Run AI generation and Image upload concurrently to maximize speed
            remote_image_url = ""
            with ThreadPoolExecutor(max_workers=2) as executor:
                ai_future = executor.submit(ai_service.generate_article, self.raw_notes)
                
                img_future = None
                if self.image_path and os.path.exists(self.image_path):
                    img_future = executor.submit(image_service.upload_image, self.image_path)
                
                if img_future:
                    remote_image_url = img_future.result()

                ai_data = ai_future.result()

            client_name = ai_data.get("client_name") or ""
            if not client_name:
                title = ai_data.get("title", "")
                if ".." in title:
                    client_name = title.split("..")[0].strip()
                else:
                    client_name = title or "خبر صحفي"

            client_phone = ai_data.get("client_phone") or ""

            # Save client to DB
            client_id = db.save_client(client_name, client_phone, self.raw_notes)

            # Auto-detect entity type (AI returned or keyword based)
            entity_type = ai_data.get("entity_type")
            if not entity_type or entity_type not in ["male", "female", "plural"]:
                entity_type = whatsapp_service.detect_entity_type(client_name)

            # 3. Format HTML
            formatted_html = ArticleFormatter.json_to_html(ai_data)
            if remote_image_url:
                formatted_html = ArticleFormatter.replace_image_placeholder(formatted_html, remote_image_url)

            # 4. Publish to Blogger
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
                "local_image_path": self.image_path,
                "remote_image_url": remote_image_url,
                "blog_id": blogger_service.blog_id,
                "post_id": post_id,
                "post_url": post_url,
                "is_draft": False,
                "blogger_status": "PUBLISHED"
            }
            article_id = db.save_article(db_payload)

            # 5. Send WhatsApp notification automatically
            wa_sent = False
            if post_url and client_phone:
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


class CreateArticleView(QWidget):
    article_generated = Signal(int, dict, str)
    published_success = Signal(int, str, dict)

    def __init__(self):
        super().__init__()
        self.selected_image_path = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # ─── Page Header ───
        header_box = QVBoxLayout()
        header_box.setSpacing(4)

        header = QLabel("إنشاء ونشر خبر صحفي بالذكاء الاصطناعي")
        header.setProperty("class", "section-title")
        header_box.addWidget(header)

        subtitle = QLabel("أدخل التفاصيل والمعلومات الخام فقط، وسيحدد الذكاء الاصطناعي نوع الجهة تلقائياً وينشر المقال ويرسل رسالة الواتساب بضغطة واحدة.")
        subtitle.setProperty("class", "section-subtitle")
        subtitle.setWordWrap(True)
        header_box.addWidget(subtitle)

        layout.addLayout(header_box)

        # ─── Raw Data Card ───
        data_group = QGroupBox("المعلومات والتفاصيل الخام للخبر")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(16, 20, 16, 16)
        data_layout.setSpacing(10)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText(
            "ضع هنا كافة البيانات والمعلومات الخام دون حاجة لتنسيقها:\n\n"
            "مثال: دكتور ناصر عبدالكريم - استشاري الجلدية والتجميل والليزر - عيادة الدقي - تقديم خدمات الفيلر والبوتكس وأحدث تقنيات الليزر - تليفون 01012345678...\n\n"
            "الذكاء الاصطناعي يتميز بالتعرف التلقائي الذكي على اسم الشخص/العيادة ونوع الجهة (مذكر/مؤنث/كيان) وصياغة ونشر الخبر فوراً."
        )
        self.notes_input.setMinimumHeight(220)
        data_layout.addWidget(self.notes_input)

        layout.addWidget(data_group)

        # ─── Image Upload Card ───
        img_group = QGroupBox("صورة الخبر الرئيسية")
        img_layout = QVBoxLayout(img_group)
        img_layout.setContentsMargins(16, 18, 16, 16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_select_image = QPushButton("📁 اختيار صورة من الجهاز")
        self.btn_select_image.setProperty("class", "secondary-btn")
        self.btn_select_image.clicked.connect(self.select_image)
        btn_row.addWidget(self.btn_select_image)

        self.btn_paste_image = QPushButton("📋 لصق صورة من الحافظة")
        self.btn_paste_image.setProperty("class", "secondary-btn")
        self.btn_paste_image.clicked.connect(self.paste_image)
        btn_row.addWidget(self.btn_paste_image)

        self.img_status_label = QLabel("لم يتم اختيار صورة بعد (يمكن رفعها لاحقاً)")
        self.img_status_label.setStyleSheet("color: #64748b; font-size: 12px;")
        btn_row.addWidget(self.img_status_label)
        btn_row.addStretch()

        # Thumbnail preview
        self.img_preview = QLabel()
        self.img_preview.setFixedSize(70, 70)
        self.img_preview.setStyleSheet("border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; background-color: #0b1120;")
        self.img_preview.setAlignment(Qt.AlignCenter)
        self.img_preview.setVisible(False)
        btn_row.addWidget(self.img_preview)

        img_layout.addLayout(btn_row)
        layout.addWidget(img_group)

        # ─── Progress Bar ───
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("جاري الصياغة والنشر وإرسال الواتساب بالذكاء الاصطناعي...")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ─── Action Buttons Layout ───
        action_layout = QVBoxLayout()
        action_layout.setSpacing(10)

        # 1-Click Direct Publish Button
        self.btn_direct_publish = QPushButton("🚀   صياغة ونشر الخبر الصحفي والواتساب مباشرة (ضغطة واحدة)")
        self.btn_direct_publish.setProperty("class", "success-btn")
        self.btn_direct_publish.setMinimumHeight(52)
        self.btn_direct_publish.setCursor(Qt.PointingHandCursor)
        self.btn_direct_publish.clicked.connect(self.start_direct_publish)
        action_layout.addWidget(self.btn_direct_publish)

        # Generate for Preview Button
        self.btn_generate = QPushButton("✨   صياغة وتجهيز للمعاينة والتعديل أولاً")
        self.btn_generate.setProperty("class", "primary-btn")
        self.btn_generate.setMinimumHeight(44)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.clicked.connect(self.start_generation)
        action_layout.addWidget(self.btn_generate)

        layout.addLayout(action_layout)
        layout.addStretch()

    # ─── Image Helpers ───

    def _set_image(self, file_path: str):
        self.selected_image_path = file_path
        self.img_status_label.setText(f"✓ تم إرفاق: {os.path.basename(file_path)}")
        self.img_status_label.setStyleSheet("color: #10b981; font-weight: bold; font-size: 12px;")
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.img_preview.setPixmap(pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img_preview.setVisible(True)

    def select_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر صورة الخبر", "", "ملفات الصور (*.png *.jpg *.jpeg *.webp)")
        if path:
            self._set_image(path)

    def paste_image(self):
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            temp_path = str(Config.STORAGE_DIR / "temp_pasted_image.png")
            image.save(temp_path, "PNG")
            self._set_image(temp_path)
            logger.info("تم لصق الصورة من الحافظة بنجاح.")
        else:
            text = clipboard.text().strip()
            if text and os.path.exists(text) and text.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                self._set_image(text)
            else:
                QMessageBox.warning(self, "تنبيه", "لا توجد صورة منسوخة في الحافظة حالياً.\nانسخ صورة أولاً ثم اضغط لصق.")

    # ─── 1-Click Direct Publish ───

    def start_direct_publish(self):
        raw_notes = self.notes_input.toPlainText().strip()
        if not raw_notes:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال البيانات والتفاصيل الخام للخبر في الصندوق أولاً.")
            return

        self.btn_direct_publish.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.direct_worker = DirectPublishWorker(raw_notes, self.selected_image_path)
        self.direct_worker.finished.connect(self._on_direct_finished)
        self.direct_worker.error.connect(self._on_direct_error)
        self.direct_worker.start()

    def _on_direct_finished(self, result):
        self.btn_direct_publish.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.info(f"تم النشر المباشر بنجاح (Article ID: {result['article_id']}).")
        self.published_success.emit(result["article_id"], result["post_url"], result)

    def _on_direct_error(self, error_msg):
        self.btn_direct_publish.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.error(f"خطأ في النشر المباشر: {error_msg}")
        QMessageBox.critical(self, "خطأ", f"فشل النشر المباشر:\n{error_msg}")

    # ─── Generation for Preview ───

    def start_generation(self):
        raw_notes = self.notes_input.toPlainText().strip()
        if not raw_notes:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال البيانات والتفاصيل الخام للخبر في الصندوق أولاً.")
            return

        self.btn_direct_publish.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.worker = AIGeneratorWorker(raw_notes)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, ai_data):
        self.btn_direct_publish.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)

        raw_notes = self.notes_input.toPlainText().strip()
        client_name = ai_data.get("client_name") or ""
        if not client_name:
            title = ai_data.get("title", "")
            if ".." in title:
                client_name = title.split("..")[0].strip()
            else:
                client_name = title or "خبر صحفي"

        client_phone = ai_data.get("client_phone") or ""

        client_id = db.save_client(client_name, client_phone, raw_notes)
        logger.info(f"تم توليد الخبر بنجاح (العميل: {client_name} - الواتساب: {client_phone}). الانتقال إلى المعاينة.")
        self.article_generated.emit(client_id, ai_data, self.selected_image_path)

    def _on_error(self, error_msg):
        self.btn_direct_publish.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.error(f"خطأ في توليد الخبر: {error_msg}")
        QMessageBox.critical(self, "خطأ", f"فشل توليد الخبر:\n{error_msg}")
