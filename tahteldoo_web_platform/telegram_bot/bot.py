import os
import sys
import logging
import asyncio
import threading
import re
from pathlib import Path
from typing import Dict, Any

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Project dependencies
from services.ai_service import ai_service, AIService
from services.image_service import image_service
from services.blogger_service import blogger_service
from services.whatsapp_service import (
    whatsapp_service,
    clean_egyptian_phone,
    extract_preferred_whatsapp_phone,
    extract_all_egyptian_phones
)
from database.db import db
from core.config import Config
from core.logger import logger
from services.central_sync_service import central_sync_service

BOT_TOKEN = getattr(Config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN", "8834102717:AAGCflNVXtYccq1oG0JqYQGW2bv4WBkwhAM")

# Dedicated AIService for Telegram Bot using TELEGRAM_ZAI_API_KEY as primary Z.AI key
TELEGRAM_ZAI_KEY = getattr(Config, "TELEGRAM_ZAI_API_KEY", "") or os.getenv("TELEGRAM_ZAI_API_KEY", "ff82d2827a0840b09f3fbb1f630af70a.doXAEqDUpjlHOEwN")
telegram_ai_service = AIService(primary_zai_key=TELEGRAM_ZAI_KEY)

# In-memory dictionary to store active user article sessions
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}


def clean_phone_and_name(text: str):
    """Extract phone number and client name from raw input text if present."""
    if not text:
        return "", ""
    
    phone = extract_preferred_whatsapp_phone(text) or clean_egyptian_phone(text)
    
    name_match = re.search(r"(?:العميل|الجهة|الاسم|د\.|أستاذ|مهندس|دكتورة|مؤسسة|شركة|أكاديمية|عيادة)[\s:]*([^\n,]+)", text)
    name = name_match.group(1).strip() if name_match else ""
    
    if name and phone:
        # Strip raw phone patterns from name if present
        name = re.sub(r'[\+\d\s\-\.\/\(\):]{8,}', '', name).strip()
    
    return phone, name


def clean_markdown_symbols(text: Any) -> str:
    """Strips/escapes problematic raw Markdown symbols to prevent Telegram entity parsing errors."""
    if not text:
        return ""
    s = str(text)
    return s.replace("_", "\\_").replace("*", " ").replace("`", "'")


