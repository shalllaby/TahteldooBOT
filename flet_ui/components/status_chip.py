import flet as ft
from flet_ui.theme import ThemeColors

def create_status_chip(text: str, is_ok: bool = True, icon: str = None):
    bg_color = "#064E3B" if is_ok else "#7F1D1D"
    text_color = ThemeColors.SUCCESS if is_ok else ThemeColors.ERROR
    border_color = ThemeColors.SUCCESS if is_ok else ThemeColors.ERROR
    
    icon_name = icon or (ft.Icons.CHECK_CIRCLE if is_ok else ft.Icons.ERROR_OUTLINE)

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(
                    icon_name,
                    color=text_color,
                    size=14
                ),
                ft.Text(
                    text,
                    color=text_color,
                    size=12,
                    weight=ft.FontWeight.W_500
                )
            ],
            spacing=5,
            alignment=ft.MainAxisAlignment.CENTER,
            tight=True
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        border_radius=16,
        bgcolor=bg_color,
        border=ft.border.all(1, border_color)
    )
