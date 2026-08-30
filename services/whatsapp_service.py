import time
import urllib.parse
import re
import requests
from core.config import Config
from core.logger import logger
from database.db import db

# =============================================================
# WHATSAPP MESSAGE TEMPLATES
# =============================================================

TEMPLATE_MALE = """السلام عليكم ورحمة الله وبركاته ✨

أهلًا وسهلًا بحضرتك {NAME}، تشرفنا بتواصلنا مع حضرتك.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية ⚡

🔹 رابط الجريدة:
https://www.tahteldoo.com/

🔹 صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

🔹 رابط الخبر:
{POST_URL}

✨ مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

📌 برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

✅ موافقة على النشر
❌ عدم الموافقة على النشر
✏️ موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

⏰ برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتك.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق 🌿"""

TEMPLATE_FEMALE = """السلام عليكم ورحمة الله وبركاته ✨

أهلًا وسهلًا بحضرتِك {NAME}، تشرفنا بتواصلنا مع حضرتِك.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية ⚡

🔹 رابط الجريدة:
https://www.tahteldoo.com/

🔹 صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتِك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتِك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

🔹 رابط الخبر:
{POST_URL}

✨ مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

📌 برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

✅ موافقة على النشر
❌ عدم الموافقة على النشر
✏️ موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

⏰ برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتِك.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق 🌿"""

TEMPLATE_GROUP = """السلام عليكم ورحمة الله وبركاته ✨

أهلًا وسهلًا بحضراتكم في {NAME}، تشرفنا بتواصلنا مع حضراتكم.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية ⚡

🔹 رابط الجريدة:
https://www.tahteldoo.com/

🔹 صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن {NAME} تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضراتكم لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

🔹 رابط الخبر:
{POST_URL}

✨ مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

📌 برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

✅ موافقة على النشر
❌ عدم الموافقة على النشر
✏️ موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

⏰ برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتكم.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق 🌿"""

DEFAULT_TEMPLATE = TEMPLATE_MALE


# =============================================================
# TITLE & GENDER DETECTION
# =============================================================

# Ordered list: (pattern_to_match, exact_title_to_use, entity_type)
# Pattern matched case-insensitively against the raw name string.
# 'exact_title' is used verbatim in the article by the AI.
_TITLE_RULES = [
    # ── Group / Entity (must come first) ───────────────────────
    (r"أكاديمية|عيادة|عيادات|مستشفى|مستشفيات|شركة|مؤسسة|مركز|فريق|منصة"
     r"|مجموعة|معمل|براند|ستوديو|مكتب|دكاترة|أطباء|مستشارون|جمعية"
     r"|مبادرة|وكالة|صيدلية|صيدليات|قرية|منتجع|فندق|مطعم|كافيه|سلسلة"
     r"|محلات|معرض|معارض"
     r"|academy|clinic|center|group|team|lab|hospital|agency|brand"
     r"|studio|office|store|marketing|storyworks",
     None, "group"),

    # ── Female titles ───────────────────────────────────────────
    (r"دكتورة|د\.\s*(?=[أ-ي].*ة\b)",  "دكتورة",  "female"),
    (r"أستاذة",                         "أستاذة",  "female"),
    (r"مهندسة",                         "مهندسة",  "female"),
    (r"محامية|المحامية",                 "المحامية", "female"),
    (r"صيدلانية|الصيدلانية",            "الصيدلانية", "female"),
    (r"معالجة|المعالجة",                "المعالجة", "female"),
    (r"مدربة|المدربة",                  "المدربة",  "female"),
    (r"مديرة|المديرة",                  "المديرة",  "female"),
    (r"مس\b|ميس\b|miss\b|ms\b|mrs\b",  "Ms.",      "female"),

    # ── Male titles ─────────────────────────────────────────────
    (r"دكتور\b|د\.\s*(?=[أ-ي])",       "دكتور",   "male"),
    (r"أستاذ\b",                        "أستاذ",   "male"),
    (r"مهندس\b",                        "مهندس",   "male"),
    (r"محامي\b|المحامي\b",              "المحامي", "male"),
    (r"صيدلاني\b|الصيدلاني\b",          "الصيدلاني", "male"),
    (r"معالج\b|المعالج\b",              "المعالج", "male"),
    (r"مدرب\b|المدرب\b",               "المدرب",  "male"),
    (r"مدير\b|المدير\b",               "المدير",  "male"),
    (r"رئيس\b",                        "رئيس",    "male"),
    (r"مستر\b|mr\b\.",                 "مستر",    "male"),
    (r"كابتن\b",                       "كابتن",   "male"),
    (r"شيف\b|chef\b",                  "شيف",     "male"),
]

