import flet as ft
from flet_ui.theme import ThemeColors

def create_page_header(title: str, subtitle: str = "", icon: str = None, actions: list = None):
    header_title_row = ft.Row(
        controls=[
            ft.Container(
                content=ft.Icon(icon or ft.Icons.ARTICLE, color=ThemeColors.GOLD_PRIMARY, size=24),
                padding=8,
                bgcolor="#332A15",
                border_radius=8
            ) if icon else ft.Container(),
            ft.Column(
                controls=[
                    ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=ThemeColors.TEXT_PRIMARY),
                    ft.Text(subtitle, size=12, color=ThemeColors.TEXT_SECONDARY) if subtitle else ft.Container(),
                ],
                spacing=2
            )
        ],
        spacing=12,
        alignment=ft.MainAxisAlignment.START,
        tight=True
    )
    
    return ft.Container(
        content=ft.Row(
            controls=[
                header_title_row,
                ft.Row(controls=actions or [], spacing=10)
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        ),
        padding=ft.padding.only(bottom=15),
        border=ft.border.only(bottom=ft.BorderSide(1, ThemeColors.BORDER_COLOR))
    )
