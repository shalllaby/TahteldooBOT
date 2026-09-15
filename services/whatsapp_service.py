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

TEMPLATE_MALE = """السلام عليكم ورحمة الله وبركاته

أهلًا وسهلًا بحضرتك {NAME}، تشرفنا بتواصلنا مع حضرتك.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية

- رابط الجريدة:
https://www.tahteldoo.com/

- صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

- رابط الخبر:
{POST_URL}

مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

- موافقة على النشر
- عدم الموافقة على النشر
- موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتك.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق."""

TEMPLATE_FEMALE = """السلام عليكم ورحمة الله وبركاته

أهلًا وسهلًا بحضرتِك {NAME}، تشرفنا بتواصلنا مع حضرتِك.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية

- رابط الجريدة:
https://www.tahteldoo.com/

- صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتِك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتِك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

- رابط الخبر:
{POST_URL}

مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

- موافقة على النشر
- عدم الموافقة على النشر
- موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتِك.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق."""

TEMPLATE_GROUP = """السلام عليكم ورحمة الله وبركاته

أهلًا وسهلًا بحضراتكم في {NAME}، تشرفنا بتواصلنا مع حضراتكم.

أنا {EDITOR_NAME}، {EDITOR_ROLE} جريدة تحت الضوء الإخبارية

- رابط الجريدة:
https://www.tahteldoo.com/

- صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن {NAME} تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضراتكم لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

- رابط الخبر:
{POST_URL}

مميزات الخبر الصحفي:
• ظهور اسمك / خدمتك على محركات بحث جوجل.
• تعزيز الحضور الإعلامي والرقمي.
• تقديم الخبرات والتخصصات المهنية بصورة احترافية أمام الجمهور والعملاء.
• المساهمة في زيادة الثقة والمصداقية لدى المتابعين والمهتمين.
• إبراز الخبرات والإنجازات بصورة صحفية جذابة ومنظمة.
• دعم الحضور الرقمي والوصول إلى جمهور أكبر.
• إمكانية استخدام رابط الخبر في الدعاية ومشاركته مع الجمهور والمتابعين.
• منح حضور إعلامي قوي يساعد في بناء صورة مهنية واحترافية.

برجاء التكرم بمراجعة الخبر والتأكد من صحة جميع البيانات والمعلومات الواردة به، ثم الرد بأحد الخيارات التالية:

- موافقة على النشر
- عدم الموافقة على النشر
- موافقة بعد التعديل مع توضيح التعديلات المطلوبة.

برجاء الرد خلال 12 ساعة من استلام الرسالة.

لن يتم اعتماد ونشر الخبر إلا بعد استلام موافقتكم.

مع خالص تمنياتنا لـ {NAME} بمزيد من النجاح والتوفيق."""

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


def normalize_arabic_digits(text: str) -> str:
    """Converts Eastern Arabic/Persian digits to standard Western ASCII digits."""
    if not text:
        return ""
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶٧٨٩"
    translation_table = str.maketrans(
        {**{arabic_digits[i]: str(i) for i in range(10)},
         **{persian_digits[i]: str(i) for i in range(10)}}
    )
    return text.translate(translation_table)


WA_KEYWORD_PATTERN = re.compile(
    r'(?:'
    r'واتس[\s_\-]*اب'
    r'|الواتس[\s_\-]*اب'
    r'|الواتساب'
    r'|واتساب'
    r'|الواتس'
    r'|واتس'
    r'|وتساب'
    r'|وتس'
    r'|whats[\s_\-]*app'
    r'|whatsapp'
    r'|wats[\s_\-]*app'
    r'|watsapp'
    r'|wapp'
    r'|wa\.me'
    r'|\bwa\b'
    r')',
    re.IGNORECASE
)

NEGATION_PATTERN = re.compile(
    r'(?:ليس|لا\s*يوجد|مش|غير\s*متاح|بدون|اتصال\s*فقط|فون\s*فقط)[\s:]*$',
    re.IGNORECASE
)

