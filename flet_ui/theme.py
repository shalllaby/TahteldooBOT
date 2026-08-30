import flet as ft

class ThemeColors:
    # Obsidian & Royal Gold Palette
    BG_DARK = "#0B0F19"
    SURFACE_DARK = "#1E293B"
    SURFACE_HOVER = "#334155"
    BORDER_COLOR = "#334155"
    
    # Accents
    GOLD_PRIMARY = "#F59E0B"
    GOLD_HOVER = "#D97706"
    GOLD_LIGHT = "#FEF3C7"
    INDIGO_ACCENT = "#6366F1"
    BLUE_ACCENT = "#3B82F6"
    
    # Text
    TEXT_PRIMARY = "#F8FAFC"
    TEXT_SECONDARY = "#94A3B8"
    TEXT_MUTED = "#64748B"
    
    # Badges
    SUCCESS = "#10B981"
    ERROR = "#EF4444"
    INFO = "#0EA5E9"
    WARNING = "#F59E0B"

def get_app_theme(is_dark=True):
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ThemeColors.GOLD_PRIMARY,
            on_primary="#000000",
            secondary=ThemeColors.INDIGO_ACCENT,
            surface=ThemeColors.SURFACE_DARK if is_dark else "#FFFFFF",
            on_surface=ThemeColors.TEXT_PRIMARY if is_dark else "#0F172A",
        ),
        font_family="Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    )

def create_glass_card(content, padding=20, border_radius=12, expand=False):
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=border_radius,
        bgcolor=ThemeColors.SURFACE_DARK,
        border=ft.border.all(1, ThemeColors.BORDER_COLOR),
        shadow=ft.BoxShadow(
            spread_radius=1,
            blur_radius=10,
            color="#00000040",
            offset=ft.Offset(0, 4)
        ),
        expand=expand
    )

def create_gold_button(text, icon=None, on_click=None, height=45, expand=False):
    return ft.ElevatedButton(
        content=text if isinstance(text, ft.Control) else ft.Text(text),
        icon=icon,
        on_click=on_click,
        height=height,
        expand=expand,
        style=ft.ButtonStyle(
            color="#000000",
            bgcolor={
                ft.ControlState.DEFAULT: ThemeColors.GOLD_PRIMARY,
                ft.ControlState.HOVERED: ThemeColors.GOLD_HOVER,
            },
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
            text_style=ft.TextStyle(weight=ft.FontWeight.BOLD, size=14)
        )
    )

def create_secondary_button(text, icon=None, on_click=None, height=45, expand=False):
    return ft.OutlinedButton(
        content=text if isinstance(text, ft.Control) else ft.Text(text),
        icon=icon,
        on_click=on_click,
        height=height,
        expand=expand,
        style=ft.ButtonStyle(
            color=ThemeColors.TEXT_PRIMARY,
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(1, ThemeColors.BORDER_COLOR),
                ft.ControlState.HOVERED: ft.BorderSide(1, ThemeColors.GOLD_PRIMARY),
            },
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
    )

def create_input_field(label, hint_text="", multiline=False, rows=1, password=False, value="", on_change=None, expand=False, prefix_icon=None):
    return ft.TextField(
        label=label,
        hint_text=hint_text,
        multiline=multiline,
        min_lines=rows if multiline else 1,
        max_lines=rows + 4 if multiline else 1,
        password=password,
        can_reveal_password=password,
        value=value,
        on_change=on_change,
        expand=expand,
        prefix_icon=prefix_icon,
        text_align=ft.TextAlign.RIGHT,
        border_color=ThemeColors.BORDER_COLOR,
        focused_border_color=ThemeColors.GOLD_PRIMARY,
        cursor_color=ThemeColors.GOLD_PRIMARY,
        label_style=ft.TextStyle(color=ThemeColors.TEXT_SECONDARY, size=13),
        text_style=ft.TextStyle(color=ThemeColors.TEXT_PRIMARY, size=14),
        fill_color="#0F172A",
        filled=True,
        border_radius=8
    )
