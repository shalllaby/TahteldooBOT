import os
import sys
import logging
import asyncio
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
from services.whatsapp_service import whatsapp_service
from database.db import db
from core.config import Config
from core.logger import logger

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8834102717:AAGCflNVXtYccq1oG0JqYQGW2bv4WBkwhAM")

# In-memory dictionary to store active user article sessions
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}


def clean_phone_and_name(text: str):
    """Extract phone number and client name from raw input text if present."""
    if not text:
        return "", ""
    phone_match = re.search(r"(?:01[0125]\d{8}|\+201[0125]\d{8})", text)
    phone = phone_match.group(0) if phone_match else ""
    
    name_match = re.search(r"(?:العميل|الجهة|الاسم|د\.|أستاذ|مهندس|دكتورة|مؤسسة|شركة|أكاديمية|عيادة)[\s:]*([^\n,]+)", text)
    name = name_match.group(1).strip() if name_match else ""
    
    return phone, name


def clean_markdown_symbols(text: Any) -> str:
    """Strips/escapes problematic raw Markdown symbols to prevent Telegram entity parsing errors."""
    if not text:
        return ""
    s = str(text)
    return s.replace("_", "\\_").replace("*", " ").replace("`", "'")


async def safe_edit_message(target, text: str, reply_markup=None, disable_web_page_preview=True):
    """
    Safely edits a telegram message with Markdown.
    If Telegram raises entity parsing errors ('Can't parse entities'), automatically falls back to plain text.
    """
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
        clean_text = text.replace("**", "").replace("`", "")
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
    """Safely sends a telegram message with plain text fallback if Markdown parsing fails."""
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview
        )
    except Exception as err:
        logger.warning(f"Telegram send_message Markdown failed ({err}). Retrying with plain text...")
        clean_text = text.replace("**", "").replace("`", "")
        return await context.bot.send_message(
            chat_id=chat_id,
            text=clean_text,
            parse_mode=None,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview
        )


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

    welcome_text = (
        f"✨ **أهلاً بك يا {clean_markdown_symbols(reporter['name'])} في بوت جريدة تحت الضوء!** 📰\n\n"
        f"💼 **الصفة التحريرية**: {reporter.get('role', 'صحفي لدى')} جريدة تحت الضوء الإخبارية\n\n"
        "📌 **طريقة الاستخدام:**\n"
        "1️⃣ أرسل نص الخبر أو تفاصيل العميل أولاً.\n"
        "2️⃣ سيطلب منك البوت إرفاق صورة الخبر.\n"
        "3️⃣ سيتم صياغة الخبر والنشر على المدونة وتوليد رابط الواتساب باسمك الفوري!\n\n"
        "💡 لتغيير اسمك في أي وقت أرسل: `/setname الاسم الجديد`\n\n"
        "✍️ **أرسل تفاصيل الخبر الآن للبدء!**"
    )
    await safe_send_message(context, chat_id, welcome_text)


async def setname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows reporter to update their name for WhatsApp messages."""
    chat_id = update.effective_chat.id
    text = update.message.text if update.message else ""
    parts = text.split(maxsplit=1)
    if len(parts) > 1:
        new_name = parts[1].strip()
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


async def myname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays current registered reporter profile."""
    chat_id = update.effective_chat.id
    reporter = db.get_reporter(str(chat_id))
    if reporter:
        msg = (
            f"👤 **بياناتك المسجلة حالياً:**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• **الاسم**: {clean_markdown_symbols(reporter['name'])}\n"
            f"• **الصفة**: {reporter.get('role', 'صحفي لدى')} جريدة تحت الضوء الإخبارية\n\n"
            f"💡 لتغيير اسمك أرسل: `/setname الاسم الجديد`"
        )
    else:
        msg = "⚠️ لم تقم بتسجيل اسمك بعد. أرسل اسمك الآن لتسجيله!"
    await safe_send_message(context, chat_id, msg)


