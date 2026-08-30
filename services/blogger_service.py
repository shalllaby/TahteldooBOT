import os
import pickle
import re

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from core.config import Config
from core.logger import logger


SCOPES = ["https://www.googleapis.com/auth/blogger"]


class BloggerService:
    """
    Service to handle Google OAuth and Blogger API v3 operations.

    Features:
    - Google OAuth authentication
    - Blogger post publishing
    - Automatic conversion of **text** to <strong>text</strong>
    - Automatic bold formatting for "جريدة تحت الضوء الإخبارية"
    - Basic cleanup of malformed <strong> tags
    """

    NEWSPAPER_NAME = "جريدة تحت الضوء الإخبارية"

    def __init__(self, blog_id: str = None):
        self.blog_id = blog_id or Config.BLOGGER_BLOG_ID
        self.creds = None
        self.service = None

    # ==========================================================
    # AUTHENTICATION
    # ==========================================================

    def authenticate(self):
        """
        Authenticate using credentials.json and token.pickle.
        """

        token_path = Config.TOKEN_FILE
        creds_path = Config.CREDENTIALS_FILE

        # ------------------------------------------------------
        # Load existing token
        # ------------------------------------------------------

        if os.path.exists(token_path):

            try:

                with open(token_path, "rb") as token:
                    self.creds = pickle.load(token)

            except Exception as e:

                logger.warning(
                    f"فشل تحميل OAuth Token: {e}"
                )

                self.creds = None

        # ------------------------------------------------------
        # Refresh expired token
        # ------------------------------------------------------

        if (
            self.creds
            and self.creds.expired
            and self.creds.refresh_token
        ):

            try:

                self.creds.refresh(Request())

                with open(token_path, "wb") as token:
                    pickle.dump(
                        self.creds,
                        token
                    )

                logger.info(
                    "تم تحديث OAuth Token بنجاح."
                )

            except Exception as e:

                logger.warning(
                    f"فشل تحديث OAuth Token تلقائياً: {e}. "
                    "سيتم طلب تسجيل الدخول مجدداً."
                )

                self.creds = None

        # ------------------------------------------------------
        # Re-authenticate if token is missing/invalid
        # ------------------------------------------------------

        if not self.creds or not self.creds.valid:

            if not os.path.exists(creds_path):

                raise FileNotFoundError(
                    f"ملف credentials.json غير موجود في: {creds_path}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path),
                SCOPES
            )

            self.creds = flow.run_local_server(
                port=0
            )

            with open(token_path, "wb") as token:
                pickle.dump(
                    self.creds,
                    token
                )

        # ------------------------------------------------------
        # Build Blogger API service
        # ------------------------------------------------------

        self.service = build(
            "blogger",
            "v3",
            credentials=self.creds
        )

        logger.info(
            "تم الاتصال بـ Blogger API بنجاح."
        )

        return self.service

    # ==========================================================
    # ACCOUNT & BLOG MANAGEMENT
    # ==========================================================

    def is_authenticated(self) -> bool:
        """Checks if there is a valid stored OAuth token without opening browser."""
        token_path = Config.TOKEN_FILE
        if self.creds and self.creds.valid:
            return True
        if os.path.exists(token_path):
            try:
                with open(token_path, "rb") as token:
                    creds = pickle.load(token)
                if creds and creds.valid:
                    self.creds = creds
                    if not self.service:
                        self.service = build("blogger", "v3", credentials=self.creds)
                    return True
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, "wb") as token:
                        pickle.dump(creds, token)
                    self.creds = creds
                    if not self.service:
                        self.service = build("blogger", "v3", credentials=self.creds)
                    return True
            except Exception as e:
                logger.warning(f"التحقق من حالة التوثيق فشل: {e}")
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

    def disconnect(self):
        """
        Disconnects current Google account and clears local credentials & config.
        """
        token_path = Config.TOKEN_FILE
        if os.path.exists(token_path):
            try:
                os.remove(token_path)
                logger.info("تم حذف ملف OAuth token.pickle بنجاح.")
            except Exception as e:
                logger.error(f"فشل حذف token.pickle: {e}")

        self.creds = None
        self.service = None
        self.blog_id = ""
        Config.clear_blogger_config()
        logger.info("تم فصل حساب Blogger وتصفير الإعدادات بنجاح.")


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
    # PUBLISH POST
    # ==========================================================

    def publish_post(
        self,
        title: str,
        content_html: str,
        labels: list = None,
        is_draft: bool = False
    ) -> dict:
        """
        Publishes a new post to Blogger.

        Before publishing:
        - Converts **text** to <strong>text</strong>
        - Makes newspaper name bold automatically
        - Cleans malformed strong tags
        """

        # ------------------------------------------------------
        # Authenticate if needed
        # ------------------------------------------------------

        if not self.service:
            self.authenticate()

        # ------------------------------------------------------
        # Format article HTML
        # ------------------------------------------------------

        logger.info(
            "جاري تجهيز محتوى المقال قبل إرساله إلى Blogger..."
        )

        formatted_content = self.format_article_html(
            content_html
        )

        # ------------------------------------------------------
        # Log useful information
        # ------------------------------------------------------

        logger.debug(
            f"المحتوى بعد تحويل Bold:\n{formatted_content[:2000]}"
        )

        active_blog_id = self.blog_id or Config.BLOGGER_BLOG_ID
        if not active_blog_id:
            raise ValueError("لم يتم اختيار أي مدونة للنشر عليها. يرجى الدخول إلى شاشة الإعدادات وربط حساب Google/Blogger واختيار المدونة.")

        # ------------------------------------------------------
        # Prepare Blogger body
        # ------------------------------------------------------

        body = {
            "kind": "blogger#post",

            "blog": {
                "id": active_blog_id
            },

            "title": title,

            "content": formatted_content,

            "labels": labels or []
        }

        logger.info(
            f"جاري إرسال المقال إلى Blogger "
            f"(Draft={is_draft}). "
            f"العنوان: {title}"
        )

        # ------------------------------------------------------
        # Insert post
        # ------------------------------------------------------

        posts_resource = self.service.posts()

        # Retry logic with backoff for Google API concurrency rate limits
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
                logger.warning(f"Blogger API insert attempt {attempt} failed ({req_err}). Retrying in {attempt * 1.5}s...")
                import time
                time.sleep(attempt * 1.5)

        # ------------------------------------------------------
        # Get response data
        # ------------------------------------------------------

        post_id = response.get(
            "id"
        )

        post_url = response.get(
            "url"
        )

        logger.info(
            f"تم إنشاء المقال في Blogger بنجاح! "
            f"ID: {post_id} | URL: {post_url}"
        )

        return {
            "post_id": post_id,
            "post_url": post_url,
            "status": (
                "DRAFT"
                if is_draft
                else "PUBLISHED"
            ),
            "raw_response": response
        }

    def publish_article(self, article_data: dict) -> dict:
        """
        Convenience wrapper method to publish an article dictionary generated by AIService.
        Automatically formats structured AI output into rich journalistic HTML via ArticleFormatter.
        Returns dict with keys: 'id', 'url', 'post_id', 'post_url'.
        """
        from services.article_formatter import ArticleFormatter

        title = article_data.get("title", "خبر صحفي جديد")
        labels = article_data.get("labels", [])
        image_url = article_data.get("image_url")
        content_html = article_data.get("content", "")

        # If content_html is empty or structured AI fields exist, format using ArticleFormatter
        if not content_html or "lead_paragraph" in article_data or "sections" in article_data:
            content_html = ArticleFormatter.json_to_html(article_data, image_url=image_url)
        elif image_url and "<img" not in content_html[:200]:
            img_html = f'<div class="separator" style="clear: both; text-align: center;"><a href="{image_url}" style="margin-left: 1em; margin-right: 1em;"><img border="0" data-original-height="800" data-original-width="1200" src="{image_url}" /></a></div><br />'
            content_html = img_html + content_html

        res = self.publish_post(title=title, content_html=content_html, labels=labels, is_draft=False)
        return {
            "id": res.get("post_id"),
            "url": res.get("post_url"),
            "post_id": res.get("post_id"),
            "post_url": res.get("post_url"),
            "raw_response": res
        }


# ==============================================================
# GLOBAL SERVICE INSTANCE
# ==============================================================

blogger_service = BloggerService()