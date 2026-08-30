import os
import threading
import flet as ft
from flet_ui.theme import ThemeColors
from core.config import Config


def play_publish_sound():
    """تشغيل صوت الإشعار عند نشر الخبر بنجاح — يعمل في الخلفية."""
    def _play():
        sound_path = str(Config.BASE_DIR / "assets" / "notification.mp3")
        try:
            # محاولة أولى: pygame
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(sound_path)
            pygame.mixer.music.play()
            import time
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            return
        except Exception:
            pass
        try:
            # محاولة ثانية: playsound
            from playsound import playsound
            playsound(sound_path, block=False)
            return
        except Exception:
            pass
        try:
            # احتياطي: winsound على Windows
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


def show_snack(page: ft.Page, message: str, is_error: bool = False, is_success: bool = False):
    if not page:
        return
    color = ThemeColors.SUCCESS if is_success else (ThemeColors.ERROR if is_error else ThemeColors.INDIGO_ACCENT)
    
    snack = ft.SnackBar(
        content=ft.Text(message, color="#FFFFFF", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT),
        bgcolor=color,
        duration=3500,
        show_close_icon=True,
    )
    try:
        if hasattr(page, "open"):
            page.open(snack)
        else:
            page.overlay.append(snack)
            snack.open = True
            page.update()
    except Exception:
        pass

def show_publish_success_dialog(page: ft.Page, post_url: str, client_name: str = "", client_phone: str = "", wa_link: str = ""):
    import webbrowser

    # 🔔 تشغيل صوت الإشعار فور النجاح
    play_publish_sound()

    def open_link(e, url):
        if url:
            webbrowser.open(url)

    def copy_link(e, url):
        if url:
            page.set_clipboard(url)
            show_snack(page, "📋 تم نسخ رابط الخبر بنجاح!", is_success=True)

    def close_dlg(e):
        if hasattr(page, "close"):
            page.close(dlg)
        else:
            dlg.open = False
            page.update()

    actions = []
    if wa_link:
        actions.append(
            ft.ElevatedButton(
                "🚀 فتح الخبر والواتساب معاً",
                icon=ft.Icons.LAUNCH,
                style=ft.ButtonStyle(bgcolor=ThemeColors.GOLD_PRIMARY, color="#000000"),
                on_click=lambda e: [webbrowser.open(post_url), webbrowser.open(wa_link), close_dlg(e)]
            )
        )
    if post_url:
        actions.append(
            ft.OutlinedButton("🌐 فتح رابط الخبر فقط", on_click=lambda e: [webbrowser.open(post_url), close_dlg(e)])
        )
    if wa_link:
        actions.append(
            ft.OutlinedButton("💬 فتح الواتساب فقط", on_click=lambda e: [webbrowser.open(wa_link), close_dlg(e)])
        )
    actions.append(
        ft.TextButton("📋 نسخ الرابط", on_click=lambda e: copy_link(e, post_url))
    )
    actions.append(
        ft.TextButton("إغلاق", on_click=close_dlg)
    )

    dlg = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE, color=ThemeColors.SUCCESS, size=28),
            ft.Text("🎉 تم نشر الخبر بنجاح!", weight=ft.FontWeight.BOLD, size=18)
        ], spacing=10),
        content=ft.Column(
            controls=[
                ft.Text("تم نشر الخبر الصحفي بنجاح على مدونة تحت الضوء الإخبارية.", size=14, color=ThemeColors.TEXT_PRIMARY),
                ft.Container(height=10),
                ft.TextField(
                    label="رابط الخبر المنشور",
                    value=post_url,
                    read_only=True,
                    border_color=ThemeColors.BORDER_COLOR,
                    fill_color="#0F172A",
                    filled=True
                )
            ],
            tight=True,
            spacing=8
        ),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
    )
    try:
        if hasattr(page, "open"):
            page.open(dlg)
        else:
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
    except Exception:
        pass
