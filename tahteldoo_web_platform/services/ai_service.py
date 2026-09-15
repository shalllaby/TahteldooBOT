import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future
from difflib import SequenceMatcher
from typing import List, Dict, Any, Callable, Optional, Tuple, Set

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from core.config import Config
from core.logger import logger


class AIService:
    """
    AI service for generating professional Arabic journalistic articles
    for "جريدة تحت الضوء الإخبارية" using Z.AI (GLM) as the sole LLM provider.
    """

    NEWSPAPER_NAME = "جريدة تحت الضوء الإخبارية"

    # ==========================================================
    # ARTICLE LENGTH
    # ==========================================================

    MIN_ARTICLE_CHARS = 1400
    MAX_ARTICLE_CHARS = 3500

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
    # EXAMPLES & FALLBACK CONFIG (Z.AI GLM MODELS ONLY)
    # ==========================================================

    EXAMPLES_FILENAME = "article_examples.json"

    FALLBACK_MODELS = [
        "glm-4.7-flash",
        "glm-4-flash",
        "glm-4-air",
        "glm-4-plus"
    ]

    # ==========================================================
    # REPETITION PREVENTION & DIVERSE JOURNALISTIC TRANSITIONS
    # ==========================================================

    REPETITIVE_PRAISE_PATTERNS = [
        r"من القامات البارزة والمشهود لها بالكفاءة والتميز",
        r"من القامات البارزة والمشهود لها",
        r"من القامات البارزة",
        r"صاحب رؤية ثاقبة وبصمة استثنائية",
        r"صاحب بصمة استثنائية",
        r"بصمة استثنائية",
        r"رؤية ثاقبة",
        r"علامة مضيئة وإضافة نوعية",
        r"علامة مضيئة",
        r"نموذج يُحتذى به في التفاني والاحترافية والريادة",
        r"نموذج يُحتذى به",
        r"سيرة مهنية حافلة بالعطاء",
    ]

    ALTERNATIVE_TRANSITIONS = [
        "وفي سياق متصل، ",
        "وعلى صعيد موازٍ، ",
        "وحول آليات العمل والمنهجية، ",
        "ويرتكز هذا التوجه على ",
        "وبالانتقال إلى الجانب التطبيقي، ",
        "وفيما يتعلق بمتطلبات الفئة المستهدفة، ",
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
        model: str = None,
        primary_zai_key: str = None
    ):
        # Z.AI / GLM Integration (Dedicated Personal Key Architecture)
        self.zai_base_url = getattr(Config, "ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        self.zai_model = (
            model
            or getattr(Config, "ZAI_MODEL", "")
            or "glm-4.7-flash"
        )
        self.model = self.zai_model

        # Only one dedicated key per instance/journalist - No shared multi-key rotation
        if primary_zai_key and primary_zai_key.strip():
            target_key = primary_zai_key.strip()
            self.zai_keys = [target_key]
        elif api_key and api_key.strip():
            target_key = api_key.strip()
            self.zai_keys = [target_key]
        else:
            default_key = getattr(Config, "ZAI_API_KEY", "") or getattr(Config, "TELEGRAM_ZAI_API_KEY", "")
            self.zai_keys = [default_key.strip()] if default_key and default_key.strip() else []

        self.api_key = self.zai_keys[0] if self.zai_keys else None

        self.zai_clients = []
        if OpenAI and self.api_key:
            try:
                c = OpenAI(api_key=self.api_key, base_url=self.zai_base_url)
                self.zai_clients.append(c)
                logger.info(f"تم تفعيل محرك Z.AI (GLM) بنجاح.")
            except Exception as zai_err:
                logger.warning(f"تعذر تهيئة محرك Z.AI: {zai_err}")

        self.zai_client = self.zai_clients[0] if self.zai_clients else None

        # Thread pool for asynchronous / parallel execution
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Cache for editorial reference string
        self._cached_editorial_reference: Optional[str] = None

        # Load editorial examples
        self.editorial_examples = (
            self.load_editorial_examples()
        )

    # ==========================================================
    # PROVIDER ROUTING & ROBUST API EXECUTION
    # ==========================================================

    def get_provider_for_model(self, model_name: str) -> str:
        """Always routes to Z.AI (GLM) as the sole LLM provider."""
        return "zai"

    def _create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model_candidates: List[Tuple[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3500,
        validate_json: bool = True,
        override_client: Any = None
    ) -> Tuple[Any, str, str, Dict[str, Any]]:
        """
        Executes a chat completion request with intelligent model fallback
        and inline JSON validation error recovery on the user's dedicated Z.AI key.
        """
        last_exception = None

        clients_to_use = [override_client] if override_client else self.zai_clients
        if not clients_to_use:
            raise ValueError("لا يوجد أي مفتاح Z.AI (GLM) مفعّل أو صالح. يرجى إدخال مفتاح API الخاص بك في الإعدادات.")

        for _, target_model in model_candidates:
            for client_to_use in clients_to_use:
                for json_attempt in [True, False]:
                    try:
                        actual_tokens = 8192
                        logger.info(
                            f"إرسال طلب توليد (Z.AI) باستخدام النموذج: {target_model} (التوكينات: {actual_tokens})..."
                        )

                        req_kwargs = {
                            "messages": messages,
                            "model": target_model,
                            "temperature": temperature,
                            "max_tokens": actual_tokens,
                            "extra_body": {"thinking": {"type": "disabled"}}
                        }

                        if json_attempt:
                            req_kwargs["response_format"] = {"type": "json_object"}

                        try:
                            response = client_to_use.chat.completions.create(**req_kwargs)
                        except Exception as api_err:
                            if "extra_body" in req_kwargs and ("thinking" in str(api_err).lower() or "extra_body" in str(api_err).lower()):
                                req_kwargs.pop("extra_body", None)
                                response = client_to_use.chat.completions.create(**req_kwargs)
                            else:
                                raise api_err

                        msg_content = ""
                        if response and hasattr(response, "choices") and response.choices:
                            m = response.choices[0].message
                            c_text = (getattr(m, "content", "") or "").strip()
                            r_text = (getattr(m, "reasoning_content", "") or "").strip()

                            if c_text and "{" in c_text:
                                msg_content = c_text
                            elif r_text and "{" in r_text:
                                msg_content = r_text
                            else:
                                msg_content = c_text or r_text

                        if not msg_content and json_attempt:
                            logger.warning(f"النموذج {target_model} أعاد استجابة فارغة مع response_format. إعادة المحاولة بدون response_format...")
                            continue

                        if hasattr(response, "usage") and response.usage:
                            logger.info(
                                f"استهلاك التوكينات [{target_model}]: Prompt={response.usage.prompt_tokens}, "
                                f"Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens}"
                            )

                        if validate_json:
                            try:
                                parsed_data = self.parse_json_response(msg_content)
                                if isinstance(parsed_data, dict):
                                    return response, "zai", target_model, parsed_data
                                else:
                                    logger.warning(f"النموذج {target_model} أعاد استجابة JSON ولكنها ليست Object. التجربة التالية...")
                            except Exception as json_err:
                                logger.warning(
                                    f"النموذج {target_model} أعاد استجابة لا تمثل JSON صالحاً ({json_err}). "
                                    f"بداية المحتوى: {msg_content[:120]}... الانتقال للنموذج/المفتاح التالي..."
                                )
                                last_exception = json_err
                                continue
                        else:
                            return response, "zai", target_model, {}

                    except Exception as exc:
                        last_exception = exc
                        exc_str = str(exc).lower()

                        # Case 1: Rate Limit (429 / TPM / Token Limit)
                        if "rate_limit" in exc_str or "413" in exc_str or "tokens per minute" in exc_str or "429" in exc_str or "resource_exhausted" in exc_str:
                            wait_match = re.search(r"try again in ([\d\.]+)s", exc_str)
                            wait_time = float(wait_match.group(1)) if wait_match else 2.0

                            if 0 < wait_time <= 6.0 and len(self.zai_clients) == 1:
                                logger.warning(
                                    f"تجاوز حد التوكينات المؤقت للنموذج {target_model}. انتظار {wait_time:.1f} ثانية وإعادة المحاولة..."
                                )
                                time.sleep(wait_time + 0.5)
                                try:
                                    response = client_to_use.chat.completions.create(**req_kwargs)
                                    msg_content = ""
                                    if response and hasattr(response, "choices") and response.choices:
                                        m = response.choices[0].message
                                        c_text = (getattr(m, "content", "") or "").strip()
                                        r_text = (getattr(m, "reasoning_content", "") or "").strip()
                                        msg_content = c_text if "{" in c_text else (r_text if "{" in r_text else (c_text or r_text))
                                    if validate_json:
                                        parsed_data = self.parse_json_response(msg_content)
                                        return response, "zai", target_model, parsed_data
                                    return response, "zai", target_model, {}
                                except Exception as retry_exc:
                                    last_exception = retry_exc
                                    logger.warning(f"محاولة الإعادة للنموذج {target_model} تعذرت. جاري الانتقال لمفتاح/نموذج آخر...")
                                    break
                            else:
                                logger.warning(
                                    f"تجاوز حد التوكينات (TPM Rate Limit) للنموذج {target_model}. التبديل الفوري للمفتاح التالي لتجنب التوقف..."
                                )
                                break

                        # Case 2: Decommissioned Model / Unregistered Zhipu Model
                        elif "decommissioned" in exc_str or "no longer supported" in exc_str or "1211" in exc_str or "模型不存在" in exc_str:
                            logger.warning(f"النموذج {target_model} ملغى أو غير مفعل على حساب Z.AI/BigModel. جاري التجاوز للنموذج التالي...")
                            break

                        # Case 3: Specific JSON Validation Failed
                        elif ("json_validate_failed" in exc_str or "failed to validate json" in exc_str or "schema" in exc_str) and json_attempt:
                            logger.warning(
                                f"تعذر الالتزام بـ JSON Schema للنموذج {target_model}. إعادة المحاولة بدون response_format..."
                            )
                            continue

                        # Case 4: Other Errors
                        else:
                            logger.warning(
                                f"تعذر استخدام النموذج {target_model} عبر Z.AI (السبب: {exc}). جاري التبديل للمفتاح/النموذج التالي..."
                            )
                            break

        raise ValueError(f"فشلت جميع محاولات الصياغة عبر Z.AI (GLM). الخطأ الأخير: {last_exception}")

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
        Convert article_examples.json into a compact, highly diverse textual
        editorial reference for the model. Caches the result in memory for speed.
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

        # Select 3 diverse representative models across platforms, experts, and educators
        preferred_ids = ["almo3jiz", "abdulrahman_hamid", "mahmoud_elghzawy"]
        selected_articles = [a for a in articles if isinstance(a, dict) and a.get("id") in preferred_ids]
        if not selected_articles:
            selected_articles = [a for a in articles if isinstance(a, dict)][:3]

        reference_blocks = []

        for index, article in enumerate(
            selected_articles,
            start=1
        ):
            title = str(article.get("title", "")).strip()
            lead = str(article.get("lead_paragraph", "")).strip()
            sections = article.get("sections", [])

            block = [
                f"REFERENCE ARTICLE {index}",
                f"TITLE: {title}",
                f"LEAD: {lead}"
            ]

            if isinstance(sections, list):
                # Pick up to 4 key sections to maintain prompt conciseness
                for section in sections[:4]:
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
        raw_notes_or_name: str = "",
        phone_or_raw: str = "",
        raw_notes: str = "",
        raw_source: str = "",
        client_name: str = "",
        client_phone: str = "",
        api_key: Optional[str] = None
    ) -> dict:

        # ------------------------------------------------------
        # API KEY RESOLUTION & ISOLATION
        # ------------------------------------------------------
        active_client = None
        clean_key = (api_key or "").strip()
        if clean_key:
            try:
                active_client = OpenAI(api_key=clean_key, base_url=self.zai_base_url)
            except Exception as ce:
                raise ValueError(f"تعذر تهيئة مفتاح Z.AI الممرر: {ce}")
        elif self.zai_clients:
            active_client = self.zai_clients[0]
        else:
            raise ValueError(
                "⚠️ مفتاح Z.AI API الخاص بك غير محدد! "
                "يرجى إدخال وتفعيل مفتاحك الشخصي في الإعدادات قبل البدء في الصياغة والنشر."
            )

        # ======================================================
        # ARGUMENT RESOLUTION & BACKWARD COMPATIBILITY
        # ======================================================

        if raw_source:
            actual_raw_notes = raw_source
            actual_name = client_name or raw_notes_or_name
            actual_phone = client_phone or phone_or_raw
        elif raw_notes:
            actual_raw_notes = raw_notes
            actual_name = client_name or raw_notes_or_name
            actual_phone = client_phone or phone_or_raw
        elif (
            phone_or_raw
            and len(phone_or_raw) > 30
        ):
            actual_raw_notes = phone_or_raw
            actual_name = client_name or raw_notes_or_name
            actual_phone = client_phone or ""
        else:
            actual_raw_notes = raw_notes_or_name
            actual_name = (
                client_name
                or (phone_or_raw if len(phone_or_raw) < 30 else "")
            )
            actual_phone = client_phone or ""

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

        from services.whatsapp_service import extract_preferred_whatsapp_phone

        if not actual_phone:
            actual_phone = extract_preferred_whatsapp_phone(actual_raw_notes)

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

        system_prompt = f"""CRITICAL FORMATTING REQUIREMENT:
Your response MUST BE A SINGLE VALID RAW JSON OBJECT ONLY.
DO NOT output any reasoning, thinking, step-by-step analysis, introductory text, preamble, or code fences.
DO NOT write "Analyze the Request", "Role", "Task", or any English text before or after the JSON.
Your output MUST start immediately with the character '{{' and end with '}}'.

You are the Senior Editor and Lead Journalist of "{self.NEWSPAPER_NAME}".

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
NON-REPETITION MANDATE (مبدأ عدم التكرار الصارم — منع الحشو والدوران اللفظي)
============================================================

CRITICAL EDITORIAL DIRECTIVE:
You are strictly forbidden from producing repetitive or redundant text. Every paragraph, subheading, and sentence MUST add unique informational and journalistic value.

Apply these non-repetition rules strictly:

1. ZERO IDEA REDUNDANCY (منع تكرار الأفكار والمعلومات):
   - Never restate facts or concepts that were already stated in the lead paragraph or in previous sections.
   - Once a fact (e.g. professional degree, specialization, year, program name, or feature) is introduced, do NOT explain it again in subsequent sections under a different title.
   - Prohibit circular paraphrasing (إعادة تدوير نفس الكلام بصياغات مختلفة): each section must progress forward with brand new information and distinct angles.

2. ZERO PRAISE CLICHÉ REPETITION (منع تكرار عبارات المدح والإنشاء المبتذل):
   - Editorial recognition must be dignified, journalistic, and grounded in real facts and achievements provided in the source.
   - NEVER repeat praise clichés (such as "من القامات البارزة", "بصمة استثنائية", "رؤية ثاقبة", "علامة مضيئة", "نموذج يُحتذى به") more than ONCE in the entire article.
   - Express excellence through concrete details, documented services, and real-world impact rather than empty superlatives.

3. DYNAMIC SECTION STRUCTURE (مرونة عدد الأقسام حسب عمق المعطيات المتاحة):
   - The article should contain 4 to 6 focused, information-dense sections (or 3 to 4 sections if the input notes are very concise).
   - NEVER force 7 or 8 artificial sections when data is sparse, as this forces severe repetition and filler.
   - Each section must tackle ONE distinct, meaningful angle:
     * Angle A: News context & core offering (ما يقدمه الكيان أو الشخصية وأهميته الراهنة).
     * Angle B: Professional methodology & operational depth (الأسلوب المتبع، المحاور، آليات التنفيذ).
     * Angle C: Target audience & practical market impact (الفئات المستفيدة، القيمة التطبيقية، وسوق العمل).
     * Angle D: Current activities, upcoming programs, or distinctive features (المزايا النوعية، البرامج الحالية).
     * Angle E: Distinct journalistic synthesis / future outlook (الرؤية المستقبلية أو القيمة المستدامة).

4. VARIED JOURNALISTIC TRANSITIONS (تنوع أدوات الربط والافتتاحيات):
   - Do NOT start multiple paragraphs with the same phrasing (e.g., repeating "وتأتي هذه...", "وتسعى...", "ويؤكد...").
   - Employ varied, natural journalistic transitions:
     "وفي سياق متصل...", "وعلى صعيد البرامج والمبادرات...", "وحول آليات العمل والمنهجية...", "وبالانتقال إلى الجانب التطبيقي...", "ويرتكز هذا التوجه على...", "وفيما يتعلق بمتطلبات الفئة المستهدفة...", "ومع تزايد الحاجة إلى...".

5. SMART SUBJECT REFERENCING (ذكاء الإشارة إلى الشخصية أو الكيان):
   - Do NOT repeat the full name of the subject at the beginning of every single sentence or paragraph.
   - Use varied natural Arabic references: professional title (الخبير / المدرب / المتخصص / المحاضر / الأستاذ), natural pronouns (موضحاً / مؤكداً / مشيراً إلى أن), and contextual references.

6. JOURNALISTIC CONCLUSION (خاتمة تحليلية رصينة وليست تكراراً لما سبق):
   - The closing section is a synthesis of value and forward-looking relevance, NOT a redundant recap of earlier paragraphs.
   - Keep it concise, focused, and impactful (1 to 2 dense paragraphs).

============================================================
ARTICLE STRUCTURE & HEADINGS
============================================================

The article MUST contain:
1. A strong journalistic title (Google SERP optimized: "[Subject Name]..[News Hook with Keyword]").
2. One compelling lead paragraph (answers core Ws, introduces **جريدة تحت الضوء الإخبارية**).
3. 4 to 6 rich, information-dense editorial sections (adapted dynamically to source depth).
4. A distinct, non-repetitive closing section.
5. A contact section only if phone/contact data exists.

Subheadings must be:
- Descriptive, journalistic, and informative (e.g. "تدريب عملي يركز على التطبيق المباشر", "رؤية تجمع بين التخصص وسوق العمل").
- Specific to the section's unique content.
- Completely free of trailing punctuation (no periods, colons, or dashes at the end).
- Never generic like "نبذة عن الشخص" or "الخدمات" or "الخاتمة".

============================================================
ARTICLE LENGTH & INFORMATION DENSITY
============================================================

The final article body MUST contain between:
{self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} CHARACTERS (typically 1500-2800 characters).
Every single paragraph must be rich with concrete information, clear explanations, and journalistic context.
DO NOT pad or stretch the text with repetitive sentences. Depth comes from thorough explanation of the facts provided.

============================================================
PARAGRAPH STYLE & JOURNALISTIC FLOW
============================================================

Write medium-length journalistic paragraphs (2-4 sentences each).

Avoid:
- one-line paragraphs
- huge unbroken walls of text
- repetitive wording or circular explanations
- excessive promotional or sales language
- social-media slang or casual phrasing
- emojis

Maintain an objective, authoritative Egyptian journalistic voice: informative, engaging, and credible.

============================================================
DIGNIFIED JOURNALISTIC RECOGNITION (الثناء والتقدير المهني الرصين)
============================================================

احرص على إبراز صاحب الخبر أو الكيان بأعلى درجات التقدير الصحفي الرصين والمستحق، مع الالتزام التام بالقواعد التالية:
1. الثناء القائم على الوقائع:
   - أبرز كفاءة الشخصية وتفوقها من خلال شرح إنجازاتها، تخصصها، وخبراتها العملية الواردة في المصدر.
2. عدم تكرار كليشيهات المدح:
   - ممنوع منعاً باتاً تكرار عبارات الثناء الفضفاضة في كل فقرة. ضع التقدير في موضعه الطبيعي بأسلوب وقور ومقنع.
3. التوازن بين النبرة الاحتفائية والمصداقية الصحفية:
   - اجعل المقال يمنح الشخصية حضوراً مميزاً ومهيباً يُشعر القارئ بقيمتها المهنية الحقيقية دون مبالغة فجة.

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
CLIENT PHONE SELECTION RULES (STRICT)
============================================================

When extracting the "client_phone":
- If the source notes contain multiple phone numbers:
  1. Priority 1: Select the phone number that has "واتساب" or "واتس" or "WhatsApp" or any indication stating it is WhatsApp.
  2. Priority 2: If multiple numbers exist but NONE has a WhatsApp indicator, select the FIRST phone number appearing in the message.
- Normalize to valid Egyptian phone format (e.g. 01xxxxxxxxx or 201xxxxxxxxx).

============================================================
GOOGLE SEO 2026 STANDARDS & SEARCH ARCHITECTURE (STRICT)
============================================================

1. SEARCH INTENT & KEYWORD STRATEGY:
   - Identify the user's explicit search intent (Navigational / Informational / Commercial).
   - "focus_keyword": Extract/formulate exactly 1 primary search keyword (2-4 words) that users search on Google (e.g., "أفضل مدرس فلسفة بالمنصورة", "عيادة جراحة العظام بالتجمع").
   - "lsi_keywords": Generate 3 to 5 semantically related keywords (LSI) that support the primary keyword and will be naturally woven into subheadings and paragraphs.

2. TITLE RULES — GOOGLE SERP OPTIMIZATION (STRICT REQUIREMENT):
   - MANDATORY NAME & KEYWORD INCLUSION (إجبارية ذكر اسم الشخص أو الكيان في بداية العنوان):
     The headline (`title`) MUST start with or prominently contain the name of the person or entity (e.g., `client_name`) extracted from raw data, followed by a journalistic hook with the focus keyword.
   - SEPARATOR RULE (قاعدة الفاصل الصحفي المعتمد):
     استخدم دائماً نقطتين متتاليتين ".." كفاصل مباشر بين اسم الشخص/الكيان والعنوان الصحفي الجاذب دون مسافات تفصل النقطتين (أو كما في المثال: اسم الشخص..فكرة الخبر).
     ممنوع استخدام النقطتين الرأسيتين ":" بعد اسم الشخص أو في العنوان إطلاقاً.
   - EXACT STRUCTURE:
     `"[اسم الشخص أو الكيان]..[فكرة صحفية جاذبة تتضمن الكلمة المفتاحية والقيمة المضافة]"`
   - LENGTH:
     Strictly between 45 and 60 characters for complete SERP display without truncation on mobile and desktop Google Search.
   - EXAMPLES:
     - `أحمد حجاج..قانون الإجراءات الجنائية الجديد يغير موازين العدالة`
     - `أ/ شريف الحصافي..منهجية مبتكرة لتعليم الفلسفة للثانوية العامة`
     - `د. أحمد طلبة..استراتيجيات حديثة لتطوير الرعاية الصحية في مصر`
     - `أكاديمية الفكر الرقمي..حلول تدريبية لتأهيل الكوادر الإعلامية`
     - `Dr. Mark Johnson..Launching Advanced AI Coding Programs in Cairo`
   - FALLBACK ONLY IF NO NAME EXISTS:
     If and only if there is absolutely no person name or brand in the raw data, construct an intent-driven topic headline.

3. META DESCRIPTION (CTR OPTIMIZATION):
   - "meta_description": Strictly 135 to 155 characters.
   - Must contain the "focus_keyword" in the first 70 characters.
   - Must summarize the core news value concisely and end with a clear action/hook (e.g., "اقرأ التفاصيل الكاملة عبر جريدة تحت الضوء.").
   - Do NOT use quotes or bold markers inside meta_description.

4. CONTENT STRUCTURE (INVERTED PYRAMID & SEMANTIC HIERARCHY):
   - Lead Paragraph: Direct answers to the 5 Ws and 1 H (من، ماذا، متى، أين، لماذا، كيف).
     The "focus_keyword" must appear naturally in the first 80 words.
     Must introduce **جريدة تحت الضوء الإخبارية** as the reporting authority.
   - Subheadings ("subheading"): 3 to 5 clear, descriptive subheadings. Each subheading MUST answer a specific user query and contain secondary/LSI keywords.

5. ARTICLE LENGTH & EDITORIAL DEPTH:
   - Total article length must be strictly between {self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} characters (sweet spot: ~1800-2600 characters).
   - High information density, zero filler words, professional Arabic journalistic tone.

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
  "focus_keyword": "",
  "lsi_keywords": [""],
  "meta_description": "",
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
FINAL QUALITY CHECK (INTERNAL MEMORY ONLY - DO NOT OUTPUT TEXT)
============================================================

Silently verify the following points in your memory before outputting the raw JSON:

- Article is in Arabic.
- Article is between {self.MIN_ARTICLE_CHARS} and {self.MAX_ARTICLE_CHARS} characters (target ~1800-2600 chars).
- 4-6 meaningful, non-repetitive sections exist with informative subheadings (free of trailing punctuation).
- ZERO repetition: Absolutely no repeated facts, sentences, praise clichés, or circular paraphrasing across sections or between lead and body.
- focus_keyword, lsi_keywords, and meta_description (135-155 chars) are provided.
- Title starts with subject name, uses '..' as separator without colon ':', and is 45-60 characters.
- Introduction begins with the required newspaper identity.
- **جريدة تحت الضوء الإخبارية** is correctly bolded in body text.
- No HTML exists.
- No bold exists in title or subheadings.
- Facts are preserved. No unsupported major facts were invented.
- Exactly one Arabic label exists from the allowed list.
- Slug is lowercase English and ends with .html.
- Contact details are included only when available.
- JSON is valid.

CRITICAL FINAL REMINDER:
DO NOT PRINT OR WRITE DOWN ANY VERIFICATION STEPS OR TEXT.
OUTPUT RAW VALID JSON ONLY, STARTING IMMEDIATELY WITH '{{' AND ENDING WITH '}}'.
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

        # Build prioritized list of Z.AI GLM model candidates
        model_candidates = [("zai", self.model)]
        for m in self.FALLBACK_MODELS:
            cand = ("zai", m)
            if cand not in model_candidates:
                model_candidates.append(cand)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response, provider_used, model_used, parsed_data = self._create_chat_completion(
            messages=messages,
            model_candidates=model_candidates,
            temperature=0.2,
            max_tokens=3500,
            validate_json=True,
            override_client=active_client
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
        # MANDATORY TITLE SAFEGUARD (Subject Name & '..' Separator)
        # ======================================================
        title = str(parsed_data.get("title", "")).strip()
        # Convert colon or dash separators after client name to '..'
        title = re.sub(r"\s*:\s*", "..", title)
        title = re.sub(r"\s*\.{2,}\s*", "..", title)
        title = re.sub(r"\s+-\s+", "..", title)

        if client_name and client_name.strip() and client_name not in ["خبر صحفي", "عميل تليجرام", ""]:
            clean_name_word = re.sub(r"^(أ/|أ\.|د/|د\.|م/|م\.|ك/|ك\.|أستاذ/|دكتور/|مهندس/|كابتن/)\s*", "", client_name).strip()
            if clean_name_word and clean_name_word.lower() not in title.lower():
                if ".." in title:
                    rest_title = title.split("..", 1)[1].strip()
                    title = f"{client_name}..{rest_title}"
                else:
                    title = f"{client_name}..{title}"
            elif ".." in title:
                parts = title.split("..", 1)
                title = f"{parts[0].strip()}..{parts[1].strip()}"
        elif ".." in title:
            parts = title.split("..", 1)
            title = f"{parts[0].strip()}..{parts[1].strip()}"
        parsed_data["title"] = title

        # ======================================================
        # CLIENT PHONE
        # ======================================================

        from services.whatsapp_service import extract_preferred_whatsapp_phone

        preferred_notes_phone = extract_preferred_whatsapp_phone(actual_raw_notes)

        client_phone = (
            preferred_notes_phone
            or parsed_data.get(
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
        # ARTICLE LENGTH ACCEPTANCE (DIRECT PASS - AS-IS)
        # ======================================================

        logger.info(
            f"تم اعتماد المقال مباشرة بطول {article_length} حرف دون إعادة ضبط أو اقتطاع."
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
            res = json.loads(cleaned_content, strict=False)
            if isinstance(res, dict):
                return res
        except json.JSONDecodeError:
            pass

        # 2. Extract from first '{' to last '}'
        start_idx = cleaned_content.find("{")
        end_idx = cleaned_content.rfind("}")
        if start_idx != -1:
            snippet = cleaned_content[start_idx:end_idx + 1] if end_idx > start_idx else cleaned_content[start_idx:]

            # Direct parse snippet
            try:
                res = json.loads(snippet, strict=False)
                if isinstance(res, dict):
                    return res
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
        """Bypassed: Articles are published directly as-is without length adjustment."""
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

        # Build prioritized list of Z.AI GLM model candidates
        model_candidates = [("zai", self.model)]
        for m in self.FALLBACK_MODELS:
            cand = ("zai", m)
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
            response, provider_used, model_used, adjusted = self._create_chat_completion(
                messages=messages,
                model_candidates=model_candidates,
                temperature=0.2,
                max_tokens=3500,
                validate_json=True
            )
            self.validate_article(adjusted)
            return adjusted
        except Exception as exc:
            logger.error(f"فشلت جميع محاولات محاذاة الطول ({exc}). سيتم اعتماد المقال الأولي.")
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

        logger.info(
            f"طول المقال النهائي المعتمد: {article_length} حرف (تم قبوله بالكامل كما هو)."
        )

    # ==========================================================
    # PHONE NORMALIZATION
    # ==========================================================

    @staticmethod
    def normalize_egyptian_phone(
        phone: str
    ) -> str:
        from services.whatsapp_service import clean_egyptian_phone
        return clean_egyptian_phone(phone)

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
    # REPETITION DEDUPLICATION & CONTENT CLEANING HELPERS
    # ==========================================================

    @staticmethod
    def clean_arabic_for_comparison(text: str) -> str:
        """Normalizes Arabic text to compare sentence and heading similarity."""
        if not text:
            return ""
        s = re.sub(r'[\*\#\"\'\`]', '', str(text)).strip()
        s = re.sub(r'[إأآا]', 'ا', s)
        s = re.sub(r'[ة]', 'ه', s)
        s = re.sub(r'[ى]', 'ي', s)
        s = re.sub(r'[^\w\s]', '', s)
        return " ".join(s.split())

    @classmethod
    def is_near_duplicate(cls, s1: str, s2: str, threshold: float = 0.80) -> bool:
        """Detects identical or near-identical sentences or phrases."""
        c1 = cls.clean_arabic_for_comparison(s1)
        c2 = cls.clean_arabic_for_comparison(s2)
        if not c1 or not c2:
            return False
        if c1 == c2:
            return True
        if len(c1) >= 25 and len(c2) >= 25:
            if c1 in c2 or c2 in c1:
                return True
        return SequenceMatcher(None, c1, c2).ratio() >= threshold

    @classmethod
    def clean_praise_cliches(cls, text: str, seen_praise: Set[str]) -> str:
        """Caps repetitive praise clichés across the article to avoid redundant hyperbole."""
        cleaned = str(text)
        for pattern in cls.REPETITIVE_PRAISE_PATTERNS:
            matches = list(re.finditer(pattern, cleaned))
            if not matches:
                continue
            if pattern in seen_praise:
                cleaned = re.sub(pattern, "المتخصص المشهود له بالخبرة", cleaned)
            else:
                seen_praise.add(pattern)
                if len(matches) > 1:
                    first_match = matches[0]
                    prefix = cleaned[:first_match.end()]
                    suffix = cleaned[first_match.end():]
                    suffix = re.sub(pattern, "المتخصص المشهود له بالخبرة", suffix)
                    cleaned = prefix + suffix
        return cleaned

    @classmethod
    def deduplicate_sentences_in_paragraphs(
        cls,
        paragraphs: List[str],
        seen_sentences: Set[str],
        seen_praise: Set[str]
    ) -> List[str]:
        """
        Removes redundant or near-duplicate sentences across paragraphs,
        softens repeated praise, and varies repetitive consecutive openers.
        """
        cleaned_paragraphs = []
        for p in paragraphs:
            p_str = str(p).strip()
            if not p_str:
                continue

            p_str = cls.clean_praise_cliches(p_str, seen_praise)

            sentences = re.split(r'([.؟!]\s*|\n+)', p_str)
            reconstructed = []
            i = 0
            while i < len(sentences):
                sent = sentences[i].strip()
                punct = sentences[i+1] if i + 1 < len(sentences) else ""
                i += 2
                if not sent:
                    continue

                if len(sent) < 15:
                    reconstructed.append(sent + punct)
                    continue

                is_dup = False
                for seen in seen_sentences:
                    if cls.is_near_duplicate(sent, seen):
                        is_dup = True
                        break

                if not is_dup:
                    seen_sentences.add(sent)
                    reconstructed.append(sent + punct)

            final_p = " ".join("".join(reconstructed).split())
            if final_p:
                cleaned_paragraphs.append(final_p)

        # Vary consecutive identical openers (e.g. وتأتي هذه... followed by وتأتي هذه...)
        for idx in range(1, len(cleaned_paragraphs)):
            prev_p = cleaned_paragraphs[idx - 1]
            curr_p = cleaned_paragraphs[idx]
            prev_words = prev_p.split()[:2]
            curr_words = curr_p.split()[:2]
            if prev_words and curr_words and prev_words == curr_words:
                alt = cls.ALTERNATIVE_TRANSITIONS[(idx - 1) % len(cls.ALTERNATIVE_TRANSITIONS)]
                cleaned_paragraphs[idx] = alt + " ".join(curr_p.split()[2:])

        return cleaned_paragraphs

    # ==========================================================
    # ARTICLE CONTENT NORMALIZATION
    # ==========================================================

    @classmethod
    def normalize_article_content(
        cls,
        parsed_data: dict
    ) -> dict:

        seen_sentences: Set[str] = set()
        seen_praise: Set[str] = set()
        seen_subheadings: Set[str] = set()

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

        # Register lead sentences to prevent body from repeating them
        clean_lead_list = cls.deduplicate_sentences_in_paragraphs(
            [lead],
            seen_sentences,
            seen_praise
        )
        lead = clean_lead_list[0] if clean_lead_list else lead

        # Also register individual clauses of the lead so body cannot repeat them
        for clause in re.split(r'[,،؛\.\?!]+', lead):
            cl = clause.strip()
            if len(cl) >= 25:
                seen_sentences.add(cl)

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
            # Strip trailing punctuation (periods, colons, dashes)
            subheading = re.sub(r"[\.،؛:!\?–\-]+$", "", subheading).strip()

            # Deduplicate or differentiate repeated subheadings
            clean_sub = cls.clean_arabic_for_comparison(subheading)
            if clean_sub in seen_subheadings and subheading:
                subheading = f"{subheading} والتطبيقات العملية"
            if clean_sub:
                seen_subheadings.add(clean_sub)

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

            # Deduplicate sentences within section against seen content
            cleaned_paragraphs = cls.deduplicate_sentences_in_paragraphs(
                cleaned_paragraphs,
                seen_sentences,
                seen_praise
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
            seen_items: Set[str] = set()

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

                clean_item_key = cls.clean_arabic_for_comparison(item)
                if clean_item_key and clean_item_key not in seen_items:
                    seen_items.add(clean_item_key)
                    cleaned_items.append(
                        item
                    )

            # --------------------------------------------------
            # Store (only if section has meaningful content)
            # --------------------------------------------------

            if cleaned_paragraphs or cleaned_items:
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
        # Title (Google SERP Clean Formatting)
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

        title = re.sub(r"\s*:\s*", "..", title)
        title = re.sub(r"\s*\.{2,}\s*", "..", title)
        title = re.sub(r"\s+-\s+", "..", title)
        if ".." in title:
            parts = title.split("..", 1)
            title = f"{parts[0].strip()}..{parts[1].strip()}"

        parsed_data[
            "title"
        ] = title.strip()

        # ------------------------------------------------------
        # Focus Keyword (SEO 2026)
        # ------------------------------------------------------
        focus_kw = str(parsed_data.get("focus_keyword", "")).strip()
        focus_kw = re.sub(r'[\*\#\"\'\`]', '', focus_kw).strip()
        if not focus_kw:
            client_name = parsed_data.get("client_name", "")
            if client_name and client_name not in ["خبر صحفي", "عميل تليجرام"]:
                focus_kw = client_name
            else:
                words = title.split()
                focus_kw = " ".join(words[:3]) if words else "أخبار تحت الضوء"
        parsed_data["focus_keyword"] = focus_kw

        # ------------------------------------------------------
        # LSI Keywords
        # ------------------------------------------------------
        raw_lsi = parsed_data.get("lsi_keywords", [])
        if isinstance(raw_lsi, str):
            raw_lsi = [k.strip() for k in raw_lsi.split(",") if k.strip()]
        elif not isinstance(raw_lsi, list):
            raw_lsi = []
        parsed_data["lsi_keywords"] = [re.sub(r'[\*\#\"\'\`]', '', str(k)).strip() for k in raw_lsi if str(k).strip()]

        # ------------------------------------------------------
        # Meta Description (135 - 155 characters)
        # ------------------------------------------------------
        meta_desc = str(parsed_data.get("meta_description", "")).strip()
        meta_desc = re.sub(r'[\*\#\"\'\`]', '', meta_desc).strip()
        if len(meta_desc) < 100:
            lead_clean = re.sub(r'\*\*', '', lead).strip()
            # Extract first sentence or up to 110 chars
            snippet = lead_clean[:110]
            if " " in snippet:
                snippet = snippet.rsplit(" ", 1)[0]
            meta_desc = f"{snippet}.. اقرأ التفاصيل الكاملة عبر جريدة تحت الضوء."

        if len(meta_desc) > 160:
            meta_desc = meta_desc[:150].rsplit(" ", 1)[0] + "..."
        parsed_data["meta_description"] = meta_desc

        # FAQs (Deprecated / Removed)
        parsed_data.pop("faqs", None)

        return parsed_data


# ==============================================================
# GLOBAL SERVICE INSTANCE
# ==============================================================

ai_service = AIService()