BETWEEN_SEPARATORS_PATTERN = re.compile(
    r'(\n+|[-—–|/\\،,;؛]|\b(?:أو|او|و|or|and)\b)',
    re.IGNORECASE
)


def evaluate_digit_string(d_str: str) -> str:
    """
    Evaluates a raw digit string to find a valid Egyptian mobile number (2010, 2011, 2012, 2015).
    Handles reversed/flipped RTL strings, prefixes (+20, 0020, 01, etc.), and trailing country codes.
    """
    if not d_str:
        return ""
    valid_prefixes = {'', '0', '00', '20', '0020', '2020', '020', '200', '0200', '2001', '02001'}
    valid_suffixes = {'', '20', '0', '200'}

    # 1. Forward check for core subscriber sequence: 10 digits starting with 10, 11, 12, or 15
    for m in re.finditer(r'1[0125]\d{8}', d_str):
        core = m.group(0)
        prefix = d_str[:m.start()]
        suffix = d_str[m.end():]
        is_valid_prefix = (
            prefix in valid_prefixes
            or not prefix.strip('02')
            or (prefix.endswith(('0', '20')) and len(prefix) <= 3)
        )
        is_valid_suffix = (
            suffix in valid_suffixes
            or not suffix.strip('02')
        )
        if is_valid_prefix and is_valid_suffix:
            return '20' + core

    # 2. Reversed check (for flipped RTL numbers)
    d_reversed = d_str[::-1]
    for m_rev in re.finditer(r'1[0125]\d{8}', d_reversed):
        core = m_rev.group(0)
        prefix = d_reversed[:m_rev.start()]
        suffix = d_reversed[m_rev.end():]
        is_valid_prefix = (
            prefix in valid_prefixes
            or not prefix.strip('02')
            or (prefix.endswith(('0', '20')) and len(prefix) <= 3)
        )
        is_valid_suffix = (
            suffix in valid_suffixes
            or not suffix.strip('02')
        )
        if is_valid_prefix and is_valid_suffix:
            return '20' + core

    return ""


