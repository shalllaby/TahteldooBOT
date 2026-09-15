"""
Compatibility bridge for services.telegram_bot.
All bot code has been modularized into the telegram_bot/ package.
"""
import sys
from pathlib import Path

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from telegram_bot.bot import *
from telegram_bot.bot_controller import bot_controller, TelegramBotController
from telegram_bot.bot import run_bot

if __name__ == "__main__":
    run_bot()
