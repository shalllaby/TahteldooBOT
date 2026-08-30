from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, 
    QTextEdit, QPushButton, QMessageBox, QGroupBox, QSpinBox, QFrame, QComboBox,
    QTabWidget, QScrollArea
)
from PySide6.QtCore import Signal, Qt
from core.config import Config
from services.whatsapp_service import DEFAULT_TEMPLATE, whatsapp_service
from services.blogger_service import blogger_service
from core.logger import logger


class SettingsView(QWidget):
    blogger_status_changed = Signal(str, str) # blog_name, status_text
    theme_changed = Signal(str) # theme_name ("dark" or "light")

    def __init__(self):
        super().__init__()
        self.blogs_data = [] # Stores [{id, name, url}]
        self.init_ui()
        self.refresh_blogger_state()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # ─── Page Header ───
        header = QLabel("⚙️ إعدادات التطبيق والتراخيص")
        header.setProperty("class", "section-title")
        main_layout.addWidget(header)

        subtitle = QLabel("إدارة حساب Google/Blogger الخاص بك، مفاتيح الذكاء الاصطناعي، مظهر البرنامج، وإعدادات الواتساب.")
        subtitle.setProperty("class", "section-subtitle")
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)

        # ─── Scroll Area ───
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # ─── Tabs Container ───
        self.tab_widget = QTabWidget()

        # Tab 1: Blogger & OAuth
        tab_blogger = self._create_blogger_tab()
        self.tab_widget.addTab(tab_blogger, "🌐   ربط Blogger والمدونة")

        # Tab 2: AI & Images
        tab_ai = self._create_ai_tab()
        self.tab_widget.addTab(tab_ai, "🤖   الذكاء الاصطناعي والصور")

        # Tab 3: WhatsApp & Templates
        tab_wa = self._create_whatsapp_tab()
        self.tab_widget.addTab(tab_wa, "💬   خدمات الواتساب والقالب")

        # Tab 4: Theme Settings
        tab_theme = self._create_theme_tab()
        self.tab_widget.addTab(tab_theme, "🎨   مظهر التطبيق")

        scroll_layout.addWidget(self.tab_widget)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)

        # ─── Global Save Button Footer ───
        save_card = QFrame()
        save_card.setStyleSheet("background-color: #0b1120; border-top: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; margin-top: 4px;")
        save_layout = QHBoxLayout(save_card)
        save_layout.setContentsMargins(16, 10, 16, 10)

        footer_hint = QLabel("💡 يتم حفظ جميع الاختيارات والإعدادات محلياً على جهازك فقط.")
        footer_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        save_layout.addWidget(footer_hint)

        save_layout.addStretch()

        self.btn_save = QPushButton("💾   حفظ جميع الإعدادات")
        self.btn_save.setProperty("class", "primary-btn")
        self.btn_save.setMinimumHeight(42)
        self.btn_save.setFixedWidth(220)
        self.btn_save.clicked.connect(self._save)
        save_layout.addWidget(self.btn_save)

        main_layout.addWidget(save_card)

    # ─── TAB BUILDERS ───

    def _create_blogger_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Group: Blogger OAuth Account
        group = QGroupBox("ربط حساب Google وتحديد المدونة")
        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(16)

        # Status & Info Card
        status_card = QFrame()
        status_card.setStyleSheet("background-color: #0b1120; border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 14px;")
        s_layout = QHBoxLayout(status_card)

        lbl_title = QLabel("حالة حساب Google:")
        lbl_title.setStyleSheet("font-weight: bold; color: #94a3b8;")
        s_layout.addWidget(lbl_title)

        self.blogger_status_label = QLabel("جاري الفحص...")
        self.blogger_status_label.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 14px;")
        s_layout.addWidget(self.blogger_status_label)

        s_layout.addStretch()
        g_layout.addWidget(status_card)

        # Buttons Row: Connect & Disconnect
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_connect_blogger = QPushButton("🔑   ربط / تسجيل الدخول بحساب Google")
        self.btn_connect_blogger.setProperty("class", "primary-btn")
        self.btn_connect_blogger.setMinimumHeight(42)
        self.btn_connect_blogger.clicked.connect(self._connect_blogger)
        btn_row.addWidget(self.btn_connect_blogger, 1)

        self.btn_disconnect_blogger = QPushButton("🚪   فصل الحساب والتغيير")
        self.btn_disconnect_blogger.setProperty("class", "secondary-btn")
        self.btn_disconnect_blogger.setMinimumHeight(42)
        self.btn_disconnect_blogger.setStyleSheet("color: #ef4444; border-color: rgba(239, 68, 68, 0.4);")
        self.btn_disconnect_blogger.clicked.connect(self._disconnect_blogger)
        btn_row.addWidget(self.btn_disconnect_blogger, 1)

        g_layout.addLayout(btn_row)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: rgba(255,255,255,0.06); max-height: 1px;")
        g_layout.addWidget(sep)

        # Grid for Blog Selection
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        lbl_blog = QLabel("المدونة النشطة:")
        lbl_blog.setFixedWidth(130)
        lbl_blog.setStyleSheet("font-weight: bold; color: #e2e8f0;")
        grid.addWidget(lbl_blog, 0, 0)

        self.blog_combo = QComboBox()
        self.blog_combo.setMinimumHeight(40)
        self.blog_combo.currentIndexChanged.connect(self._on_blog_selected)
        grid.addWidget(self.blog_combo, 0, 1)

        btn_refresh_blogs = QPushButton("🔄   جلب المدونات")
        btn_refresh_blogs.setProperty("class", "secondary-btn")
        btn_refresh_blogs.setMinimumHeight(40)
        btn_refresh_blogs.setFixedWidth(130)
        btn_refresh_blogs.clicked.connect(self._load_user_blogs)
        grid.addWidget(btn_refresh_blogs, 0, 2)

        g_layout.addLayout(grid)

        # Active Blog Details Box
        self.lbl_active_blog_id = QLabel("")
        self.lbl_active_blog_id.setStyleSheet("color: #64748b; font-size: 12px; padding-top: 4px;")
        g_layout.addWidget(self.lbl_active_blog_id)

        layout.addWidget(group)
        layout.addStretch()
        return tab

    def _create_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Group: AI Keys
        group = QGroupBox("مفاتيح خدمات الذكاء الاصطناعي ورفع الصور")
        grid = QGridLayout(group)
        grid.setContentsMargins(18, 22, 18, 18)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(16)

        # Groq API Key
        lbl_groq = QLabel("Groq API Key:")
        lbl_groq.setFixedWidth(140)
        lbl_groq.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_groq, 0, 0)

        self.groq_input = QLineEdit(Config.GROQ_API_KEY)
        self.groq_input.setEchoMode(QLineEdit.Password)
        self.groq_input.setMinimumHeight(40)
        grid.addWidget(self.groq_input, 0, 1)

        # Groq Model
        lbl_model = QLabel("Groq Model:")
        lbl_model.setFixedWidth(140)
        lbl_model.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_model, 1, 0)

        self.model_input = QLineEdit(Config.GROQ_MODEL)
        self.model_input.setMinimumHeight(40)
        grid.addWidget(self.model_input, 1, 1)

        # ImgBB API Key
        lbl_imgbb = QLabel("ImgBB API Key:")
        lbl_imgbb.setFixedWidth(140)
        lbl_imgbb.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_imgbb, 2, 0)

        self.imgbb_input = QLineEdit(Config.IMGBB_API_KEY)
        self.imgbb_input.setMinimumHeight(40)
        grid.addWidget(self.imgbb_input, 2, 1)

        layout.addWidget(group)
        layout.addStretch()
        return tab

    def _create_whatsapp_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Group 1: Connection Configs
        group_wa = QGroupBox("إعدادات الاتصال بـ WP Sender API")
        grid = QGridLayout(group_wa)
        grid.setContentsMargins(18, 22, 18, 18)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # API Key
        lbl_token = QLabel("API Key / Token:")
        lbl_token.setFixedWidth(140)
        lbl_token.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_token, 0, 0)

        self.wa_token_input = QLineEdit(Config.WHATSAPP_TOKEN)
        self.wa_token_input.setMinimumHeight(38)
        grid.addWidget(self.wa_token_input, 0, 1, 1, 2)

        # Session ID Row
        lbl_session = QLabel("Session ID:")
        lbl_session.setFixedWidth(140)
        lbl_session.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_session, 1, 0)

        self.wa_session_input = QLineEdit(Config.WHATSAPP_SESSION_ID)
        self.wa_session_input.setMinimumHeight(38)
        grid.addWidget(self.wa_session_input, 1, 1)

        sess_btns = QHBoxLayout()
        btn_fetch = QPushButton("🔄   جلب")
        btn_fetch.setProperty("class", "secondary-btn")
        btn_fetch.setMinimumHeight(38)
        btn_fetch.setFixedWidth(90)
        btn_fetch.clicked.connect(self._fetch_sessions)
        sess_btns.addWidget(btn_fetch)

        btn_status = QPushButton("⚡   فحص")
        btn_status.setProperty("class", "secondary-btn")
        btn_status.setMinimumHeight(38)
        btn_status.setFixedWidth(90)
        btn_status.clicked.connect(self._check_status)
        sess_btns.addWidget(btn_status)
        grid.addLayout(sess_btns, 1, 2)

        # Endpoint URL
        lbl_endpoint = QLabel("Endpoint URL:")
        lbl_endpoint.setFixedWidth(140)
        lbl_endpoint.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_endpoint, 2, 0)

        self.wa_endpoint_input = QLineEdit(
            Config.WHATSAPP_API_URL or "https://backendapi.wpsenderx.com/api/messages/send"
        )
        self.wa_endpoint_input.setMinimumHeight(38)
        grid.addWidget(self.wa_endpoint_input, 2, 1, 1, 2)

        # Delay
        lbl_delay = QLabel("التأخير بين الرسائل:")
        lbl_delay.setFixedWidth(140)
        lbl_delay.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_delay, 3, 0)

        delay_box = QHBoxLayout()
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 600)
        self.delay_spinbox.setValue(Config.WHATSAPP_DELAY_SECONDS)
        self.delay_spinbox.setSuffix("   ثانية")
        self.delay_spinbox.setMinimumHeight(38)
        self.delay_spinbox.setFixedWidth(160)
        delay_box.addWidget(self.delay_spinbox)
        delay_box.addStretch()
        grid.addLayout(delay_box, 3, 1, 1, 2)

        # Test Send Row
        lbl_test = QLabel("إرسال تجريبي:")
        lbl_test.setFixedWidth(140)
        lbl_test.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_test, 4, 0)

        test_box = QHBoxLayout()
        self.test_phone = QLineEdit()
        self.test_phone.setPlaceholderText("مثال: 201000000000")
        self.test_phone.setMinimumHeight(38)
        test_box.addWidget(self.test_phone)

        btn_test = QPushButton("📲   تجربة الإرسال")
        btn_test.setProperty("class", "secondary-btn")
        btn_test.setMinimumHeight(38)
        btn_test.setFixedWidth(140)
        btn_test.clicked.connect(self._test_send)
        test_box.addWidget(btn_test)
        grid.addLayout(test_box, 4, 1, 1, 2)

        layout.addWidget(group_wa)

        # Group 2: Template
        group_tmpl = QGroupBox("قالب نص رسالة الواتساب")
        tmpl_layout = QVBoxLayout(group_tmpl)
        tmpl_layout.setContentsMargins(18, 20, 18, 18)
        tmpl_layout.setSpacing(8)

        tmpl_hint = QLabel("💡 المتغيرات المتاحة: {NAME} لاسم العميل، و {POST_URL} لرابط الخبر المنشور.")
        tmpl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        tmpl_layout.addWidget(tmpl_hint)

        self.template_edit = QTextEdit()
        self.template_edit.setText(DEFAULT_TEMPLATE)
        self.template_edit.setMinimumHeight(120)
        self.template_edit.setMaximumHeight(160)
        tmpl_layout.addWidget(self.template_edit)

        layout.addWidget(group_tmpl)
        layout.addStretch()
        return tab

    def _create_theme_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        group = QGroupBox("مظهر الواجهة والأسلوب البصري (Theme)")
        grid = QGridLayout(group)
        grid.setContentsMargins(18, 22, 18, 18)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(16)

        lbl_theme = QLabel("اختر ثيم البرنامج:")
        lbl_theme.setFixedWidth(140)
        lbl_theme.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_theme, 0, 0)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("🌙   المظهر الداكن (Dark Obsidian Mode)", "dark")
        self.theme_combo.addItem("☀️   المظهر الفاتح (Light Mode)", "light")
        self.theme_combo.setMinimumHeight(40)

        # Select current theme
        current_theme = getattr(Config, "APP_THEME", "dark")
        idx = 1 if current_theme == "light" else 0
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        grid.addWidget(self.theme_combo, 0, 1)

        layout.addWidget(group)
        layout.addStretch()
        return tab

    def set_theme_combo_silent(self, theme_name: str):
        if hasattr(self, 'theme_combo'):
            self.theme_combo.blockSignals(True)
            idx = 1 if theme_name == "light" else 0
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

    def _on_theme_changed(self, index):
        theme_code = self.theme_combo.itemData(index)
        if theme_code:
            Config.APP_THEME = theme_code
            Config.update_env("APP_THEME", theme_code)
            self.theme_changed.emit(theme_code)

    # ─── ACTIONS & CONTROLS ───

    def refresh_blogger_state(self):
        """Refreshes the Blogger authentication status and blogs dropdown."""
        is_auth = blogger_service.is_authenticated()
        if is_auth:
            info = blogger_service.get_user_info()
            display_name = info.get("display_name", "حساب Google")
            self.blogger_status_label.setText(f"🟢 متصل ({display_name})")
            self.blogger_status_label.setStyleSheet("font-weight: bold; color: #10b981; font-size: 14px;")
            self.btn_connect_blogger.setEnabled(True)
            self.btn_disconnect_blogger.setEnabled(True)
            self._load_user_blogs(auto_quiet=True)
        else:
            self.blogger_status_label.setText("🔴 غير متصل بـ Blogger")
            self.blogger_status_label.setStyleSheet("font-weight: bold; color: #ef4444; font-size: 14px;")
            self.btn_connect_blogger.setEnabled(True)
            self.btn_disconnect_blogger.setEnabled(False)
            self.blog_combo.blockSignals(True)
            self.blog_combo.clear()
            self.blog_combo.addItem("يرجى ربط الحساب أولاً", None)
            self.blog_combo.blockSignals(False)
            self.lbl_active_blog_id.setText("")
            self.blogger_status_changed.emit("", "🔴 غير متصل")

    def _connect_blogger(self):
        try:
            QMessageBox.information(
                self, 
                "Google OAuth", 
                "سيتم فتح متصفح الإنترنت الآن لتسجيل الدخول بحساب Google المنشور عليه المدونة.\n\nيرجى إعطاء الصلاحيات المطلوبة."
            )
            service = blogger_service.authenticate()
            if service:
                QMessageBox.information(self, "نجاح", "تم تسجيل الدخول بنجاح! جاري جلب قائمة المدونات...")
                self.refresh_blogger_state()
        except Exception as e:
            logger.error(f"خطأ أثناء تسجيل دخول Google: {e}")
            QMessageBox.critical(self, "خطأ الربط", f"فشل تسجيل الدخول عبر Google:\n{e}")

    def _load_user_blogs(self, auto_quiet=False):
        try:
            blogs = blogger_service.get_user_blogs()
            self.blogs_data = blogs
            self.blog_combo.blockSignals(True)
            self.blog_combo.clear()

            if not blogs:
                self.blog_combo.addItem("لم يتم العثور على أي مدونة للحساب", None)
                self.lbl_active_blog_id.setText("")
                if not auto_quiet:
                    QMessageBox.warning(self, "تنبيـه", "لم يتم العثور على أي مدونة مرتبطة بحساب Google هذا.")
                self.blog_combo.blockSignals(False)
                return

            saved_blog_id = Config.BLOGGER_BLOG_ID
            selected_idx = 0

            for idx, b in enumerate(blogs):
                display_text = f"{b['name']} ({b['url'] or b['id']})"
                self.blog_combo.addItem(display_text, b['id'])
                if saved_blog_id and b['id'] == saved_blog_id:
                    selected_idx = idx

            self.blog_combo.setCurrentIndex(selected_idx)
            self.blog_combo.blockSignals(False)

            self._on_blog_selected(selected_idx)

            if not auto_quiet:
                QMessageBox.information(self, "نجاح", f"تم جلب {len(blogs)} مدونة بنجاح.")
        except Exception as e:
            logger.error(f"خطأ جلب المدونات: {e}")
            if not auto_quiet:
                QMessageBox.critical(self, "خطأ", f"فشل جلب المدونات:\n{e}")

    def _on_blog_selected(self, index):
        if index < 0 or index >= len(self.blogs_data):
            return

        selected_blog = self.blogs_data[index]
        blog_id = selected_blog["id"]
        blog_name = selected_blog["name"]

        Config.BLOGGER_BLOG_ID = blog_id
        Config.BLOGGER_BLOG_NAME = blog_name
        Config.update_env("BLOGGER_BLOG_ID", blog_id)
        Config.update_env("BLOGGER_BLOG_NAME", blog_name)

        self.lbl_active_blog_id.setText(f"📌 معرّف المدونة النشطة (Blog ID): {blog_id}")
        logger.info(f"تم اختيار المدونة النشطة: {blog_name} (ID: {blog_id})")

        self.blogger_status_changed.emit(blog_name, f"🟢 {blog_name}")

    def _disconnect_blogger(self):
        reply = QMessageBox.question(
            self,
            "تأكيد فصل الحساب",
            "هل أنت تأكد من رغبتك في فصل حساب Google / Blogger الحالي وتصفير الإعدادات من هذا الجهاز؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            blogger_service.disconnect()
            self.refresh_blogger_state()
            QMessageBox.information(self, "تم الفصل", "تم فصل الحساب بنجاح. يمكنك الآن ربط حساب جديد.")

    def _fetch_sessions(self):
        self._save()
        sessions = whatsapp_service.fetch_sessions()
        if not sessions:
            QMessageBox.warning(self, "تنبيه", "لم يتم العثور على جلسات أو فشل الاتصال.")
            return
        ids = [s.get("session_id") for s in sessions if s.get("session_id")]
        if ids:
            self.wa_session_input.setText(ids[0])
            QMessageBox.information(self, "نجاح", f"تم جلب {len(ids)} جلسة.\nالجلسة النشطة: {ids[0]}")

    def _check_status(self):
        self._save()
        sid = self.wa_session_input.text().strip()
        if not sid:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال Session ID أولاً.")
            return
        status = whatsapp_service.check_session_status(sid)
        if status.lower() == "connected":
            QMessageBox.information(self, "متصل", f"✅ الجلسة متصلة بنجاح.")
        else:
            QMessageBox.warning(self, "حالة الجلسة", f"الحالة: {status}")

    def _test_send(self):
        phone = self.test_phone.text().strip()
        if not phone:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال رقم هاتف تجريبي.")
            return
        self._save()
        ok = whatsapp_service.send_message(
            article_id=0, phone=phone, name="تجربة النظام",
            post_url="https://www.tahteldoo.com/", delay_seconds=0
        )
        if ok:
            QMessageBox.information(self, "نجاح", f"تم الإرسال بنجاح إلى {phone}.")
        else:
            QMessageBox.critical(self, "فشل", "فشل الإرسال. راجع سجل النظام.")

    def _save(self):
        try:
            vals = {
                "GROQ_API_KEY": self.groq_input.text().strip(),
                "GROQ_MODEL": self.model_input.text().strip(),
                "IMGBB_API_KEY": self.imgbb_input.text().strip(),
                "WHATSAPP_TOKEN": self.wa_token_input.text().strip(),
                "WHATSAPP_SESSION_ID": self.wa_session_input.text().strip(),
                "WHATSAPP_API_URL": self.wa_endpoint_input.text().strip(),
                "WHATSAPP_DELAY_SECONDS": str(self.delay_spinbox.value()),
            }
            for key, val in vals.items():
                Config.update_env(key, val)

            # Update live config
            Config.GROQ_API_KEY = vals["GROQ_API_KEY"]
            Config.GROQ_MODEL = vals["GROQ_MODEL"]
            Config.IMGBB_API_KEY = vals["IMGBB_API_KEY"]
            Config.WHATSAPP_TOKEN = vals["WHATSAPP_TOKEN"]
            Config.WHATSAPP_SESSION_ID = vals["WHATSAPP_SESSION_ID"]
            Config.WHATSAPP_API_URL = vals["WHATSAPP_API_URL"]
            Config.WHATSAPP_DELAY_SECONDS = int(vals["WHATSAPP_DELAY_SECONDS"])

            logger.info("تم حفظ الإعدادات بنجاح.")
            QMessageBox.information(self, "حفظ الإعدادات", "تم حفظ كافة الإعدادات بنجاح.")
        except Exception as e:
            logger.error(f"خطأ أثناء حفظ الإعدادات: {e}")
            QMessageBox.critical(self, "خطأ", f"فشل حفظ الإعدادات:\n{e}")
