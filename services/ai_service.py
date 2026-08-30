import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Any, Callable, Optional, Tuple

from groq import Groq
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from core.config import Config
from core.logger import logger


class AIService:
    """
    AI service for generating professional Arabic journalistic articles
    for "جريدة تحت الضوء الإخبارية".
    """

    NEWSPAPER_NAME = "جريدة تحت الضوء الإخبارية"

    # ==========================================================
    # ARTICLE LENGTH
    # ==========================================================

    MIN_ARTICLE_CHARS = 1200
    MAX_ARTICLE_CHARS = 6000

    # ==========================================================
    # ALLOWED EDITORIAL CATEGORIES / LABELS (STRICT LIST OF 7)
    # ==========================================================

    ALLOWED_LABELS = [
        "تعليم",
        "صحة",
        "شخصيات عامة",
        "تطوير ذات",
        "التغذية العلاجية",
        "أعمال",
        "خدمات"
    ]

    # ==========================================================
    # EXAMPLES & FALLBACK CONFIG
    # ==========================================================

    EXAMPLES_FILENAME = "article_examples.json"

    FALLBACK_MODELS = [
        "glm-4.7-flash",
        "GLM-4.7-Flash",
        "glm-4-flash",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "openai/gpt-oss-120b",
        "gemini-3.6-flash",
        "openai/gpt-oss-20b"
    ]

    @staticmethod
    def optimize_input_text(text: str, max_chars: int = 3000) -> str:
        """
        Compresses and cleans input notes to conserve prompt tokens.
        """
        if not text:
            return ""
        cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        if len(cleaned) > max_chars:
            logger.info(f"ضغط النص المدخل من {len(cleaned)} إلى {max_chars} حرف لتوفير التوكينات.")
            cleaned = cleaned[:max_chars] + "\n...[تم اختصار بقية النص لترشيد التوكينات]"
        return cleaned

    def __init__(
        self,
        api_key: str = None,
        model: str = None
    ):
        self.api_key = (
            api_key
            or Config.GROQ_API_KEY
        )

        self.model = (
            model
            or getattr(Config, "ZAI_MODEL", "")
            or Config.GROQ_MODEL
        )

        self.client = (
            Groq(api_key=self.api_key)
            if self.api_key
            else None
        )

        self.groq_api_key_2 = getattr(Config, "GROQ_API_KEY_2", "")
        self.groq_client_2 = None
        if Groq and self.groq_api_key_2:
            try:
                self.groq_client_2 = Groq(api_key=self.groq_api_key_2)
                logger.info("تم تفعيل مفتاح Groq الاحتياطي الثاني (GROQ_API_KEY_2) بنجاح.")
            except Exception as g2_err:
                logger.warning(f"تعذر تهيئة مفتاح Groq الثاني: {g2_err}")

        # Z.AI / GLM Integration (Primary - Multi-Key Rotation)
        self.zai_base_url = getattr(Config, "ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        self.zai_model = getattr(Config, "ZAI_MODEL", "glm-4.7-flash")
        
        self.zai_keys = [
            getattr(Config, "ZAI_API_KEY", ""),
            getattr(Config, "ZAI_API_KEY_2", ""),
            getattr(Config, "ZAI_API_KEY_3", "")
        ]
        self.zai_clients = []
        if OpenAI:
            for idx, k in enumerate(self.zai_keys, 1):
                if k.strip():
                    try:
                        c = OpenAI(api_key=k.strip(), base_url=self.zai_base_url)
                        self.zai_clients.append(c)
                        logger.info(f"تم تفعيل مفتاح Z.AI (GLM) رقم {idx} بنجاح.")
                    except Exception as zai_err:
                        logger.warning(f"تعذر تهيئة مفتاح Z.AI رقم {idx}: {zai_err}")
        
        self.zai_client = self.zai_clients[0] if self.zai_clients else None

        # Google Gemini AI Integration
        self.gemini_api_key = Config.GEMINI_API_KEY
        self.gemini_base_url = Config.GEMINI_BASE_URL
        self.gemini_model = Config.GEMINI_MODEL
        self.gemini_client = None

        if OpenAI and self.gemini_api_key:
            try:
                self.gemini_client = OpenAI(
                    api_key=self.gemini_api_key,
                    base_url=self.gemini_base_url
                )
                logger.info(f"تم تفعيل Google Gemini AI Provider بنجاح بالنموذج: {self.gemini_model}")
            except Exception as gem_err:
                logger.warning(f"تعذر تهيئة Google Gemini AI Provider: {gem_err}")

        # ZenMux / OpenAI API Integration
        self.zenmux_api_key = Config.ZENMUX_API_KEY
        self.zenmux_base_url = Config.ZENMUX_BASE_URL
        self.zenmux_model = Config.ZENMUX_MODEL
        self.zenmux_client = None

        if OpenAI and self.zenmux_api_key:
            try:
                self.zenmux_client = OpenAI(
                    api_key=self.zenmux_api_key,
                    base_url=self.zenmux_base_url
                )
                logger.info(f"تم تفعيل ZenMux AI Provider بنجاح بالنموذج: {self.zenmux_model}")
            except Exception as zm_err:
                logger.warning(f"تعذر تهيئة ZenMux AI Provider: {zm_err}")

        # OpenRouter AI Integration
        self.openrouter_api_key = Config.OPENROUTER_API_KEY
        self.openrouter_base_url = Config.OPENROUTER_BASE_URL
        self.openrouter_model = Config.OPENROUTER_MODEL
        self.openrouter_client = None

        if OpenAI and self.openrouter_api_key:
            try:
                self.openrouter_client = OpenAI(
                    api_key=self.openrouter_api_key,
                    base_url=self.openrouter_base_url
                )
                logger.info(f"تم تفعيل OpenRouter AI Provider بنجاح بالنموذج: {self.openrouter_model}")
            except Exception as or_err:
                logger.warning(f"تعذر تهيئة OpenRouter AI Provider: {or_err}")

        # Thread pool for asynchronous / parallel execution
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Cache for editorial reference string
        self._cached_editorial_reference: Optional[str] = None

        # ------------------------------------------------------
        # Load editorial examples
        # ------------------------------------------------------

        self.editorial_examples = (
            self.load_editorial_examples()
        )

    # ==========================================================
    # PROVIDER ROUTING & ROBUST API EXECUTION
    # ==========================================================

    def get_provider_for_model(self, model_name: str) -> str:
        """Determines whether to route to Z.AI, Gemini, OpenRouter, ZenMux, or Groq based on model name."""
        if not model_name:
            return "zai" if self.zai_client else "groq"
        model_str = str(model_name).lower()
        if "glm" in model_str or "z.ai" in model_str or "zhipu" in model_str:
            if self.zai_client:
                return "zai"
        if ":free" in model_str or "meta-llama/" in model_str or "google/" in model_str or "openrouter" in model_str:
            if self.openrouter_client:
                return "openrouter"
        if "gemini" in model_str:
            if self.gemini_client:
                return "gemini"
        if "deepseek/" in model_str or "openai/gpt-4" in model_str:
            if self.zenmux_client:
                return "zenmux"
        return "groq"

    def _create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model_candidates: List[Tuple[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3500
    ) -> Tuple[Any, str, str]:
        """
        Executes a chat completion request with intelligent multi-provider, multi-model fallback,
        smart rate limit handling (sleep or instant model switch), and JSON validation error recovery.
        """
        last_exception = None

        for provider, target_model in model_candidates:
            if provider == "zai":
                clients_for_provider = [c for c in self.zai_clients if c]
            elif provider == "gemini":
                clients_for_provider = [c for c in [self.gemini_client] if c]
            elif provider == "openrouter":
                clients_for_provider = [c for c in [self.openrouter_client] if c]
            elif provider == "zenmux":
                clients_for_provider = [c for c in [self.zenmux_client] if c]
            else:
                clients_for_provider = [c for c in [self.client, self.groq_client_2] if c]

            if not clients_for_provider:
                continue

            use_response_format = (provider in ["groq", "gemini", "zai"])
            attempts = [True, False] if use_response_format else [False]

            for client_to_use in clients_for_provider:
                client_success = False
                for json_attempt in attempts:
                    try:
                        actual_tokens = 6000 if provider in ["gemini", "zai", "openrouter"] else (4000 if provider == "groq" else max_tokens)
                        logger.info(
                            f"إرسال طلب توليد ({provider}) باستخدام النموذج: {target_model} (التوكينات: {actual_tokens})..."
                        )

                        req_kwargs = {
                            "messages": messages,
                            "model": target_model,
                            "temperature": temperature,
                            "max_tokens": actual_tokens
                        }

                        if json_attempt:
                            req_kwargs["response_format"] = {"type": "json_object"}

                        response = client_to_use.chat.completions.create(**req_kwargs)

                        msg_content = ""
                        if response and hasattr(response, "choices") and response.choices:
                            m = response.choices[0].message
                            msg_content = (getattr(m, "content", "") or getattr(m, "reasoning_content", "") or "").strip()

                        if not msg_content and json_attempt:
                            logger.warning(f"النموذج {target_model} أعاد استجابة فارغة مع response_format. إعادة المحاولة بدون response_format...")
                            continue

                        if hasattr(response, "usage") and response.usage:
                            logger.info(
                                f"استهلاك التوكينات [{target_model}]: Prompt={response.usage.prompt_tokens}, "
                                f"Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens}"
                            )

                        return response, provider, target_model

                    except Exception as exc:
                        last_exception = exc
                        exc_str = str(exc).lower()

                        # Case 1: Rate Limit (429 / TPM / Token Limit)
                        if "rate_limit" in exc_str or "413" in exc_str or "tokens per minute" in exc_str or "429" in exc_str or "resource_exhausted" in exc_str:
                            wait_match = re.search(r"try again in ([\d\.]+)s", exc_str)
                            wait_time = float(wait_match.group(1)) if wait_match else 2.0

                            if 0 < wait_time <= 6.0 and len(clients_for_provider) == 1:
                                logger.warning(
                                    f"تجاوز حد التوكينات المؤقت للنموذج {target_model}. انتظار {wait_time:.1f} ثانية وإعادة المحاولة..."
                                )
                                time.sleep(wait_time + 0.5)
                                try:
                                    response = client_to_use.chat.completions.create(**req_kwargs)
                                    return response, provider, target_model
                                except Exception as retry_exc:
                                    last_exception = retry_exc
                                    logger.warning(f"محاولة الإعادة للنموذج {target_model} تعذرت. جاري الانتقال لمفتاح/نموذج آخر...")
                                    break
                            else:
                                logger.warning(
                                    f"تجاوز حد التوكينات (TPM Rate Limit) للنموذج {target_model}. التبديل الفوري للمفتاح/النموذج التالي لتجنب التوقف..."
                                )
                                break

                        # Case 2: Decommissioned Model / Unregistered Zhipu Model
                        elif "decommissioned" in exc_str or "no longer supported" in exc_str or "1211" in exc_str or "模型不存在" in exc_str:
                            logger.warning(f"النموذج {target_model} ملغى أو غير مفعل على حساب Z.AI/BigModel. جاري التجاوز للنموذج التالي...")
                            break

                        # Case 3: Credit / Account Balance (ZenMux 402 / reject_no_credit)
                        elif "reject_no_credit" in exc_str or "402" in exc_str or "credit" in exc_str:
                            logger.warning(f"المزود {provider} يتطلب رصيداً أكبر من $0. جاري الانتقال لمزود آخر...")
                            break

                        # Case 4: Specific JSON Validation Failed
                        elif ("json_validate_failed" in exc_str or "failed to validate json" in exc_str or "schema" in exc_str) and json_attempt:
                            logger.warning(
                                f"تعذر الالتزام بـ JSON Schema للنموذج {target_model}. إعادة المحاولة بدون response_format..."
                            )
                            continue

                        # Case 5: Other Errors
                        else:
                            logger.warning(
                                f"تعذر استخدام النموذج {target_model} عبر {provider} (السبب: {exc}). جاري التبديل لنموذج آخر..."
                            )
                            break

        raise ValueError(f"فشلت جميع المحاولات والنماذج الاحتياطية. الخطأ الأخير: {last_exception}")

    # ==========================================================
    # LOAD EDITORIAL JSON
    # ==========================================================

    @classmethod
    def load_editorial_examples(cls) -> dict:
        """
        Load article_examples.json from the same directory
        as this Python file.
        """

        examples_path = (
            Path(__file__).resolve().parent
            / cls.EXAMPLES_FILENAME
        )

        if not examples_path.exists():

            logger.warning(
                f"ملف المرجع التحريري غير موجود: "
                f"{examples_path}"
            )

            return {
                "articles": []
            }

        try:

            with open(
                examples_path,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

            if not isinstance(data, dict):

                logger.warning(
                    "article_examples.json "
                    "لا يحتوي على JSON Object."
                )

                return {
                    "articles": []
                }

            logger.info(
                f"تم تحميل المرجع التحريري بنجاح: "
                f"{examples_path}"
            )

            return data

        except Exception as e:

            logger.exception(
                f"فشل تحميل article_examples.json: {e}"
            )

            return {
                "articles": []
            }

    # ==========================================================
    # FORMAT EDITORIAL EXAMPLES (WITH CACHING FOR SPEED)
    # ==========================================================

    def build_editorial_reference(self) -> str:
        """
        Convert article_examples.json into a compact textual
        reference for the model. Caches the result in memory for speed.
        """

        if self._cached_editorial_reference is not None:
            return self._cached_editorial_reference

        articles = self.editorial_examples.get(
            "articles",
            []
        )

        if not isinstance(articles, list) or not articles:
            self._cached_editorial_reference = "No editorial examples available."
            return self._cached_editorial_reference

        reference_blocks = []

        for index, article in enumerate(
            articles,
            start=1
        ):

            if not isinstance(article, dict):
                continue

            title = str(article.get("title", "")).strip()
            lead = str(article.get("lead_paragraph", "")).strip()
            sections = article.get("sections", [])

            block = [
                f"REFERENCE ARTICLE {index}",
                f"TITLE: {title}",
                f"LEAD: {lead}"
            ]

            if isinstance(sections, list):

                for section in sections:

                    if not isinstance(section, dict):
                        continue

                    subheading = str(section.get("subheading", "")).strip()
                    paragraphs = section.get("paragraphs", [])

                    block.append(f"SUBHEADING: {subheading}")

                    if isinstance(paragraphs, list) and paragraphs:
                        first_p = str(paragraphs[0]).strip()
                        if first_p:
                            block.append(first_p)

            reference_blocks.append("\n".join(block))

        result = (
            "\n\n"
            + "\n\n==============================\n\n"
            .join(reference_blocks)
        )

        self._cached_editorial_reference = result
        return result

    # ==========================================================
    # ASYNCHRONOUS & MULTI-THREADED GENERATION
    # ==========================================================

    def generate_article_async(
        self,
        raw_notes_or_name: str,
        phone_or_raw: str = "",
        raw_notes: str = "",
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Future:
        """
        Executes article generation in a background thread without blocking the UI.
        Optionally takes a callback function executed upon completion.
        """
        def _task():
            res = self.generate_article(raw_notes_or_name, phone_or_raw, raw_notes)
            if callback:
                try:
                    callback(res)
                except Exception as cb_err:
                    logger.error(f"Error in generation callback: {cb_err}")
            return res

        return self._executor.submit(_task)

    def generate_articles_batch(
        self,
        items: List[Dict[str, str]],
        max_workers: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Generates multiple articles in parallel using multithreading for maximum throughput.
        
        `items` parameter format:
        [
            {"raw_notes_or_name": "...", "phone_or_raw": "...", "raw_notes": "..."},
            ...
        ]
        """
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self.generate_article,
                    item.get("raw_notes_or_name", ""),
                    item.get("phone_or_raw", ""),
                    item.get("raw_notes", "")
                )
                for item in items
            ]
            results = [f.result() for f in futures]
        return results

    # ==========================================================
    # LABEL NORMALIZATION HELPER
    # ==========================================================

    @classmethod
    def normalize_label(cls, raw_label: str, raw_notes: str = "") -> str:
        """
        Ensures the label is strictly one of the 7 ALLOWED_LABELS.
        If an unallowed label is provided, maps it to the closest allowed category
        based on label name and article content keywords.
        """
        if not raw_label:
            raw_label = ""

        clean = str(raw_label).strip()

        # Exact match check
        if clean in cls.ALLOWED_LABELS:
            return clean

        # Combine label and notes for keyword matching
        combined_text = f"{clean} {raw_notes}".lower()

        # Keyword mapping priority rules
        if any(k in combined_text for k in ["تغذي", "دايت", "سمنة", "نحافة", "وجبة", "طعام", "غذاء", "حمية", "تخسيس"]):
            return "التغذية العلاجية"

        health_keywords = ["طبية", "الطب", "طبيب", "أطباء", "علاج", "عياد", "مستشف", "دكتور", "صحة", "مرض", "جراح", "جلد", "تجميل", "أسنان", "روشتة", "صيدل"]
        if any(k in combined_text for k in health_keywords) or re.search(r"(?<!ت)طبي(?!\s*ق)", combined_text):
            return "صحة"

        if any(k in combined_text for k in ["تعليم", "تعلم", "درس", "دراسة", "مدرس", "جامعة", "جامعي", "كورس", "مدرسة", "طالب", "طلاب", "أكاديم", "مناهج"]):
            return "تعليم"

        if any(k in combined_text for k in ["شخصيات عامة", "شخصية عامة", "سيرة", "مسيرة", "قائد", "مؤسس", "فنان", "فنانة", "سفير", "دبلوماس"]):
            return "شخصيات عامة"

        if any(k in combined_text for k in ["تطوير ذات", "تطوير الذات", "مهار", "تدريب", "تحفيز", "نمو شخصي", "وعي", "تفكير", "كوتش"]):
            return "تطوير ذات"

        if any(k in combined_text for k in ["تجارة", "تجارية", "شركة", "شركات", "استثمار", "مال", "أعمال", "تسويق", "مشروع", "مشاريع", "صناع", "اقتصاد", "ريادة"]):
            return "أعمال"

        # Default fallback category
        return "خدمات"

    # ==========================================================
    # MAIN ARTICLE GENERATOR
    # ==========================================================

    def generate_article(
        self,
        raw_notes_or_name: str,
        phone_or_raw: str = "",
        raw_notes: str = ""
    ) -> dict:

        # ------------------------------------------------------
        # API KEY
        # ------------------------------------------------------

        if not self.api_key:

            raise ValueError(
                "مفتاح Groq API غير محدد. "
                "يرجى ضبط GROQ_API_KEY في ملف .env "
                "أو في إعدادات التطبيق."
            )

        if not self.client:

            self.client = Groq(
                api_key=self.api_key
            )

        # ======================================================
        # BACKWARD COMPATIBILITY
        # ======================================================

        if raw_notes:

            actual_raw_notes = raw_notes
            actual_name = raw_notes_or_name
            actual_phone = phone_or_raw

        elif (
            phone_or_raw
            and len(phone_or_raw) > 30
        ):

            actual_raw_notes = phone_or_raw
            actual_name = raw_notes_or_name
            actual_phone = ""

        else:

            actual_raw_notes = raw_notes_or_name

            actual_name = (
                phone_or_raw
                if len(phone_or_raw) < 30
                else ""
            )

            actual_phone = ""

        # ======================================================
        # EXTRACT & TRANSLITERATE NAME FROM FIRST LINES IF MISSING
        # ======================================================
        if not actual_name:
            lines = [l.strip() for l in actual_raw_notes.splitlines() if l.strip()]
            for line in lines[:5]:
                name_match = re.search(
                    r"^(?:Mr|Dr|Eng|Prof|Coach|أ|د|م|ك|أستاذ|دكتور|مهندس|كابتن|الشيخ)[/\.\s]+([A-Za-z\s]{3,35}|[\u0600-\u06FF\s]{3,35})$",
                    line,
                    re.IGNORECASE
                )
                if name_match:
                    extracted = line.strip()
                    # Separate attached slash e.g. Mr/Adham -> Mr/ Adham
                    extracted = re.sub(
                        r"^(Mr|Dr|Eng|Prof|Coach|أ|د|م|ك|أستاذ|دكتور|مهندس|كابتن|الشيخ)[/\.](?=\w)",
                        r"\1/ ",
                        extracted,
                        flags=re.IGNORECASE
                    )
                    words = extracted.split()
                    trans_words = []
                    mapping = {
                        "adham": "أدهم",
                        "emad": "عماد",
                        "sherif": "شريف",
                        "hassafi": "الحصافي",
                        "ahmed": "أحمد",
                        "mohamed": "محمد",
                        "mahmoud": "محمود",
                        "mostafa": "مصطفى",
                        "tarek": "طارق",
                        "amr": "عمرو",
                        "ali": "علي",
                        "hassan": "حسن",
                        "hosam": "حسام",
                        "hossam": "حسام",
                        "john": "جون",
                        "mark": "مارك",
                        "sarah": "سارة",
                        "dina": "دينا",
                        "shelby": "شلبي",
                        "shalaby": "شلبي",
                        "tolba": "طلبة",
                        "elsayed": "السيد",
                    }
                    for w in words:
                        cw = w.lower().strip(",.")
                        if cw in ["mr/", "mr.", "mr"]:
                            trans_words.append("أ/")
                        elif cw in ["dr/", "dr.", "dr"]:
                            trans_words.append("د/")
                        elif cw in ["eng/", "eng.", "eng"]:
                            trans_words.append("م/")
                        elif cw in mapping:
                            trans_words.append(mapping[cw])
                        else:
                            trans_words.append(w)
                    actual_name = " ".join(trans_words)
                    break

        # Optimize and clean raw notes to save prompt tokens
        actual_raw_notes = self.optimize_input_text(actual_raw_notes)

        # ======================================================
        # EXTRACT PHONE
        # ======================================================

        if not actual_phone:

            phone_match = re.search(
                r"(?:01[0125]\d{8}|\+?201[0125]\d{8})",
                actual_raw_notes
            )

            if phone_match:

                actual_phone = (
                    phone_match.group(0)
                )

        # ======================================================
        # NORMALIZE PHONE
        # ======================================================

        actual_phone = (
            self.normalize_egyptian_phone(
                actual_phone
            )
        )

        # ======================================================
        # EDITORIAL REFERENCE (CACHED)
        # ======================================================

        editorial_reference = (
            self.build_editorial_reference()
        )

        # ======================================================
        # SYSTEM PROMPT
        # ======================================================

        system_prompt = f"""You must output a valid JSON object.
You are the Senior Editor and Lead Journalist of
"{self.NEWSPAPER_NAME}".

Your job is to transform raw client information into a
professionally written Arabic journalistic feature article
suitable for publication on the official newspaper website.

============================================================
CORE LANGUAGE RULE
============================================================

The OUTPUT CONTENT MUST BE IN ARABIC.

Use Modern Standard Arabic with a natural Egyptian-newsroom
tone.

Do NOT answer in English.

English words are allowed ONLY when they are:
- official brand names
- product names
- course names
- technical terms commonly used by the client
- names of platforms or services

The instructions in this prompt are written in English for
instruction precision, but the ARTICLE itself MUST be Arabic.

============================================================
ARABIC SPELLING & GRAMMAR — MANDATORY RULES
============================================================

You MUST write flawless Arabic. Apply these rules strictly:

1. HAMZA (الهمزة):
   - همزة القطع: أ / إ — used at the beginning of words
     (examples: أكد، إن، أوضح، إلى، أعلن، أسهم).
   - همزة الوصل: ا — used with (ال، اسم، است، انف، اثن).
   - همزة وسط الكلمة: ئ / ؤ / أ — depends on vowel context
     (examples: رئيس، مسؤول، تأثير).
   - همزة آخر الكلمة: ء / ئ / ؤ / ا — depends on vowel
     (examples: شيء، جزء، ملاءمة، شركاء).
   - NEVER write "رئيس" as "رئيس" with wrong hamza form.
   - NEVER confuse (أعلن / اعلن) — correct: أعلن.

2. TA MARBUTA (التاء المربوطة) vs. TA MABSUTA (التاء المفتوحة):
   - Use ة only at end of feminine nouns/adjectives.
   - Use ت at end of verbs and some nouns (e.g., أثبت، قدمت).
   - NEVER write: "خدمات" as "خدمات" with wrong final letter.

3. ALEF MAQSURA (الألف المقصورة):
   - Words ending with ى (not ا): مستوى، محتوى، أسمى، قوى.
   - Words ending with ا (not ى): علا، سما، أمنا.
   - NEVER write: "مستوا" or "محتوا".

4. TANWIN & NUNATION:
   - Correct: تلقائيًا، صحفيًا، مهنيًا، أساسيًا.
   - NEVER drop the small alef after tanwin fatah.

5. WORD SPACING:
   - No double spaces between words.
   - Correct punctuation spacing: period/comma immediately after the word, then space.

6. COMMON EGYPTIAN MEDIA SPELLING — verified correct forms:
   - رئيس تحرير (NOT رئيس التحرير for role titles)
   - مستوى (NOT مستوا)
   - تلقائيًا (NOT تلقائيا)
   - مسؤول (NOT مسئول in Modern Standard Arabic)
   - مشروع (NOT مشروع with wrong hamza)
   - إعداد (NOT اعداد — starts with hamza qat')
   - أسهم (NOT اسهم)
   - إجراء (NOT اجراء)

============================================================
ARABIC & EGYPTIAN NAMES — MANDATORY RULES (STRICT GLM PARSING)
============================================================

Names are SACRED and define the primary identity of the article. Apply these rules without exception:

1. ABSOLUTE ACCURACY IN EXTRACTION (استخراج محكم ودقيق لاسم صاحب الخبر):
   - You MUST accurately identify the PRIMARY SUBJECT of the article (the main person, educator, doctor, coach, expert, or organization being featured).
   - DO NOT confuse background names (e.g. references, authors of books mentioned in notes, secondary institutions) with the main subject (`client_name`).
   - Fill the `"client_name"` JSON field strictly with this primary subject's exact name.

2. PRESERVE NAMES & TITLES EXACTLY AS PROVIDED:
   - Copy names from the source AS-IS. Never alter spelling, never drop father/family names, never translate, and never "invent" middle names.
   - Preserve professional prefixes (أ. / أ/ / أستاذ / أستاذة / د. / د/ / دكتور / دكتورة / م. / م/ / مهندس / مهندسة / ك. / ك/ / كابتن / الشيخ).
   - Examples:
     - "أ/ شريف الحصافي" -> MUST remain exactly "أ/ شريف الحصافي" (do NOT drop "أ/" or alter "الحصافي").
     - "د. أحمد طلبة" -> MUST remain exactly "د. أحمد طلبة".
     - "أكاديمية الفكر" -> MUST remain exactly "أكاديمية الفكر".

3. ENGLISH TO ARABIC NAME TRANSLITERATION RULES (STRICT ACCURACY):
   - When transliterating English names to Arabic, map letters precisely and NEVER confuse phonetically different names!
   - "Adham" MUST be transliterated to "أدهم" (NEVER transliterate Adham to عادل!).
   - "Emad" MUST be transliterated to "عماد" (NEVER transliterate Emad to إمام!).
   - "Mr/Adham Emad" MUST become "أ/ أدهم عماد" or "أستاذ أدهم عماد" (NEVER "أ/ عادل إمام"!).
   - Honorific Prefixes:
     - "Mr." / "Mr/" -> "أ/" (أستاذ)
     - "Dr." / "Dr/" -> "د/" (دكتور)
     - "Eng." / "Eng/" -> "م/" (مهندس)
     - "Coach/" -> "ك/" (كابتن)

4. COMMON EGYPTIAN MALE/FEMALE NAMES & SURNAMES — DO NOT MISSPPELL:
   - Male: أدهم، عماد، شريف، الحصافي، شلبي، طلبة، أحمد، محمد، محمود، مصطفى، إبراهيم، خليل، علي، حسن، حسين، طارق، عمرو، أشرف.
   - Female: نورهان، سارة، هبة، مريم، فاطمة، رانيا، شيماء، آية، ياسمين، منى، دعاء، دينا، شيرين.

============================================================
EDITORIAL IDENTITY
============================================================

Newspaper:
{self.NEWSPAPER_NAME}

The newspaper presents professional, informative,
well-structured feature articles about:

- professionals
- educators
- academies
- companies
- startups
- digital platforms
- training providers
- coaches
- service providers
- experts
- entrepreneurs
- specialized projects
- creative initiatives

The article should feel like a real editorial feature,
NOT like a social-media advertisement.

It may have a positive and promotional character, but it must
remain journalistic, credible, informative, and professionally
written.

============================================================
PRONOUN & GENDER AGREEMENT RULE (VERY IMPORTANT)
============================================================

Identify the subject's gender and entity type accurately:

1. MALE INDIVIDUAL (مذكر / رجل / طبيب / مهندس):
   - Use masculine Arabic verbs, pronouns, and adjectives consistently throughout the entire article (e.g., "أكد الدكتور...", "أوضح أن...", "يسعى إلى...", "في مسيرته المهنية...").
   - Use masculine honorifics (الدكتور / الأستاذ / المهندس / المستشار) when mentioned.

2. FEMALE INDIVIDUAL (مؤنث / سيدة / طبيبة / مهندسة):
   - Use feminine Arabic verbs, pronouns, and adjectives consistently throughout the entire article (e.g., "أكدت الدكتورة...", "أوضحت أن...", "تسعى إلى...", "في مسيرتها المهنية...").
   - Use feminine honorifics (الدكتورة / الأستاذة / المهندسة / المستشارة) when mentioned.

3. ENTITY / GROUP / COMPANY (شركة / أكاديمية / مؤسسة / فريق / عيادة):
   - Use appropriate company/group Arabic verbs and pronouns (e.g., "أعلنت شركة...", "تقدم أكاديمية...", "تلتزم المؤسسة...", "يهدف الفريق...").

CRITICAL: Maintain absolute pronoun consistency! Never mix male and female pronouns for the same person.

============================================================
HONORIFIC TITLES PRESERVATION RULE (VERY IMPORTANT)
============================================================

1. PRESERVE EXISTING OR IMPLIED TITLES:
   - Always preserve professional and social honorific titles mentioned in the source or inferred from context:
     (دكتور / دكتورة / أستاذ / أستاذة / مهندس / مهندسة / أخصائي / أخصائية / استشاري / استشارية / مستشار / مستشارة / كابتن / شيخ).
   - Use the title naturally with the person's name throughout the article (e.g., "أكد الدكتور أحمد...", "أوضحت الأستاذة مريم...").

2. DO NOT INVENT UNMENTIONED TITLES:
   - If NO honorific title is mentioned or implied (e.g., for a brand, project, or plain entity), DO NOT invent artificial titles!
   - Example: Do not add "الدكتور" to a company name or a plain brand name.

============================================================
PRIMARY OBJECTIVE
============================================================

Create ONE complete article from the supplied raw information.

The article must:

1. Preserve the actual facts.
2. Organize scattered information intelligently.
3. Expand explanations using ONLY information supported by
   the raw material.
4. Improve journalistic readability.
5. Explain why the subject is relevant to its audience.
6. Highlight services, expertise, methodology, achievements,
   programs, products, or distinguishing features.
7. End naturally with a concise editorial conclusion.
8. Include a communication section when contact information
   exists.
9. Follow the editorial style demonstrated by the reference
   articles.
10. Never fabricate important facts.

============================================================
VERY IMPORTANT: FACTUAL INTEGRITY
============================================================

NEVER invent:

- certifications
- degrees
- years of experience
- branches
- locations
- prices
- clients
- partnerships
- awards
- statistics
- number of students
- number of customers
- results
- guarantees
- official affiliations
- dates
- claims of leadership
- claims of being "the first"
- claims of being "the largest"
- claims of guaranteed results

unless explicitly supported by the raw information.

If a fact is missing, DO NOT manufacture it.

You may improve wording and explain the significance of
information that is already provided, but you must not create
new factual claims.

============================================================
EDITORIAL REFERENCE POLICY
============================================================

The following articles are STYLE AND STRUCTURE REFERENCES.

They are NOT source material for the new article.

Study them to understand:

- article rhythm
- introduction style
- paragraph length
- heading structure
- journalistic transitions
- level of detail
- balance between information and promotion
- conclusion style
- communication section
- use of bold markers

DO NOT copy sentences from the references.

DO NOT reuse their facts.

DO NOT mention the reference articles.

DO NOT imitate a specific article word-for-word.

Extract the underlying editorial pattern only.

EDITORIAL REFERENCES:

{editorial_reference}

============================================================
INTRODUCTION RULE
============================================================

The article must begin with a professional editorial lead.

The lead must naturally include:

"في إطار اهتمام **جريدة تحت الضوء الإخبارية** بتسليط الضوء على..."

Then adapt the rest of the sentence according to the subject.

Examples of suitable directions:

- الكفاءات التعليمية
- الشركات المتخصصة
- المنصات الرقمية
- المبادرات التدريبية
- المشروعات المتخصصة
- الخبرات المهنية
- الحلول والخدمات
- الكيانات الإبداعية

Do NOT use the same exact sentence mechanically every time.

The introduction should feel customized to the subject.

============================================================
ARTICLE STRUCTURE
============================================================

The article MUST contain:

1. A strong journalistic title.
2. One lead paragraph.
3. 5 to 8 meaningful editorial sections.
4. A final summary/conclusion section.
5. A communication section when contact information exists.

Recommended flow:

TITLE

LEAD

SECTION 1:
Who is the subject and what does it offer?

SECTION 2:
Expertise / specialization / background.

SECTION 3:
Services / programs / products / methodology.

SECTION 4:
Practical value / audience / use cases.

SECTION 5:
Distinctive aspects supported by the source.

SECTION 6:
Current activities / developments / opportunities,
if supported.

SECTION 7:
Overall value and future relevance,
if supported.

CONCLUSION

CONTACT

Do not create empty or generic sections.

============================================================
HEADINGS
============================================================

Use 5 to 8 subheadings.

Subheadings must be:

- journalistic
- descriptive
- specific
- naturally connected to the content

Avoid generic headings such as:

"نبذة عن الشركة"

"الخدمات"

"الخاتمة"

"معلومات مهمة"

Prefer headings that communicate actual content.

Examples:

"خبرة تجمع بين المعرفة والتطبيق"

"حلول رقمية تسهّل الوصول إلى المعرفة"

"تدريب عملي يركز على التطبيق"

"من الفكرة إلى التنفيذ"

============================================================
ARTICLE LENGTH — HARD REQUIREMENT
============================================================

The final article body MUST contain between:

{self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} CHARACTERS.

To hit this required target in your VERY FIRST output, write at least 6 comprehensive sections, with each section containing 2 to 3 rich, multi-sentence journalistic paragraphs.

Target approximately:

1500-5000 characters.

DO NOT produce a short article. Avoid single-line sections.

Reach the required length through:

- useful explanations
- contextual information
- detailed service descriptions
- practical relevance
- smooth transitions
- audience-focused explanations
- supported details

============================================================
PARAGRAPH STYLE
============================================================

Write medium-length journalistic paragraphs.

Avoid:

- one-line paragraphs
- huge blocks
- repetitive wording
- excessive marketing language
- social-media style
- emoji-heavy writing

Use clear transitions such as:

"وتأتي هذه الخطوة..."
"ومن أبرز ما يميز..."
"ولا يقتصر..."
"كما..."
"وفي هذا السياق..."
"ويعكس ذلك..."
"ومن هنا..."
"ومع..."
"وتستهدف..."

Use them naturally, not mechanically.

============================================================
PROMOTIONAL BALANCE
============================================================

The article can highlight the strengths of the subject.

However:

DO NOT sound like a paid advertisement.

Avoid exaggerated phrases such as:

"الأفضل على الإطلاق"
"رقم واحد"
"لا مثيل له"
"يضمن النجاح"
"يحقق نتائج مضمونة"

unless such claims are explicitly present in the source and
clearly attributed to the client.

The preferred tone is:

professional + informative + positive + credible.

============================================================
BOLD MARKERS
============================================================

The AI MUST use Markdown-style bold markers:

**important phrase**

These are INTERNAL editorial markers.

They are NOT HTML.

Use bold selectively for:

- names
- important services
- major specialties
- important achievements
- important numbers
- key concepts

Do NOT bold every sentence.

Do NOT bold headings.

Do NOT use HTML.

Do NOT use <strong>.

============================================================
NEWSPAPER NAME
============================================================

Inside the article body, the newspaper name must appear as:

**جريدة تحت الضوء الإخبارية**

Never shorten it to:

"تحت الضوء"

Never write:

"جريدة تحت الضوء"

The official name is:

جريدة تحت الضوء الإخبارية

============================================================
CONTACT SECTION
============================================================

If a phone or WhatsApp number exists, include a final section:

"للتواصل والحجز"

or

"للتواصل واستفسار"

Use the appropriate wording according to the subject.

Do not invent opening hours.

Do not invent booking procedures.

Do not invent social links.

Only use available information.

============================================================
TITLE RULES — MANDATORY SUBJECT NAME INCLUSION (STRICT REQUIREMENT)
============================================================

1. MANDATORY NAME INCLUSION (إجبارية ذكر اسم الشخص أو الكيان في العنوان الرئيسي):
   - The headline (`title`) MUST MANDATORILY start with or prominently contain the name of the person or entity (e.g., `client_name`) extracted from raw data.
   - Preserve the exact language of the name (Arabic or English) as given in raw data.
   - OBLIGATORY TITLE STRUCTURE:
     `"اسم الشخص أو الكيان.. [وصف صحفي مباشر وجذاب ومحدد]"`
   - Examples of Mandatory Headlines:
     - `أ/ شريف الحصافي.. منهجية متخصصة لتعليم الفلسفة والمنطق والتاريخ الوطني`
     - `د. أحمد طلبة.. رؤية جديدة لتطوير الرعاية الصحية في مصر`
     - `أكاديمية الفكر الرقمي.. حلول تدريبية متقدمة لتأهيل الكوادر الإعلامية`
     - `Dr. Mark Johnson.. Launching Advanced AI Coding Programs`

2. FALLBACK ONLY IF NO NAME EXISTS:
   - IF and ONLY IF there is absolutely NO person name, brand, or entity name anywhere in the raw data, you may construct a descriptive topic headline (e.g. `منهجية حديثة لتعليم الفلسفة والمنطق في الثانوية العامة`).
   - Otherwise, including the subject's name in the title is 100% COMPULSORY (إجباري).

3. FORMATTING:
   - The title MUST NOT contain **bold markers**.
   - Avoid clickbait or exaggerated punctuation.

============================================================
SLUG
============================================================

Generate a lowercase English slug.

Rules:

- English letters only
- numbers allowed
- hyphens allowed
- no Arabic
- no spaces
- must end with .html

Example:

dr-mohamed-samy-accounting-academy.html

============================================================
LABEL — STRICT REQUIREMENT
============================================================

Return exactly ONE Arabic editorial label chosen strictly from this ALLOWED LIST OF 7 CATEGORIES ONLY:

- تعليم
- صحة
- شخصيات عامة
- تطوير ذات
- التغذية العلاجية
- أعمال
- خدمات

CRITICAL RULE: DO NOT generate or invent any label outside this list. Choose the single category from the list above that is closest and most appropriate to the content of the article.

============================================================
OUTPUT FORMAT — ABSOLUTE
============================================================

Return ONLY valid JSON.

No markdown.

No explanation.

No introductory text.

No code fences.

No text before JSON.

No text after JSON.

Use exactly this structure:

{{
  "client_name": "",
  "client_phone": "",
  "entity_type": "male | female | plural",
  "title": "",
  "slug": "",
  "labels": [""],
  "lead_paragraph": "",
  "sections": [
    {{
      "subheading": "",
      "paragraphs": [
        ""
      ],
      "is_bullet_list": false,
      "items": []
    }}
  ]
}}

============================================================
JSON SAFETY
============================================================

The response MUST be valid JSON.

Escape quotation marks correctly.

Do not put raw line breaks inside JSON strings.

Do not add trailing commas.

Do not return Python dictionaries.

Do not return comments.

============================================================
FINAL QUALITY CHECK BEFORE OUTPUT
============================================================

Before returning the JSON, silently verify:

[ ] Article is Arabic.
[ ] Article is between {self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} characters.
[ ] Target is approximately 3500-5000 characters.
[ ] 5-8 meaningful sections exist.
[ ] Introduction begins with the required newspaper identity.
[ ] **جريدة تحت الضوء الإخبارية** is correctly bolded in body text.
[ ] No HTML exists.
[ ] No bold exists in title.
[ ] No bold exists in subheadings.
[ ] Facts are preserved.
[ ] No unsupported major facts were invented.
[ ] Exactly one Arabic label exists.
[ ] Slug is lowercase English and ends with .html.
[ ] Contact details are included only when available.
[ ] JSON is valid.
[ ] The article does not copy reference examples.
[ ] The article reads like a professional newspaper feature.

If the draft is below {self.MIN_ARTICLE_CHARS} characters, expand useful
supported details before returning.

If the draft exceeds {self.MAX_ARTICLE_CHARS} characters, compress repetitive
sentences before returning.

Raw source information follows in the USER message.
"""

        # ======================================================
        # USER PROMPT
        # ======================================================

        user_prompt = f"""
SOURCE DATA FOR THE ARTICLE
============================

Raw information:

{actual_raw_notes}

Known client name:
{actual_name if actual_name else "Extract from source data."}

Known phone:
{actual_phone if actual_phone else "Extract from source data if available."}

EDITORIAL TASK
==============

Transform the source data into the final Arabic journalistic
article according to every rule in the system instructions.

The reference articles are only editorial benchmarks.

Do not copy their facts or sentences.

Preserve all supported facts from the source.

The final article must be {self.MIN_ARTICLE_CHARS}-{self.MAX_ARTICLE_CHARS} characters in actual
article content.

Return JSON only.
"""

        # ======================================================
        # SEND REQUEST WITH AUTOMATED MODEL FALLBACK & TOKEN PROTECTION
        # ======================================================

        # Build prioritized list of (provider, model) candidates
        model_candidates = []
        primary_prov = self.get_provider_for_model(self.model)
        model_candidates.append((primary_prov, self.model))

        if self.gemini_client and self.gemini_model:
            cand = ("gemini", self.gemini_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        if self.openrouter_client and self.openrouter_model:
            cand = ("openrouter", self.openrouter_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        if self.zenmux_client and self.zenmux_model:
            cand = ("zenmux", self.zenmux_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        for m in self.FALLBACK_MODELS:
            prov = self.get_provider_for_model(m)
            cand = (prov, m)
            if cand not in model_candidates:
                model_candidates.append(cand)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response, provider_used, model_used = self._create_chat_completion(
            messages=messages,
            model_candidates=model_candidates,
            temperature=0.2,
            max_tokens=3500
        )

        msg_obj = response.choices[0].message if (response and hasattr(response, "choices") and response.choices) else None
        content = (getattr(msg_obj, "content", "") or getattr(msg_obj, "reasoning_content", "") or "") if msg_obj else ""

        logger.debug(
            f"استجابة Groq الخام: {content}"
        )

        # ======================================================
        # PARSE JSON
        # ======================================================

        parsed_data = self.parse_json_response(
            content
        )

        # ======================================================
        # VALIDATE OBJECT
        # ======================================================

        if not isinstance(
            parsed_data,
            dict
        ):

            raise ValueError(
                "استجابة الـ AI ليست JSON Object صالح."
            )

        # ======================================================
        # CLIENT NAME
        # ======================================================

        client_name = (
            parsed_data.get(
                "client_name"
            )
            or actual_name
        )

        if not client_name:

            title = str(
                parsed_data.get(
                    "title",
                    ""
                )
            )

            if ".." in title:

                client_name = (
                    title
                    .split("..")[0]
                    .strip()
                )

            else:

                client_name = (
                    title
                    or "خبر صحفي"
                )

        parsed_data[
            "client_name"
        ] = client_name

        # ======================================================
        # MANDATORY TITLE SAFEGUARD (Ensure Subject Name in Title)
        # ======================================================
        title = str(parsed_data.get("title", "")).strip()
        if client_name and client_name.strip() and client_name not in ["خبر صحفي", "عميل تليجرام", ""]:
            clean_name_word = re.sub(r"^(أ/|أ\.|د/|د\.|م/|م\.|ك/|ك\.|أستاذ/|دكتور/|مهندس/|كابتن/)\s*", "", client_name).strip()
            if clean_name_word and clean_name_word.lower() not in title.lower():
                if ".." in title:
                    rest_title = title.split("..", 1)[1].strip()
                    title = f"{client_name}.. {rest_title}"
                else:
                    title = f"{client_name}.. {title}"
        parsed_data["title"] = title

        # ======================================================
        # CLIENT PHONE
        # ======================================================

        client_phone = (
            parsed_data.get(
                "client_phone"
            )
            or actual_phone
        )

        client_phone = (
            self.normalize_egyptian_phone(
                client_phone
            )
        )

        parsed_data[
            "client_phone"
        ] = client_phone

        # ======================================================
        # NORMALIZE LABELS
        # ======================================================

        labels = parsed_data.get(
            "labels",
            []
        )

        if isinstance(
            labels,
            str
        ):

            labels = [
                labels
            ]

        if not isinstance(
            labels,
            list
        ):

            labels = []

        labels = [
            str(label).strip()
            for label in labels
            if str(label).strip()
        ]

        raw_label = labels[0] if labels else ""
        final_label = self.normalize_label(raw_label, actual_raw_notes)

        parsed_data[
            "labels"
        ] = [final_label]

        # ======================================================
        # NORMALIZE SLUG
        # ======================================================

        slug = str(
            parsed_data.get(
                "slug",
                ""
            )
        ).strip().lower()

        slug = re.sub(
            r"\s+",
            "-",
            slug
        )

        slug = re.sub(
            r"[^a-z0-9\-\.]",
            "",
            slug
        )

        if (
            not slug
            or slug == ".html"
        ):

            fallback_slug = re.sub(
                r"[^a-z0-9-]",
                "",
                client_name
                .lower()
                .replace(
                    " ",
                    "-"
                )
            )

            if not fallback_slug:

                fallback_slug = "article"

            slug = (
                fallback_slug
                + ".html"
            )

        elif not slug.endswith(
            ".html"
        ):

            slug += ".html"

        parsed_data[
            "slug"
        ] = slug

        # ======================================================
        # NORMALIZE CONTENT
        # ======================================================

        parsed_data = (
            self.normalize_article_content(
                parsed_data
            )
        )

        # ======================================================
        # ARTICLE LENGTH
        # ======================================================

        article_text = (
            self.get_article_text(
                parsed_data
            )
        )

        article_length = len(
            article_text
        )

        logger.info(
            f"طول الخبر بعد التوليد: "
            f"{article_length} حرف"
        )

        # ======================================================
        # SECOND PASS IF LENGTH IS INVALID
        # ======================================================

        if (
            article_length
            < self.MIN_ARTICLE_CHARS
            or article_length
            > self.MAX_ARTICLE_CHARS
        ):

            logger.warning(
                "طول الخبر خارج النطاق المطلوب. "
                "سيتم تنفيذ محاولة ضبط تلقائية."
            )

            parsed_data = (
                self.adjust_article_length(
                    parsed_data,
                    actual_raw_notes
                )
            )

            final_length = len(
                self.get_article_text(
                    parsed_data
                )
            )

            logger.info(
                f"طول الخبر بعد الضبط: "
                f"{final_length} حرف"
            )

        # ======================================================
        # FINAL VALIDATION
        # ======================================================

        self.validate_article(
            parsed_data
        )

        logger.info(
            f"تم توليد الخبر بنجاح للعميل: "
            f"{client_name}"
        )

        return parsed_data

    # ==========================================================
    # JSON PARSER
    # ==========================================================

    @staticmethod
    def parse_json_response(
        content: str
    ) -> dict:

        if not content:
            raise ValueError("الـ AI أعاد استجابة فارغة.")

        # 0. Strip reasoning/think blocks (<think>...</think>)
        cleaned_content = re.sub(r'<think>[\s\S]*?</think>', '', content, flags=re.IGNORECASE).strip()

        # 1. Clean markdown code blocks anywhere in text
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*(?:```|$)", cleaned_content, re.IGNORECASE)
        if match:
            cleaned_content = match.group(1).strip()

        # Direct json parsing
        try:
            return json.loads(cleaned_content, strict=False)
        except json.JSONDecodeError:
            pass

        # 2. Extract from first '{' to last '}'
        start_idx = cleaned_content.find("{")
        end_idx = cleaned_content.rfind("}")
        if start_idx != -1:
            snippet = cleaned_content[start_idx:end_idx + 1] if end_idx > start_idx else cleaned_content[start_idx:]

            # Direct parse snippet
            try:
                return json.loads(snippet, strict=False)
            except json.JSONDecodeError:
                pass

            # Try raw_decode
            try:
                obj, _ = json.JSONDecoder(strict=False).raw_decode(cleaned_content[start_idx:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

            # 3. Clean control characters and invalid escapes
            cleaned_snippet_strict = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', snippet)

            try:
                return json.loads(cleaned_snippet_strict, strict=False)
            except json.JSONDecodeError:
                pass

            try:
                obj, _ = json.JSONDecoder(strict=False).raw_decode(cleaned_snippet_strict)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

            # 4. Robust Auto-repair for Truncated JSON (Token Limit Exceeded Recovery)
            truncated = cleaned_snippet_strict.strip()

            # Handle unclosed string quote
            quote_count = len(re.findall(r'(?<!\\)"', truncated))
            if quote_count % 2 != 0:
                truncated += '"'

            # Remove trailing commas and incomplete property assignments
            truncated = re.sub(r',\s*$', '', truncated)
            truncated = re.sub(r',\s*([\}\]])', r'\1', truncated)
            truncated = re.sub(r',\s*"[^"]*"?\s*:\s*$', '', truncated)

            # Balance open brackets '[' and braces '{'
            stack = []
            in_string = False
            for idx, ch in enumerate(truncated):
                if ch == '"' and (idx == 0 or truncated[idx - 1] != '\\'):
                    in_string = not in_string
                elif not in_string:
                    if ch in '{[':
                        stack.append(ch)
                    elif ch in '}]':
                        if stack:
                            top = stack[-1]
                            if (ch == '}' and top == '{') or (ch == ']' and top == '['):
                                stack.pop()

            while stack:
                top = stack.pop()
                if top == '{':
                    truncated += '}'
                elif top == '[':
                    truncated += ']'

            try:
                return json.loads(truncated, strict=False)
            except json.JSONDecodeError:
                pass

            try:
                obj, _ = json.JSONDecoder(strict=False).raw_decode(truncated)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        logger.error(f"فشل فك JSON بعد جميع المحاولات والإصلاح. محتوى الاستجابة: {content[:300]}...")
        raise ValueError("استجابة الـ AI تحتوي على JSON غير صالح.")

    # ==========================================================
    # ARTICLE LENGTH
    # ==========================================================

    @classmethod
    def get_article_text(
        cls,
        parsed_data: dict
    ) -> str:

        parts = []

        title = str(
            parsed_data.get(
                "title",
                ""
            )
        ).strip()

        if title:

            parts.append(
                title
            )

        lead = str(
            parsed_data.get(
                "lead_paragraph",
                ""
            )
        ).strip()

        if lead:

            parts.append(
                lead
            )

        sections = parsed_data.get(
            "sections",
            []
        )

        if isinstance(
            sections,
            list
        ):

            for section in sections:

                if not isinstance(
                    section,
                    dict
                ):
                    continue

                subheading = str(
                    section.get(
                        "subheading",
                        ""
                    )
                ).strip()

                if subheading:

                    parts.append(
                        subheading
                    )

                paragraphs = section.get(
                    "paragraphs",
                    []
                )

                if isinstance(
                    paragraphs,
                    list
                ):

                    parts.extend(
                        str(p).strip()
                        for p in paragraphs
                        if str(p).strip()
                    )

                items = section.get(
                    "items",
                    []
                )

                if isinstance(
                    items,
                    list
                ):

                    parts.extend(
                        str(item).strip()
                        for item in items
                        if str(item).strip()
                    )

        text = "\n".join(
            parts
        )

        # Remove internal bold markers
        text = re.sub(
            r"\*\*",
            "",
            text
        )

        return text.strip()

    # ==========================================================
    # AUTOMATIC LENGTH ADJUSTMENT
    # ==========================================================

    def adjust_article_length(
        self,
        parsed_data: dict,
        raw_source: str
    ) -> dict:

        current_length = len(
            self.get_article_text(
                parsed_data
            )
        )

        if (
            self.MIN_ARTICLE_CHARS
            <= current_length
            <= self.MAX_ARTICLE_CHARS
        ):

            return parsed_data

        current_json = json.dumps(
            parsed_data,
            ensure_ascii=False
        )

        if current_length < self.MIN_ARTICLE_CHARS:

            task_instruction = f"""
The current article is too short.

Current article length:
{current_length} characters.

Required minimum:
{self.MIN_ARTICLE_CHARS} characters.

Expand the article to approximately
1500-5000 characters.

IMPORTANT:

Do NOT invent facts.

Do NOT add unsupported statistics.

Do NOT add fake achievements.

Expand only by developing information already present
in the source and current article.

Add useful journalistic context, explanations,
service descriptions, audience relevance, methodology,
and supported details.

Keep the same JSON structure.

Return JSON only.
"""

        else:

            task_instruction = f"""
The current article is too long.

Current article length:
{current_length} characters.

Required maximum:
{self.MAX_ARTICLE_CHARS} characters.

Reduce the article to approximately
3500-5000 characters.

Remove:

- repetition
- redundant explanations
- repeated claims
- unnecessary adjectives
- duplicated conclusions

Do NOT remove important facts.

Keep the same JSON structure.

Return JSON only.
"""

        adjustment_prompt = f"""
SOURCE DATA
===========

{raw_source}

CURRENT ARTICLE
===============

{current_json}

EDITORIAL ADJUSTMENT
====================

{task_instruction}

The final article MUST remain Arabic.

The final response MUST be valid JSON only.

Do not return Markdown.
Do not return explanations.
"""

        model_candidates = []
        primary_prov = self.get_provider_for_model(self.model)
        model_candidates.append((primary_prov, self.model))

        if self.gemini_client and self.gemini_model:
            cand = ("gemini", self.gemini_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        if self.openrouter_client and self.openrouter_model:
            cand = ("openrouter", self.openrouter_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        if self.zenmux_client and self.zenmux_model:
            cand = ("zenmux", self.zenmux_model)
            if cand not in model_candidates:
                model_candidates.append(cand)

        for m in self.FALLBACK_MODELS:
            prov = self.get_provider_for_model(m)
            cand = (prov, m)
            if cand not in model_candidates:
                model_candidates.append(cand)

        messages = [
            {
                "role": "system",
                "content": f"""You are a professional Arabic newspaper editor.
You are correcting the length of an already generated journalistic article for {self.NEWSPAPER_NAME}.
Preserve factual integrity. Return valid JSON only.
The article must remain between {self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} characters.
Do not invent facts."""
            },
            {
                "role": "user",
                "content": adjustment_prompt
            }
        ]

        try:
            response, provider_used, model_used = self._create_chat_completion(
                messages=messages,
                model_candidates=model_candidates,
                temperature=0.2,
                max_tokens=3500
            )
        except Exception as exc:
            logger.error(f"فشلت جميع محاولات محاذاة الطول. سيتم اعتماد الموديل الأولي. السبب: {exc}")
            return parsed_data

        content = (
            response
            .choices[0]
            .message
            .content
        )

        try:
            adjusted = self.parse_json_response(content)
            self.validate_article(adjusted)
            return adjusted
        except Exception as parse_err:
            logger.warning(f"تعذر استخدام المقال المعدل بعد محاذاة الطول ({parse_err}). سيتم اعتماد المقال الأصلي.")
            return parsed_data

    # ==========================================================
    # FINAL VALIDATION
    # ==========================================================

    @classmethod
    def validate_article(
        cls,
        parsed_data: dict
    ) -> None:

        if not isinstance(
            parsed_data,
            dict
        ):

            raise ValueError(
                "المقال ليس JSON Object."
            )

        required_fields = [
            "client_name",
            "client_phone",
            "title",
            "slug",
            "labels",
            "lead_paragraph",
            "sections"
        ]

        for field in required_fields:

            if field not in parsed_data:

                raise ValueError(
                    f"الحقل الإجباري مفقود: {field}"
                )

        title = str(
            parsed_data.get(
                "title",
                ""
            )
        )

        if "**" in title:

            raise ValueError(
                "العنوان يحتوي على Bold markers."
            )

        slug = str(
            parsed_data.get(
                "slug",
                ""
            )
        )

        if not re.fullmatch(
            r"[a-z0-9\-]+\.html",
            slug
        ):

            raise ValueError(
                f"Slug غير صالح: {slug}"
            )

        labels = parsed_data.get(
            "labels"
        )

        if (
            not isinstance(
                labels,
                list
            )
            or len(labels) != 1
            or labels[0] not in cls.ALLOWED_LABELS
        ):

            raise ValueError(
                f"يجب أن يحتوي labels على تصنيف واحد فقط من القائمة المعتمدة: {cls.ALLOWED_LABELS}"
            )

        sections = parsed_data.get(
            "sections"
        )

        if not isinstance(
            sections,
            list
        ):

            raise ValueError(
                "sections يجب أن تكون List."
            )

        if len(sections) < 1:
            raise ValueError(
                "الخبر يجب أن يحتوي على قسم واحد على الأقل."
            )

        article_length = len(
            cls.get_article_text(
                parsed_data
            )
        )

        if not (
            cls.MIN_ARTICLE_CHARS
            <= article_length
            <= cls.MAX_ARTICLE_CHARS
        ):

            logger.warning(
                f"الخبر خارج نطاق الطول النهائي: "
                f"{article_length} حرف"
            )

    # ==========================================================
    # PHONE NORMALIZATION
    # ==========================================================

    @staticmethod
    def normalize_egyptian_phone(
        phone: str
    ) -> str:

        if not phone:

            return ""

        phone = str(
            phone
        ).strip()

        phone = re.sub(
            r"[\s\-\(\)]",
            "",
            phone
        )

        # +201XXXXXXXXX
        if re.fullmatch(
            r"\+20\d{10}",
            phone
        ):

            phone = (
                "0"
                + phone[3:]
            )

        # 201XXXXXXXXX
        elif re.fullmatch(
            r"20\d{10}",
            phone
        ):

            phone = (
                "0"
                + phone[2:]
            )

        elif re.fullmatch(
            r"01[0125]\d{8}",
            phone
        ):

            pass

        return phone

    # ==========================================================
    # BOLD NORMALIZATION
    # ==========================================================

    @staticmethod
    def clean_bold_markers(
        text: str
    ) -> str:

        if not text:

            return ""

        text = str(
            text
        )

        # ------------------------------------------------------
        # Remove HTML strong tags
        # ------------------------------------------------------

        text = re.sub(
            r"<\s*strong\s*>",
            "**",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"<\s*/\s*strong\s*>",
            "**",
            text,
            flags=re.IGNORECASE
        )

        # ------------------------------------------------------
        # Normalize duplicated **
        # ------------------------------------------------------

        text = re.sub(
            r"\*\*\*\*+(.*?)\*\*\*\*+",
            r"**\1**",
            text,
            flags=re.DOTALL
        )

        # ------------------------------------------------------
        # Fix odd number of markers
        # ------------------------------------------------------

        count = text.count(
            "**"
        )

        if count % 2 != 0:

            last_pos = text.rfind(
                "**"
            )

            if last_pos != -1:

                text = (
                    text[:last_pos]
                    +
                    text[last_pos + 2:]
                )

        return text

    # ==========================================================
    # NEWSPAPER NAME BOLD
    # ==========================================================

    @classmethod
    def force_newspaper_bold(
        cls,
        text: str
    ) -> str:

        if not text:

            return text

        text = str(
            text
        )

        escaped_name = re.escape(
            cls.NEWSPAPER_NAME
        )

        # Remove accidental duplicate wrappers
        text = re.sub(
            rf"\*\*\s*{escaped_name}\s*\*\*",
            cls.NEWSPAPER_NAME,
            text
        )

        text = text.replace(
            cls.NEWSPAPER_NAME,
            f"**{cls.NEWSPAPER_NAME}**"
        )

        return text

    # ==========================================================
    # ARTICLE CONTENT NORMALIZATION
    # ==========================================================

    @classmethod
    def normalize_article_content(
        cls,
        parsed_data: dict
    ) -> dict:

        # ------------------------------------------------------
        # Lead
        # ------------------------------------------------------

        lead = str(
            parsed_data.get(
                "lead_paragraph",
                ""
            )
        )

        lead = cls.clean_bold_markers(
            lead
        )

        lead = cls.force_newspaper_bold(
            lead
        )

        parsed_data[
            "lead_paragraph"
        ] = lead.strip()

        # ------------------------------------------------------
        # Sections
        # ------------------------------------------------------

        sections = parsed_data.get(
            "sections",
            []
        )

        if not isinstance(
            sections,
            list
        ):

            sections = []

        cleaned_sections = []

        for section in sections:

            if not isinstance(
                section,
                dict
            ):
                continue

            # --------------------------------------------------
            # Subheading
            # --------------------------------------------------

            subheading = str(
                section.get(
                    "subheading",
                    ""
                )
            ).strip()

            subheading = re.sub(
                r"\*\*",
                "",
                subheading
            )

            # --------------------------------------------------
            # Paragraphs
            # --------------------------------------------------

            paragraphs = section.get(
                "paragraphs",
                []
            )

            if isinstance(
                paragraphs,
                str
            ):

                paragraphs = [
                    paragraphs
                ]

            if not isinstance(
                paragraphs,
                list
            ):

                paragraphs = []

            cleaned_paragraphs = []

            for paragraph in paragraphs:

                paragraph = str(
                    paragraph
                ).strip()

                if not paragraph:

                    continue

                paragraph = (
                    cls.clean_bold_markers(
                        paragraph
                    )
                )

                paragraph = (
                    cls.force_newspaper_bold(
                        paragraph
                    )
                )

                cleaned_paragraphs.append(
                    paragraph
                )

            # --------------------------------------------------
            # Items
            # --------------------------------------------------

            items = section.get(
                "items",
                []
            )

            if isinstance(
                items,
                str
            ):

                items = [
                    items
                ]

            if not isinstance(
                items,
                list
            ):

                items = []

            cleaned_items = []

            for item in items:

                item = str(
                    item
                ).strip()

                if not item:

                    continue

                item = (
                    cls.clean_bold_markers(
                        item
                    )
                )

                item = (
                    cls.force_newspaper_bold(
                        item
                    )
                )

                cleaned_items.append(
                    item
                )

            # --------------------------------------------------
            # Store
            # --------------------------------------------------

            cleaned_sections.append(
                {
                    "subheading": subheading,
                    "paragraphs": cleaned_paragraphs,
                    "is_bullet_list": bool(
                        section.get(
                            "is_bullet_list",
                            False
                        )
                    ),
                    "items": cleaned_items
                }
            )

        parsed_data[
            "sections"
        ] = cleaned_sections

        # ------------------------------------------------------
        # Title
        # ------------------------------------------------------

        title = str(
            parsed_data.get(
                "title",
                ""
            )
        ).strip()

        title = re.sub(
            r"\*\*",
            "",
            title
        )

        parsed_data[
            "title"
        ] = title

        return parsed_data


# ==============================================================
# GLOBAL SERVICE INSTANCE
# ==============================================================

ai_service = AIService()