# Common female first names for fallback detection
_FEMALE_NAMES = {
    "نورهان", "سارة", "ساره", "هبة", "هبه", "مريم", "فاطمة", "فاطمه",
    "رانيا", "شيماء", "آية", "اية", "ياسمين", "منى", "منه", "منة",
    "دعاء", "دينا", "أسماء", "اسماء", "هالة", "هاله", "ندى", "شروق",
    "أميرة", "اميرة", "مروة", "مروه", "إيمان", "ايمان", "نهى", "سهام",
    "رحاب", "عبير", "وفاء", "صفاء", "سحر", "سمر", "روان", "شهد",
    "خلود", "إلهام", "الهام", "نجلاء", "رضوى", "ريهام", "نادية", "ناديه",
    "بسمة", "بسمه", "مي", "مى", "علا", "رانين", "يارا", "سلمى",
    "جنى", "جنة", "جنه", "غادة", "غاده", "إسراء", "اسراء", "شيرين",
    "شرين", "لمياء", "حنان", "زينب", "سعاد", "سناء", "لبنى", "وداد",
    "أمل", "امل", "إيناس", "نسرين", "رنا", "لين", "لارا", "نيرمين",
}


def detect_title_and_gender(text: str) -> dict:
    """
    Analyses the name / raw notes and returns a dict:

        {
            "title":       str | None,   # exact title as found ("مستر", "دكتور", ...)
            "entity_type": str,          # "male" | "female" | "group"
        }

    Priority: group keywords → explicit title keywords → female name list → male (default).
    The 'title' is preserved exactly as supplied by the user.
    """
    if not text:
        return {"title": None, "entity_type": "male"}

    s = text.strip()
    s_lower = s.lower()

    for pattern, title_label, etype in _TITLE_RULES:
        if re.search(pattern, s_lower, re.IGNORECASE):
            if etype == "group":
                return {"title": None, "entity_type": "group"}
            # Try to grab the exact title token from the original string
            m = re.search(pattern, s, re.IGNORECASE)
            exact = m.group(0).strip() if m else title_label
            return {"title": exact, "entity_type": etype}

    # Fallback: scan for female first names
    words = set(re.findall(r'[\u0600-\u06FF]+', s))
    if words & _FEMALE_NAMES:
        return {"title": None, "entity_type": "female"}

    return {"title": None, "entity_type": "male"}


def detect_entity_type(name: str) -> str:
    """Convenience wrapper — returns entity_type string only."""
    return detect_title_and_gender(name)["entity_type"]


# =============================================================
# WHATSAPP SERVICE
# =============================================================

