import os
import webbrowser
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, 
    QLabel, QPushButton, QStackedWidget, QMessageBox, QApplication, QFrame
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from ui.views.create_view import CreateArticleView
from ui.views.preview_view import PreviewArticleView
from ui.views.history_view import HistoryView
from ui.views.settings_view import SettingsView
from ui.views.logs_view import LogsView
from services.whatsapp_service import whatsapp_service
from core.config import Config

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"تطبيق نشر الأخبار الصحفية — {Config.NEWSPAPER_NAME}")
        self.resize(1360, 860)
        self.setMinimumSize(1000, 640)

        self.load_stylesheet()
        self.init_ui()

    def load_stylesheet(self, theme=None):
        theme_name = theme or getattr(Config, "APP_THEME", "dark")
        filename = "style_light.qss" if theme_name == "light" else "style.qss"
        style_path = Config.BASE_DIR / "assets" / filename
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def change_theme(self, theme_name: str):
        Config.APP_THEME = theme_name
        Config.update_env("APP_THEME", theme_name)
        self.load_stylesheet(theme_name)
        if hasattr(self, 'btn_theme_toggle'):
            self.btn_theme_toggle.setText("☀️" if theme_name == "dark" else "🌙")
            self.btn_theme_toggle.setToolTip("التبديل إلى المظهر الفاتح" if theme_name == "dark" else "التبديل إلى المظهر الداكن")

    def toggle_theme(self):
        new_theme = "light" if Config.APP_THEME == "dark" else "dark"
        self.change_theme(new_theme)
        if hasattr(self, 'settings_view'):
            self.settings_view.set_theme_combo_silent(new_theme)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─── Sidebar Panel ───
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Brand Header & Avatar
        brand_container = QWidget()
        brand_layout = QVBoxLayout(brand_container)
        brand_layout.setContentsMargins(18, 20, 18, 12)
        brand_layout.setSpacing(6)

        header_top = QHBoxLayout()
        header_top.setSpacing(10)

        avatar = QLabel("📰")
        avatar.setObjectName("brand_avatar")
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignCenter)
        header_top.addWidget(avatar)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        nav_title = QLabel("تحت الضوء")
        nav_title.setObjectName("nav_title")
        version_label = QLabel("أتمتة النشر والواتساب")
        version_label.setObjectName("nav_version")
        title_box.addWidget(nav_title)
        title_box.addWidget(version_label)
        header_top.addLayout(title_box)

        header_top.addStretch()

        # Theme Toggle Quick Button
        self.btn_theme_toggle = QPushButton("☀️" if Config.APP_THEME == "dark" else "🌙")
        self.btn_theme_toggle.setProperty("class", "secondary-btn")
        self.btn_theme_toggle.setFixedSize(36, 36)
        self.btn_theme_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_theme_toggle.setToolTip("التبديل بين المظهر الفاتح والداكن")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        header_top.addWidget(self.btn_theme_toggle)

        brand_layout.addLayout(header_top)
        sidebar_layout.addWidget(brand_container)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: rgba(255, 255, 255, 0.06); max-height: 1px; margin: 6px 14px;")
        sidebar_layout.addWidget(sep1)

        # Status Chips Bar
        status_box = QHBoxLayout()
        status_box.setContentsMargins(16, 4, 16, 8)
        status_box.setSpacing(6)

        self.chip_blogger = QLabel("🟢 Blogger")
        self.chip_blogger.setProperty("class", "status-chip-ok")
        chip_wa = QLabel("💬 WhatsApp API")
        chip_wa.setProperty("class", "status-chip-info")

        status_box.addWidget(self.chip_blogger)
        status_box.addWidget(chip_wa)
        status_box.addStretch()
        sidebar_layout.addLayout(status_box)

        # Navigation Section Header
        section_label = QLabel("القائمة الرئيسية")
        section_label.setObjectName("sidebar_header")
        sidebar_layout.addWidget(section_label)

        # Navigation Buttons
        nav_items = [
            ("📝   إنشاء خبر جديد", 0),
            ("👁️   معاينة وتعديل ونشر", 1),
            ("📊   أرشيف الأخبار", 2),
            ("⚙️   إعدادات النظام", 3),
            ("📜   سجل العمليات", 4),
        ]

        self.nav_buttons = []
        for text, index in nav_items:
            btn = QPushButton(text)
            btn.setProperty("class", "nav-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=index: self.switch_tab(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self.nav_buttons[0].setChecked(True)

        sidebar_layout.addStretch()

        # Footer in sidebar
        footer_label = QLabel("© جريدة تحت الضوء 2026\nالإصدار الذكي 2.0")
        footer_label.setStyleSheet("color: #475569; font-size: 10px; padding: 14px 16px; line-height: 1.4;")
        footer_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(footer_label)

        main_layout.addWidget(sidebar)

        # ─── Main Content Area ───
        self.stacked_widget = QStackedWidget()

        self.create_view = CreateArticleView()
        self.preview_view = PreviewArticleView()
        self.history_view = HistoryView()
        self.settings_view = SettingsView()
        self.logs_view = LogsView()

        self.stacked_widget.addWidget(self.create_view)   # 0
        self.stacked_widget.addWidget(self.preview_view)  # 1
        self.stacked_widget.addWidget(self.history_view)  # 2
        self.stacked_widget.addWidget(self.settings_view) # 3
        self.stacked_widget.addWidget(self.logs_view)     # 4

        main_layout.addWidget(self.stacked_widget)

        # Connect Signals
        self.create_view.article_generated.connect(self.on_article_generated)
        self.create_view.published_success.connect(self.on_published_success)
        self.preview_view.published_success.connect(self.on_published_success)
        self.settings_view.blogger_status_changed.connect(self.update_blogger_chip)
        self.settings_view.theme_changed.connect(self.change_theme)

        # Initial chip update
        if Config.BLOGGER_BLOG_NAME:
            self.update_blogger_chip(Config.BLOGGER_BLOG_NAME, f"🟢 {Config.BLOGGER_BLOG_NAME}")
        elif Config.BLOGGER_BLOG_ID:
            self.update_blogger_chip("", "🟢 Blogger متصل")
        else:
            self.update_blogger_chip("", "🔴 غير متصل")

    def switch_tab(self, index: int):
        self.stacked_widget.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

        if index == 2:
            self.history_view.load_data()
        elif index == 4:
            self.logs_view.load_logs()

    def on_article_generated(self, client_id: int, ai_data: dict, selected_image_path: str):
        self.preview_view.load_article(client_id, ai_data, selected_image_path)
        self.switch_tab(1)

    def on_published_success(self, article_id: int, post_url: str, result: dict):
        client_name = result.get("client_name", "العميل")
        client_phone = result.get("client_phone", "")
        wa_sent = result.get("wa_sent", False)
        entity_type = result.get("entity_type")

        wa_status = "✅ تم إرسال رسالة WhatsApp تلقائياً عبر API." if wa_sent else "يمكنك فتح الشات المباشر لإرسال الرسالة بنقرة واحدة."

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("🎉 تم نشر الخبر بنجاح")
        msg_box.setText(
            f"تم نشر الخبر الصحفي بنجاح على مدونة تحت الضوء!\n\n"
            f"🔗 رابط الخبر:\n{post_url}\n\n"
            f"{wa_status}"
        )
        msg_box.setIcon(QMessageBox.Information)

        btn_both = None
        if client_phone and post_url:
            btn_both = msg_box.addButton("🚀  فتح التبويبتين معاً (الخبر + الواتساب)", QMessageBox.AcceptRole)

        btn_open = msg_box.addButton("🌐  فتح رابط الخبر فقط", QMessageBox.ActionRole)
        btn_wa = None
        if client_phone:
            btn_wa = msg_box.addButton("💬  فتح شات الواتساب فقط", QMessageBox.ActionRole)
        btn_copy = msg_box.addButton("📋  نسخ رابط الخبر", QMessageBox.ActionRole)
        msg_box.addButton("إغلاق", QMessageBox.RejectRole)

        msg_box.exec()

        clicked = msg_box.clickedButton()
        if btn_both and clicked == btn_both:
            wa_link = whatsapp_service.generate_whatsapp_click_link(client_phone, client_name, post_url, entity_type=entity_type)
            webbrowser.open(post_url)
            webbrowser.open(wa_link)
        elif clicked == btn_open and post_url:
            webbrowser.open(post_url)
        elif btn_wa and clicked == btn_wa and client_phone:
            wa_link = whatsapp_service.generate_whatsapp_click_link(client_phone, client_name, post_url, entity_type=entity_type)
            webbrowser.open(wa_link)
        elif clicked == btn_copy and post_url:
            QApplication.clipboard().setText(post_url)

        self.switch_tab(2)

    def update_blogger_chip(self, blog_name: str, status_text: str):
        if "🔴" in status_text:
            self.chip_blogger.setText("🔴 غير متصل")
            self.chip_blogger.setProperty("class", "status-chip-err")
        else:
            name = blog_name or "Blogger"
            self.chip_blogger.setText(f"🟢 {name}")
            self.chip_blogger.setProperty("class", "status-chip-ok")
        # Re-apply style
        self.chip_blogger.style().unpolish(self.chip_blogger)
        self.chip_blogger.style().polish(self.chip_blogger)