def extract_preferred_whatsapp_phone(text: str) -> str:
    """
    Extracts the preferred WhatsApp phone number from input text according to editorial rules:
    1. If multiple phone numbers exist:
       - Select the number explicitly associated with WhatsApp (e.g. 'واتساب', 'واتس', 'WhatsApp', 'wa.me', etc.).
       - If multiple numbers exist but NONE has a WhatsApp indicator, select the FIRST phone number in the message.
    2. Normalize to standard 12-digit Egyptian format '201xxxxxxxxx'.
    """
    if not text:
        return ""

    normalized_text = normalize_arabic_digits(str(text))
    normalized_text = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', normalized_text)

    # Candidate blocks: use horizontal whitespace [ \t] so numbers on different lines are not merged
    candidate_matches = list(re.finditer(r'(?:\+?\d[\d \t\-\.\/\(\)]{7,}\d)', normalized_text))
    
    valid_candidates = []
    for m in candidate_matches:
        cand_str = m.group(0)
        # Strip leading bullet numbering like '1- ' or '1. ' before local mobile number
        cand_str = re.sub(r'^\d+[\s\.\-:\)\/]+(?=0?1[0125])', '', cand_str)
        digits_only = re.sub(r'\D', '', cand_str)
        clean_num = evaluate_digit_string(digits_only)
        if clean_num:
            valid_candidates.append({
                'number': clean_num,
                'start': m.start(),
                'end': m.end(),
                'raw': cand_str
            })

    if not valid_candidates:
        all_digits = re.sub(r'\D', '', normalized_text)
        return evaluate_digit_string(all_digits)

    if len(valid_candidates) == 1:
        return valid_candidates[0]['number']

    # For each candidate, determine its dedicated prefix and suffix context boundaries
    prefix_texts = []
    suffix_texts = []

    for i, cand in enumerate(valid_candidates):
        # 1. Determine prefix context
        if i == 0:
            p_start = max(0, cand['start'] - 80)
            prefix_chunk = normalized_text[p_start:cand['start']]
            if '\n' in prefix_chunk:
                prefix_chunk = prefix_chunk.split('\n')[-1]
            prefix_texts.append(prefix_chunk)
        else:
            prev_cand = valid_candidates[i - 1]
            between = normalized_text[prev_cand['end']:cand['start']]
            
            if '\n' in between:
                prefix_chunk = between.split('\n')[-1]
            else:
                sep_matches = list(BETWEEN_SEPARATORS_PATTERN.finditer(between))
                if sep_matches:
                    last_sep = sep_matches[-1]
                    prefix_chunk = between[last_sep.end():]
                else:
                    wa_m = WA_KEYWORD_PATTERN.search(between)
                    if wa_m:
                        prefix_chunk = between[wa_m.start():]
                    else:
                        mid = len(between) // 2
                        prefix_chunk = between[mid:]
            prefix_texts.append(prefix_chunk)

        # 2. Determine suffix context
        if i == len(valid_candidates) - 1:
            s_end = min(len(normalized_text), cand['end'] + 80)
            suffix_chunk = normalized_text[cand['end']:s_end]
            if '\n' in suffix_chunk:
                suffix_chunk = suffix_chunk.split('\n')[0]
            suffix_texts.append(suffix_chunk)
        else:
            next_cand = valid_candidates[i + 1]
            between = normalized_text[cand['end']:next_cand['start']]
            if '\n' in between:
                suffix_chunk = between.split('\n')[0]
            else:
                sep_matches = list(BETWEEN_SEPARATORS_PATTERN.finditer(between))
                if sep_matches:
                    first_sep = sep_matches[0]
                    suffix_chunk = between[:first_sep.start()]
                else:
                    wa_m = WA_KEYWORD_PATTERN.search(between)
                    if wa_m:
                        suffix_chunk = between[:wa_m.start()]
                    else:
                        mid = len(between) // 2
                        suffix_chunk = between[:mid]
            suffix_texts.append(suffix_chunk)

    # Score candidates based on WhatsApp markers in their context
    scored_candidates = []
    for i, cand in enumerate(valid_candidates):
        p_text = prefix_texts[i]
        s_text = suffix_texts[i]

        has_wa = False
        min_dist = 9999

        for wa_m in WA_KEYWORD_PATTERN.finditer(p_text):
            before_wa = p_text[:wa_m.start()].strip()
            if not NEGATION_PATTERN.search(before_wa):
                has_wa = True
                dist = len(p_text) - wa_m.end()
                if dist < min_dist:
                    min_dist = dist

        for wa_m in WA_KEYWORD_PATTERN.finditer(s_text):
            has_wa = True
            dist = wa_m.start()
            if dist < min_dist:
                min_dist = dist

        scored_candidates.append((cand, has_wa, min_dist, i))

    wa_candidates = [sc for sc in scored_candidates if sc[1]]
    if wa_candidates:
        wa_candidates.sort(key=lambda x: (x[2], x[3]))
        return wa_candidates[0][0]['number']

    # Priority 2: If NO WhatsApp marker found, pick the FIRST phone number in the message
    return valid_candidates[0]['number']


def clean_egyptian_phone(text: str) -> str:
    """
    Extracts and normalizes an Egyptian mobile phone number from raw text input.
    Fixes Eastern Arabic digits, prefixes, formatting noise, reversed RTL numbers, etc.
    If multiple numbers exist:
    - Prioritizes the number explicitly marked as WhatsApp.
    - If no WhatsApp mark exists, picks the first number in the message.
    Returns standard 12-digit format starting with 2010, 2011, 2012, or 2015 (e.g. '201044103160').
    Returns '' if no valid Egyptian number found.
    """
    return extract_preferred_whatsapp_phone(text)


