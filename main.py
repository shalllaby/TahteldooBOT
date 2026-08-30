import os
import sys

# Ensure project root is in Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.telegram_bot import run_bot

if __name__ == "__main__":
    run_bot()
