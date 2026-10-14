from .ai_service import AIService, ai_service
from .wordpress_service import WordPressService, wordpress_service
from .image_service import ImageService, image_service
from .whatsapp_service import WhatsAppService, whatsapp_service
from .article_formatter import ArticleFormatter

# ── Backward-Compatibility Alias ──
# كل الكود القديم اللي بيستخدم blogger_service أو BloggerService
# هيشتغل بدون أي تغيير تلقائياً
BloggerService = WordPressService
blogger_service = wordpress_service

__all__ = [
    "AIService",
    "ai_service",
    "WordPressService",
    "wordpress_service",
    "BloggerService",     # alias
    "blogger_service",   # alias
    "ImageService",
    "image_service",
    "WhatsAppService",
    "whatsapp_service",
    "ArticleFormatter",
]
