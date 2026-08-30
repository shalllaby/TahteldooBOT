import sqlite3
import json
from datetime import datetime
from pathlib import Path
from core.config import Config
from core.logger import logger

class DatabaseManager:
    def __init__(self, db_path: Path = None):
        self.db_path = db_path or Config.DB_PATH
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Create necessary tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Clients Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Articles Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER,
                    title TEXT NOT NULL,
                    slug TEXT,
                    labels TEXT,
                    raw_ai_json TEXT,
                    final_html TEXT,
                    local_image_path TEXT,
                    remote_image_url TEXT,
                    blog_id TEXT,
                    post_id TEXT,
                    post_url TEXT,
                    is_draft INTEGER DEFAULT 0,
                    blogger_status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
                )
            """)

            # WhatsApp Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER,
                    recipient_phone TEXT,
                    recipient_name TEXT,
                    message_body TEXT,
                    status TEXT DEFAULT 'PENDING',
                    error_message TEXT,
                    sent_at TIMESTAMP,
                    delay_seconds INTEGER DEFAULT 5,
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
                )
            """)

            # System Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    module TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Application Settings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # Reporters Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reporters (
                    telegram_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT DEFAULT 'صحفي لدى',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info("Database tables initialized successfully.")

    # --- Client Operations ---
    def save_client(self, name: str, phone: str, raw_data: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO clients (name, phone, raw_data) VALUES (?, ?, ?)",
                (name, phone, raw_data)
            )
            conn.commit()
            return cursor.lastrowid

    # --- Article Operations ---
    def save_article(self, article_data: dict = None, **kwargs) -> int:
        data = article_data.copy() if isinstance(article_data, dict) else {}
        data.update(kwargs)

        client_name = data.get("client_name") or data.get("name")
        client_phone = data.get("client_phone") or data.get("phone")
        client_id = data.get("client_id")

        if not client_id and (client_name or client_phone):
            try:
                client_id = self.save_client(client_name or "عميل تليجرام", client_phone or "", "")
            except Exception as ce:
                logger.warning(f"save_client failed in save_article: {ce}")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO articles (
                    client_id, title, slug, labels, raw_ai_json, final_html,
                    local_image_path, remote_image_url, blog_id, post_id,
                    post_url, is_draft, blogger_status, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                data.get("title", ""),
                data.get("slug", ""),
                data.get("labels", ""),
                data.get("raw_ai_json", ""),
                data.get("final_html", "") or data.get("content", ""),
                data.get("local_image_path", ""),
                data.get("remote_image_url", ""),
                data.get("blog_id", ""),
                data.get("blogger_post_id") or data.get("post_id", ""),
                data.get("blogger_url") or data.get("post_url", ""),
                1 if data.get("is_draft") else 0,
                data.get("blogger_status", "PUBLISHED"),
                data.get("published_at") or datetime.now().isoformat()
            ))
            conn.commit()
            return cursor.lastrowid

    def update_article(self, article_id: int, update_fields: dict):
        keys = list(update_fields.keys())
        values = list(update_fields.values())
        set_clause = ", ".join([f"{k} = ?" for k in keys])
        values.append(article_id)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE articles SET {set_clause} WHERE id = ?", values)
            conn.commit()

    def get_article(self, article_id: int) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_articles(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT a.*, c.name as client_name, c.phone as client_phone 
                FROM articles a 
                LEFT JOIN clients c ON a.client_id = c.id 
                ORDER BY a.id DESC
            """)
            return [dict(r) for r in cursor.fetchall()]

    # --- WhatsApp Log Operations ---
    def log_whatsapp(self, article_id: int, recipient_phone: str, recipient_name: str, message_body: str, status: str, error_message: str = None, delay_seconds: int = 5) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO whatsapp_logs (
                    article_id, recipient_phone, recipient_name, message_body, status, error_message, sent_at, delay_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article_id, recipient_phone, recipient_name, message_body, status, error_message,
                datetime.now().isoformat() if status == "SENT" else None,
                delay_seconds
            ))
            conn.commit()
            return cursor.lastrowid

    def get_whatsapp_logs(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM whatsapp_logs ORDER BY id DESC")
            return [dict(r) for r in cursor.fetchall()]

    # --- System Logs ---
    def log_system(self, level: str, module: str, message: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO system_logs (level, module, message) VALUES (?, ?, ?)",
                (level, module, message)
            )
            conn.commit()

    def get_system_logs(self, limit: int = 200) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # --- Reporter Operations ---
    def save_reporter(self, telegram_id: str, name: str, role: str = "صحفي لدى") -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reporters (telegram_id, name, role)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name, role=excluded.role
            """, (str(telegram_id), name, role))
            conn.commit()
            return True

    def get_reporter(self, telegram_id: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reporters WHERE telegram_id = ?", (str(telegram_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

db = DatabaseManager()
