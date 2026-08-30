from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, 
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from database.db import db
from services.whatsapp_service import whatsapp_service
from core.logger import logger


class HistoryView(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # ─── Page Header ───
        header = QLabel("سجل الأخبار المنشورة")
        header.setProperty("class", "section-title")
        layout.addWidget(header)

        subtitle = QLabel("جميع الأخبار التي تم نشرها أو حفظها كمسودات، مع إمكانية إعادة إرسال رسائل الواتساب.")
        subtitle.setProperty("class", "section-subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ─── Top Bar ───
        top_bar = QHBoxLayout()

        self.btn_refresh = QPushButton("🔄  تحديث")
        self.btn_refresh.setProperty("class", "secondary-btn")
        self.btn_refresh.clicked.connect(self.load_data)
        top_bar.addWidget(self.btn_refresh)

        top_bar.addStretch()

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #64748b; font-size: 12px;")
        top_bar.addWidget(self.count_label)

        layout.addLayout(top_bar)

        # ─── Table ───
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID", "العنوان", "العميل", "الحالة", "الرابط", "التاريخ", "إجراءات"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 260)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        self.load_data()

    def load_data(self):
        articles = db.get_all_articles()
        self.table.setRowCount(len(articles))
        self.count_label.setText(f"إجمالي: {len(articles)} خبر")

        for row, article in enumerate(articles):
            self.table.setItem(row, 0, QTableWidgetItem(str(article["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(article.get("title", "")))
            self.table.setItem(row, 2, QTableWidgetItem(article.get("client_name") or "—"))

            status = article.get("blogger_status", "PENDING")
            status_item = QTableWidgetItem(status)
            if status == "PUBLISHED":
                status_item.setForeground(Qt.green)
            elif status == "DRAFT":
                status_item.setForeground(Qt.yellow)
            self.table.setItem(row, 3, status_item)

            self.table.setItem(row, 4, QTableWidgetItem(article.get("post_url") or "—"))
            self.table.setItem(row, 5, QTableWidgetItem(str(article.get("created_at", ""))))

            # Actions
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)

            post_url = article.get("post_url") or ""
            if post_url:
                btn_open = QPushButton("🔗")
                btn_open.setToolTip("فتح رابط الخبر")
                btn_open.setProperty("class", "secondary-btn")
                btn_open.setFixedWidth(36)
                btn_open.clicked.connect(lambda _, url=post_url: QDesktopServices.openUrl(QUrl(url)))
                action_layout.addWidget(btn_open)

            btn_wa = QPushButton("💬 واتساب")
            btn_wa.setProperty("class", "success-btn")
            btn_wa.setFixedHeight(28)
            btn_wa.clicked.connect(lambda _, a=article: self._open_wa(a))
            action_layout.addWidget(btn_wa)

            btn_api = QPushButton("⚡ API")
            btn_api.setProperty("class", "secondary-btn")
            btn_api.setFixedHeight(28)
            btn_api.clicked.connect(lambda _, a=article: self._retry_api(a))
            action_layout.addWidget(btn_api)

            self.table.setCellWidget(row, 6, action_widget)

    def _open_wa(self, article):
        phone = article.get("client_phone")
        if not phone:
            QMessageBox.warning(self, "تنبيه", "لا يوجد رقم هاتف مسجل.")
            return
        name = article.get("client_name") or "العميل"
        url = article.get("post_url") or "https://www.tahteldoo.com/"
        import webbrowser
        wa_link = whatsapp_service.generate_whatsapp_click_link(phone, name, url)
        webbrowser.open(wa_link)

    def _retry_api(self, article):
        phone = article.get("client_phone")
        post_url = article.get("post_url")
        if not post_url:
            QMessageBox.warning(self, "تنبيه", "لا يوجد رابط خبر منشور.")
            return
        if not phone:
            QMessageBox.warning(self, "تنبيه", "لا يوجد رقم واتساب مسجل.")
            return

        name = article.get("client_name", "")
        success = whatsapp_service.send_message(
            article_id=article["id"], phone=phone, name=name, post_url=post_url
        )
        if success:
            QMessageBox.information(self, "نجاح", f"تم إرسال الواتساب بنجاح لـ {name}.")
        else:
            reply = QMessageBox.question(
                self, "فشل API",
                "فشل الإرسال عبر API.\nهل تريد فتح شات واتساب مباشر بالرسالة الجاهزة؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self._open_wa(article)
        self.load_data()