def extract_all_egyptian_phones(text: str) -> list:
    """
    Extracts and normalizes ALL distinct valid Egyptian mobile phone numbers from raw text.
    Returns a list of unique standard 12-digit strings ('201xxxxxxxxx')
    preserving their order of appearance in the text.
    """
    if not text:
        return []

    normalized_text = normalize_arabic_digits(str(text))
    normalized_text = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', normalized_text)

    # Candidate blocks: use horizontal whitespace [ \t] so numbers on different lines are not merged
    candidate_matches = list(re.finditer(r'(?:\+?\d[\d \t\-\.\/\(\)]{7,}\d)', normalized_text))

    found_numbers = []
    seen = set()
    for m in candidate_matches:
        cand_str = m.group(0)
        cand_str = re.sub(r'^\d+[\s\.\-:\)\/]+(?=0?1[0125])', '', cand_str)
        digits_only = re.sub(r'\D', '', cand_str)
        clean_num = evaluate_digit_string(digits_only)
        if clean_num and clean_num not in seen:
            seen.add(clean_num)
            found_numbers.append(clean_num)

    if not found_numbers:
        all_digits = re.sub(r'\D', '', normalized_text)
        single = evaluate_digit_string(all_digits)
        if single and single not in seen:
            found_numbers.append(single)

    return found_numbers


def remove_emojis(text: str) -> str:
    """Removes emoji symbols and pictorial characters from text."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002300-\U000023FF"  # Technical symbols (alarm clock, timer etc.)
        "\U00002600-\U000027BF"  # Miscellaneous Symbols & Dingbats
        "\U00002B00-\U00002BFF"  # Misc Symbols and Arrows
        "\U000024C2-\U0001F251"  # Enclosed Characters
        "\U0000200D"            # ZWJ
        "\U0000FE0F"            # Variation Selector
        "]+",
        flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub("", text)
    # Clean trailing/leading spaces on lines left after emoji removal
    lines = [re.sub(r'^[ \t]+|[ \t]+$', '', line) for line in cleaned.splitlines()]
    return "\n".join(lines)


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

    @staticmethod
    def clean_phone(phone: str) -> str:
        return clean_egyptian_phone(phone)

    def __init__(self, api_url: str = None, token: str = None,
                 session_id: str = None, template: str = None):
        self.api_url    = api_url    or Config.WHATSAPP_API_URL
        self.token      = token      or Config.WHATSAPP_TOKEN
        self.session_id = session_id or Config.WHATSAPP_SESSION_ID
        self.template   = template   or DEFAULT_TEMPLATE

    def format_message(self, name: str, post_url: str,
                       custom_template: str = None, entity_type: str = None,
                       editor_name: str = None, editor_role: str = None,
                       remove_emojis_flag: bool = None) -> str:
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

        msg = (
            tmpl
            .replace("{NAME}", name)
            .replace("{POST_URL}", post_url)
            .replace("{EDITOR_NAME}", eff_editor_name)
            .replace("{EDITOR_ROLE}", eff_editor_role)
        )

        should_remove = remove_emojis_flag if remove_emojis_flag is not None else getattr(Config, "REMOVE_WHATSAPP_EMOJIS", True)
        if should_remove:
            msg = remove_emojis(msg)

        return msg

    def format_phone_number(self, phone: str) -> str:
        """Normalise to standard Egyptian 12-digit format (e.g. 201044103160)."""
        cleaned = clean_egyptian_phone(phone)
        if cleaned:
            return cleaned
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

    def generate_whatsapp_clean_link(self, phone: str) -> str:
        """Generates a clean wa.me link directly to the chat without any ?text= payload, protecting the account from automation flags."""
        formatted_phone = self.format_phone_number(phone)
        return f"https://wa.me/{formatted_phone}"

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