async def generate_and_publish_article(chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg=None):
    """Generates AI article combining saved text/image and IMMEDIATELY publishes it to Blogger."""
    session = USER_SESSIONS.get(chat_id)
    if not session:
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
        # 1. Generate Article using AIService asynchronously to allow high multi-user concurrency
        article_data = await asyncio.to_thread(
            ai_service.generate_article,
            raw_notes_or_name=raw_text,
            phone_or_raw=extracted_phone,
            raw_notes=raw_text
        )
        
        article_data["image_url"] = image_url
        client_name = article_data.get("client_name") or extracted_name or "العميل الكريم"
        client_phone = article_data.get("client_phone") or extracted_phone or ""
        labels = article_data.get("labels", ["خدمات"])
        current_label = labels[0] if labels else "خدمات"
        current_label = AIService.normalize_label(current_label, raw_text)
        article_data["labels"] = [current_label]
        article_data["raw_text"] = raw_text

        # 2. Instant Publish to Blogger via BloggerService
        if hasattr(blogger_service, "publish_article"):
            published_post = await asyncio.to_thread(blogger_service.publish_article, article_data)
        else:
            from services.article_formatter import ArticleFormatter
            title = article_data.get("title", "خبر صحفي جديد")
            content_html = ArticleFormatter.json_to_html(article_data, image_url=image_url)
            res = await asyncio.to_thread(
                blogger_service.publish_post,
                title=title,
                content_html=content_html,
                labels=[current_label],
                is_draft=False
            )
            published_post = {
                "id": res.get("post_id"),
                "url": res.get("post_url")
            }
            
        post_url = published_post.get("url") or published_post.get("post_url", "")
        post_id = published_post.get("id") or published_post.get("post_id", "")
        
        # Save record to DB
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
                entity_type=article_data.get("entity_type", "male")
            )
        except Exception as db_err:
            logger.error(f"DB Save Error in Telegram Bot: {db_err}")

        # Fetch Reporter info for WhatsApp message customization
        reporter = db.get_reporter(str(chat_id))
        editor_name = reporter.get("name") if reporter else "محمد شلبي"
        editor_role = reporter.get("role") if reporter else "صحفي لدى"

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

        success_text = (
            f"✅ **تم نشر الخبر بنجاح على جريدة تحت الضوء!** 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 **العنوان**: {clean_title}\n"
            f"🏷️ **القسم**: `{current_label}`\n"
            f"👤 **جهة العميل**: {clean_markdown_symbols(client_name)}\n"
            f"📱 **الهاتف**: `{client_phone or 'غير محدد'}`\n"
            f"🔗 **رابط الخبر**: {post_url}\n"
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
    
    session = USER_SESSIONS.get(chat_id, {})

    # Check reporter onboarding status (must register name once)
    reporter = db.get_reporter(str(chat_id))
    if not reporter:
        if raw_text and session.get("state") == "AWAITING_REPORTER_NAME":
            reporter_name = raw_text.strip()
            if len(reporter_name) >= 2:
                db.save_reporter(str(chat_id), reporter_name, "صحفي لدى")
                session["state"] = None
                USER_SESSIONS[chat_id] = session
                confirm_msg = (
                    f"✅ **تم تسجيل اسمك بنجاح!**\n\n"
                    f"👤 **الاسم**: {clean_markdown_symbols(reporter_name)}\n"
                    f"💼 **الصفة**: صحفي لدى جريدة تحت الضوء الإخبارية ⚡\n\n"
                    f"الآن يمكنك إرسال تفاصيل أي خبر أو صورة لبدء النشر التلقائي! 🚀"
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

    # CASE 1: Photo received
    if photo:
        status_msg = await safe_send_message(context, chat_id, "📸 **جاري رفع صورة الخبر وتجهيز المقال للنشر...**")
        
        file = await context.bot.get_file(photo.file_id, read_timeout=30)
        temp_img_path = Path(f"temp_tg_{chat_id}.jpg")
        await file.download_to_drive(temp_img_path)
        
        try:
            image_url = await asyncio.to_thread(image_service.upload_image, str(temp_img_path))
        except Exception as img_err:
            logger.error(f"Telegram Bot Image Upload Error: {img_err}")
            image_url = getattr(Config, "DEFAULT_IMAGE_URL", "https://i.ibb.co/1q20tJ0/default-news.jpg")
        finally:
            if temp_img_path.exists():
                temp_img_path.unlink()

        session["image_url"] = image_url
        if raw_text:
            session["raw_text"] = raw_text
            extracted_phone, extracted_name = clean_phone_and_name(raw_text)
            session["extracted_phone"] = extracted_phone
            session["extracted_name"] = extracted_name
        
        USER_SESSIONS[chat_id] = session

        if session.get("raw_text"):
            await generate_and_publish_article(chat_id, context, status_msg)
        else:
            await safe_edit_message(status_msg, "✍️ **تم استلام الصورة! الآن برجاء إرسال تفاصيل الخبر أو النص.**")
        return

    # CASE 2: Text received first
    if raw_text:
        extracted_phone, extracted_name = clean_phone_and_name(raw_text)
        session["raw_text"] = raw_text
        session["extracted_phone"] = extracted_phone
        session["extracted_name"] = extracted_name
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
            f"✍️ **تم استلام تفاصيل الخبر بنجاح!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 **جهة العميل**: {clean_markdown_symbols(extracted_name) or 'غير محدد'}\n"
            f"📱 **الهاتف**: `{extracted_phone or 'غير محدد'}`\n"
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

    elif data == "cancel_post":
        USER_SESSIONS.pop(chat_id, None)
        await safe_edit_message(query, "❌ **تم إلغاء عملية النشر.**")


def run_bot():
    """Start Telegram Bot application polling."""
    logger.info("⚡ جاري تفعيل بوت تليجرام لجريدة تحت الضوء...")
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
    app.add_handler(CommandHandler(["setname", "name", "اسم", "تغيير_الاسم"], setname_command))
    app.add_handler(CommandHandler(["myname", "اسمي"], myname_command))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("✅ البوت يعمل بنجاح وجاهز لاستقبال الطلبات!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
