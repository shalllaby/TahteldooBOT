import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure project root is in Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Lightweight HTTP handler so Render recognizes it as a free Web Service."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("✅ جريدة تحت الضوء - بوت تليجرام يعمل بنجاح في السحاب!".encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress standard HTTP request logging
        pass


def run_health_server():
    """Starts HTTP health check server on $PORT for Render compatibility."""
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        print(f"Health server error: {e}")


if __name__ == "__main__":
    # 1. Launch HTTP health check thread for Render Free Web Service
    threading.Thread(target=run_health_server, daemon=True).start()

    # 2. Launch Telegram Bot polling
    from services.telegram_bot import run_bot
    run_bot()