class WhatsAppService:
    """Service to handle WhatsApp notifications via WP Sender API or direct wa.me links."""

    @staticmethod
    def detect_entity_type(name: str) -> str:
        return detect_entity_type(name)

    @staticmethod
    def detect_title_and_gender(text: str) -> dict:
        return detect_title_and_gender(text)

    def __init__(self, api_url: str = None, token: str = None,
                 session_id: str = None, template: str = None):
        self.api_url    = api_url    or Config.WHATSAPP_API_URL
        self.token      = token      or Config.WHATSAPP_TOKEN
        self.session_id = session_id or Config.WHATSAPP_SESSION_ID
        self.template   = template   or DEFAULT_TEMPLATE

    def format_message(self, name: str, post_url: str,
                       custom_template: str = None, entity_type: str = None,
                       editor_name: str = None, editor_role: str = None) -> str:
        """Select the correct template based on entity_type and fill placeholders."""
        if custom_template:
            tmpl = custom_template
        else:
            etype = entity_type or detect_entity_type(name)
            if etype == "female":
                tmpl = TEMPLATE_FEMALE
            elif etype in ("group", "plural"):
                tmpl = TEMPLATE_GROUP
            else:
                tmpl = TEMPLATE_MALE

        eff_editor_name = editor_name or getattr(Config, "EDITOR_NAME", "محمد شلبي") or "محمد شلبي"
        eff_editor_role = editor_role or getattr(Config, "EDITOR_ROLE", "صحفي لدى") or "صحفي لدى"

        return (
            tmpl
            .replace("{NAME}", name)
            .replace("{POST_URL}", post_url)
            .replace("{EDITOR_NAME}", eff_editor_name)
            .replace("{EDITOR_ROLE}", eff_editor_role)
        )

    def format_phone_number(self, phone: str) -> str:
        """Normalise to WP Sender format (e.g. 201012345678)."""
        clean = "".join(filter(str.isdigit, str(phone)))
        if clean.startswith("0"):
            clean = "20" + clean[1:]
        elif not clean.startswith("20") and len(clean) == 10:
            clean = "20" + clean
        return clean

    def generate_whatsapp_click_link(self, phone: str, name: str,
                                     post_url: str, entity_type: str = None,
                                     editor_name: str = None, editor_role: str = None,
                                     shorten: bool = False) -> str:
        formatted_phone = self.format_phone_number(phone)
        message_body    = self.format_message(name, post_url, entity_type=entity_type, editor_name=editor_name, editor_role=editor_role)
        encoded_msg     = urllib.parse.quote(message_body, safe='')
        return f"https://wa.me/{formatted_phone}?text={encoded_msg}"

    def get_headers(self, token: str = None) -> dict:
        t = token or Config.WHATSAPP_TOKEN or self.token
        return {
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":        "application/json, text/plain, */*",
            "Content-Type":  "application/json; charset=utf-8",
            "X-API-Key":     t,
            "Authorization": f"Bearer {t}",
        }

    def fetch_sessions(self) -> list:
        url = "https://backendapi.wpsenderx.com/api/whatsapp-session/list"
        try:
            res  = requests.get(url, headers=self.get_headers(), timeout=15)
            data = res.json().get("data", []) if res.status_code == 200 else []
            logger.info(f"تم جلب {len(data)} جلسة واتساب.")
            return data
        except Exception as e:
            logger.error(f"خطأ جلب جلسات الواتساب: {e}")
            return []

    def check_session_status(self, session_id: str) -> str:
        url = f"https://backendapi.wpsenderx.com/api/whatsapp-session/{session_id}/status"
        try:
            res = requests.get(url, headers=self.get_headers(), timeout=15)
            if res.status_code == 200:
                return res.json().get("data", {}).get("status", "unknown")
            return f"HTTP {res.status_code}"
        except Exception as e:
            logger.error(f"خطأ فحص حالة الجلسة {session_id}: {e}")
            return str(e)

    def send_message(self, article_id: int, phone: str, name: str,
                     post_url: str, delay_seconds: int = 0,
                     image_url: str = None, entity_type: str = None) -> bool:

        token      = Config.WHATSAPP_TOKEN      or self.token
        session_id = Config.WHATSAPP_SESSION_ID or self.session_id
        raw_url    = Config.WHATSAPP_API_URL    or ""

        target_url = (
            raw_url
            if ("backendapi.wpsenderx.com" in raw_url or raw_url.endswith("/messages/send"))
            else "https://backendapi.wpsenderx.com/api/messages/send"
        )

        formatted_phone = self.format_phone_number(phone)
        message_body    = self.format_message(name, post_url, entity_type=entity_type)

        delay = delay_seconds or Config.WHATSAPP_DELAY_SECONDS
        if delay > 0:
            logger.info(f"انتظار {delay} ثانية قبل إرسال الواتساب...")
            time.sleep(delay)

        etype = entity_type or detect_entity_type(name)
        logger.info(
            f"إرسال واتساب [{etype}] لـ: {name} ({formatted_phone}) | "
            f"Endpoint: {target_url} | Session: {session_id}"
        )

        headers = self.get_headers(token)
        payload = {
            "recipients":    formatted_phone,
            "message":       message_body,
            "contentType":   "MessageMediaFromURL" if image_url else "string",
            "sessionId":     session_id,
            "session_id":    session_id,
            "no_duplication": False,
        }
        if image_url:
            payload["content"] = image_url

        try:
            res = requests.post(target_url, json=payload, headers=headers, timeout=25)
            logger.info(f"WP Sender [{res.status_code}]: {res.text[:200]}")

            if res.status_code in (200, 201, 202):
                res_json   = {}
                try:    res_json = res.json()
                except Exception: pass

                status_val = res_json.get("status", "")
                if status_val in ("success", "queued", "ok") or res.status_code == 200:
                    db.log_whatsapp(
                        article_id=article_id, recipient_phone=formatted_phone,
                        recipient_name=name, message_body=message_body,
                        status="SENT", delay_seconds=delay,
                    )
                    logger.info(f"✅ واتساب أُرسل بنجاح لـ {name} [{etype}]")
                    return True

            err = f"HTTP {res.status_code}: {res.text[:300]}"
            logger.error(f"فشل الواتساب لـ {name}: {err}")
            db.log_whatsapp(
                article_id=article_id, recipient_phone=formatted_phone,
                recipient_name=name, message_body=message_body,
                status="FAILED", error_message=err, delay_seconds=delay,
            )
            return False

        except Exception as e:
            err = str(e)
            logger.error(f"استثناء WP Sender: {err}")
            db.log_whatsapp(
                article_id=article_id, recipient_phone=formatted_phone,
                recipient_name=name, message_body=message_body,
                status="FAILED", error_message=err, delay_seconds=delay,
            )
            return False


whatsapp_service = WhatsAppService()
