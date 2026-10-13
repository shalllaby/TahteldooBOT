"""
WordPress REST API Service — جريدة تحت الضوء الإخبارية
بديل كامل لـ BloggerService يعمل مع WordPress REST API
نفس الـ interface بالضبط لتقليل التغييرات في باقي الكود

هيكل الحسابات:
    REVIEW SITE (review.tahteldoo.com):
        Account 1 (td_admin_1) → Telegram Bot
        Account 2 (td_admin_2) → Web Platform
        Account 3 (td_admin_3) → Press Automation (Facebook pipeline)
        Account 4 (td_admin_4) → Fallback 1
        Account 5 (td_admin_5) → Fallback 2

    MAIN SITE (www.tahteldoo.com):
        Account   (td_admin_1) → اعتماد ونشر الخبر النهائي
"""

import os
import re
import time
import uuid
import base64
import threading
import requests
from pathlib import Path
from typing import List, Optional, Dict, Any

from core.config import Config
from core.logger import logger


# ================================================================
# CATEGORY MAP — review.tahteldoo.com Categories
# الفئات المتاحة في موقع الريفيو
# ================================================================
CATEGORY_MAP: Dict[str, int] = {
    # Arabic labels → WordPress Category ID
    "أعمال":          3,
    "تحت الضوء":      8,
    "تطوير ذات":      11,
    "تعليم":          12,
    "خدمات":          13,
    "شخصيات عامة":    14,
    "صحة":            15,
    # Aliases / common labels from AI
    "business":       3,
    "education":      12,
    "services":       13,
    "health":         15,
    "أخبار":          8,
    "عام":            13,
    "General":        13,
}
DEFAULT_CATEGORY_ID = 13  # خدمات — الفئة الافتراضية


def resolve_category_id(label: str) -> int:
    """Resolves an Arabic/English label string to a WordPress category ID."""
    if not label:
        return DEFAULT_CATEGORY_ID
    label_clean = str(label).strip()
    # Direct match
    if label_clean in CATEGORY_MAP:
        return CATEGORY_MAP[label_clean]
    # Case-insensitive
    for k, v in CATEGORY_MAP.items():
        if k.lower() == label_clean.lower():
            return v
    # Partial match
    for k, v in CATEGORY_MAP.items():
        if k in label_clean or label_clean in k:
            return v
    return DEFAULT_CATEGORY_ID


def resolve_category_ids(labels: list) -> List[int]:
    """Resolves a list of labels to a list of unique WordPress category IDs."""
    if not labels:
        return [DEFAULT_CATEGORY_ID]
    ids = list({resolve_category_id(lbl) for lbl in labels if lbl})
    return ids if ids else [DEFAULT_CATEGORY_ID]


# ================================================================
# WORDPRESS ACCOUNT
# ================================================================

class WordPressAccount:
    """
    Represents a single WordPress account with Application Password credentials.
    Mirrors BloggerAccount interface for drop-in compatibility.
    """

    def __init__(self, account_id: int, site_url: str, username: str, app_password: str, role: str = ""):
        self.account_id = account_id
        self.site_url = site_url.rstrip("/")
        self.username = username
        self.app_password = app_password
        self.role = role  # e.g. "telegram", "platform", "automation", "fallback1", "fallback2"
        self.lock = threading.RLock()
        self.cooldown_until = 0.0
        # Pre-compute auth header
        raw = f"{username}:{app_password}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_upload_headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._auth_header,
        }

    def is_valid(self) -> bool:
        """Quick connection check against WordPress REST API."""
        try:
            r = requests.get(
                f"{self.site_url}/wp-json/wp/v2/users/me",
                headers=self.get_headers(),
                timeout=8
            )
            return r.status_code == 200
        except Exception:
            return False

    def __repr__(self):
        return f"<WordPressAccount id={self.account_id} user={self.username} role={self.role} site={self.site_url}>"


# ================================================================
# WORDPRESS SERVICE
# ================================================================