def split_text_chunks(text: str, max_length: int = 4000) -> list:
    """Splits a long message into safe chunks preserving line breaks when possible."""
    if not text:
        return [""]
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    while len(text) > max_length:
        split_idx = text.rfind("\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = text.rfind(" ", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = max_length
            
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    
    if text:
        chunks.append(text)
    return chunks


def strip_markdown_formatting_safe(text: str) -> str:
    """Strips Markdown syntax bold/italic/code markers while preserving URLs intact."""
    if not text:
        return ""
    clean = text.replace("**", "").replace("`", "")
    words = clean.split()
    sanitized = []
    for word in words:
        if word.startswith("http://") or word.startswith("https://") or "www." in word or ".html" in word:
            sanitized.append(word)
        else:
            sanitized.append(word.replace("_", ""))
    return " ".join(sanitized)


async def safe_edit_message(target, text: str, reply_markup=None, disable_web_page_preview=True):
    """
    Safely edits a telegram message with Markdown.
    Truncates text if it exceeds 4000 characters to fit Telegram limits.
    If Telegram raises entity parsing errors ('Can't parse entities'), automatically falls back to plain text.
    """
    if not text:
        return

    if len(text) > 4000:
        text = text[:3950] + "\n\n...(تم اختصار النص لحجم تلجرام)"

    try:
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        else:
            await target.edit_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
    except Exception as err:
        logger.warning(f"Telegram Markdown parse failed ({err}). Retrying with plain text fallback...")
        clean_text = strip_markdown_formatting_safe(text)
        try:
            if hasattr(target, "edit_message_text"):
                await target.edit_message_text(
                    text=clean_text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            else:
                await target.edit_text(
                    text=clean_text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
        except Exception as fallback_err:
            logger.error(f"Fallback edit message also failed: {fallback_err}")


async def safe_send_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None, disable_web_page_preview=True):
    """Safely sends a telegram message, automatically splitting long text into multiple chunks if it exceeds Telegram's limit."""
    if not text:
        return None
        
    chunks = split_text_chunks(text, max_length=4000)
    last_sent_msg = None

    for i, chunk in enumerate(chunks):
        current_markup = reply_markup if i == len(chunks) - 1 else None
        try:
            last_sent_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
                reply_markup=current_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception as err:
            logger.warning(f"Telegram send_message Markdown failed ({err}). Retrying chunk {i+1}/{len(chunks)} with plain text...")
            clean_chunk = strip_markdown_formatting_safe(chunk)
            try:
                last_sent_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=clean_chunk,
                    parse_mode=None,
                    reply_markup=current_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except Exception as fallback_err:
                logger.error(f"Fallback send_message failed for chunk {i+1}: {fallback_err}")

    return last_sent_msg


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and onboarding prompt on /start."""
    chat_id = update.effective_chat.id
    reporter = db.get_reporter(str(chat_id))
    
    if not reporter:
        session = USER_SESSIONS.get(chat_id, {})
        session["state"] = "AWAITING_REPORTER_NAME"
        USER_SESSIONS[chat_id] = session
        prompt = (
            "👋 **أهلاً بك في بوت جريدة تحت الضوء الإخبارية!** 📰\n\n"
            "يرجى إدخال **اسمك الكريم** (مثل: *أحمد محمود*) ليتم اعتماده كـ (**صحفي لدى جريدة تحت الضوء**) في رسائل الواتساب الموجهة للعملاء.\n\n"
            "✍️ **اكتب اسمك الآن للبدء:**"
        )
        await safe_send_message(context, chat_id, prompt)
        return

    # Check reporter activation code
    api_key = reporter.get("api_key")
    if not api_key:
        session = USER_SESSIONS.get(chat_id, {})
        session["state"] = "AWAITING_ACTIVATION_CODE"
        USER_SESSIONS[chat_id] = session
        prompt = (
            f"👋 **أهلاً بك يا {clean_markdown_symbols(reporter['name'])} في بوت جريدة تحت الضوء!** 📰\n\n"
            f"🔑 **الخطوة الأخيرة للتفعيل:** يرجى إدخال **كود تفعيل الحساب** (Activation Code) المسلّم لك من إدارة الجريدة لتفعيل حسابك والبدء في النشر:\n\n"
            f"✍️ **اكتب كود التفعيل الآن:**"
        )
        await safe_send_message(context, chat_id, prompt)
        return

    welcome_text = (
        f"✨ **أهلاً بك يا {clean_markdown_symbols(reporter['name'])} في بوت جريدة تحت الضوء!** 📰\n\n"
        f"💼 **الصفة التحريرية**: {reporter.get('role', 'صحفي لدى')} جريدة تحت الضوء الإخبارية\n"
        f"🔑 **حالة الحساب**: مفعل وجاهز للنشر المباشر ⚡\n\n"
        "📌 **طريقة الاستخدام:**\n"
        "1️⃣ أرسل نص الخبر أو تفاصيل العميل أولاً.\n"
        "2️⃣ سيطلب منك البوت إرفاق صورة الخبر.\n"
        "3️⃣ سيتم صياغة الخبر بحسابك والنشر المباشر على المدونة وتوليد رابط الواتساب المخصص باسمك الفوري!\n\n"
        "💡 لتغيير اسمك: `/setname الاسم الجديد`\n"
        "💡 لتحديث كود التفعيل: `/activate كود_التفعيل`\n\n"
        "✍️ **أرسل تفاصيل الخبر الآن للبدء!**"
    )
    await safe_send_message(context, chat_id, welcome_text)


async def setname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows reporter to update their name for WhatsApp messages."""
    chat_id = update.effective_chat.id
    text = update.message.text if update.message else ""
    parts = text.split(maxsplit=1)
    if len(parts) > 1:
        new_name = parts[1].strip()[:100]
        db.save_reporter(str(chat_id), new_name, "صحفي لدى")
        await safe_send_message(
            context, chat_id,
            f"✅ **تم تحديث اسم الصحفي بنجاح!**\n\n"
            f"👤 **الاسم الجديد المسجل**: {clean_markdown_symbols(new_name)}\n"
            f"💼 **الصفة**: صحفي لدى جريدة تحت الضوء الإخبارية ⚡\n\n"
            f"سيتم استخدام هذا الاسم تلقائياً في جميع رسائل التنسيق والواتساب القادمة!"
        )
    else:
        reporter = db.get_reporter(str(chat_id))
        curr_name = reporter.get('name') if reporter else "غير مسجل"
        await safe_send_message(
            context, chat_id,
            f"👤 **الاسم المسجل حالياً**: {clean_markdown_symbols(curr_name)}\n\n"
            f"✍️ **طريقة تغيير اسمك:**\n"
            f"أرسل الأمر متبوعاً باسمك الجديد، مثل:\n"
            f"`/setname محمد شلبي`\n"
            f"أو\n"
            f"`/اسم محمد شلبي`"
        )


async def activate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows reporter to activate or update their personal LLM API activation code."""
    chat_id = update.effective_chat.id
    text = update.message.text if update.message else ""
    parts = text.split(maxsplit=1)
    
    reporter = db.get_reporter(str(chat_id))
    if not reporter:
        await start_command(update, context)
        return

    if len(parts) > 1:
        new_key = parts[1].strip()
        if len(new_key) < 10:
            await safe_send_message(context, chat_id, "⚠️ **كود التفعيل غير صالح!** يرجى التأكد من كتابة الكود كاملاً كما استلمته من إدارة الجريدة.")
            return
        
        db.update_reporter_key(str(chat_id), new_key)
        session = USER_SESSIONS.get(chat_id, {})
        session["state"] = None
        USER_SESSIONS[chat_id] = session

        masked_key = f"...{new_key[-4:]}" if len(new_key) > 6 else new_key
        await safe_send_message(
            context, chat_id,
            f"🎉 **تم تفعيل وتحديث كود حسابك بنجاح!** ✅\n\n"
            f"👤 **الصحفي**: {clean_markdown_symbols(reporter['name'])}\n"
            f"🔑 **كود التفعيل المسجل**: `{masked_key}`\n\n"
            f"🚀 حسابك الآن يعمل باستقلالية تامة وبأقصى سرعة دون أي انتظار. أرسل أي خبر للبدء!"
        )
    else:
        curr_key = reporter.get("api_key")
        if curr_key:
            masked = f"...{curr_key[-4:]}" if len(curr_key) > 6 else curr_key
            status_txt = f"✅ حسابك مفعل بالكود: `{masked}`"
        else:
            status_txt = "⚠️ حسابك غير مفعل بعد!"

        await safe_send_message(
            context, chat_id,
            f"🔑 **إدارة كود التفعيل:**\n"
            f"{status_txt}\n\n"
            f"✍️ لتفعيل حسابك أو تغيير الكود، أرسل الأمر متبوعاً بالكود:\n"
            f"`/activate كود_التفعيل_الجديد`\n"
            f"أو\n"
            f"`/كود كود_التفعيل_الجديد`"
        )


async def myname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays current registered reporter profile."""
    chat_id = update.effective_chat.id
    reporter = db.get_reporter(str(chat_id))
    if reporter:
        key = reporter.get("api_key")
        if key:
            key_display = f"مفعل ✅ (`...{key[-4:]}`)"
        else:
            key_display = "غير مفعل ❌ (أرسل `/activate الكود` للتفعيل)"

        msg = (
            f"👤 **بياناتك المسجلة حالياً:**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• **الاسم**: {clean_markdown_symbols(reporter['name'])}\n"
            f"• **الصفة**: {reporter.get('role', 'صحفي لدى')} جريدة تحت الضوء الإخبارية\n"
            f"• **حالة الحساب**: {key_display}\n\n"
            f"💡 لتغيير اسمك أرسل: `/setname الاسم الجديد`\n"
            f"💡 لتحديث كود التفعيل: `/activate كود_التفعيل`"
        )
    else:
        msg = "⚠️ لم تقم بتسجيل اسمك بعد. أرسل اسمك الآن لتسجيله!"
    await safe_send_message(context, chat_id, msg)


def check_duplicate_alert(phone: str, name: str = "", all_phones: list = None) -> str:
    """Checks central sync service for duplicate phone and formats an alert message if exists."""
    phones_to_check = []
    if all_phones and isinstance(all_phones, list):
        for p in all_phones:
            if p and p not in phones_to_check:
                phones_to_check.append(p)
    if phone and phone not in phones_to_check:
        phones_to_check.insert(0, phone)

    if not phones_to_check:
        return ""

    for p in phones_to_check:
        dup = central_sync_service.check_phone(p)
        if dup.get("exists"):
            title = dup.get("title", "خبر سابق")
            post_url = dup.get("post_url", "")
            pub_at = str(dup.get("published_at", ""))[:10]
            c_name = dup.get("client_name") or name or "العميل"
            link_line = f"🔗 **رابط المقال المنشور**: {post_url}\n" if post_url else ""
            return (
                f"⚠️ **تنبيه: هذا العميل سبق نشر خبر له مسبقاً!** 🔍\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 **صاحب الخبر**: {clean_markdown_symbols(c_name)}\n"
                f"📱 **رقم الهاتف**: `{p}`\n"
                f"📌 **عنوان الخبر السابق**: {clean_markdown_symbols(title)}\n"
                f"📅 **تاريخ النشر**: {pub_at}\n"
                f"{link_line}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💡 **خيار النشر متاح:** يمكنك الضغط على ⚡ **[النشر مرة أخرى لهذا العميل]** لمتابعة النشر بشكل طبيعي دون أي مشكلة، أو الإلغاء إذا كان عن طريق الخطأ."
            )
    return ""


def get_duplicate_inline_keyboard() -> InlineKeyboardMarkup:
    """Returns interactive keyboard allowing reporter to republish or cancel when duplicate is detected."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ النشر مرة أخرى لهذا العميل", callback_data="confirm_republish")
        ],
        [
            InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_post")
        ]
    ])


async def generate_and_publish_article(chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg=None):
    """Generates AI article combining saved text/image and IMMEDIATELY publishes it to Blogger."""
    session = USER_SESSIONS.get(chat_id)
    if not session:
        return

    raw_text = session.get("raw_text", "")
    image_url = session.get("image_url") or getattr(Config, "DEFAULT_IMAGE_URL", "https://i.ibb.co/1q20tJ0/default-news.jpg")
    extracted_phone = session.get("extracted_phone", "")
    extracted_name = session.get("extracted_name", "")

    # Layer 1 Protection: Verify duplicate against Central Hub before spending tokens (bypass if user confirmed republish)
    all_phones = extract_all_egyptian_phones(raw_text)
    if not session.get("force_republish"):
        dup_alert = check_duplicate_alert(extracted_phone, extracted_name, all_phones=all_phones)
        if dup_alert:
            reply_markup = get_duplicate_inline_keyboard()
            if status_msg:
                await safe_edit_message(status_msg, dup_alert, reply_markup=reply_markup)
            else:
                await safe_send_message(context, chat_id, dup_alert, reply_markup=reply_markup)
            return

    # Check reporter activation key
    reporter = db.get_reporter(str(chat_id))
    user_key = (reporter.get("api_key") if reporter else "") or ""
    if not user_key:
        session["state"] = "AWAITING_ACTIVATION_CODE"
        USER_SESSIONS[chat_id] = session
        err_msg = (
            "⚠️ **حسابك غير مفعل بعد!**\n\n"
            "يرجى إدخال **كود تفعيل الحساب** (Activation Code) المسلّم لك من إدارة الجريدة لتتمكن من صياغة ونشر الأخبار.\n\n"
            "✍️ **أرسل كود التفعيل الآن للبدء:**"
        )
        if status_msg:
            await safe_edit_message(status_msg, err_msg)
        else:
            await safe_send_message(context, chat_id, err_msg)
        return

    raw_text = session.get("raw_text", "")
    image_url = session.get("image_url") or getattr(Config, "DEFAULT_IMAGE_URL", "https://i.ibb.co/1q20tJ0/default-news.jpg")
    extracted_phone = session.get("extracted_phone", "")
    extracted_name = session.get("extracted_name", "")

    if status_msg:
        await safe_edit_message(status_msg, "⚡ **جاري صياغة الخبر بالذكاء الاصطناعي والنشر المباشر على المدونة...**")
    else:
        status_msg = await safe_send_message(context, chat_id, "⚡ **جاري صياغة الخبر بالذكاء الاصطناعي والنشر المباشر على المدونة...**")

    try:
        # 1. Generate Article using reporter's dedicated AIService instance (complete user isolation, zero waiting queue)
        user_ai_service = AIService(primary_zai_key=user_key)
        article_data = await asyncio.to_thread(
            user_ai_service.generate_article,
            raw_notes_or_name=raw_text,
            phone_or_raw=extracted_phone,
            raw_notes=raw_text
        )
        
        article_data["image_url"] = image_url
        client_name = article_data.get("client_name") or extracted_name or "العميل الكريم"
        client_phone = (
            extract_preferred_whatsapp_phone(raw_text)
            or article_data.get("client_phone")
            or extracted_phone
            or ""
        )
        labels = article_data.get("labels", ["خدمات"])
        current_label = labels[0] if labels else "خدمات"
        current_label = AIService.normalize_label(current_label, raw_text)
        article_data["labels"] = [current_label]
        article_data["raw_text"] = raw_text

        # 2. Enforce Newspaper-wide Rate Limit (1 article per minute across all reporters)
        remaining = central_sync_service.get_publish_cooldown(cooldown_seconds=60)
        if remaining > 0:
            if status_msg:
                try:
                    await safe_edit_message(
                        status_msg,
                        f"⏳ **تنظيم تدفق الأخبار للجريدة (ليمت دقيقة):**\n\n"
                        f"تم نشر خبر بالجريدة منذ قليل. لضمان سرعة الأرشفة وتجنب الحظر، سيبدأ نشر خبرك تلقائياً بعد **{remaining}** ثانية... 🕒"
                    )
                except Exception:
                    pass
            while remaining > 0:
                await asyncio.sleep(min(remaining, 5))
                remaining = central_sync_service.get_publish_cooldown(cooldown_seconds=60)
                if remaining > 0 and status_msg:
                    try:
                        await safe_edit_message(
                            status_msg,
                            f"⏳ **تنظيم تدفق الأخبار للجريدة:**\n\n"
                            f"متبقي **{remaining}** ثانية على موعد إطلاق ونشر خبرك تلقائياً... 🕒"
                        )
                    except Exception:
                        pass

        central_sync_service.record_publish_event()

        # 3. Instant Publish to Blogger via Multi-Account Pool in BloggerService
        if hasattr(blogger_service, "publish_article"):
            published_post = await asyncio.to_thread(blogger_service.publish_article, article_data, use_pool=True)
        else:
            from services.article_formatter import ArticleFormatter
            title = article_data.get("title", "خبر صحفي جديد")
            content_html = ArticleFormatter.json_to_html(article_data, image_url=image_url)
            res = await asyncio.to_thread(
                blogger_service.publish_post,
                title=title,
                content_html=content_html,
                labels=[current_label],
                is_draft=False,
                use_pool=True
            )
            published_post = {
                "id": res.get("post_id"),
                "url": res.get("post_url")
            }
            
        post_url = published_post.get("url") or published_post.get("post_url", "")
        post_id = published_post.get("id") or published_post.get("post_id", "")
        
        # Fetch Reporter info for WhatsApp message customization and activity log
        reporter = db.get_reporter(str(chat_id))
        reporter_name = reporter.get("name") if reporter else "صحفي"
        editor_name = reporter.get("name") if reporter else "محمد شلبي"
        editor_role = reporter.get("role") if reporter else "صحفي لدى"

        # Save record to DB with reporter ID and log activity
        try:
            db.save_article(
                client_name=client_name,
                client_phone=client_phone,
                title=article_data.get("title"),
                slug=article_data.get("slug"),
                labels=current_label,
                content=article_data.get("content", ""),
                blogger_post_id=post_id,
                blogger_url=post_url,
                entity_type=article_data.get("entity_type", "male"),
                reporter_telegram_id=str(chat_id)
            )
            db.log_bot_activity(
                telegram_id=str(chat_id),
                reporter_name=reporter_name,
                action="نشر خبر",
                details=f"العنوان: {article_data.get('title', '')[:50]}... | القسم: {current_label}"
            )
        except Exception as db_err:
            logger.error(f"DB Save Error in Telegram Bot: {db_err}")

        # Sync to Central Server Hub
        try:
            central_sync_service.register_published_post({
                "client_name": client_name,
                "client_phone": client_phone,
                "title": article_data.get("title"),
                "slug": article_data.get("slug"),
                "labels": current_label,
                "post_url": post_url,
                "post_id": post_id,
                "reporter_telegram_id": str(chat_id),
                "blogger_status": "PUBLISHED"
            })
        except Exception as sync_err:
            logger.warning(f"Central sync error in Telegram bot: {sync_err}")

        # Register all secondary phone numbers found in raw notes under the same organization
        registered_secondaries = []
        try:
            registered_secondaries = db.register_secondary_client_phones(
                primary_phone=client_phone,
                all_phones=all_phones,
                client_name=client_name,
                article_data={
                    "title": article_data.get("title"),
                    "slug": article_data.get("slug"),
                    "labels": current_label,
                    "post_url": post_url,
                    "post_id": post_id,
                    "final_html": article_data.get("content", ""),
                    "reporter_telegram_id": str(chat_id),
                    "author_name": reporter_name,
                    "blogger_status": "PUBLISHED"
                }
            )
        except Exception as sec_err:
            logger.warning(f"Secondary phone registration error in bot: {sec_err}")

        # 3. Generate Direct WhatsApp Link (Zero shorteners)
        wa_link = whatsapp_service.generate_whatsapp_click_link(
            phone=client_phone,
            name=client_name,
            post_url=post_url,
            entity_type=article_data.get("entity_type", "male"),
            editor_name=editor_name,
            editor_role=editor_role,
            shorten=False
        )

        keyboard = [
            [
                InlineKeyboardButton("💬 فتح محادثة الواتساب ومراسلة العميل", url=wa_link)
            ],
            [
                InlineKeyboardButton("🌐 زيارة الخبر على المدونة", url=post_url)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        clean_title = clean_markdown_symbols(article_data.get("title"))

        sec_phones_text = ""
        if registered_secondaries:
            sec_list_str = " ، ".join([f"`{p}`" for p in registered_secondaries])
            sec_phones_text = f"\n⚡ **أرقام إضافية مسجلة لنفس المنظومة**: {sec_list_str}\n"

        success_text = (
            f"✅ **تم نشر الخبر بنجاح على جريدة تحت الضوء!** 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 **العنوان**: {clean_title}\n"
            f"🏷️ **القسم**: `{current_label}`\n"
            f"👤 **جهة العميل**: {clean_markdown_symbols(client_name)}\n"
            f"📱 **هاتف الواتساب المعتمد**: `{client_phone or 'غير محدد'}`\n"
            f"{sec_phones_text}"
            f"🔗 **رابط الخبر**: [{post_url}]({post_url})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"اضغط 💬 **[فتح محادثة الواتساب]** لمراسلة العميل بالخبر المنسق فوراً."
        )

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        await safe_send_message(context, chat_id, success_text, reply_markup=reply_markup)

        # Clear session
        USER_SESSIONS.pop(chat_id, None)

    except Exception as e:
        logger.error(f"Error generating and publishing article in telegram bot: {e}")
        try:
            reporter = db.get_reporter(str(chat_id))
            r_name = reporter.get("name") if reporter else "صحفي"
            db.log_bot_error(
                telegram_id=str(chat_id),
                reporter_name=r_name,
                action="صياغة ونشر خبر",
                error_message=str(e)
            )
        except Exception:
            pass

        error_txt = f"❌ حدث خطأ أثناء صياغة وتوليد الخبر: {clean_markdown_symbols(str(e))}"
        if status_msg:
            await safe_edit_message(status_msg, error_txt)
        else:
            await safe_send_message(context, chat_id, error_txt)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct handler: Text/Photo -> Instant AI generation & Blogger publication."""
    chat_id = update.effective_chat.id
    message = update.message
    
    if not message:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    raw_text = message.caption or message.text or ""
    photo = message.photo[-1] if message.photo else None
    
    # Intercept Arabic slash commands
    stripped_text = raw_text.strip()
    if stripped_text.startswith(("/كود", "/تفعيل")):
        return await activate_command(update, context)
    if stripped_text.startswith("/اسم"):
        return await setname_command(update, context)
    if stripped_text.startswith("/حسابي"):
        return await myname_command(update, context)
    
    session = USER_SESSIONS.get(chat_id, {})

    # Check reporter onboarding status (must register name + activation code)
    reporter = db.get_reporter(str(chat_id))
    if not reporter:
        if raw_text and session.get("state") == "AWAITING_REPORTER_NAME":
            reporter_name = raw_text.strip()[:100]
            if len(reporter_name) >= 2:
                db.save_reporter(str(chat_id), reporter_name, "صحفي لدى")
                session["state"] = "AWAITING_ACTIVATION_CODE"
                USER_SESSIONS[chat_id] = session
                confirm_msg = (
                    f"✅ **تم تسجيل اسمك بنجاح:** {clean_markdown_symbols(reporter_name)}! 👏\n\n"
                    f"🔑 **الخطوة الأخيرة للتفعيل:**\n"
                    f"يرجى إرسال **كود التفعيل** الخاص بك (Activation Code) المسلّم لك من إدارة الجريدة:\n\n"
                    f"✍️ **اكتب كود التفعيل الآن:**"
                )
                await safe_send_message(context, chat_id, confirm_msg)
                return
        
        session["state"] = "AWAITING_REPORTER_NAME"
        USER_SESSIONS[chat_id] = session
        prompt = (
            "👋 **أهلاً بك في بوت جريدة تحت الضوء الإخبارية!** 📰\n\n"
            "يرجى إدخال **اسمك الكريم** (مثل: *أحمد محمود*) ليتم اعتماده كـ (**صحفي لدى جريدة تحت الضوء**) في رسائل الواتساب الموجهة للعملاء.\n\n"
            "✍️ **اكتب اسمك الآن للبدء:**"
        )
        await safe_send_message(context, chat_id, prompt)
        return

    # Check activation code
    reporter_key = reporter.get("api_key")
    if not reporter_key:
        if raw_text and session.get("state") == "AWAITING_ACTIVATION_CODE":
            code = raw_text.strip()
            if len(code) >= 10:
                db.update_reporter_key(str(chat_id), code)
                session["state"] = None
                USER_SESSIONS[chat_id] = session
                confirm_msg = (
                    f"🎉 **تم تفعيل حسابك بنجاح!** ✅\n\n"
                    f"👤 **الصحفي**: {clean_markdown_symbols(reporter['name'])}\n"
                    f"💼 **الصفة**: صحفي لدى جريدة تحت الضوء الإخبارية ⚡\n"
                    f"🔑 **حالة الحساب**: مفعل ومستقل بالكامل\n\n"
                    f"🚀 الآن يمكنك إرسال تفاصيل أي خبر أو صورة لبدء النشر التلقائي فوراً!"
                )
                await safe_send_message(context, chat_id, confirm_msg)
                return
            else:
                await safe_send_message(context, chat_id, "⚠️ **كود التفعيل قصير أو غير صالح!** يرجى التأكد من كتابة كود التفعيل الصحيح كاملاً:")
                return

        session["state"] = "AWAITING_ACTIVATION_CODE"
        USER_SESSIONS[chat_id] = session
        prompt = (
            f"🔑 **تنبيه:** حسابك غير مفعل بعد يا {clean_markdown_symbols(reporter['name'])}.\n\n"
            f"يرجى إدخال **كود تفعيل الحساب** (Activation Code) المسلّم لك من إدارة الجريدة للبدء في استخدام البوت:\n\n"
            f"✍️ **اكتب كود التفعيل الآن:**"
        )
        await safe_send_message(context, chat_id, prompt)
        return

    # CASE 1: Photo received
    if photo:
        status_msg = await safe_send_message(context, chat_id, "📸 **جاري رفع صورة الخبر وتجهيز المقال للنشر...**")
        
        temp_img_path = Path(f"temp_tg_{chat_id}.jpg")
        image_url = getattr(Config, "DEFAULT_IMAGE_URL", "https://i.ibb.co/1q20tJ0/default-news.jpg")
        try:
            file = await context.bot.get_file(photo.file_id, read_timeout=45)
            await file.download_to_drive(temp_img_path)
            image_url = await asyncio.to_thread(image_service.upload_image, str(temp_img_path))
        except Exception as img_err:
            logger.error(f"Telegram Bot Image Download/Upload Error: {img_err}")
        finally:
            if temp_img_path.exists():
                try:
                    temp_img_path.unlink()
                except Exception:
                    pass

        session["image_url"] = image_url
        if raw_text:
            session["raw_text"] = raw_text
            extracted_phone, extracted_name = clean_phone_and_name(raw_text)
            all_phones = extract_all_egyptian_phones(raw_text)
            session["extracted_phone"] = extracted_phone
            session["extracted_name"] = extracted_name
            session["all_phones"] = all_phones

            # Layer 1 Protection: Instant duplicate check on photo caption
            if not session.get("force_republish"):
                dup_alert = check_duplicate_alert(extracted_phone, extracted_name, all_phones=all_phones)
                if dup_alert:
                    USER_SESSIONS[chat_id] = session
                    reply_markup = get_duplicate_inline_keyboard()
                    if status_msg:
                        await safe_edit_message(status_msg, dup_alert, reply_markup=reply_markup)
                    else:
                        await safe_send_message(context, chat_id, dup_alert, reply_markup=reply_markup)
                    return
        
        USER_SESSIONS[chat_id] = session

        if session.get("raw_text"):
            await generate_and_publish_article(chat_id, context, status_msg)
        else:
            await safe_edit_message(status_msg, "✍️ **تم استلام الصورة! الآن برجاء إرسال تفاصيل الخبر أو النص.**")
        return

    # CASE 2: Text received first
    if raw_text:
        extracted_phone, extracted_name = clean_phone_and_name(raw_text)
        all_phones = extract_all_egyptian_phones(raw_text)

        session["raw_text"] = raw_text
        session["extracted_phone"] = extracted_phone
        session["extracted_name"] = extracted_name
        session["all_phones"] = all_phones

        # Layer 1 Protection: Instant duplicate check on raw text
        if not session.get("force_republish"):
            dup_alert = check_duplicate_alert(extracted_phone, extracted_name, all_phones=all_phones)
            if dup_alert:
                session["state"] = "DUPLICATE_CONFIRMATION"
                USER_SESSIONS[chat_id] = session
                reply_markup = get_duplicate_inline_keyboard()
                await safe_send_message(context, chat_id, dup_alert, reply_markup=reply_markup)
                return

        session["state"] = "AWAITING_PHOTO"
        USER_SESSIONS[chat_id] = session

        keyboard = [
            [
                InlineKeyboardButton("⚡ النشر المباشر بصورة افتراضية", callback_data="skip_photo")
            ],
            [
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel_post")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sec_phones = [p for p in all_phones if p != extracted_phone]
        sec_note = f"\n⚡ **أرقام إضافية سيتم قيدها**: {', '.join(sec_phones)}" if sec_phones else ""

        prompt_text = (
            f"✍️ **تم استلام تفاصيل الخبر بنجاح!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 **جهة العميل**: {clean_markdown_symbols(extracted_name) or 'غير محدد'}\n"
            f"📱 **هاتف الواتساب**: `{extracted_phone or 'غير محدد'}`{sec_note}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📸 **برجاء إرسال صورة الخبر للبدء في النشر المباشر** 🏞️\n\n"
            f"*(أو اضغط على ⚡ [النشر المباشر بصورة افتراضية] للنشر التلقائي فوراً).* "
        )
        await safe_send_message(context, chat_id, prompt_text, reply_markup=reply_markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle interactive inline keyboard button clicks."""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    session = USER_SESSIONS.get(chat_id)
    if not session and data != "cancel_post":
        await safe_edit_message(query, "⚠️ **انتهت الجلسة الحالية. برجاء إرسال تفاصيل الخبر مرة أخرى.**")
        return

    if data == "skip_photo":
        session["image_url"] = getattr(Config, "DEFAULT_IMAGE_URL", "https://i.ibb.co/1q20tJ0/default-news.jpg")
        await generate_and_publish_article(chat_id, context, query.message)

    elif data == "confirm_republish":
        session["force_republish"] = True

        # If user already provided photo (either uploaded before or photo-caption flow)
        if session.get("image_url") and session.get("raw_text"):
            status_msg = await safe_edit_message(
                query,
                "⚡ **تم تأكيد رغبتك في إعادة النشر! جاري صياغة الخبر بالذكاء الاصطناعي والنشر المباشر على المدونة...**"
            )
            await generate_and_publish_article(chat_id, context, status_msg)
        else:
            session["state"] = "AWAITING_PHOTO"
            USER_SESSIONS[chat_id] = session
            keyboard = [
                [
                    InlineKeyboardButton("⚡ النشر المباشر بصورة افتراضية", callback_data="skip_photo")
                ],
                [
                    InlineKeyboardButton("❌ إلغاء", callback_data="cancel_post")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            prompt_text = (
                f"✅ **تم اعتماد رغبتك في النشر مرة أخرى لهذا العميل بنجاح!**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 **العميل**: {clean_markdown_symbols(session.get('extracted_name', '')) or 'غير محدد'}\n"
                f"📱 **الهاتف**: `{session.get('extracted_phone', '') or 'غير محدد'}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📸 **برجاء إرسال صورة الخبر للبدء في النشر المباشر** 🏞️\n\n"
                f"*(أو اضغط على ⚡ [النشر المباشر بصورة افتراضية] للنشر التلقائي فوراً).* "
            )
            await safe_edit_message(query, prompt_text, reply_markup=reply_markup)

    elif data == "cancel_post":
        USER_SESSIONS.pop(chat_id, None)
        await safe_edit_message(query, "❌ **تم إلغاء عملية النشر.**")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates and record them in DB."""
    logger.error(f"Exception while handling Telegram update: {context.error}", exc_info=context.error)
    try:
        user_id = ""
        user_name = "مستخدم تليجرام"
        if isinstance(update, Update):
            if update.effective_user:
                user_id = str(update.effective_user.id)
                user_name = update.effective_user.full_name or update.effective_user.first_name or "مستخدم"
            elif update.effective_chat:
                user_id = str(update.effective_chat.id)

        err_str = str(context.error)
        # Suppress noise in DB for transient network timeouts or polling disconnects
        if any(ign in err_str.lower() for ign in ["timed out", "bad gateway", "network is unreachable", "conflict: terminated"]):
            logger.warning(f"Transient network glitch in Telegram polling: {err_str}")
            return

        db.log_bot_error(user_id, user_name, "معالجة التحديث", err_str)
    except Exception:
        pass


def create_bot_app():
    """Builds and configures Telegram Bot Application instance."""
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], start_command))
    app.add_handler(CommandHandler(["setname", "name"], setname_command))
    app.add_handler(CommandHandler(["activate", "code"], activate_command))
    app.add_handler(CommandHandler(["myname"], myname_command))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)
    return app



from telegram_bot.bot_controller import bot_controller, TelegramBotController


def run_bot():
    """Start Telegram Bot application polling (CLI / Standalone)."""
    logger.info("⚡ جاري تفعيل بوت تليجرام لجريدة تحت الضوء...")
    app = create_bot_app()
    logger.info("✅ البوت يعمل بنجاح وجاهز لاستقبال الطلبات!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
