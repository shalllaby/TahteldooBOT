import os
import pickle
import re
import threading
import time
from pathlib import Path
from typing import List, Optional, Dict

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from core.config import Config
from core.logger import logger


SCOPES = ["https://www.googleapis.com/auth/blogger"]


class BloggerAccount:
    """Represents an individual Google/Blogger account with its own token file, service, and concurrency lock."""
    def __init__(self, account_id: int, token_path: Path):
        self.account_id = account_id
        self.token_path = token_path
        self.creds = None
        self.service = None
        self.lock = threading.RLock()
        self.user_email = ""
        self.display_name = ""

    def token_exists(self) -> bool:
        return self.token_path.exists()

    def __repr__(self):
        return f"<BloggerAccount id={self.account_id} path={self.token_path.name} exists={self.token_exists()}>"


class BloggerService:
    """
    Service to handle Google OAuth and Blogger API v3 operations.

    Features:
    - Multi-Account Pool: supports rotating across up to 3 Google/Blogger accounts (Round-Robin).
    - Concurrency Lock: thread-safe token refresh and publishing per account.
    - Automatic Failover: if Account A reaches quota/rate limits, automatically fails over to Account B.
    - Automatic bold formatting for "جريدة تحت الضوء الإخبارية" and **text**.
    """

    NEWSPAPER_NAME = "جريدة تحت الضوء الإخبارية"

    def __init__(self, blog_id: str = None):
        self.blog_id = blog_id or Config.BLOGGER_BLOG_ID
        self.creds = None
        self.service = None
        self._pool_lock = threading.RLock()
        self._rr_index = 0

        # Personal account for Desktop journalists (strictly token.pickle)
        personal_token = Config.TOKEN_FILE if Config.TOKEN_FILE.exists() else (Config.BASE_DIR / "token.pickle")
        if not personal_token.exists():
            personal_token = Config.TOKEN_FILE
        self.personal_account = BloggerAccount(0, personal_token)

        # Multi-Account Pool for Telegram Bot (token_1.pickle, token_2.pickle, token_3.pickle)
        self.accounts: List[BloggerAccount] = []
        self._init_accounts_pool()

    def _init_accounts_pool(self):
        """Initializes account slots for up to 3 Blogger accounts in the Telegram Bot pool (token_1.pickle, token_2.pickle, token_3.pickle)."""
        app_data = Config.APP_DATA_DIR
        base_dir = Config.BASE_DIR

        def find_token(slot: int) -> Path:
            name = f"token_{slot}.pickle"
            if (app_data / name).exists():
                return app_data / name
            if (base_dir / name).exists():
                return base_dir / name
            return app_data / name

        tok1 = find_token(1)
        tok2 = find_token(2)
        tok3 = find_token(3)

        self.accounts = [
            BloggerAccount(1, tok1),
            BloggerAccount(2, tok2),
            BloggerAccount(3, tok3)
        ]

    def get_active_accounts(self) -> List[BloggerAccount]:
        """Returns active pool accounts for Telegram Bot. Falls back to personal account if no pool tokens exist."""
        self._init_accounts_pool()
        active = [acc for acc in self.accounts if acc.token_exists()]
        if not active:
            if self.personal_account.token_exists():
                return [self.personal_account]
            return [self.accounts[0]]
        return active

    # ==========================================================
    # AUTHENTICATION
    # ==========================================================

    def authenticate_account(self, account: BloggerAccount, allow_browser: bool = False):
        """Authenticates a specific BloggerAccount slot with thread safety."""
        with account.lock:
            token_path = account.token_path
            creds_path = Config.CREDENTIALS_FILE

            # 1. Load existing token
            if token_path.exists():
                try:
                    with open(token_path, "rb") as token:
                        account.creds = pickle.load(token)
                except Exception as e:
                    logger.warning(f"[حساب بلوجر {account.account_id}] فشل تحميل OAuth Token ({e}).")
                    account.creds = None

            # 2. Refresh expired token
            if account.creds and account.creds.expired and account.creds.refresh_token:
                try:
                    account.creds.refresh(Request())
                    with open(token_path, "wb") as token:
                        pickle.dump(account.creds, token)
                    logger.info(f"[حساب بلوجر {account.account_id}] تم تحديث OAuth Token بنجاح.")
                except Exception as e:
                    logger.warning(f"[حساب بلوجر {account.account_id}] فشل تحديث OAuth Token تلقائياً ({e}).")
                    account.creds = None

            # 3. Interactive authentication if missing or invalid
            if not account.creds or not account.creds.valid:
                if not allow_browser:
                    raise PermissionError(
                        f"[حساب بلوجر {account.account_id}] التوكن غير صالح أو منتهي الصلاحية ويتطلب إعادة تسجيل الدخول عبر المتصفح."
                    )

                if not os.path.exists(creds_path):
                    raise FileNotFoundError(f"ملف credentials.json غير موجود في: {creds_path}")

                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                account.creds = flow.run_local_server(port=0)

                with open(token_path, "wb") as token:
                    pickle.dump(account.creds, token)

            # 4. Build Blogger service
            account.service = build("blogger", "v3", credentials=account.creds)

            logger.info(f"[حساب بلوجر {account.account_id}] تم الاتصال بـ Blogger API بنجاح.")
            return account.service

    def authenticate(self, allow_browser: bool = True):
        """
        Authenticates the journalist's personal Google/Blogger account for the Desktop Application.
        Strictly writes and reads from Config.TOKEN_FILE (token.pickle).
        """
        self.personal_account.token_path = Config.TOKEN_FILE if Config.TOKEN_FILE.exists() else (Config.BASE_DIR / "token.pickle")
        if not self.personal_account.token_path.exists():
            self.personal_account.token_path = Config.TOKEN_FILE

        service = self.authenticate_account(self.personal_account, allow_browser=allow_browser)
        self.creds = self.personal_account.creds
        self.service = self.personal_account.service
        return service

    # ==========================================================
    # ACCOUNT & BLOG MANAGEMENT
    # ==========================================================

    def is_authenticated(self) -> bool:
        """
        Checks if the journalist has a valid personal Google/Blogger OAuth token for Desktop.
        Does NOT rely on Telegram Bot pool accounts.
        """
        if self.creds and self.creds.valid and self.service:
            return True

        token_path = Config.TOKEN_FILE
        if not token_path.exists() and (Config.BASE_DIR / "token.pickle").exists():
            token_path = Config.BASE_DIR / "token.pickle"

        if token_path.exists():
            try:
                with open(token_path, "rb") as token:
                    creds = pickle.load(token)
                if creds and creds.valid:
                    self.creds = creds
                    self.personal_account.creds = creds
                    if not self.service:
                        self.service = build("blogger", "v3", credentials=self.creds)
                        self.personal_account.service = self.service
                    return True
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, "wb") as token:
                        pickle.dump(creds, token)
                    self.creds = creds
                    self.personal_account.creds = creds
                    if not self.service:
                        self.service = build("blogger", "v3", credentials=self.creds)
                        self.personal_account.service = self.service
                    return True
            except Exception as e:
                logger.warning(f"التحقق من حالة توثيق الحساب الشخصي فشل: {e}")
        return False

    def get_user_blogs(self) -> list:
        """
        Fetches all Blogger blogs accessible to the authenticated Google account.
        Returns a list of dicts: [{'id': '...', 'name': '...', 'url': '...'}]
        """
        if not self.service:
            if not self.is_authenticated():
                self.authenticate()

        if not self.service:
            return []

        try:
            logger.info("جاري استعلام قائمة المدونات الخاصة بالحساب...")
            blogs_response = self.service.blogs().listByUser(userId="self").execute()
            items = blogs_response.get("items", [])
            result = []
            for b in items:
                result.append({
                    "id": b.get("id"),
                    "name": b.get("name", "مدونة بدون عنوان"),
                    "url": b.get("url", "")
                })
            logger.info(f"تم العثور على {len(result)} مدونة للحساب.")
            return result
        except Exception as e:
            logger.error(f"فشل جلب قائمة المدونات: {e}")
            raise e

    def get_user_info(self) -> dict:
        """
        Fetches authenticated user profile info if available.
        """
        if not self.service:
            if not self.is_authenticated():
                return {}

        try:
            user_res = self.service.users().get(userId="self").execute()
            display_name = user_res.get("displayName", "")
            user_id = user_res.get("id", "")
            return {"display_name": display_name, "id": user_id}
        except Exception as e:
            logger.warning(f"تعذر جلب معلومات الحساب: {e}")
            return {}

    def get_current_user_profile(self) -> dict:
        """
        Returns the profile of the currently authenticated desktop user.
        Dict: {"id": str, "name": str, "email": str, "is_auth": bool}
        """
        if self.is_authenticated():
            info = self.get_user_info()
            name = info.get("display_name") or Config.EDITOR_NAME or "محرر مسجل"
            uid = str(info.get("id") or name)
            email = Config.GOOGLE_USER_EMAIL or ""
            return {"id": uid, "name": name, "email": email, "is_auth": True}
        return {
            "id": Config.EDITOR_NAME or "desktop_user",
            "name": Config.EDITOR_NAME or "صحفي غير مسجل",
            "email": "",
            "is_auth": False
        }

    def get_google_account_details(self) -> dict:
        """
        Extracts details of the currently authenticated Google/Blogger account:
        Email, Display Name, Profile Picture / Avatar, and authentication status.
        """
        if not self.is_authenticated():
            return {
                "is_connected": False,
                "email": "",
                "name": "",
                "picture": ""
            }

        email = ""
        name = ""
        picture = ""

        # 1. Try decoding id_token (instant, no network call)
        creds = self.creds or self.personal_account.creds
        if creds and hasattr(creds, "id_token") and creds.id_token:
            try:
                import base64
                import json
                parts = creds.id_token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    payload = json.loads(base64.b64decode(padded).decode("utf-8"))
                    email = payload.get("email", "")
                    name = payload.get("name", "")
                    picture = payload.get("picture", "")
            except Exception as e:
                logger.warning(f"Could not parse id_token payload: {e}")

        # 2. If email or name missing, try oauth2 userinfo API
        if (not email or not name) and creds and creds.valid:
            try:
                user_info_service = build("oauth2", "v2", credentials=creds)
                u = user_info_service.userinfo().get().execute()
                email = email or u.get("email", "")
                name = name or u.get("name", "")
                picture = picture or u.get("picture", "")
            except Exception as e:
                logger.warning(f"Could not fetch userinfo via oauth2 API: {e}")

        # 3. Fallback to Blogger user profile
        if not name and self.service:
            try:
                b_user = self.service.users().get(userId="self").execute()
                name = b_user.get("displayName", "")
            except Exception:
                pass

        if not email and Config.GOOGLE_USER_EMAIL:
            email = Config.GOOGLE_USER_EMAIL

        return {
            "is_connected": True,
            "email": email,
            "name": name or (email.split("@")[0] if email else "مستخدم Google"),
            "picture": picture
        }

    def disconnect(self, clear_blog_id: bool = False):
        """
        Disconnects the personal Google account and clears local credentials.
        """
        for token_path in [Config.TOKEN_FILE, Config.BASE_DIR / "token.pickle"]:
            if os.path.exists(token_path):
                try:
                    os.remove(token_path)
                    logger.info(f"تم حذف ملف OAuth token.pickle الشخصي بنجاح: {token_path}")
                except Exception as e:
                    logger.error(f"فشل حذف token.pickle: {e}")

        self.personal_account.creds = None
        self.personal_account.service = None
        self.creds = None
        self.service = None
        if clear_blog_id:
            self.blog_id = ""
            Config.clear_blogger_config()
        else:
            Config.GOOGLE_USER_EMAIL = ""
            try:
                Config.update_env("GOOGLE_USER_EMAIL", "")
            except Exception:
                pass
        logger.info("تم تسجيل خروج الحساب الشخصي من Google بنجاح.")

    def get_quota_info(self) -> dict:
        """
        Queries Google Cloud Service Usage / Monitoring API for Blogger API Quota usage,
        falling back to local DB tracking if direct API call is unpermitted or offline.
        """
        project_id = "blogeer-506200"
        creds_path = Config.CREDENTIALS_FILE
        if os.path.exists(creds_path):
            try:
                import json
                with open(creds_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    installed = cdata.get("installed") or cdata.get("web") or {}
                    project_id = installed.get("project_id") or project_id
            except Exception:
                pass

        daily_limit = 10000
        used_count = 0
        is_live_google = False

        if self.is_authenticated() and self.creds:
            try:
                su_service = build("serviceusage", "v1", credentials=self.creds)
                res = su_service.services().consumerQuotaMetrics().list(
                    parent=f"projects/{project_id}/services/blogger.googleapis.com"
                ).execute()
                metrics = res.get("metrics", [])
                for m in metrics:
                    for bucket in m.get("quotaBuckets", []):
                        if "effectiveLimit" in bucket:
                            daily_limit = int(bucket.get("effectiveLimit", daily_limit))
                        if "usage" in bucket:
                            used_count = int(bucket.get("usage", 0))
                            is_live_google = True
            except Exception as su_err:
                logger.debug(f"Direct ServiceUsage API query fallback: {su_err}")

        if not is_live_google:
            try:
                from database.db import db
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT count(*) FROM articles 
                        WHERE DATE(published_at) = DATE('now', 'localtime')
                        AND blogger_status = 'PUBLISHED'
                    """)
                    row = cursor.fetchone()
                    used_count = row[0] if row else 0
            except Exception as db_err:
                logger.warning(f"Failed to calculate local quota: {db_err}")

        remaining = max(0, daily_limit - used_count)
        percentage = min(100.0, round((used_count / daily_limit) * 100, 1))

        if used_count >= daily_limit:
            status = "EXHAUSTED"
            status_text = f"🔴 الكوتا منتهية (0/{daily_limit:,})"
        elif percentage >= 85:
            status = "WARNING"
            status_text = f"🟡 كوتا منخفضة ({remaining:,} متبقي)"
        else:
            status = "OK"
            status_text = f"🟢 الكوتا: {remaining:,}/{daily_limit:,}"

        return {
            "used": used_count,
            "limit": daily_limit,
            "remaining": remaining,
            "percentage": percentage,
            "status": status,
            "status_text": status_text,
            "is_live_google": is_live_google
        }


    # ==========================================================
    # HTML / BOLD FORMATTER
    # ==========================================================


    def format_article_html(self, content: str) -> str:
        """
        Converts AI markdown bold markers (**text**) to clean <strong>text</strong> HTML tags.
        Safely bolds "جريدة تحت الضوء الإخبارية" with explicit font-family matching.
        """
        if not content:
            return ""

        content = str(content).strip()
        from services.article_formatter import ArticleFormatter

        # 1. Convert ***text*** and **text** into strong with explicit font
        content = re.sub(r"\*\*\*(.*?)\*\*\*", f"{ArticleFormatter.STRONG_OPEN}\\1</strong>", content, flags=re.DOTALL)
        content = re.sub(r"\*\*(.*?)\*\*", f"{ArticleFormatter.STRONG_OPEN}\\1</strong>", content, flags=re.DOTALL)
        content = content.replace("**", "")

        # 2. Convert any <b> or plain <strong> tags to uniform strong with explicit font
        content = re.sub(r"<\s*b\b[^>]*>", ArticleFormatter.STRONG_OPEN, content, flags=re.IGNORECASE)
        content = re.sub(r"<\s*/\s*b\s*>", "</strong>", content, flags=re.IGNORECASE)
        content = re.sub(r"<\s*strong\s*>", ArticleFormatter.STRONG_OPEN, content, flags=re.IGNORECASE)

        # 3. Safely bold newspaper name if present outside of existing strong tags
        content = ArticleFormatter._bold_phrase_safely(content, self.NEWSPAPER_NAME)

        # 4. Clean any nested or duplicate <strong> tags
        prev = None
        while prev != content:
            prev = content
            content = re.sub(r"<strong\b[^>]*>\s*<strong\b[^>]*>(.*?)</strong>\s*<\/strong>", f"{ArticleFormatter.STRONG_OPEN}\\1</strong>", content, flags=re.DOTALL | re.IGNORECASE)

        return content

    # ==========================================================
    # PUBLISH POST (PERSONAL FOR DESKTOP / POOL FOR TELEGRAM)
    # ==========================================================

    def publish_post(
        self,
        title: str,
        content_html: str,
        labels: list = None,
        is_draft: bool = False,
        meta_description: str = None,
        use_pool: bool = False
    ) -> dict:
        """
        Publishes a new post to Blogger.
        - If use_pool=False (Desktop App): Uses strictly the journalist's personal account.
          Raises PermissionError if the journalist has not logged in with their personal account.
        - If use_pool=True (Telegram Bot): Uses the multi-account Round-Robin pool across up to 3 accounts.
        """

        active_blog_id = self.blog_id or Config.BLOGGER_BLOG_ID
        if not active_blog_id:
            raise ValueError("لم يتم اختيار أي مدونة للنشر عليها. يرجى الدخول إلى شاشة الإعدادات وربط حساب Google/Blogger واختيار المدونة.")

        # Format article HTML
        logger.info("جاري تجهيز محتوى المقال قبل إرساله إلى Blogger...")
        formatted_content = self.format_article_html(content_html)

        body = {
            "kind": "blogger#post",
            "blog": {"id": active_blog_id},
            "title": title,
            "content": formatted_content,
            "labels": labels or []
        }

        if meta_description and str(meta_description).strip():
            body["customMetaData"] = str(meta_description).strip()

        # ── 1. PERSONAL ACCOUNT MODE (Desktop Application) ──
        if not use_pool:
            if not self.is_authenticated():
                raise PermissionError("⚠️ يجب على الصحفي تسجيل الدخول بحسابه الشخصي في Blogger أولاً من صفحة الإعدادات قبل النشر.")

            with self.personal_account.lock:
                if not self.personal_account.service or not self.personal_account.creds or not self.personal_account.creds.valid:
                    self.authenticate(allow_browser=False)

                if not self.personal_account.service:
                    raise PermissionError("⚠️ تعذر الاتصال بـ Blogger بحسابك الشخصي. يرجى تسجيل الدخول مجدداً من صفحة الإعدادات.")

                posts_resource = self.personal_account.service.posts()
                response = None

                for attempt in range(1, 4):
                    try:
                        request = posts_resource.insert(
                            blogId=active_blog_id,
                            body=body,
                            isDraft=is_draft
                        )
                        response = request.execute()
                        break
                    except Exception as req_err:
                        if attempt == 3:
                            raise req_err
                        logger.warning(f"[الحساب الشخصي للصحفي] المحاولة {attempt} فشلت ({req_err}). إعادة المحاولة...")
                        time.sleep(attempt * 1.5)

                post_id = response.get("id")
                post_url = response.get("url")

                logger.info(
                    f"✅ [تطبيق الديسكتوب] تم النشر في Blogger بنجاح عبر الحساب الشخصي للصحفي! "
                    f"ID: {post_id} | URL: {post_url}"
                )

                return {
                    "post_id": post_id,
                    "post_url": post_url,
                    "status": "DRAFT" if is_draft else "PUBLISHED",
                    "account_id": "personal",
                    "raw_response": response
                }

        # ── 2. MULTI-ACCOUNT POOL MODE (Telegram Bot Only) ──
        active_accounts = self.get_active_accounts()
        total_accounts = len(active_accounts)

        with self._pool_lock:
            start_idx = self._rr_index
            self._rr_index = (self._rr_index + 1) % total_accounts

        last_error = None

        # Try accounts in Round-Robin order with automatic failover
        for attempt_i in range(total_accounts):
            curr_acc = active_accounts[(start_idx + attempt_i) % total_accounts]
            logger.info(f"🔄 [حوض التليجرام] جاري النشر عبر حساب Blogger رقم {curr_acc.account_id} (من أصل {total_accounts} حسابات متاحة)...")

            with curr_acc.lock:
                try:
                    if not curr_acc.service or not curr_acc.creds or not curr_acc.creds.valid:
                        self.authenticate_account(curr_acc, allow_browser=False)

                    posts_resource = curr_acc.service.posts()
                    response = None

                    # Retry logic with backoff for Google API concurrency/rate limits
                    for attempt in range(1, 4):
                        try:
                            request = posts_resource.insert(
                                blogId=active_blog_id,
                                body=body,
                                isDraft=is_draft
                            )
                            response = request.execute()
                            break
                        except Exception as req_err:
                            if attempt == 3:
                                raise req_err
                            logger.warning(f"[حوض التليجرام - حساب {curr_acc.account_id}] المحاولة {attempt} فشلت ({req_err}). إعادة المحاولة...")
                            time.sleep(attempt * 1.5)

                    post_id = response.get("id")
                    post_url = response.get("url")

                    logger.info(
                        f"✅ [حوض التليجرام] تم النشر في Blogger بنجاح عبر الحساب {curr_acc.account_id}! "
                        f"ID: {post_id} | URL: {post_url}"
                    )

                    return {
                        "post_id": post_id,
                        "post_url": post_url,
                        "status": "DRAFT" if is_draft else "PUBLISHED",
                        "account_id": curr_acc.account_id,
                        "raw_response": response
                    }

                except Exception as acc_err:
                    last_error = acc_err
                    logger.warning(
                        f"⚠️ تعذر النشر بحساب Blogger رقم {curr_acc.account_id} ({acc_err}). "
                        f"جاري الانتقال لحساب بديل في حوض التليجرام..."
                    )

        raise last_error or RuntimeError("فشلت جميع حسابات حوض بلوجر المتاحة في نشر المقال.")

    def publish_article(self, article_data: dict, use_pool: bool = True) -> dict:
        """
        Convenience wrapper method to publish an article dictionary generated by AIService.
        Automatically formats structured AI output into rich journalistic HTML via ArticleFormatter.
        Default use_pool=True for Telegram Bot.
        Returns dict with keys: 'id', 'url', 'post_id', 'post_url'.
        """
        from services.article_formatter import ArticleFormatter

        title = article_data.get("title", "خبر صحفي جديد")
        labels = article_data.get("labels", [])
        image_url = article_data.get("image_url")
        content_html = article_data.get("content", "")

        meta_description = article_data.get("meta_description", "")

        # If content_html is empty or structured AI fields exist, format using ArticleFormatter
        if not content_html or "lead_paragraph" in article_data or "sections" in article_data:
            content_html = ArticleFormatter.json_to_html(article_data, image_url=image_url)
        elif image_url and "<img" not in content_html[:200]:
            img_html = f'<div class="separator" style="clear: both; text-align: center;"><a href="{image_url}" style="margin-left: 1em; margin-right: 1em;"><img border="0" data-original-height="800" data-original-width="1200" src="{image_url}" /></a></div><br />'
            content_html = img_html + content_html

        res = self.publish_post(
            title=title,
            content_html=content_html,
            labels=labels,
            is_draft=False,
            meta_description=meta_description,
            use_pool=use_pool
        )
        return {
            "id": res.get("post_id"),
            "url": res.get("post_url"),
            "post_id": res.get("post_id"),
            "post_url": res.get("post_url"),
            "raw_response": res
        }

    def get_pool_status(self) -> list:
        """Returns visual status information for all 3 Blogger account slots."""
        self._init_accounts_pool()
        statuses = []
        for acc in self.accounts:
            exists = acc.token_exists()
            status_text = "⚪ غير مسجل"
            is_valid = False
            user_name = acc.display_name

            if exists:
                try:
                    if not acc.creds:
                        with open(acc.token_path, "rb") as f:
                            acc.creds = pickle.load(f)
                    if acc.creds and acc.creds.valid:
                        status_text = "✅ متصل ونشط"
                        is_valid = True
                    elif acc.creds and acc.creds.refresh_token:
                        status_text = "🟡 متصل (تجديد تلقائي)"
                        is_valid = True
                    else:
                        status_text = "⚠️ منتهي الصلاحية"
                except Exception:
                    status_text = "❌ ملف تالف"

            statuses.append({
                "account_id": acc.account_id,
                "token_file": acc.token_path.name,
                "exists": exists,
                "is_valid": is_valid,
                "status_text": status_text,
                "display_name": user_name or f"حساب بلوجر {acc.account_id}"
            })
        return statuses

    def authenticate_slot_browser(self, slot: int) -> tuple:
        """Launches browser OAuth flow for a specific account slot (1, 2, or 3). Returns (success, name_or_error)."""
        self._init_accounts_pool()
        if slot < 1 or slot > len(self.accounts):
            return False, "رقم الحساب غير صحيح"

        acc = self.accounts[slot - 1]
        try:
            self.authenticate_account(acc, allow_browser=True)
            name = ""
            try:
                user_res = acc.service.users().get(userId="self").execute()
                name = user_res.get("displayName", "")
                acc.display_name = name
            except Exception:
                pass
            return True, name or f"حساب {slot}"
        except Exception as e:
            return False, str(e)

    # Alias for API compatibility
    create_post = publish_post


# ==============================================================
# GLOBAL SERVICE INSTANCE
# ==============================================================

blogger_service = BloggerService()