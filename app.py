import sys
import os
import flet as ft
from main_flet import main

if __name__ == "__main__":
    # Launch Flet Desktop Application with universal compatibility
    if hasattr(ft, "run"):
        try:
            ft.run(main, assets_dir="assets")
        except Exception:
            ft.app(target=main, assets_dir="assets")
    else:
        ft.app(target=main, assets_dir="assets")
