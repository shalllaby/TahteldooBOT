import flet as ft
from flet_ui.theme import ThemeColors, create_glass_card, create_gold_button, create_secondary_button, create_input_field
from flet_ui.components.header import create_page_header
from flet_ui.components.notification import show_snack

from core.config import Config
from services.blogger_service import blogger_service
from services.whatsapp_service import whatsapp_service, DEFAULT_TEMPLATE
from core.logger import logger


class SettingsView(ft.Container):
    def __init__(self, page: ft.Page, on_navigate=None, on_blogger_status_changed=None):
        super().__init__(expand=True, padding=20)
        self.app_page = page
        self.on_navigate = on_navigate
        self.on_blogger_status_changed = on_blogger_status_changed
        self.blogs_data = []

        self.init_ui()

    def init_ui(self):
        header = create_page_header(
            title="إعدادات النظام والاشتراكات",
            subtitle="إدارة حسابات Google/Blogger، مفاتيح الذكاء الاصطناعي، ورسائل الواتساب تلقائياً",
            icon=ft.Icons.SETTINGS
        )

        # Tabs Navigation (Flet 0.80+ standard: Tabs + TabBar + TabBarView)
        tab_bar = ft.TabBar(
            tabs=[
                ft.Tab(label="🌐 Blogger والمدونة"),
                ft.Tab(label="🤖 الذكاء الاصطناعي"),
                ft.Tab(label="💬 خدمات الواتساب"),
                ft.Tab(label="👥 فريق التحرير"),
                ft.Tab(label="🎨 المظهر والنظام"),
            ],
            indicator_color=ThemeColors.GOLD_PRIMARY,
            label_color=ThemeColors.GOLD_PRIMARY,
            unselected_label_color=ThemeColors.TEXT_SECONDARY,
        )

        tab_view = ft.TabBarView(
            controls=[
                self.build_blogger_tab(),
                self.build_ai_tab(),
                self.build_whatsapp_tab(),
                self.build_staff_tab(),
                self.build_theme_tab(),
            ],
            expand=True
        )

        self.tabs = ft.Tabs(
            length=5,
            selected_index=0,
            animation_duration=250,
            content=ft.Column(
                controls=[tab_bar, tab_view],
                spacing=10,
                expand=True
            ),
            expand=True
        )

        # Global Save Footer Button
        btn_save_all = create_gold_button(
            "💾   حفظ جميع الإعدادات",
            on_click=self.save_all_settings,
            height=45,
            expand=False
        )

        footer = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text("💡 يتم حفظ جميع الإعدادات والمفاتيح محلياً وبطريقة آمنة على جهازك فقط.", size=12, color=ThemeColors.TEXT_MUTED),
                    btn_save_all
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER
            ),
            padding=15,
            bgcolor="#0F172A",
            border_radius=10,
            border=ft.border.all(1, ThemeColors.BORDER_COLOR)
        )

        self.content = ft.Column(
            controls=[
                header,
                self.tabs,
                footer
            ],
            spacing=16,
            expand=True
        )

    # ─── TAB 1: BLOGGER ───
    def build_blogger_tab(self):
        self.blogger_status_text = ft.Text("جاري الفحص...", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.INFO)

        status_card = create_glass_card(
            content=ft.Row(
                controls=[
                    ft.Text("حالة حساب Google:", size=14, color=ThemeColors.TEXT_SECONDARY),
                    self.blogger_status_text
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=10
            )
        )

        btn_connect = create_gold_button(
            "🔑 ربط / تسجيل الدخول بحساب Google",
            on_click=self.connect_blogger,
            height=42,
            expand=True
        )

        btn_disconnect = create_secondary_button(
            "🚪 فصل الحساب",
            icon=ft.Icons.LOGOUT,
            on_click=self.disconnect_blogger,
            height=42,
            expand=True
        )

        self.blog_dropdown = ft.Dropdown(
            label="المدونة النشطة",
            border_color=ThemeColors.BORDER_COLOR,
            focused_border_color=ThemeColors.GOLD_PRIMARY,
            text_style=ft.TextStyle(color=ThemeColors.TEXT_PRIMARY, size=14),
            fill_color="#0F172A",
            filled=True,
            border_radius=8,
            expand=True,
            on_select=self.on_blog_selected
        )

        btn_fetch_blogs = create_secondary_button(
            "🔄 جلب المدونات",
            icon=ft.Icons.REFRESH,
            on_click=lambda e: self.load_user_blogs()
        )

        self.active_blog_id_text = ft.Text("", size=12, color=ThemeColors.TEXT_MUTED)

        self.refresh_blogger_state()

        return ft.Container(
            content=ft.Column(
                controls=[
                    status_card,
                    ft.Row([btn_connect, btn_disconnect], spacing=10),
                    ft.Row([self.blog_dropdown, btn_fetch_blogs], spacing=10),
                    self.active_blog_id_text
                ],
                spacing=16
            ),
            padding=15
        )

    # ─── TAB 2: AI KEYS ───
    def build_ai_tab(self):
        # ── Gemini ──
        self.gemini_key_input = create_input_field(
            label="Google Gemini API Key",
            password=True,
            value=Config.GEMINI_API_KEY
        )
        self.gemini_model_input = create_input_field(
            label="Gemini Model",
            value=Config.GEMINI_MODEL
        )

        # ── Z.AI / GLM ──
        self.zai_key_input = create_input_field(
            label="Z.AI (GLM) API Key",
            password=True,
            value=Config.ZAI_API_KEY
        )
        self.zai_url_input = create_input_field(
            label="Z.AI Base URL",
            value=Config.ZAI_BASE_URL
        )
        self.zai_model_input = create_input_field(
            label="Z.AI Model",
            value=Config.ZAI_MODEL
        )

        # ── Groq ──
        self.groq_key_input = create_input_field(
            label="Groq API Key",
            password=True,
            value=Config.GROQ_API_KEY
        )
        self.groq_model_input = create_input_field(
            label="Groq Model",
            value=Config.GROQ_MODEL
        )

        # ── OpenRouter ──
        self.openrouter_key_input = create_input_field(
            label="OpenRouter API Key",
            password=True,
            value=Config.OPENROUTER_API_KEY
        )
        self.openrouter_model_input = create_input_field(
            label="OpenRouter Model",
            value=Config.OPENROUTER_MODEL
        )

        # ── ZenMux ──
        self.zenmux_key_input = create_input_field(
            label="ZenMux API Key",
            password=True,
            value=Config.ZENMUX_API_KEY
        )
        self.zenmux_url_input = create_input_field(
            label="ZenMux Base URL",
            value=Config.ZENMUX_BASE_URL
        )
        self.zenmux_model_input = create_input_field(
            label="ZenMux Model",
            value=Config.ZENMUX_MODEL
        )

        # ── ImgBB ──
        self.imgbb_key_input = create_input_field(
            label="ImgBB API Key (لرفع الصور)",
            password=True,
            value=Config.IMGBB_API_KEY
        )

        def provider_card(title, icon_name, *fields):
            return create_glass_card(
                content=ft.Column(
                    controls=[
                        ft.Row([
                            ft.Icon(icon_name, color=ThemeColors.GOLD_PRIMARY, size=18),
                            ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY)
                        ], spacing=8),
                        *fields
                    ],
                    spacing=12
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    provider_card("🟢 Google Gemini (الأساسي)",
                                  ft.Icons.STAR,
                                  self.gemini_key_input, self.gemini_model_input),
                    provider_card("🔵 Z.AI / GLM (بيغ مودل)",
                                  ft.Icons.BOLT,
                                  self.zai_key_input, self.zai_url_input, self.zai_model_input),
                    provider_card("🟣 Groq API",
                                  ft.Icons.FLASH_ON,
                                  self.groq_key_input, self.groq_model_input),
                    provider_card("🟠 OpenRouter",
                                  ft.Icons.HUB,
                                  self.openrouter_key_input, self.openrouter_model_input),
                    provider_card("🟡 ZenMux / DeepSeek",
                                  ft.Icons.LAYERS,
                                  self.zenmux_key_input, self.zenmux_url_input, self.zenmux_model_input),
                    provider_card("🖼️ ImgBB — رفع الصور",
                                  ft.Icons.IMAGE,
                                  self.imgbb_key_input),
                ],
                spacing=14,
                scroll=ft.ScrollMode.AUTO
            ),
            padding=15
        )

    # ─── TAB 3: WHATSAPP ───
    def build_whatsapp_tab(self):
        self.wa_token_input = create_input_field(label="WP Sender Token / API Key", value=Config.WHATSAPP_TOKEN, password=True)
        self.wa_session_input = create_input_field(label="Session ID", value=Config.WHATSAPP_SESSION_ID)
        self.wa_url_input = create_input_field(label="Endpoint URL", value=Config.WHATSAPP_API_URL or "https://backendapi.wpsenderx.com/api/messages/send")
        self.wa_delay_input = create_input_field(label="التأخير بين الرسائل (ثواني)", value=str(Config.WHATSAPP_DELAY_SECONDS))
        self.wa_template_input = create_input_field(label="قالب نص رسالة الواتساب", value=DEFAULT_TEMPLATE, multiline=True, rows=5)

        self.test_phone_input = create_input_field(label="رقم هاتف تجريبي", hint_text="مثال: 201000000000")

        btn_test_send = create_secondary_button(
            "📲 تجربة الإرسال",
            icon=ft.Icons.SEND,
            on_click=self.test_send_wa
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    create_glass_card(
                        content=ft.Column(
                            controls=[
                                ft.Text("إعدادات الاتصال بـ WP Sender API", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                                self.wa_token_input,
                                self.wa_session_input,
                                self.wa_url_input,
                                self.wa_delay_input,
                                ft.Row([self.test_phone_input, btn_test_send], spacing=10)
                            ],
                            spacing=12
                        )
                    ),
                    create_glass_card(
                        content=ft.Column(
                            controls=[
                                ft.Text("قالب نص رسالة الواتساب التفاعلية", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                                ft.Text("💡 المتغيرات المتاحة: {NAME} لاسم العميل، و {POST_URL} لرابط الخبر.", size=12, color=ThemeColors.TEXT_MUTED),
                                self.wa_template_input
                            ],
                            spacing=10
                        )
                    )
                ],
                spacing=16,
                scroll=ft.ScrollMode.AUTO
            ),
            padding=15
        )

    # ─── TAB 4: THEME ───
    def build_theme_tab(self):
        self.theme_dropdown = ft.Dropdown(
            label="مظهر واجهة التطبيق",
            options=[
                ft.dropdown.Option("dark", "🌙   المظهر الداكن (Dark Obsidian Mode)"),
                ft.dropdown.Option("light", "☀️   المظهر الفاتح (Light Mode)"),
            ],
            value=getattr(Config, "APP_THEME", "dark"),
            border_color=ThemeColors.BORDER_COLOR,
            focused_border_color=ThemeColors.GOLD_PRIMARY,
            text_style=ft.TextStyle(color=ThemeColors.TEXT_PRIMARY, size=14),
            fill_color="#0F172A",
            filled=True,
            border_radius=8
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    create_glass_card(
                        content=ft.Column(
                            controls=[
                                ft.Text("مظهر البرنامج والألوان الرسمية", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                                self.theme_dropdown
                            ],
                            spacing=12
                        )
                    )
                ],
                spacing=16
            ),
            padding=15
        )

    # ─── TAB 4: STAFF / EDITOR TEAM ───
    def build_staff_tab(self):
        self.editor_name_input = create_input_field(
            label="اسم المحرر / مسؤول التواصل",
            hint_text="مثال: محمد شلبي",
            value=Config.EDITOR_NAME
        )
        self.editor_role_input = create_input_field(
            label="الدور الوظيفي",
            hint_text="مثال: رئيس تحرير",
            value=Config.EDITOR_ROLE
        )
        self.editor_phone_input = create_input_field(
            label="رقم هاتف المحرر (اختياري)",
            hint_text="مثال: 201012345678",
            value=Config.EDITOR_PHONE
        )

        preview_box = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("👁️ معاينة كيف تظهر رسالة الواتساب", size=12, color=ThemeColors.TEXT_MUTED),
                    ft.Text(
                        f"أنا {Config.EDITOR_NAME}\u060c {Config.EDITOR_ROLE} جريدة تحت الضوء الإخبارية ⚡",
                        size=13,
                        color=ThemeColors.GOLD_PRIMARY,
                        italic=True
                    )
                ],
                spacing=4
            ),
            padding=12,
            bgcolor="#0A0F1E",
            border_radius=8,
            border=ft.border.all(1, ThemeColors.BORDER_COLOR)
        )
        self._staff_preview = preview_box

        def on_staff_change(e):
            name = (self.editor_name_input.value or "").strip() or "محمد شلبي"
            role = (self.editor_role_input.value or "").strip() or "رئيس تحرير"
            self._staff_preview.content.controls[1].value = f"أنا {name}\u060c {role} جريدة تحت الضوء الإخبارية ⚡"
            self._staff_preview.update()

        self.editor_name_input.on_change = on_staff_change
        self.editor_role_input.on_change = on_staff_change

        return ft.Container(
            content=ft.Column(
                controls=[
                    create_glass_card(
                        content=ft.Column(
                            controls=[
                                ft.Text("👥 بيانات فريق التحرير", size=14, weight=ft.FontWeight.BOLD, color=ThemeColors.GOLD_PRIMARY),
                                ft.Text(
                                    "💡 سيتم استخدام هذه البيانات تلقائياً في جميع رسائل الواتساب المرسلة من النظام.",
                                    size=12, color=ThemeColors.TEXT_MUTED
                                ),
                                self.editor_name_input,
                                self.editor_role_input,
                                self.editor_phone_input,
                                preview_box
                            ],
                            spacing=14
                        )
                    )
                ],
                spacing=16
            ),
            padding=15
        )

    # ─── TAB 5: THEME ───
    # ─── CONTROLS LOGIC ───
    def refresh_blogger_state(self):
        is_auth = blogger_service.is_authenticated()
        if is_auth:
            info = blogger_service.get_user_info()
            display_name = info.get("display_name", "حساب Google")
            self.blogger_status_text.value = f"🟢 متصل ({display_name})"
            self.blogger_status_text.color = ThemeColors.SUCCESS
            self.load_user_blogs(auto_quiet=True)
        else:
            self.blogger_status_text.value = "🔴 غير متصل بـ Blogger"
            self.blogger_status_text.color = ThemeColors.ERROR
            self.blog_dropdown.options = [ft.dropdown.Option("none", "يرجى ربط الحساب أولاً")]
            self.blog_dropdown.value = "none"
            self.active_blog_id_text.value = ""

    def connect_blogger(self, e):
        try:
            service = blogger_service.authenticate()
            if service:
                show_snack(self.app_page, "✅ تم تسجيل الدخول بنجاح بحساب Google!", is_success=True)
                self.refresh_blogger_state()
        except Exception as ex:
            logger.error(f"خطأ Google OAuth: {ex}")
            show_snack(self.app_page, f"❌ فشل اتصال Google: {ex}", is_error=True)

    def disconnect_blogger(self, e):
        blogger_service.disconnect()
        self.refresh_blogger_state()
        show_snack(self.app_page, "🚪 تم فصل الحساب بنجاح", is_success=True)

    def load_user_blogs(self, auto_quiet=False):
        try:
            blogs = blogger_service.get_user_blogs()
            self.blogs_data = blogs
            if not blogs:
                self.blog_dropdown.options = [ft.dropdown.Option("none", "لم يتم العثور على مدونات")]
                self.blog_dropdown.value = "none"
                return

            options = []
            saved_blog_id = Config.BLOGGER_BLOG_ID
            selected_val = blogs[0]["id"]

            for b in blogs:
                options.append(ft.dropdown.Option(b["id"], f"{b['name']} ({b['url'] or b['id']})"))
                if saved_blog_id and b["id"] == saved_blog_id:
                    selected_val = b["id"]

            self.blog_dropdown.options = options
            self.blog_dropdown.value = selected_val
            self.active_blog_id_text.value = f"📌 معرّف المدونة النشطة: {selected_val}"

            if not auto_quiet:
                show_snack(self.app_page, f"✅ تم جلب {len(blogs)} مدونة بنجاح", is_success=True)
            if self.page:
                try:
                    self.update()
                except Exception:
                    pass
        except Exception as ex:
            logger.error(f"خطأ جلب المدونات: {ex}")
            if not auto_quiet:
                show_snack(self.app_page, f"❌ فشل جلب المدونات: {ex}", is_error=True)

    def on_blog_selected(self, e):
        val = self.blog_dropdown.value
        if not val or val == "none":
            return
        selected = next((b for b in self.blogs_data if b["id"] == val), None)
        if selected:
            Config.BLOGGER_BLOG_ID = selected["id"]
            Config.BLOGGER_BLOG_NAME = selected["name"]
            Config.update_env("BLOGGER_BLOG_ID", selected["id"])
            Config.update_env("BLOGGER_BLOG_NAME", selected["name"])
            self.active_blog_id_text.value = f"📌 معرّف المدونة النشطة: {selected['id']}"
            if callable(self.on_blogger_status_changed):
                self.on_blogger_status_changed(selected["name"], f"🟢 {selected['name']}")
            show_snack(self.app_page, f"📌 تم اختيار المدونة: {selected['name']}", is_success=True)

    def test_send_wa(self, e):
        phone = (self.test_phone_input.value or "").strip()
        if not phone:
            show_snack(self.app_page, "⚠️ يرجى إدخال رقم تجريبي أولاً", is_error=True)
            return
        self.save_all_settings(None)
        ok = whatsapp_service.send_message(article_id=0, phone=phone, name="تجربة النظام", post_url="https://www.tahteldoo.com/", delay_seconds=0)
        if ok:
            show_snack(self.app_page, f"✅ تم إرسال الرسالة التجريبية لـ {phone}", is_success=True)
        else:
            show_snack(self.app_page, f"❌ فشل إرسال الرسالة التجريبية", is_error=True)

    def save_all_settings(self, e):
        try:
            vals = {
                # Gemini
                "GEMINI_API_KEY": (self.gemini_key_input.value or "").strip(),
                "GEMINI_MODEL": (self.gemini_model_input.value or "").strip(),
                # Z.AI / GLM
                "ZAI_API_KEY": (self.zai_key_input.value or "").strip(),
                "ZAI_BASE_URL": (self.zai_url_input.value or "").strip(),
                "ZAI_MODEL": (self.zai_model_input.value or "").strip(),
                # Groq
                "GROQ_API_KEY": (self.groq_key_input.value or "").strip(),
                "GROQ_MODEL": (self.groq_model_input.value or "").strip(),
                # OpenRouter
                "OPENROUTER_API_KEY": (self.openrouter_key_input.value or "").strip(),
                "OPENROUTER_MODEL": (self.openrouter_model_input.value or "").strip(),
                # ZenMux
                "ZENMUX_API_KEY": (self.zenmux_key_input.value or "").strip(),
                "ZENMUX_BASE_URL": (self.zenmux_url_input.value or "").strip(),
                "ZENMUX_MODEL": (self.zenmux_model_input.value or "").strip(),
                # ImgBB
                "IMGBB_API_KEY": (self.imgbb_key_input.value or "").strip(),
                # WhatsApp
                "WHATSAPP_TOKEN": (self.wa_token_input.value or "").strip(),
                "WHATSAPP_SESSION_ID": (self.wa_session_input.value or "").strip(),
                "WHATSAPP_API_URL": (self.wa_url_input.value or "").strip(),
                "WHATSAPP_DELAY_SECONDS": (self.wa_delay_input.value or "0").strip(),
                # Editor / Staff
                "EDITOR_NAME": (self.editor_name_input.value or "").strip(),
                "EDITOR_ROLE": (self.editor_role_input.value or "").strip(),
                "EDITOR_PHONE": (self.editor_phone_input.value or "").strip(),
                # Theme
                "APP_THEME": self.theme_dropdown.value or "dark"
            }
            for k, v in vals.items():
                Config.update_env(k, v)

            # Update in-memory Config
            Config.GEMINI_API_KEY = vals["GEMINI_API_KEY"]
            Config.GEMINI_MODEL = vals["GEMINI_MODEL"]
            Config.ZAI_API_KEY = vals["ZAI_API_KEY"]
            Config.ZAI_BASE_URL = vals["ZAI_BASE_URL"]
            Config.ZAI_MODEL = vals["ZAI_MODEL"]
            Config.GROQ_API_KEY = vals["GROQ_API_KEY"]
            Config.GROQ_MODEL = vals["GROQ_MODEL"]
            Config.OPENROUTER_API_KEY = vals["OPENROUTER_API_KEY"]
            Config.OPENROUTER_MODEL = vals["OPENROUTER_MODEL"]
            Config.ZENMUX_API_KEY = vals["ZENMUX_API_KEY"]
            Config.ZENMUX_BASE_URL = vals["ZENMUX_BASE_URL"]
            Config.ZENMUX_MODEL = vals["ZENMUX_MODEL"]
            Config.IMGBB_API_KEY = vals["IMGBB_API_KEY"]
            Config.WHATSAPP_TOKEN = vals["WHATSAPP_TOKEN"]
            Config.WHATSAPP_SESSION_ID = vals["WHATSAPP_SESSION_ID"]
            Config.WHATSAPP_API_URL = vals["WHATSAPP_API_URL"]
            Config.WHATSAPP_DELAY_SECONDS = int(vals["WHATSAPP_DELAY_SECONDS"] or "0")
            Config.EDITOR_NAME = vals["EDITOR_NAME"] or "محمد شلبي"
            Config.EDITOR_ROLE = vals["EDITOR_ROLE"] or "رئيس تحرير"
            Config.EDITOR_PHONE = vals["EDITOR_PHONE"]
            Config.APP_THEME = vals["APP_THEME"]

            show_snack(self.app_page, "💾 تم حفظ جميع الإعدادات بنجاح!", is_success=True)
        except Exception as ex:
            logger.error(f"خطأ حفظ الإعدادات: {ex}")
            show_snack(self.app_page, f"❌ فشل حفظ الإعدادات: {ex}", is_error=True)
