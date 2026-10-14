"""
Compatibility Stub — BloggerService Redirect
يقوم بإعادة توجيه أي طلبات قديمة لـ BloggerService مباشرة إلى WordPressService
لضمان عدم حدوث أي خطأ ونشر كل شيء على ورد بريس جريدة الريفيو
"""

from services.wordpress_service import WordPressService, wordpress_service

BloggerService = WordPressService
blogger_service = wordpress_service

__all__ = ["BloggerService", "blogger_service", "WordPressService", "wordpress_service"]