class WordPressService:
    """
    Service to handle WordPress REST API operations.
    Provides identical interface to the old BloggerService for seamless migration.

    Features:
    - Multi-Account Pool: 5 accounts with dedicated roles + 2 fallbacks
    - Thread-Safe: per-account RLock for concurrent publishing
    - Automatic Fallback: Account 1→2→3→4→5 on failure
    - Review Site: review.tahteldoo.com (publishing/drafts)
    - Main Site:   www.tahteldoo.com   (final approval publishing)
    - Media Upload: auto-uploads images to WordPress Media Library
    - transfer_review_to_main(): fetches from review via REST API → publishes to main
    - delete_review_posts(): deletes posts from review site by WP post ID
    """

    NEWSPAPER_NAME = "جريدة تحت الضوء الإخبارية"

    # Sites
    REVIEW_SITE_URL = "https://review.tahteldoo.com"
    MAIN_SITE_URL   = "https://www.tahteldoo.com"

    # ── Review Site Accounts (5 accounts) ──
    _REVIEW_ACCOUNTS_CONFIG = [
        # (account_id, username, app_password, role)
        (1, "td_admin_1", "ppdNg8SybmabtVv9hfLOjRPP", "telegram"),
        (2, "td_admin_2", "FgDcvcbL2z0F8a23gRDBbCDX", "platform"),
        (3, "td_admin_3", "pcrvEJ6PIOW2hdA4O7i7jqwa", "automation"),
        (4, "td_admin_4", "RBh0kfKDFyORL0bEuLQUuotb", "fallback1"),
        (5, "td_admin_5", "X8GYkqErs5q22yLHX08Oin1k", "fallback2"),
    ]

    # ── Main Site Account (1 account for final publishing) ──
    _MAIN_ACCOUNT_CONFIG = (0, "td_admin_1", "rK4c5UZkJpKz7N9E5qT0Os5R", "main")

    def __init__(self):
        # Build review accounts pool
        self.review_accounts: List[WordPressAccount] = [
            WordPressAccount(acc_id, self.REVIEW_SITE_URL, user, pwd, role)
            for acc_id, user, pwd, role in self._REVIEW_ACCOUNTS_CONFIG
        ]
        # Build main account
        acc_id, user, pwd, role = self._MAIN_ACCOUNT_CONFIG
        self.main_account = WordPressAccount(acc_id, self.MAIN_SITE_URL, user, pwd, role)

        # Pool for Telegram Bot (account 1)
        self.telegram_account: WordPressAccount = self.review_accounts[0]
        # Pool for Platform (account 2)
        self.platform_account: WordPressAccount = self.review_accounts[1]
        # Pool for Automation (account 3)
        self.automation_account: WordPressAccount = self.review_accounts[2]
        # Fallback pool (accounts 4, 5)
        self.fallback_accounts: List[WordPressAccount] = self.review_accounts[3:]

        # Compatibility: expose blog_id/blog_url mirrors
        self.blog_id = "review.tahteldoo.com"
        self.REVIEW_BLOG_ID = "review.tahteldoo.com"
        self.MAIN_BLOG_ID   = "www.tahteldoo.com"
        self.FALLBACK_BLOG_ID = "review.tahteldoo.com"  # No separate fallback blog

        self._pool_lock = threading.RLock()

    # ================================================================
    # INTERNAL — RESILIENT PUBLISH ENGINE
    # ================================================================

    def _get_ordered_accounts(self, use_pool: bool = True, preferred_role: str = None) -> List[WordPressAccount]:
        """
        Returns accounts in priority order:
        1. preferred_role account (if specified and not in cooldown)
        2. Active accounts (not in cooldown)
        3. Cooling accounts (last resort)
        """
        all_accs = list(self.review_accounts)

        # Prefer specified role first
        ordered = []
        if preferred_role:
            preferred = [a for a in all_accs if a.role == preferred_role and not a.is_in_cooldown()]
            ordered.extend(preferred)

        # Then active accounts (not in cooldown)
        active = [a for a in all_accs if not a.is_in_cooldown() and a not in ordered]
        ordered.extend(active)

        # Then cooling accounts
        cooling = [a for a in all_accs if a.is_in_cooldown() and a not in ordered]
        ordered.extend(cooling)

        return ordered

    def _upload_media_full(
        self,
        account: WordPressAccount,
        image_url: str,
        title: str = "",
        alt_text: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Downloads image from URL and uploads to WordPress Media Library.
        Automatically attaches SEO alt_text, title, and caption to the media item.
        Returns dict {"id": media_id, "url": source_url}, or None on failure.
        """
        if not image_url or not image_url.startswith("http"):
            return None
        try:
            # Download image with user agent
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            img_resp = requests.get(image_url, headers=headers, timeout=25, stream=True)
            if img_resp.status_code != 200:
                logger.warning(f"[WP Media] Failed to download image {image_url}: HTTP {img_resp.status_code}")
                return None

            # Determine filename and content type
            content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            ext_map = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
                "image/gif": "gif",
                "image/bmp": "bmp",
                "image/x-ms-bmp": "bmp",
                "image/avif": "avif"
            }
            ext = ext_map.get(content_type, "jpg")
            filename = f"tahteldoo_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"

            # Upload to WP Media
            upload_headers = account.get_upload_headers()
            upload_headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            upload_headers["Content-Type"] = content_type

            up_resp = requests.post(
                f"{account.site_url}/wp-json/wp/v2/media",
                headers=upload_headers,
                data=img_resp.content,
                timeout=40
            )
            if up_resp.status_code in (200, 201):
                data = up_resp.json()
                media_id = data.get("id")
                source_url = data.get("source_url") or data.get("guid", {}).get("rendered", "")
                logger.info(f"[WP Media] Uploaded image → Media ID: {media_id} | URL: {source_url}")

                # Apply SEO alt_text, title, and caption
                final_alt = alt_text.strip() if alt_text else (f"{title} | جريدة تحت الضوء الإخبارية" if title else "جريدة تحت الضوء الإخبارية")
                final_title = title.strip() if title else "صورة الخبر - جريدة تحت الضوء"
                try:
                    patch_headers = account.get_headers()
                    requests.post(
                        f"{account.site_url}/wp-json/wp/v2/media/{media_id}",
                        headers=patch_headers,
                        json={"alt_text": final_alt, "title": final_title, "caption": final_alt},
                        timeout=15
                    )
                except Exception as me_patch_err:
                    logger.warning(f"[WP Media] Could not patch alt_text: {me_patch_err}")

                return {"id": media_id, "url": source_url}
            else:
                logger.warning(f"[WP Media] Upload failed: HTTP {up_resp.status_code} | {up_resp.text[:200]}")
                return None

        except Exception as e:
            logger.warning(f"[WP Media] Exception during media upload: {e}")
            return None

    def _upload_media(
        self,
        account: WordPressAccount,
        image_url: str,
        title: str = "",
        alt_text: str = ""
    ) -> Optional[int]:
        """
        Downloads image from URL and uploads to WordPress Media Library.
        Returns WordPress media ID, or None on failure.
        """
        res = self._upload_media_full(account, image_url, title=title, alt_text=alt_text)
        return res.get("id") if res else None

    @staticmethod
    def _clean_slug(raw_slug: Optional[str]) -> Optional[str]:
        """
        Sanitizes raw slug into a clean URL-friendly identifier:
        - Removes .html / .htm extension
        - Converts to lowercase
        - Replaces spaces and underscores with hyphens
        - Strips punctuation and duplicate hyphens
        """
        if not raw_slug or not isinstance(raw_slug, str):
            return None
        s = raw_slug.strip().lower()
        s = re.sub(r"\.html?$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"[^\w\-]+", "", s, flags=re.UNICODE)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        return s or None

    def _do_publish(
        self,
        account: WordPressAccount,
        title: str,
        content_html: str,
        category_ids: List[int],
        is_draft: bool = False,
        featured_media_id: Optional[int] = None,
        meta_description: str = "",
        slug: Optional[str] = None
    ) -> dict:
        """
        Core single-account publish attempt to WordPress REST API.
        Returns raw WP response dict on success.
        Raises Exception on failure.
        """
        payload: Dict[str, Any] = {
            "title":   title,
            "content": content_html,
            "status":  "draft" if is_draft else "publish",
            "categories": category_ids,
        }
        clean_slug = self._clean_slug(slug)
        if clean_slug:
            payload["slug"] = clean_slug

        if featured_media_id:
            payload["featured_media"] = featured_media_id
        if meta_description:
            payload["excerpt"] = meta_description

        resp = requests.post(
            f"{account.site_url}/wp-json/wp/v2/posts",
            headers=account.get_headers(),
            json=payload,
            timeout=30
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            return data
        else:
            err_body = resp.text[:300]
            status_code = resp.status_code
            # Rate limit / server overload
            if status_code == 429:
                account.cooldown_until = time.time() + 1800  # 30 min cooldown
                raise RuntimeError(f"429 Rate Limit — حساب {account.username} وصل للحد الأقصى")
            raise RuntimeError(f"HTTP {status_code}: {err_body}")

    def _resilient_publish(
        self,
        title: str,
        content_html: str,
        labels: list = None,
        is_draft: bool = False,
        meta_description: str = None,
        image_url: str = None,
        preferred_role: str = None,
        slug: Optional[str] = None
    ) -> dict:
        """
        Full Fallback Engine — tries accounts in priority order until success.
        Mirrors execute_resilient_publish() from the old BloggerService.
        """
        category_ids = resolve_category_ids(labels or [])
        meta_desc = meta_description or ""

        accounts = self._get_ordered_accounts(preferred_role=preferred_role)
        if not accounts:
            raise RuntimeError("لا توجد حسابات WordPress نشطة في النظام")

        errors_log = []
        is_first = True

        for account in accounts:
            if not is_first:
                logger.warning(
                    f"🔄 [WP Fallback] التحويل للحساب التالي: {account.username} (دور: {account.role})"
                )
            else:
                logger.info(f"🚀 [WP Publish] محاولة النشر عبر {account.username} (دور: {account.role})")
            is_first = False

            with account.lock:
                try:
                    # Upload featured image if provided with full SEO alt & title
                    media_id = None
                    if image_url:
                        media_id = self._upload_media(
                            account,
                            image_url,
                            title=title,
                            alt_text=f"{title} | جريدة تحت الضوء الإخبارية"
                        )

                    response = self._do_publish(
                        account=account,
                        title=title,
                        content_html=content_html,
                        category_ids=category_ids,
                        is_draft=is_draft,
                        featured_media_id=media_id,
                        meta_description=meta_desc,
                        slug=slug
                    )

                    post_id  = str(response.get("id", ""))
                    post_url = response.get("link", "")

                    logger.info(
                        f"🎉 [WP Publish] تم النشر بنجاح! "
                        f"الحساب: {account.username} | ID: {post_id} | URL: {post_url}"
                    )
                    return {
                        "post_id":   post_id,
                        "post_url":  post_url,
                        "url":       post_url,
                        "status":    "DRAFT" if is_draft else "PUBLISHED",
                        "account_id": account.account_id,
                        "account_username": account.username,
                        "blog_id":   account.site_url,
                        "is_fallback": (account.role not in ("telegram", "platform", "automation")),
                        "raw_response": response
                    }

                except Exception as err:
                    msg = f"{account.username} ({account.role}): {err}"
                    errors_log.append(msg)
                    logger.warning(f"⚠️ [WP Fallback] فشل الحساب {account.username}: {err}")

        combined = " | ".join(errors_log)
        logger.critical(f"🛑 [WP Fatal] فشل النشر بعد تجربة كل الحسابات: {combined}")
        raise RuntimeError(f"❌ فشل النشر على WordPress بعد تجربة كل الحسابات: {combined}")

    # ================================================================
    # PUBLIC INTERFACE — نفس أسماء الـ methods القديمة
    # ================================================================

    def publish_post(
        self,
        title: str,
        content_html: str,
        labels: list = None,
        is_draft: bool = False,
        meta_description: str = None,
        use_pool: bool = False,
        token_path: Optional[str] = None,
        strict_token: bool = False,
        slug: Optional[str] = None,
        image_url: Optional[str] = None
    ) -> dict:
        """
        Publishes a new post to review.tahteldoo.com WordPress.
        Same signature as BloggerService.publish_post() for drop-in compatibility.

        Args:
            title:           Article title
            content_html:    Full HTML content
            labels:          List of Arabic category labels (e.g. ['صحة', 'تعليم'])
            is_draft:        If True, publish as draft
            meta_description: Article excerpt/meta description
            use_pool:        Ignored — kept for compatibility (always uses account pool)
            token_path:      Ignored — kept for compatibility (WP uses app passwords)
            strict_token:    Ignored — kept for compatibility
            slug:            Custom clean slug (e.g. 'al-noor-center')
            image_url:       Featured image URL (auto-extracted from content if omitted)
        Returns:
            dict with: post_id, post_url, url, status, account_id, blog_id
        """
        # Determine preferred account based on caller context
        preferred_role = "telegram" if use_pool else None

        # Auto-extract image_url from content_html if not explicitly provided
        if not image_url and content_html:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_html)
            if m:
                image_url = m.group(1).strip()

        return self._resilient_publish(
            title=title,
            content_html=content_html,
            labels=labels,
            is_draft=is_draft,
            meta_description=meta_description,
            image_url=image_url,
            preferred_role=preferred_role,
            slug=slug
        )

    def publish_article(self, article_data: dict, use_pool: bool = True) -> dict:
        """
        Publishes an article dict generated by AIService to review.tahteldoo.com.
        Same signature as BloggerService.publish_article() for drop-in compatibility.
        Returns dict with: id, url, post_id, post_url, status, raw_response
        """
        from services.article_formatter import ArticleFormatter

        title = article_data.get("title", "خبر صحفي جديد")
        labels = article_data.get("labels", ["خدمات"])
        image_url = article_data.get("image_url") or article_data.get("featured_image") or ""
        content_html = article_data.get("content_html") or article_data.get("content", "")
        meta_description = article_data.get("meta_description", "")
        slug = article_data.get("slug")

        # Format HTML if not already formatted
        if not content_html or "lead_paragraph" in article_data or "sections" in article_data:
            content_html = ArticleFormatter.json_to_html(article_data, image_url=image_url)
        elif image_url and "<img" not in content_html[:200]:
            # Prepend featured image if not already in content
            img_html = (
                f'<div style="text-align:center;margin-bottom:1em;">'
                f'<img src="{image_url}" style="max-width:100%;height:auto;" />'
                f'</div>'
            )
            content_html = img_html + content_html

        preferred_role = "telegram" if use_pool else None

        res = self._resilient_publish(
            title=title,
            content_html=content_html,
            labels=labels,
            is_draft=False,
            meta_description=meta_description,
            image_url=image_url,
            preferred_role=preferred_role,
            slug=slug
        )

        return {
            "id": res.get("post_id"),
            "url": res.get("post_url"),
            "post_id": res.get("post_id"),
            "post_url": res.get("post_url"),
            "status": res.get("status"),
            "raw_response": res
        }

    # ================================================================
    # TRANSFER REVIEW → MAIN (اعتماد الخبر ونقله للجريدة الأصلية)
    # ================================================================

    def transfer_review_to_main(self, review_url: str, token_path: str = None) -> dict:
        """
        Fetches an article from review.tahteldoo.com via WordPress REST API
        and publishes it as Published on www.tahteldoo.com (الجريدة الأصلية).

        Args:
            review_url: Full URL of the review article
                        e.g. https://review.tahteldoo.com/2026/09/some-article/
            token_path: Ignored — kept for API compatibility

        Returns:
            dict: success, title, main_url, main_post_id, review_url, labels, content_html
        """
        import urllib.parse
        import requests as req_lib
        from bs4 import BeautifulSoup

        clean_url = (review_url or "").strip()
        if not clean_url:
            raise ValueError("يرجى إدخال رابط خبر الريفيو")

        logger.info(f"[WP Transfer] بدء نقل الخبر: {clean_url}")

        # ── Step 1: Resolve WordPress post ID from URL ──
        title   = ""
        content = ""
        excerpt = ""
        labels  = []
        review_post_id = ""
        category_ids = [DEFAULT_CATEGORY_ID]
        featured_image_url = None

        # Try WordPress REST API: search by slug variants & search query
        transfer_slug = None
        try:
            parsed = urllib.parse.urlparse(clean_url)
            slug_parts = [p for p in parsed.path.strip("/").split("/") if p]
            raw_slug = slug_parts[-1].replace(".html", "") if slug_parts else ""
            
            slug_candidates = []
            if raw_slug:
                slug_candidates.append(raw_slug)
                if "_" in raw_slug:
                    slug_candidates.append(raw_slug.replace("_", "-"))
                if "-" in raw_slug:
                    slug_candidates.append(raw_slug.replace("-", "_"))
                cleaned = self._clean_slug(raw_slug)
                if cleaned and cleaned not in slug_candidates:
                    slug_candidates.append(cleaned)

            headers = self.platform_account.get_headers() if hasattr(self, 'platform_account') else self.main_account.get_headers()

            # 1. Try slug candidate search
            for s in slug_candidates:
                r = requests.get(
                    f"{self.REVIEW_SITE_URL}/wp-json/wp/v2/posts",
                    params={"slug": s, "_fields": "id,title,content,excerpt,categories,link,slug,featured_media", "_embed": 1},
                    headers=headers,
                    timeout=12
                )
                if r.status_code == 200:
                    posts = r.json()
                    if posts:
                        post = posts[0]
                        title      = post.get("title", {}).get("rendered", "")
                        content    = post.get("content", {}).get("rendered", "")
                        excerpt    = post.get("excerpt", {}).get("rendered", "")
                        category_ids = post.get("categories", [DEFAULT_CATEGORY_ID])
                        review_post_id = str(post.get("id", ""))
                        transfer_slug = post.get("slug", s)

                        # Extract featured image from _embedded or featured_media
                        embedded_media = post.get("_embedded", {}).get("wp:featuredmedia", [])
                        if embedded_media and isinstance(embedded_media, list) and len(embedded_media) > 0:
                            featured_image_url = embedded_media[0].get("source_url")
                        elif post.get("featured_media"):
                            try:
                                mr = requests.get(
                                    f"{self.REVIEW_SITE_URL}/wp-json/wp/v2/media/{post.get('featured_media')}",
                                    headers=headers,
                                    timeout=10
                                )
                                if mr.status_code == 200:
                                    featured_image_url = mr.json().get("source_url")
                            except Exception as me:
                                logger.warning(f"[WP Transfer] Could not fetch featured media: {me}")

                        logger.info(f"[WP Transfer] جُلب المقال عبر REST API (slug='{s}'): '{title}' (ID: {review_post_id}) | Featured Image: {featured_image_url}")
                        break

            # 2. Try search query if slug search didn't find post
            if not title and raw_slug:
                search_term = raw_slug.replace("blog-post", "").replace("-", " ").replace("_", " ").strip()
                if search_term:
                    r = requests.get(
                        f"{self.REVIEW_SITE_URL}/wp-json/wp/v2/posts",
                        params={"search": search_term, "per_page": 5, "_fields": "id,title,content,excerpt,categories,link,slug,featured_media", "_embed": 1},
                        headers=headers,
                        timeout=12
                    )
                    if r.status_code == 200:
                        posts = r.json()
                        for p in posts:
                            p_slug = p.get("slug", "")
                            if p_slug in slug_candidates or str(p.get("id")) == raw_slug:
                                post = p
                                title      = post.get("title", {}).get("rendered", "")
                                content    = post.get("content", {}).get("rendered", "")
                                excerpt    = post.get("excerpt", {}).get("rendered", "")
                                category_ids = post.get("categories", [DEFAULT_CATEGORY_ID])
                                review_post_id = str(post.get("id", ""))
                                transfer_slug = post.get("slug", raw_slug)

                                embedded_media = post.get("_embedded", {}).get("wp:featuredmedia", [])
                                if embedded_media and isinstance(embedded_media, list) and len(embedded_media) > 0:
                                    featured_image_url = embedded_media[0].get("source_url")
                                elif post.get("featured_media"):
                                    try:
                                        mr = requests.get(
                                            f"{self.REVIEW_SITE_URL}/wp-json/wp/v2/media/{post.get('featured_media')}",
                                            headers=headers,
                                            timeout=10
                                        )
                                        if mr.status_code == 200:
                                            featured_image_url = mr.json().get("source_url")
                                    except Exception as me:
                                        logger.warning(f"[WP Transfer] Could not fetch featured media: {me}")

                                logger.info(f"[WP Transfer] جُلب المقال عبر REST API (search='{search_term}'): '{title}' (ID: {review_post_id})")
                                break
        except Exception as api_err:
            logger.warning(f"[WP Transfer] فشل جلب المقال عبر REST API: {api_err}")

        # ── Fallback: Web Scraping (Strict: no cross-post redirect) ──
        if not title or not content:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                scrape_resp = req_lib.get(clean_url, headers=headers, allow_redirects=False, timeout=15)
                
                # If 301/302 redirect, only follow if it stays on valid article URL (not ?p= or category)
                if scrape_resp.status_code in (301, 302, 307, 308):
                    loc = scrape_resp.headers.get("Location", "")
                    if loc and "?p=" not in loc and "/category/" not in loc and "page_id=" not in loc:
                        scrape_resp = req_lib.get(loc, headers=headers, allow_redirects=False, timeout=15)
                
                if scrape_resp.status_code == 200:
                    soup = BeautifulSoup(scrape_resp.text, "html.parser")
                    # Check if 404 page
                    body_classes = " ".join(soup.find("body").get("class", [])) if soup.find("body") else ""
                    if "error404" in body_classes or "الصفحة غير موجودة" in soup.get_text():
                        raise ValueError(f"المقال غير موجود على رابط الريفيو: {clean_url}")
                    
                    # Title
                    title_el = (
                        soup.find("h1", class_="entry-title") or
                        soup.find("h1", class_="post-title") or
                        soup.find("h1") or
                        soup.find("title")
                    )
                    if title_el:
                        title = title_el.get_text(strip=True)
                        title = re.sub(r"\s*[-|–—]\s*(جريدة\s+)?تحت\s+الضوء.*$", "", title).strip()

                    # Extract excerpt/meta description
                    meta_desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                    if meta_desc_tag and meta_desc_tag.get("content"):
                        excerpt = meta_desc_tag["content"].strip()

                    # Extract featured image from scraping if not found yet
                    if not featured_image_url:
                        og_tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
                        if og_tag and og_tag.get("content"):
                            featured_image_url = og_tag["content"].strip()
                        if not featured_image_url:
                            tw_tag = soup.find("meta", attrs={"name": "twitter:image"})
                            if tw_tag and tw_tag.get("content"):
                                featured_image_url = tw_tag["content"].strip()
                        if not featured_image_url:
                            thumb_el = soup.find("div", class_="single-post-thumb") or soup.find("div", class_="post-thumbnail")
                            if thumb_el:
                                img_el = thumb_el.find("img")
                                if img_el and img_el.get("src"):
                                    featured_image_url = img_el["src"].strip()

                    # Content
                    content_el = (
                        soup.find("div", class_="single-post-content") or
                        soup.find("div", class_="entry-content") or
                        soup.find("div", class_="post-body") or
                        soup.find("div", class_="post-content") or
                        soup.find("article")
                    )
                    if content_el:
                        content = str(content_el)

                    # Categories/tags
                    for a_tag in soup.find_all("a", rel="tag"):
                        tag_txt = a_tag.get_text(strip=True)
                        if tag_txt and tag_txt not in labels:
                            labels.append(tag_txt)
                    if not labels:
                        cat_badge = soup.find("span", class_="grid-post-cat")
                        if cat_badge:
                            c_txt = cat_badge.get_text(strip=True)
                            if c_txt:
                                labels.append(c_txt)
                    if labels:
                        category_ids = resolve_category_ids(labels)

                    logger.info(f"[WP Transfer] جُلب المقال عبر Web Scraping: '{title}' | Image: {featured_image_url}")
            except Exception as scrape_err:
                logger.warning(f"[WP Transfer] فشل Scraping: {scrape_err}")

        if not title or not content:
            raise ValueError(
                "تعذر استخراج بيانات الخبر من رابط الريفيو. "
                "يرجى التأكد من صحة الرابط وأن المقال منشور."
            )

        # ── Additional fallback for featured image from content ──
        if not featured_image_url and content:
            try:
                chk_soup = BeautifulSoup(content, "html.parser")
                first_img = chk_soup.find("img")
                if first_img and first_img.get("src"):
                    featured_image_url = first_img["src"].strip()
            except Exception:
                pass

        # ── Clean & Format SEO Excerpt (Meta Description) ──
        clean_excerpt = ""
        if excerpt:
            c_txt = re.sub(r"<[^>]+>", " ", excerpt)
            c_txt = re.sub(r"\s+", " ", c_txt).strip().strip(' "\'“”')
            if len(c_txt) > 155:
                cut = c_txt[:152]
                last_space = cut.rfind(" ")
                if last_space > 80:
                    cut = cut[:last_space]
                c_txt = cut + "..."
            clean_excerpt = c_txt
        if not clean_excerpt and title:
            clean_excerpt = f"اقرأ التفاصيل الكاملة لخبر «{title}» عبر التغطية الرسمية في جريدة تحت الضوء الإخبارية."

        # ── Step 2: Upload featured image to Main Site & migrate internal images ──
        main_featured_media_id = None
        main_featured_image_url = None
        if featured_image_url:
            logger.info(f"[WP Transfer] جاري نقل ورفع الصورة البارزة إلى الموقع الأساسي: {featured_image_url}")
            up_res = self._upload_media_full(
                self.main_account,
                featured_image_url,
                title=title,
                alt_text=f"{title} | جريدة تحت الضوء الإخبارية"
            )
            if up_res and up_res.get("id"):
                main_featured_media_id = up_res["id"]
                main_featured_image_url = up_res.get("url")
                logger.info(f"✅ [WP Transfer] تم ربط الصورة البارزة بنجاح! ID: {main_featured_media_id} | URL: {main_featured_image_url}")
            else:
                logger.warning(f"⚠️ [WP Transfer] تعذر رفع الصورة البارزة للموقع الأساسي: {featured_image_url}")

        try:
            c_soup = BeautifulSoup(content, "html.parser")
            selectors_to_remove = [
                "h1",
                ".entry-title", ".post-title", ".article-title", ".single-post-title",
                ".single-breadcrumbs", ".breadcrumbs", ".breadcrumb", "nav.breadcrumb", "ol.breadcrumb",
                ".entry-meta", ".post-meta", ".single-post-meta", ".post-date", ".author-date",
                ".post-categories", ".category-badge", ".single-category", "span.category",
                ".grid-post-cat", ".single-share-bar", ".single-post-thumb", ".single-post-container",
                ".post-nav-wrap", ".related-posts-wrap", "meta[name='description']",
                ".share-buttons", ".post-share", ".social-share"
            ]
            for sel in selectors_to_remove:
                for el in c_soup.select(sel):
                    el.decompose()

            # Migrate internal images inside content & ensure SEO alt_text
            for img in c_soup.find_all("img"):
                src = img.get("src", "").strip()
                if not src:
                    continue
                # Ensure SEO alt & title
                if not img.get("alt") or not img["alt"].strip():
                    img["alt"] = f"{title} | جريدة تحت الضوء الإخبارية"
                if not img.get("title"):
                    img["title"] = title

                # If image matches the featured image we already uploaded:
                if main_featured_image_url and (src == featured_image_url or (len(src) > 10 and src.split("/")[-1].split("?")[0] == featured_image_url.split("/")[-1].split("?")[0])):
                    img["src"] = main_featured_image_url
                    if img.get("srcset"):
                        del img["srcset"]
                elif "review.tahteldoo.com" in src or "/wp-content/uploads/" in src:
                    full_src = src if src.startswith("http") else f"{self.REVIEW_SITE_URL.rstrip('/')}/{src.lstrip('/')}"
                    up = self._upload_media_full(
                        self.main_account,
                        full_src,
                        title=title,
                        alt_text=f"{title} | جريدة تحت الضوء الإخبارية"
                    )
                    if up and up.get("url"):
                        img["src"] = up["url"]
                        if img.get("srcset"):
                            del img["srcset"]
                    # If upload failed, leave src pointing to review site rather than generating a 404 URL

            content = str(c_soup).strip()
            content = re.sub(r'^<(article|body|html)[^>]*>(.*)</(article|body|html)>$', r'\2', content, flags=re.DOTALL | re.IGNORECASE).strip()
        except Exception as clean_err:
            logger.warning(f"[WP Transfer] Could not clean content headers: {clean_err}")

        # ── Contextual Internal Linking Widget (SEO Cluster Authority) ──
        if "td-related-internal-box" not in content:
            cat_label = "خدمات"
            if category_ids:
                for lbl, cid in CATEGORY_MAP.items():
                    if cid in category_ids:
                        cat_label = lbl
                        break
            cat_map = {
                "صحة": ("صحة", "https://www.tahteldoo.com/category/%d8%b5%d8%ad%d8%a9"),
                "التغذية العلاجية": ("التغذية العلاجية", "https://www.tahteldoo.com/category/%d8%b5%d8%ad%d8%a9"),
                "تعليم": ("تعليم", "https://www.tahteldoo.com/category/%d8%aa%d8%b9%d9%84%d9%8a%d9%85"),
                "أعمال": ("أعمال", "https://www.tahteldoo.com/category/%d8%a3%d8%b9%d9%85%d8%a7%d9%84"),
                "خدمات": ("خدمات", "https://www.tahteldoo.com/category/%d8%ae%d8%af%d9%85%d8%a7%d8%aa"),
                "شخصيات عامة": ("شخصيات عامة", "https://www.tahteldoo.com/category/%d8%b4%d8%ae%d8%b5%d9%8a%d8%a7%d8%aa-%d8%b9%d8%a7%d9%85%d8%a9"),
                "تطوير ذات": ("تطوير ذات", "https://www.tahteldoo.com/category/%d8%aa%d8%b7%d9%88%d9%8a%d8%b1-%d8%b0%d8%a7%d8%aa"),
            }
            target_cat, cat_url = cat_map.get(cat_label, ("خدمات", "https://www.tahteldoo.com/category/%d8%ae%d8%af%d9%85%d8%a7%d8%aa"))
            internal_links_box = f'''<div class="td-related-internal-box" style="margin: 24px 0 16px; padding: 14px 18px; background: #F8FAFC; border-right: 4px solid #D97706; border-radius: 8px; font-size: 13.5px; line-height: 1.8;">
  <div style="font-weight: 700; color: #1E293B; margin-bottom: 6px;">📌 موضوعات ذات صلة في جريدة تحت الضوء:</div>
  <div style="color: #475569;">
    • تابع تغطيات وأحدث تقارير قسم <a href="{cat_url}" style="color: #0284C7; text-decoration: none; font-weight: 600;">«{target_cat}»</a> عبر موقعنا.<br/>
    • تصفح <a href="https://www.tahteldoo.com/" style="color: #0284C7; text-decoration: none; font-weight: 600;">الصفحة الرئيسية لجريدة تحت الضوء الإخبارية</a> لمتابعة أحدث الأخبار والتغطيات الحصرية.
  </div>
</div>'''
            content = content + "\n" + internal_links_box

        # ── Step 3: Publish to Main Site (www.tahteldoo.com) ──
        logger.info(f"[WP Transfer] نشر الخبر على الجريدة الأصلية: '{title}'")

        # Extract slug from review URL if available
        transfer_slug = None
        slug_match = re.search(r"/([^/]+?)(?:\.html)?/?$", clean_url)
        if slug_match:
            transfer_slug = self._clean_slug(slug_match.group(1))

        payload = {
            "title":      title,
            "content":    content,
            "status":     "publish",
            "categories": category_ids if category_ids else [DEFAULT_CATEGORY_ID],
            "excerpt":    clean_excerpt,
        }
        if transfer_slug:
            payload["slug"] = transfer_slug
        if main_featured_media_id:
            payload["featured_media"] = main_featured_media_id

        resp = requests.post(
            f"{self.MAIN_SITE_URL}/wp-json/wp/v2/posts",
            headers=self.main_account.get_headers(),
            json=payload,
            timeout=30
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"فشل النشر على الجريدة الأصلية: HTTP {resp.status_code} — {resp.text[:300]}"
            )

        new_post = resp.json()
        main_url     = new_post.get("link", "")
        main_post_id = str(new_post.get("id", ""))

        logger.info(f"✅ [WP Transfer] تم النقل والنشر بنجاح! الرابط الجديد: {main_url} | صورة بارزة: {main_featured_media_id}")

        return {
            "success":       True,
            "title":         title,
            "main_url":      main_url,
            "main_post_id":  main_post_id,
            "review_url":    clean_url,
            "original_post_id": review_post_id,
            "labels":        labels,
            "content_html":  content,
            "featured_image_url": main_featured_image_url or featured_image_url,
            "featured_media_id": main_featured_media_id
        }

    # ================================================================
    # FETCH POST BY URL (سحب المقال من الريفيو أو الرئيسي عبر الرابط)
    # ================================================================

    def fetch_post_by_url(self, article_url: str) -> dict:
        """
        Fetches an existing article by URL from either Review site or Main site.
        Auto-detects site domain, resolves post ID, slug, title, content, excerpt, and categories.
        """
        import urllib.parse
        from bs4 import BeautifulSoup

        clean_url = (article_url or "").strip()
        if not clean_url:
            return {"success": False, "error": "يرجى إدخال رابط المقال"}

        # Detect site
        is_review = "review" in clean_url.lower()
        site_type = "review" if is_review else "main"
        site_url = self.REVIEW_SITE_URL if is_review else self.MAIN_SITE_URL
        account = self.platform_account if is_review else self.main_account
        headers = account.get_headers()

        parsed = urllib.parse.urlparse(clean_url)
        slug_parts = [p for p in parsed.path.strip("/").split("/") if p]
        raw_slug = slug_parts[-1].replace(".html", "") if slug_parts else ""

        slug_candidates = []
        if raw_slug:
            slug_candidates.append(raw_slug)
            if "_" in raw_slug:
                slug_candidates.append(raw_slug.replace("_", "-"))
            if "-" in raw_slug:
                slug_candidates.append(raw_slug.replace("-", "_"))
            cleaned = self._clean_slug(raw_slug)
            if cleaned and cleaned not in slug_candidates:
                slug_candidates.append(cleaned)

        post = None

        # 1. Try slug candidate search via WP REST API
        for s in slug_candidates:
            try:
                r = requests.get(
                    f"{site_url}/wp-json/wp/v2/posts",
                    params={"slug": s, "_fields": "id,title,content,excerpt,categories,link,slug,featured_media", "_embed": 1},
                    headers=headers,
                    timeout=12
                )
                if r.status_code == 200:
                    posts = r.json()
                    if posts and isinstance(posts, list):
                        post = posts[0]
                        break
            except Exception as e:
                logger.warning(f"[fetch_post_by_url] Slug search error for {s}: {e}")

        # 2. Try search by keyword if slug search failed
        if not post and raw_slug:
            search_term = raw_slug.replace("blog-post", "").replace("-", " ").replace("_", " ").strip()
            if search_term:
                try:
                    r = requests.get(
                        f"{site_url}/wp-json/wp/v2/posts",
                        params={"search": search_term, "per_page": 5, "_fields": "id,title,content,excerpt,categories,link,slug,featured_media", "_embed": 1},
                        headers=headers,
                        timeout=12
                    )
                    if r.status_code == 200:
                        posts = r.json()
                        for p in posts:
                            if p.get("slug") in slug_candidates or str(p.get("id")) == raw_slug:
                                post = p
                                break
                        if not post and posts:
                            post = posts[0]
                except Exception as e:
                    logger.warning(f"[fetch_post_by_url] Search query error: {e}")

        # 3. Fallback: Direct HTML scraping from URL
        if not post:
            try:
                web_resp = requests.get(clean_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
                if web_resp.status_code == 200:
                    soup = BeautifulSoup(web_resp.text, "html.parser")
                    # Try finding shortlink or post ID in html
                    shortlink = soup.find("link", rel="shortlink")
                    scraped_post_id = ""
                    if shortlink and shortlink.get("href"):
                        sh_url = shortlink.get("href")
                        if "?p=" in sh_url:
                            scraped_post_id = sh_url.split("?p=")[-1].split("&")[0]

                    scraped_title = ""
                    og_title = soup.find("meta", property="og:title")
                    if og_title and og_title.get("content"):
                        scraped_title = og_title["content"].strip()
                    elif soup.find("h1"):
                        scraped_title = soup.find("h1").get_text(strip=True)

                    entry_content = soup.find(class_=re.compile(r"entry-content|post-content|article-content|wp-block-post-content"))
                    scraped_content = str(entry_content) if entry_content else ""

                    if scraped_post_id:
                        # Verify via REST API
                        try:
                            rp = requests.get(f"{site_url}/wp-json/wp/v2/posts/{scraped_post_id}", headers=headers, timeout=10)
                            if rp.status_code == 200:
                                post = rp.json()
                        except Exception:
                            pass

                    if not post and scraped_title and scraped_content:
                        return {
                            "success": True,
                            "post_id": scraped_post_id or "0",
                            "site_type": site_type,
                            "site_url": site_url,
                            "title": scraped_title,
                            "content_html": scraped_content,
                            "slug": raw_slug,
                            "link": clean_url,
                            "categories": [DEFAULT_CATEGORY_ID],
                            "featured_media": None
                        }
            except Exception as scrap_err:
                logger.warning(f"[fetch_post_by_url] Scrape fallback error: {scrap_err}")

        if not post:
            return {"success": False, "error": f"تعذر العثور على المقال عبر الرابط المدخل ({clean_url})"}

        title = post.get("title", {}).get("rendered", "") if isinstance(post.get("title"), dict) else str(post.get("title", ""))
        content = post.get("content", {}).get("rendered", "") if isinstance(post.get("content"), dict) else str(post.get("content", ""))
        excerpt = post.get("excerpt", {}).get("rendered", "") if isinstance(post.get("excerpt"), dict) else str(post.get("excerpt", ""))
        post_id = str(post.get("id", ""))
        link = post.get("link", clean_url)
        slug = post.get("slug", raw_slug)

        return {
            "success": True,
            "post_id": post_id,
            "site_type": site_type,
            "site_url": site_url,
            "title": title,
            "content_html": content,
            "excerpt": excerpt,
            "slug": slug,
            "link": link,
            "categories": post.get("categories", [DEFAULT_CATEGORY_ID]),
            "featured_media": post.get("featured_media")
        }

    def update_post(
        self,
        site_type: str,
        post_id: str,
        title: Optional[str] = None,
        content_html: Optional[str] = None,
        labels: Optional[List[str]] = None,
        meta_description: Optional[str] = None,
        slug: Optional[str] = None,
        featured_media_id: Optional[int] = None
    ) -> dict:
        """
        Updates an existing WordPress post on either review or main site.
        """
        is_main = str(site_type).lower() in ("main", "official", "www")
        account = self.main_account if is_main else self.platform_account
        site_url = self.MAIN_SITE_URL if is_main else self.REVIEW_SITE_URL

        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        if content_html:
            payload["content"] = content_html
        if labels:
            payload["categories"] = resolve_category_ids(labels)
        if meta_description:
            payload["excerpt"] = meta_description
        if slug:
            clean_s = self._clean_slug(slug)
            if clean_s:
                payload["slug"] = clean_s
        if featured_media_id:
            payload["featured_media"] = featured_media_id

        if not payload:
            return {"success": True, "message": "No fields to update"}

        resp = requests.post(
            f"{site_url}/wp-json/wp/v2/posts/{post_id}",
            headers=account.get_headers(),
            json=payload,
            timeout=20
        )
        if resp.status_code in (200, 201):
            d = resp.json()
            return {
                "success": True,
                "post_id": str(d.get("id")),
                "url": d.get("link"),
                "site": site_url,
                "title": d.get("title", {}).get("rendered")
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                "site": site_url,
                "post_id": post_id
            }

    def delete_post(self, post_id: str, site_type: str = "review", force: bool = True) -> dict:
        """
        Deletes a WordPress post from either review or main site.
        """
        is_main = str(site_type).lower() in ("main", "official", "www")
        account = self.main_account if is_main else self.platform_account
        site_url = self.MAIN_SITE_URL if is_main else self.REVIEW_SITE_URL

        try:
            resp = requests.delete(
                f"{site_url}/wp-json/wp/v2/posts/{post_id}",
                params={"force": str(force).lower()},
                headers=account.get_headers(),
                timeout=20
            )
            if resp.status_code in (200, 204):
                return {"success": True, "post_id": str(post_id), "site": site_url}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}", "post_id": str(post_id)}
        except Exception as e:
            return {"success": False, "error": str(e), "post_id": str(post_id)}

    def sync_update_article_both_sites(
        self,
        review_post_id: Optional[str] = None,
        main_post_id: Optional[str] = None,
        title: Optional[str] = None,
        content_html: Optional[str] = None,
        labels: Optional[List[str]] = None,
        meta_description: Optional[str] = None,
        slug: Optional[str] = None
    ) -> dict:
        """
        Two-Way Synchronization: Updates both Review and Main sites concurrently.
        Ensures content stays 100% identical across both installations.
        """
        results = {"success": True, "review": None, "main": None}

        # Update Main site
        if main_post_id and str(main_post_id).isdigit():
            res_main = self.update_post(
                site_type="main",
                post_id=str(main_post_id),
                title=title,
                content_html=content_html,
                labels=labels,
                meta_description=meta_description,
                slug=slug
            )
            results["main"] = res_main
            if not res_main.get("success"):
                results["success"] = False

        # Update Review site
        if review_post_id and str(review_post_id).isdigit():
            res_rev = self.update_post(
                site_type="review",
                post_id=str(review_post_id),
                title=title,
                content_html=content_html,
                labels=labels,
                meta_description=meta_description,
                slug=slug
            )
            results["review"] = res_rev
            if not res_rev.get("success"):
                results["success"] = False

        return results

    def get_blog_posts_by_date_window(self, blog_id: str, date_str: str, days: int = 1, token_path: str = None) -> list:
        """
        Fetches WordPress posts published in a specific date window (date_str to date_str + days).
        Returns a list of dicts with keys: id, title, url, published.
        Mirrors BloggerService.get_blog_posts_by_date_window().
        """
        import datetime
        try:
            is_main = "www.tahteldoo.com" in str(blog_id).lower() or str(blog_id) == self.MAIN_BLOG_ID
            site_url = self.MAIN_SITE_URL if is_main else self.REVIEW_SITE_URL
            account = self.main_account if is_main else self.platform_account
            
            dt_start = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            dt_end = dt_start + datetime.timedelta(days=days)
            
            after_iso = dt_start.strftime("%Y-%m-%dT00:00:00")
            before_iso = dt_end.strftime("%Y-%m-%dT23:59:59")
            
            resp = requests.get(
                f"{site_url}/wp-json/wp/v2/posts",
                params={
                    "after": after_iso,
                    "before": before_iso,
                    "per_page": 100,
                    "_fields": "id,title,link,date"
                },
                headers=account.get_headers(),
                timeout=15
            )
            if resp.status_code == 200:
                posts = resp.json()
                results = []
                for p in posts:
                    t_val = p.get("title", {})
                    t_str = t_val.get("rendered", "") if isinstance(t_val, dict) else str(t_val or "")
                    results.append({
                        "id": str(p.get("id", "")),
                        "title": t_str,
                        "url": p.get("link", ""),
                        "published": p.get("date", "")
                    })
                return results
        except Exception as e:
            logger.warning(f"[WP get_blog_posts_by_date_window] Error fetching posts for {date_str} from {blog_id}: {e}")
        return []

    # ================================================================
    # DELETE REVIEW POSTS (حذف من موقع الريفيو)
    # ================================================================

    def delete_review_posts(self, post_ids: list, token_path: str = None) -> dict:
        """
        Deletes a list of WordPress post IDs from review.tahteldoo.com.
        Also resolves by slug/title search if a non-WordPress ID is provided.
        """
        deleted = []
        failed  = []
        account = self.automation_account

        for pid in post_ids:
            clean_pid = str(pid).strip()
            if not clean_pid or clean_pid.startswith("db_"):
                continue

            wp_id_to_delete = None

            # If it's a standard WP integer ID (typically < 1,000,000)
            if clean_pid.isdigit() and len(clean_pid) < 10:
                wp_id_to_delete = clean_pid
            else:
                # Might be a Blogger ID or slug — search WP by query
                try:
                    search_resp = requests.get(
                        f"{account.site_url}/wp-json/wp/v2/posts",
                        headers=account.get_headers(),
                        params={"search": clean_pid, "per_page": 5},
                        timeout=10
                    )
                    if search_resp.status_code == 200 and search_resp.json():
                        wp_id_to_delete = str(search_resp.json()[0].get("id"))
                except Exception as s_err:
                    logger.warning(f"[WP Delete] Search fallback failed for {clean_pid}: {s_err}")

            if not wp_id_to_delete:
                wp_id_to_delete = clean_pid

            try:
                resp = requests.delete(
                    f"{account.site_url}/wp-json/wp/v2/posts/{wp_id_to_delete}",
                    headers=account.get_headers(),
                    params={"force": True},  # permanent delete (skip trash)
                    timeout=15
                )
                if resp.status_code in (200, 201, 204, 410):
                    deleted.append(clean_pid)
                    logger.info(f"[WP Delete] Deleted review post {wp_id_to_delete} (target: {clean_pid}) successfully.")
                elif resp.status_code == 404:
                    logger.warning(f"[WP Delete] Post {wp_id_to_delete} not found on WordPress (404).")
                    failed.append({"post_id": clean_pid, "error": "المقال غير موجود على ووردبريس (404)"})
                else:
                    err = f"HTTP {resp.status_code}: {resp.text[:150]}"
                    failed.append({"post_id": clean_pid, "error": err})
                    logger.warning(f"[WP Delete] Failed to delete post {wp_id_to_delete}: {err}")

            except Exception as e:
                failed.append({"post_id": clean_pid, "error": str(e)})
                logger.warning(f"[WP Delete] Exception deleting post {wp_id_to_delete}: {e}")

        return {
            "success":       len(deleted) > 0 or len(failed) == 0,
            "deleted_count": len(deleted),
            "deleted_ids":   deleted,
            "failed_count":  len(failed),
            "failed":        failed
        }

    def delete_post(self, post_id: str, blog_id: str = None) -> dict:
        """Convenience method to delete a single post by ID."""
        res = self.delete_review_posts([str(post_id)])
        return {"success": res.get("success", False), "post_id": post_id, "details": res}



    # ================================================================
    # ACCOUNT STATUS & TESTING
    # ================================================================

    def get_slots_status(self) -> Dict[str, Any]:
        """
        Returns status of all review accounts and main account.
        Mirrors BloggerService.get_slots_status() for UI compatibility.
        """
        slots_list = []
        for acc in self.review_accounts:
            slots_list.append({
                "slot_id":    acc.account_id,
                "title":      f"حساب {acc.account_id} ({acc.role})",
                "file_name":  acc.username,
                "exists":     True,
                "username":   acc.username,
                "role":       acc.role,
                "is_connected": True,  # Assumed — validated via test_single_account
                "in_cooldown":  acc.is_in_cooldown(),
                "cooldown_remaining_sec": max(0, int(acc.cooldown_until - time.time())) if acc.is_in_cooldown() else 0
            })

        main_info = {
            "slot_id":    0,
            "title":      "الجريدة الأصلية (Main — www.tahteldoo.com)",
            "file_name":  self.main_account.username,
            "exists":     True,
            "username":   self.main_account.username,
            "role":       "main",
            "is_connected": True,
            "in_cooldown":  False,
        }

        return {
            "success": True,
            "master": main_info,
            "slots":  slots_list,
            "tier3":  {"count": 0, "items": []}
        }

    def test_single_account(self, slot_id: int) -> Dict[str, Any]:
        """
        Tests a specific account by creating a draft post then deleting it.
        slot_id: 1-5 for review accounts, 0 for main account.
        Mirrors BloggerService.test_single_account() for UI compatibility.
        """
        if slot_id == 0:
            account = self.main_account
            site = self.MAIN_SITE_URL
        else:
            idx = slot_id - 1
            if idx >= len(self.review_accounts):
                return {"success": False, "slot_id": slot_id, "error": "رقم الحساب غير موجود"}
            account = self.review_accounts[idx]
            site = self.REVIEW_SITE_URL

        t0 = time.time()
        test_title = f"[فحص سريع] حساب {account.username} — {int(time.time())}"
        try:
            # Create draft
            resp = requests.post(
                f"{site}/wp-json/wp/v2/posts",
                headers=account.get_headers(),
                json={
                    "title":   test_title,
                    "content": "<p>فحص آلي سريع — سيتم الحذف فوراً</p>",
                    "status":  "draft",
                    "categories": [DEFAULT_CATEGORY_ID]
                },
                timeout=15
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "slot_id": slot_id,
                    "status":  "error",
                    "error":   f"HTTP {resp.status_code}: {resp.text[:200]}"
                }

            post_id = resp.json().get("id")
            latency_ms = int((time.time() - t0) * 1000)

            # Immediate delete
            if post_id:
                try:
                    requests.delete(
                        f"{site}/wp-json/wp/v2/posts/{post_id}",
                        headers=account.get_headers(),
                        params={"force": True},
                        timeout=10
                    )
                except Exception:
                    pass

            return {
                "success":     True,
                "slot_id":     slot_id,
                "status":      "ready",
                "username":    account.username,
                "role":        account.role,
                "site":        site,
                "latency_ms":  latency_ms,
                "message":     f"✅ الحساب {account.username} متصل وصالح! ({latency_ms}ms)"
            }

        except Exception as e:
            return {
                "success": False,
                "slot_id": slot_id,
                "status":  "error",
                "error":   str(e)
            }

    def get_pool_status(self) -> list:
        """
        Returns visual status for all accounts.
        Mirrors BloggerService.get_pool_status() for UI compatibility.
        """
        statuses = []
        for acc in self.review_accounts:
            statuses.append({
                "account_id":   acc.account_id,
                "token_file":   acc.username,
                "exists":       True,
                "is_valid":     True,
                "status_text":  "✅ متصل ونشط" if not acc.is_in_cooldown() else "⏳ في فترة راحة",
                "display_name": f"{acc.username} ({acc.role})"
            })
        return statuses

    def is_authenticated(self) -> bool:
        """Compatibility method — always True for WordPress (credentials are static)."""
        return True

    def get_current_user_profile(self) -> dict:
        """Compatibility method for Settings UI."""
        return {
            "id":      "wp_review",
            "name":    "WordPress Review Admin",
            "email":   "td_admin_1",
            "is_auth": True
        }

    def get_google_account_details(self) -> dict:
        """Compatibility method — returns WP account details instead of Google."""
        return {
            "is_connected": True,
            "email":   "td_admin_1 (WordPress)",
            "name":    "WordPress Admin",
            "picture": ""
        }

    def format_article_html(self, content: str) -> str:
        """
        Converts AI markdown bold markers to clean HTML.
        Same as BloggerService.format_article_html() — kept for pipeline compatibility.
        """
        if not content:
            return ""
        content = str(content).strip()
        from services.article_formatter import ArticleFormatter
        content = re.sub(r"\*\*\*(.*?)\*\*\*", f"{ArticleFormatter.STRONG_OPEN}\\1</strong>", content, flags=re.DOTALL)
        content = re.sub(r"\*\*(.*?)\*\*",     f"{ArticleFormatter.STRONG_OPEN}\\1</strong>", content, flags=re.DOTALL)
        content = content.replace("**", "")
        return content

    def delete_slot(self, slot_id: int) -> Dict[str, Any]:
        """
        Compatibility method — WP accounts don't need deletion (no token files).
        Returns success for UI compatibility.
        """
        return {
            "success":  True,
            "slot_id":  slot_id,
            "deleted":  False,
            "message":  "حسابات WordPress لا تحتاج لحذف توكن. يمكنك تغيير Application Password من لوحة تحكم WordPress."
        }

    def get_quota_info(self) -> dict:
        """
        Compatibility method — WordPress has no quota system like Blogger.
        Returns unlimited quota status.
        """
        return {
            "used":        0,
            "limit":       999999,
            "remaining":   999999,
            "percentage":  0.0,
            "status":      "OK",
            "status_text": "🟢 WordPress — لا يوجد حد نشر يومي",
            "is_live_google": False
        }

    # ── Aliases for API compatibility ──
    create_post          = publish_post
    execute_resilient_publish = _resilient_publish


# ================================================================
# GLOBAL SINGLETON INSTANCE
# ================================================================

wordpress_service = WordPressService()

# ── Alias: blogger_service → wordpress_service (for zero-change imports) ──
blogger_service = wordpress_service
