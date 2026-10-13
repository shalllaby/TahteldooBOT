import sqlite3
import json
import re
import time
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from core.config import Config
from core.logger import logger

class DatabaseManager:
    def __init__(self, db_path: Path = None):
        self.db_path = db_path or Config.DB_PATH
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
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
                    user_id TEXT,
                    user_name TEXT,
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
                    api_key TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Facebook Posts Management & Commercial Tracking Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facebook_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fb_post_id TEXT UNIQUE NOT NULL,
                    article_id INTEGER,
                    client_id INTEGER,
                    client_name TEXT,
                    post_message TEXT,
                    post_url TEXT,
                    image_url TEXT,
                    payment_status TEXT DEFAULT 'UNPAID',
                    amount REAL DEFAULT 0.0,
                    currency TEXT DEFAULT 'EGP',
                    payment_notes TEXT,
                    likes_count INTEGER DEFAULT 0,
                    comments_count INTEGER DEFAULT 0,
                    shares_count INTEGER DEFAULT 0,
                    reach_estimate INTEGER DEFAULT 0,
                    published_by_name TEXT,
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE SET NULL,
                    FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE SET NULL
                )
            """)

            # Smart Article Edit Backups (For Undo / Recovery)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS article_edit_backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    site_type TEXT NOT NULL,
                    article_url TEXT,
                    original_title TEXT NOT NULL,
                    original_content TEXT NOT NULL,
                    modified_title TEXT,
                    modified_content TEXT,
                    client_notes TEXT,
                    user_id TEXT,
                    user_name TEXT,
                    restored INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: Ensure api_key column exists in reporters table
            try:
                cursor.execute("SELECT api_key FROM reporters LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE reporters ADD COLUMN api_key TEXT")
                    logger.info("Migrated reporters table: added api_key column.")
                except Exception as mig_err:
                    logger.warning(f"reporters table migration warning: {mig_err}")

            # Migration: Ensure reporter_telegram_id column exists in articles table
            try:
                cursor.execute("SELECT reporter_telegram_id FROM articles LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE articles ADD COLUMN reporter_telegram_id TEXT")
                    logger.info("Migrated articles table: added reporter_telegram_id column.")
                except Exception as mig_err:
                    logger.warning(f"articles table migration warning: {mig_err}")

            # Migration: Ensure user_id & user_name columns exist in system_logs table
            try:
                cursor.execute("SELECT user_id FROM system_logs LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE system_logs ADD COLUMN user_id TEXT")
                    logger.info("Migrated system_logs table: added user_id column.")
                except Exception as mig_err:
                    logger.warning(f"system_logs user_id migration warning: {mig_err}")

            try:
                cursor.execute("SELECT user_name FROM system_logs LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE system_logs ADD COLUMN user_name TEXT")
                    logger.info("Migrated system_logs table: added user_name column.")
                except Exception as mig_err:
                    logger.warning(f"system_logs user_name migration warning: {mig_err}")

            # Users Table (Web Authentication & RBAC)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'journalist',
                    email TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)

            # Performance & Fast Lookup Indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_client_id ON articles(client_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_user ON system_logs(user_id, module)")
            # Migration: Ensure author_email & author_name in articles
            try:
                cursor.execute("SELECT author_email FROM articles LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE articles ADD COLUMN author_email TEXT")
                    cursor.execute("ALTER TABLE articles ADD COLUMN author_name TEXT")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_author ON articles(author_email)")
                    logger.info("Migrated articles table: added author_email and author_name columns.")
                except Exception as mig_err:
                    logger.warning(f"articles author migration warning: {mig_err}")

            # Migration: Ensure google_avatar & blogger_token_path in users
            try:
                cursor.execute("SELECT google_avatar FROM users LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN google_avatar TEXT")
                    cursor.execute("ALTER TABLE users ADD COLUMN blogger_token_path TEXT")
                    logger.info("Migrated users table: added google_avatar and blogger_token_path columns.")
                except Exception as mig_err:
                    logger.warning(f"users google migration warning: {mig_err}")

            # Migration: Ensure phone column exists in users
            try:
                cursor.execute("SELECT phone FROM users LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
                    logger.info("Migrated users table: added phone column.")
                except Exception:
                    pass

            # Migration: Ensure zai_api_key column exists in users for personal journalist keys
            try:
                cursor.execute("SELECT zai_api_key FROM users LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN zai_api_key TEXT DEFAULT ''")
                    logger.info("Migrated users table: added zai_api_key column.")
                except Exception as mig_err:
                    logger.warning(f"users zai_api_key migration warning: {mig_err}")

            # Migration: Ensure gender column exists in users
            try:
                cursor.execute("SELECT gender FROM users LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT ''")
                    logger.info("Migrated users table: added gender column.")
                except Exception as mig_err:
                    logger.warning(f"users gender migration warning: {mig_err}")

            # Activation & Invitation Codes Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activation_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    journalist_name TEXT NOT NULL,
                    journalist_phone TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'journalist',
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_by TEXT,
                    used_by_email TEXT,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activation_code ON activation_codes(code)")

            # Accounting Transactions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounting_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    author_email TEXT,
                    user_role TEXT NOT NULL,
                    article_id INTEGER,
                    article_title TEXT NOT NULL,
                    article_url TEXT,
                    client_name TEXT,
                    client_phone TEXT NOT NULL,
                    amount_paid REAL NOT NULL,
                    newspaper_cut REAL NOT NULL,
                    journalist_net REAL NOT NULL,
                    payment_method TEXT DEFAULT 'vodafone_cash',
                    receipt_image_path TEXT,
                    settlement_status TEXT DEFAULT 'PENDING',
                    settled_at TIMESTAMP,
                    settled_by TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_user_id ON accounting_transactions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_created_at ON accounting_transactions(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_phone ON accounting_transactions(client_phone)")

            # Customer Leads Table (Exclusive Chief Editor CRM)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_name TEXT NOT NULL,
                    client_phone TEXT,
                    category TEXT DEFAULT 'عام',
                    article_title TEXT,
                    article_url TEXT,
                    article_id INTEGER,
                    promoted_by_name TEXT,
                    promoted_by_email TEXT,
                    contact_status TEXT DEFAULT 'NEW',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lead_phone ON customer_leads(client_phone)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lead_category ON customer_leads(category)")
            # Gemini Fallback Monitoring Table (Chief Editor & Deputy Exclusive)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gemini_fallback_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_title TEXT,
                    reporter_name TEXT,
                    reporter_id TEXT,
                    trigger_reason TEXT,
                    glm_model TEXT DEFAULT 'glm-4.7-flash',
                    gemini_model TEXT DEFAULT 'gemini-3.6-flash',
                    latency_seconds REAL DEFAULT 0.0,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'SUCCESS',
                    error_details TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_fallback_created ON gemini_fallback_logs(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_fallback_status ON gemini_fallback_logs(status)")

            # Migration: Ensure custom_deduction column exists in users table
            try:
                cursor.execute("SELECT custom_deduction FROM users LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN custom_deduction REAL DEFAULT NULL")
                    logger.info("Migrated users table: added custom_deduction column.")
                except Exception:
                    pass

            # Seed default financial settings in settings table
            default_financial_settings = {
                "official_article_price": "150.0",
                "cut_certified_journalist": "75.0",
                "cut_premium_editor": "50.0",
                "cut_admin": "0.0"
            }
            for k, v in default_financial_settings.items():
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            # Seed Master Editor-in-Chief admin user and activation codes
            cursor.execute("""
                INSERT OR IGNORE INTO users (
                    id, username, password_hash, full_name, role, email, is_active, phone
                ) VALUES (
                    1, 'shalllaby1', '09fea9dcfa2654e16d2123e7669969e8$833536741c2067dfa0ad4b2857176d68230bc3bf0290a80606c491af4f963b4a', 'أ/ محمد شلبي (رئيس التحرير العام)', 'admin', 'shalllaby1@gmail.com', 1, '01062501088'
                )
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO activation_codes (
                    code, journalist_name, journalist_phone, role, status, created_by, used_by_email, used_at
                ) VALUES (
                    'TD-SHALABY-ADMIN', 'أ/ محمد شلبي (رئيس التحرير العام)', '01062501088', 'admin', 'USED', 'System Master', 'shalllaby1@gmail.com', CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO activation_codes (
                    code, journalist_name, journalist_phone, role, status, created_by, used_by_email, used_at
                ) VALUES (
                    'TD-7F4E46-ADMIN', 'أ/ محمد شلبي (رئيس التحرير العام)', '01062501088', 'admin', 'USED', 'System Master', 'shalllaby1@gmail.com', CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info("Database tables initialized successfully.")

    # --- User & Authentication Operations ---
    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000)
        return f"{salt}${key.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        try:
            salt, key_hex = stored_hash.split('$')
            computed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000)
            return secrets.compare_digest(computed.hex(), key_hex)
        except Exception:
            return False

    def authenticate_user(self, username: str, password: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username.strip().lower(),))
            row = cursor.fetchone()
            if row and self.verify_password(password, row['password_hash']):
                user = dict(row)
                cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
                conn.commit()
                user.pop('password_hash', None)
                return user
        return None

    def get_user_by_id(self, user_id: int) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                u = dict(row)
                u.pop("password_hash", None)
                return u
            return None

    def get_user_by_username(self, username: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),))
            row = cursor.fetchone()
            if row:
                u = dict(row)
                u.pop("password_hash", None)
                return u
            return None

    def get_all_users(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY id ASC")
            users = []
            for r in cursor.fetchall():
                u = dict(r)
                u.pop("password_hash", None)
                users.append(u)
            return users

    def create_user(self, username: str, password: str, full_name: str, role: str = 'journalist', email: str = '') -> int:
        phash = self.hash_password(password)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, email)
                VALUES (?, ?, ?, ?, ?)
            """, (username.strip().lower(), phash, full_name.strip(), role, email.strip()))
            conn.commit()
            return cursor.lastrowid

    def get_or_create_google_user(self, email: str, full_name: str, avatar: str = "", token_path: str = "", role: str = None, phone: str = None) -> dict:
        email_clean = email.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_clean,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT * FROM users WHERE LOWER(username) = ? AND (email IS NULL OR email = '')", (email_clean.split("@")[0],))
                row = cursor.fetchone()
            if row:
                user_id = row["id"]
                updates = ["last_login = CURRENT_TIMESTAMP"]
                vals = []
                if full_name:
                    updates.append("full_name = ?")
                    vals.append(full_name)
                if avatar:
                    updates.append("google_avatar = ?")
                    vals.append(avatar)
                if token_path:
                    updates.append("blogger_token_path = ?")
                    vals.append(token_path)
                if role:
                    updates.append("role = ?")
                    vals.append(role)
                if phone:
                    updates.append("phone = ?")
                    vals.append(phone)
                vals.append(user_id)
                cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", vals)
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = dict(cursor.fetchone())
                user.pop("password_hash", None)
                return user
            else:
                username = email_clean.split("@")[0]
                phash = self.hash_password(secrets.token_urlsafe(16))
                assigned_role = role or "journalist"
                assigned_phone = phone or ""
                cursor.execute("""
                    INSERT INTO users (username, password_hash, full_name, role, email, phone, google_avatar, blogger_token_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (username, phash, full_name or username, assigned_role, email_clean, assigned_phone, avatar, token_path))
                conn.commit()
                user_id = cursor.lastrowid
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = dict(cursor.fetchone())
                user.pop("password_hash", None)
                return user

    def update_user(self, user_id: int, full_name: str = None, role: str = None, is_active: int = None, password: str = None):
        fields = []
        values = []
        if full_name is not None:
            fields.append("full_name = ?")
            values.append(full_name.strip())
        if role is not None:
            fields.append("role = ?")
            values.append(role)
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(int(is_active))
        if password:
            fields.append("password_hash = ?")
            values.append(self.hash_password(password))
        if not fields:
            return
        values.append(user_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()

    def delete_user(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()

    def update_user_blogger_token(self, user_id: int, token_path: str, avatar: str = "") -> bool:
        """Assigns or updates a personal Blogger token for a specific user ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = ["blogger_token_path = ?"]
            vals = [token_path]
            if avatar:
                updates.append("google_avatar = ?")
                vals.append(avatar)
            vals.append(user_id)
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(vals))
            conn.commit()
            return cursor.rowcount > 0

    def update_user_identity(self, user_id: int, full_name: str, gender: str) -> dict:
        """Updates user's official two-part full name and gender/identity in the platform."""
        clean_name = (full_name or "").strip()
        clean_gender = (gender or "").strip().lower()
        if clean_gender not in ("male", "female"):
            clean_gender = "male"
            
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET full_name = ?, gender = ?
                WHERE id = ?
            """, (clean_name, clean_gender, user_id))
            
            # Also update journalist_name in activation_codes if linked to this user's email
            cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()
            if u_row and u_row["email"]:
                cursor.execute("""
                    UPDATE activation_codes 
                    SET journalist_name = ?
                    WHERE LOWER(used_by_email) = ?
                """, (clean_name, u_row["email"].strip().lower()))
                
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            user_dict = dict(row) if row else {}
            user_dict.pop("password_hash", None)
            return user_dict

    def get_user_zai_key(self, user_id: int) -> str:
        """Retrieves the journalist's personal Z.AI API key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT zai_api_key FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["zai_api_key"]:
                return str(row["zai_api_key"]).strip()
        return ""

    def set_user_zai_key(self, user_id: int, api_key: str):
        """Saves or updates the journalist's personal Z.AI API key."""
        clean_key = (api_key or "").strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET zai_api_key = ? WHERE id = ?", (clean_key, user_id))
            conn.commit()

    # --- Activation & Invitation Codes ---
    def create_activation_code(self, journalist_name: str, journalist_phone: str, role: str = "journalist", created_by: str = None) -> str:
        """Generates a secure, branded one-time activation code for onboarding journalists."""
        suffix = "DEPUTY" if role == "deputy_editor" else ("GOLD" if role == "editor" else ("ADMIN" if role == "admin" else "PRESS"))
        code = f"TD-{secrets.token_hex(2).upper()}{secrets.randbelow(90)+10}-{suffix}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activation_codes (code, journalist_name, journalist_phone, role, created_by)
                VALUES (?, ?, ?, ?, ?)
            """, (code, journalist_name.strip(), journalist_phone.strip(), role, created_by or "Admin"))
            conn.commit()
        return code

    def verify_activation_code(self, code: str) -> dict:
        """Verifies if an activation code is valid. If already used, enables direct re-login for the linked journalist."""
        clean_code = (code or "").strip().upper()
        if not clean_code:
            return {"valid": False, "message": "يرجى إدخال كود التفعيل"}
            
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM activation_codes WHERE UPPER(code) = ?", (clean_code,))
            row = cursor.fetchone()
            if not row:
                return {"valid": False, "message": "كود الصحفي غير صحيح أو غير مسجل في الجريدة"}
            
            if row["status"] == "USED":
                return {
                    "valid": True,
                    "is_already_active": True,
                    "code": row["code"],
                    "user_email": row["used_by_email"],
                    "journalist_name": row["journalist_name"],
                    "journalist_phone": row["journalist_phone"],
                    "role": row["role"],
                    "used_at": row["used_at"]
                }
            elif row["status"] != "PENDING":
                return {"valid": False, "message": "هذا الكود تم إيقافه من قبل إدارة الجريدة"}
                
            return {
                "valid": True,
                "is_already_active": False,
                "code": row["code"],
                "journalist_name": row["journalist_name"],
                "journalist_phone": row["journalist_phone"],
                "role": row["role"],
                "created_at": row["created_at"]
            }

    def consume_activation_code(self, code: str, email: str) -> bool:
        """Burns/consumes an activation code once Google account is linked."""
        clean_code = (code or "").strip().upper()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE activation_codes 
                SET status = 'USED', used_by_email = ?, used_at = CURRENT_TIMESTAMP
                WHERE UPPER(code) = ? AND status = 'PENDING'
            """, (email.strip().lower(), clean_code))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_activation_codes(self) -> list:
        """Lists all activation codes issued by admins."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM activation_codes ORDER BY id DESC")
            return [dict(r) for r in cursor.fetchall()]

    def revoke_activation_code(self, code: str) -> bool:
        """Revokes an unused activation code."""
        clean_code = (code or "").strip().upper()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE activation_codes SET status = 'REVOKED' WHERE UPPER(code) = ? AND status = 'PENDING'", (clean_code,))
            conn.commit()
            return cursor.rowcount > 0

    # --- System Settings & Feature Permissions ---
    def get_setting(self, key: str, default: str = "") -> str:
        """Retrieves a setting value from settings table."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Saves or updates a setting in settings table."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, str(value)))
            conn.commit()

    def get_allowed_transfer_usernames(self) -> list:
        """Returns list of usernames explicitly allowed to promote review articles."""
        raw = self.get_setting("allowed_transfer_usernames", "")
        if not raw:
            return []
        return [u.strip().lower() for u in raw.split(",") if u.strip()]

    def set_allowed_transfer_usernames(self, usernames: list) -> bool:
        """Sets the list of usernames allowed to promote review articles."""
        clean = [str(u).strip().lower() for u in usernames if str(u).strip()]
        self.set_setting("allowed_transfer_usernames", ",".join(clean))
        return True

    def is_user_allowed_transfer(self, user: dict) -> bool:
        """
        Checks if a user is authorized to use the Review -> Main promote tool.
        Authorized if:
        1. User role is 'admin' or 'editor' (Editor-in-Chief / رئيس التحرير).
        2. OR user's username is explicitly in allowed_transfer_usernames list.
        """
        if not user:
            return False
        role = (user.get("role") or "").strip().lower()
        if role in ["admin", "deputy_editor", "editor"]:
            return True
        username = (user.get("username") or "").strip().lower()
        if not username:
            return False
        return username in self.get_allowed_transfer_usernames()

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

        # Ensure labels is a comma-separated string
        labels_val = data.get("labels", "")
        if isinstance(labels_val, list):
            labels_val = ", ".join([str(l).strip() for l in labels_val if l])
        elif labels_val is None:
            labels_val = ""
        else:
            labels_val = str(labels_val)

        # Ensure raw_ai_json is a valid string
        raw_json_val = data.get("raw_ai_json", "")
        if isinstance(raw_json_val, (dict, list)):
            raw_json_val = json.dumps(raw_json_val, ensure_ascii=False)
        elif raw_json_val is None:
            raw_json_val = ""
        else:
            raw_json_val = str(raw_json_val)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO articles (
                    client_id, title, slug, labels, raw_ai_json, final_html,
                    local_image_path, remote_image_url, blog_id, post_id,
                    post_url, is_draft, blogger_status, published_at, reporter_telegram_id,
                    author_email, author_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                str(data.get("title", "") or ""),
                str(data.get("slug", "") or ""),
                labels_val,
                raw_json_val,
                str(data.get("final_html", "") or data.get("content", "") or ""),
                str(data.get("local_image_path", "") or ""),
                str(data.get("remote_image_url", "") or ""),
                str(data.get("blog_id", "") or ""),
                str(data.get("blogger_post_id") or data.get("post_id", "") or ""),
                str(data.get("blogger_url") or data.get("post_url", "") or ""),
                1 if data.get("is_draft") else 0,
                str(data.get("blogger_status", "PUBLISHED") or "PUBLISHED"),
                data.get("published_at") or datetime.now().isoformat(),
                str(data.get("reporter_telegram_id") or ""),
                str(data.get("author_email") or ""),
                str(data.get("author_name") or "")
            ))
            conn.commit()
            return cursor.lastrowid

    def update_article(self, article_id: int, update_fields: dict):
        sanitized_fields = {}
        for k, v in update_fields.items():
            if isinstance(v, list):
                if k == "labels":
                    sanitized_fields[k] = ", ".join([str(x).strip() for x in v if x])
                else:
                    sanitized_fields[k] = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, dict):
                sanitized_fields[k] = json.dumps(v, ensure_ascii=False)
            else:
                sanitized_fields[k] = v

        keys = list(sanitized_fields.keys())
        values = list(sanitized_fields.values())
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

    def get_article_by_url(self, url: str) -> Optional[dict]:
        """Finds an article by exact post_url or partial path/slug match, joining client info."""
        if not url or not url.strip():
            return None
        clean_url = url.strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            base_sql = """
                SELECT a.*, c.name as client_name, c.phone as client_phone
                FROM articles a
                LEFT JOIN clients c ON a.client_id = c.id
            """
            # 1. Exact post_url match
            cursor.execute(f"{base_sql} WHERE a.post_url = ? ORDER BY a.id DESC LIMIT 1", (clean_url,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # 2. Normalized match (without scheme or trailing slash)
            norm = clean_url.replace("https://", "").replace("http://", "").rstrip("/")
            cursor.execute(f"{base_sql} WHERE a.post_url LIKE ? ORDER BY a.id DESC LIMIT 1", (f"%{norm}%",))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # 3. Path / slug match
            slug_part = clean_url.split("/")[-1].replace(".html", "").strip()
            if slug_part and len(slug_part) >= 4:
                cursor.execute(f"{base_sql} WHERE a.slug LIKE ? OR a.post_url LIKE ? ORDER BY a.id DESC LIMIT 1", (f"%{slug_part}%", f"%{slug_part}%"))
                row = cursor.fetchone()
                if row:
                    return dict(row)
        return None

    def get_all_articles(self, author_email: str = None, author_name: str = None, user_id: str = None) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            sub_conds = []
            if author_email:
                sub_conds.append("LOWER(a.author_email) = ?")
                params.append(author_email.strip().lower())
            if author_name:
                sub_conds.append("a.author_name = ?")
                params.append(author_name.strip())
            if user_id:
                sub_conds.append("a.reporter_telegram_id = ?")
                params.append(str(user_id).strip())
                
            if sub_conds:
                conditions.append("(" + " OR ".join(sub_conds) + ")")
                
            where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            query = f"""
                SELECT a.*, c.name as client_name, c.phone as client_phone 
                FROM articles a 
                LEFT JOIN clients c ON a.client_id = c.id 
                {where_sql}
                ORDER BY a.id DESC
            """
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def find_article_by_phone(self, phone: str) -> dict:
        """Looks up existing articles published for this phone number."""
        if not phone:
            return {"exists": False}

        from services.whatsapp_service import clean_egyptian_phone
        clean_num = clean_egyptian_phone(phone)
        digits = "".join(filter(str.isdigit, str(phone)))
        core_10 = clean_num[-10:] if clean_num and len(clean_num) >= 10 else (digits[-10:] if len(digits) >= 10 else digits)

        if not core_10 or len(core_10) < 9:
            return {"exists": False}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT a.*, c.name as client_name, c.phone as client_phone
                FROM articles a
                JOIN clients c ON a.client_id = c.id
                WHERE c.phone LIKE ? OR c.phone LIKE ?
                ORDER BY a.id DESC LIMIT 1
            """
            cursor.execute(query, (f"%{core_10}%", f"%{clean_num}%" if clean_num else f"%{core_10}%"))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["exists"] = True
                return res

            # Fallback: check clients table directly if registered without article or as secondary
            cursor.execute("SELECT * FROM clients WHERE phone LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 1",
                           (f"%{core_10}%", f"%{clean_num}%" if clean_num else f"%{core_10}%"))
            client_row = cursor.fetchone()
            if client_row:
                c_dict = dict(client_row)
                return {
                    "exists": True,
                    "client_id": c_dict["id"],
                    "client_name": c_dict["name"],
                    "client_phone": c_dict["phone"],
                    "title": f"منظومة مسجلة مسبقاً — {c_dict['name']}",
                    "published_at": c_dict.get("created_at"),
                    "blogger_status": "REGISTERED_CLIENT"
                }
            return {"exists": False}

    def register_secondary_client_phones(
        self,
        primary_phone: str,
        all_phones: list,
        client_name: str,
        article_data: dict = None
    ) -> list:
        """
        Registers all additional/secondary phone numbers found in raw notes under the SAME client/organization.
        Each secondary number is saved as a client record and linked to the same published article,
        ensuring complete protection against duplicate contacting across all the organization's numbers.
        """
        if not all_phones or not isinstance(all_phones, list):
            return []

        clean_primary = str(primary_phone).strip() if primary_phone else ""
        registered = []

        art_data = article_data.copy() if isinstance(article_data, dict) else {}
        title = art_data.get("title") or f"خبر صحفي — {client_name}"
        post_url = art_data.get("post_url") or ""
        post_id = art_data.get("post_id") or ""
        slug = art_data.get("slug") or ""
        labels = art_data.get("labels") or "خدمات"
        final_html = art_data.get("final_html") or ""
        author_name = art_data.get("author_name") or "محرر الجريدة"
        author_email = art_data.get("author_email") or ""
        reporter_id = str(art_data.get("reporter_telegram_id") or "")
        now_iso = datetime.now().isoformat()

        from services.central_sync_service import central_sync_service

        for phone in all_phones:
            p_clean = str(phone).strip()
            if not p_clean or p_clean == clean_primary:
                continue

            # Check if this secondary phone is already registered to avoid redundant rows
            existing = self.find_article_by_phone(p_clean)
            if existing.get("exists"):
                registered.append(p_clean)
                continue

            # 1. Save client record under the same organization
            try:
                c_id = self.save_client(
                    name=client_name,
                    phone=p_clean,
                    raw_data=f"رقم إضافي تابع لنفس المنظومة: {client_name} | هاتف الواتساب الرئيسي: {clean_primary}"
                )
            except Exception as ce:
                logger.warning(f"Failed to save secondary client {p_clean}: {ce}")
                c_id = None

            # 2. Save article record linked to the same published post
            try:
                sub_title = f"{title} (رقم إضافي: {p_clean})"
                self.save_article({
                    "client_id": c_id,
                    "client_name": client_name,
                    "client_phone": p_clean,
                    "title": sub_title,
                    "slug": slug,
                    "labels": labels,
                    "post_url": post_url,
                    "post_id": post_id,
                    "blogger_status": "PUBLISHED",
                    "author_name": author_name,
                    "author_email": author_email,
                    "reporter_telegram_id": reporter_id,
                    "published_at": now_iso,
                    "final_html": final_html
                })
            except Exception as ae:
                logger.warning(f"Failed to save secondary article for {p_clean}: {ae}")

            # 3. Sync to Central Server Hub
            try:
                central_sync_service.register_published_post({
                    "client_name": client_name,
                    "client_phone": p_clean,
                    "title": f"{title} (رقم إضافي: {p_clean})",
                    "slug": slug,
                    "labels": labels,
                    "post_url": post_url,
                    "post_id": post_id,
                    "reporter_telegram_id": reporter_id,
                    "blogger_status": "PUBLISHED"
                })
            except Exception as se:
                logger.debug(f"Central sync for secondary phone {p_clean}: {se}")

            registered.append(p_clean)
            logger.info(f"✅ تم تسجيل رقم إضافي ({p_clean}) تحت نفس المنظومة: {client_name}")

        return registered

    def find_article_by_name(self, name: str) -> dict:
        """Looks up existing articles published for this client name."""
        if not name or len(name.strip()) < 3:
            return {"exists": False}

        clean_name = re.sub(r"^(أ/|أ\.|د/|د\.|م/|م\.|ك/|ك\.|أستاذ/|دكتور/|مهندس/|كابتن/|الشيخ/)\s*", "", name.strip()).strip()
        if len(clean_name) < 3:
            return {"exists": False}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT a.*, c.name as client_name, c.phone as client_phone
                FROM articles a
                JOIN clients c ON a.client_id = c.id
                WHERE c.name LIKE ? OR a.title LIKE ?
                ORDER BY a.id DESC LIMIT 1
            """
            cursor.execute(query, (f"%{clean_name}%", f"%{clean_name}%"))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["exists"] = True
                return res
            return {"exists": False}

    def check_client_duplicate(self, phone: str = "", name: str = "") -> dict:
        """Master method to check whether a client already has a published article by phone or name."""
        if phone:
            res = self.find_article_by_phone(phone)
            if res.get("exists"):
                return res

        if name:
            res = self.find_article_by_name(name)
            if res.get("exists"):
                return res

        return {"exists": False}

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
    def log_system(self, level: str, module: str, message: str, user_id: str = None, user_name: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO system_logs (level, module, message, user_id, user_name) VALUES (?, ?, ?, ?, ?)",
                (level, module, message, str(user_id) if user_id is not None else None, str(user_name) if user_name is not None else None)
            )
            conn.commit()

    def get_system_logs(self, limit: int = 200) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def log_desktop_activity(self, action: str, details: str, user_id: str = None, user_name: str = None, level: str = "INFO"):
        """Logs a desktop user operation specifically tagged with module='DesktopApp' and their account credentials."""
        uname = user_name or "صحفي سطح المكتب"
        uid = user_id or "desktop_user"
        msg = f"[{action}] {details}"
        self.log_system(level, "DesktopApp", msg, user_id=str(uid), user_name=uname)

    def get_desktop_user_logs(self, user_id: str = None, user_name: str = None, limit: int = 300) -> list:
        """
        Retrieves operations performed ONLY by the specified desktop user.
        Excludes any TelegramBot logs or activities from other users.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            conditions = ["module = 'DesktopApp'"]
            params = []

            user_clauses = []
            if user_id:
                user_clauses.append("user_id = ?")
                params.append(str(user_id))
            if user_name:
                user_clauses.append("user_name = ?")
                params.append(str(user_name))

            if user_clauses:
                conditions.append(f"({' OR '.join(user_clauses)})")

            query = f"SELECT * FROM system_logs WHERE {' AND '.join(conditions)} ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # --- Reporter Operations ---
    def save_reporter(self, telegram_id: str, name: str, role: str = "صحفي لدى", api_key: str = None) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if api_key is not None:
                cursor.execute("""
                    INSERT INTO reporters (telegram_id, name, role, api_key)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name, role=excluded.role, api_key=excluded.api_key
                """, (str(telegram_id), name, role, api_key.strip()))
            else:
                cursor.execute("""
                    INSERT INTO reporters (telegram_id, name, role)
                    VALUES (?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name, role=excluded.role
                """, (str(telegram_id), name, role))
            conn.commit()
            return True

    def update_reporter_key(self, telegram_id: str, api_key: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE reporters SET api_key = ? WHERE telegram_id = ?
            """, (api_key.strip() if api_key else "", str(telegram_id)))
            conn.commit()
            return cursor.rowcount > 0

    def get_reporter(self, telegram_id: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reporters WHERE telegram_id = ?", (str(telegram_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_reporters_with_stats(self) -> list:
        """Returns all registered reporters with today's and total published articles count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    r.telegram_id,
                    r.name,
                    r.role,
                    r.api_key,
                    r.created_at,
                    COALESCE(SUM(CASE WHEN DATE(a.published_at) = DATE('now', 'localtime') AND a.blogger_status = 'PUBLISHED' THEN 1 ELSE 0 END), 0) as articles_today,
                    COALESCE(COUNT(a.id), 0) as articles_total
                FROM reporters r
                LEFT JOIN articles a ON a.reporter_telegram_id = r.telegram_id AND a.blogger_status = 'PUBLISHED'
                GROUP BY r.telegram_id
                ORDER BY r.created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_all_reporters(self) -> list:
        """Returns all registered reporters with their stats."""
        return self.get_reporters_with_stats()

    def save_whatsapp_log(self, article_id: int, recipient_phone: str, recipient_name: str, message_body: str, status: str = "READY", error_message: str = None, delay_seconds: int = 5) -> int:
        """Alias for log_whatsapp to store WhatsApp delivery state."""
        return self.log_whatsapp(article_id, recipient_phone, recipient_name, message_body, status, error_message, delay_seconds)

    def delete_reporter(self, telegram_id: str) -> bool:
        """Deletes a reporter record by telegram_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reporters WHERE telegram_id = ?", (str(telegram_id),))
            conn.commit()
            return cursor.rowcount > 0

    def log_bot_error(self, telegram_id: str, reporter_name: str, action: str, error_message: str):
        """Logs a bot user activity/error into system_logs table."""
        msg = f"[{action}] الصحفي: {reporter_name} (ID: {telegram_id}) - التفاصيل: {error_message}"
        self.log_system("ERROR", "TelegramBot", msg, user_id=str(telegram_id), user_name=reporter_name)

    def log_bot_activity(self, telegram_id: str, reporter_name: str, action: str, details: str):
        """Logs a successful bot activity into system_logs table."""
        msg = f"[{action}] الصحفي: {reporter_name} (ID: {telegram_id}) - {details}"
        self.log_system("INFO", "TelegramBot", msg, user_id=str(telegram_id), user_name=reporter_name)

    def get_bot_logs(self, limit: int = 150) -> list:
        """Returns the latest logs specifically for Telegram Bot events and errors."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM system_logs 
                WHERE module = 'TelegramBot' OR message LIKE '%Telegram%' OR message LIKE '%الصحفي%'
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # --- Newspaper-Wide Publishing Rate Limit (1 article/min) ---
    def get_latest_published_timestamp(self) -> float:
        """Returns epoch timestamp of the most recently published article across the newspaper."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT published_at FROM articles 
                    WHERE blogger_status = 'PUBLISHED' 
                      AND post_id IS NOT NULL 
                      AND post_id != ''
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                if row and row["published_at"]:
                    val = str(row["published_at"]).replace("Z", "").replace(" ", "T")
                    ts = datetime.fromisoformat(val).timestamp()
                    now = time.time()
                    # Sanity check: ignore future timestamps (clock skew) or articles older than 1 hour
                    if 0 <= (now - ts) < 3600:
                        return ts
        except Exception:
            pass
        return 0.0

    def record_publish_event(self):
        """Records that an article was published right now."""
        global _MEM_LAST_PUBLISH_TIME
        _MEM_LAST_PUBLISH_TIME = time.time()

    def reset_publish_cooldown(self):
        """Allows administrators to manually reset the publish cooldown timer."""
        global _MEM_LAST_PUBLISH_TIME
        _MEM_LAST_PUBLISH_TIME = 0.0

    def get_publish_cooldown_remaining(self, cooldown_seconds: int = 60) -> int:
        """
        Calculates remaining seconds before the newspaper allows publishing another article.
        Enforces maximum 1 article per minute across all reporters.
        Returns 0 if cooldown has elapsed.
        """
        now = time.time()
        latest_db = self.get_latest_published_timestamp()
        latest_t = max(_MEM_LAST_PUBLISH_TIME, latest_db)
        if latest_t <= 0:
            return 0
        elapsed = now - latest_t
        if 0 <= elapsed < cooldown_seconds:
            return int(cooldown_seconds - elapsed) + 1
        return 0

    # --- Journalist Accounting & Financial Operations ---
    def get_financial_settings(self) -> dict:
        """Retrieves global official article price and role deduction cuts."""
        defaults = {
            "official_article_price": 150.0,
            "cut_certified_journalist": 75.0,
            "cut_premium_editor": 50.0,
            "cut_admin": 0.0
        }
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'cut_%' OR key = 'official_article_price'")
            for row in cursor.fetchall():
                try:
                    defaults[row["key"]] = float(row["value"])
                except Exception:
                    pass
        return defaults

    def update_financial_settings(self, settings_dict: dict) -> bool:
        """Updates global financial settings (official price and default role cuts)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for k, v in settings_dict.items():
                if v is not None:
                    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
            conn.commit()
            return True

    def set_user_custom_cut(self, user_id: int, custom_cut: Optional[float]) -> bool:
        """Sets or clears a custom deduction override for an individual journalist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET custom_deduction = ? WHERE id = ?", (custom_cut, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def calculate_effective_cut(self, user_id: int, role: str) -> float:
        """Calculates the newspaper cut for a user: custom override takes precedence over role defaults."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT custom_deduction FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["custom_deduction"] is not None:
                return float(row["custom_deduction"])
        
        # Fallback to role defaults
        settings = self.get_financial_settings()
        if role in ["admin", "deputy_editor"]:
            return float(settings.get("cut_admin", 0.0))
        elif role == "editor":
            return float(settings.get("cut_premium_editor", 50.0))
        else:
            return float(settings.get("cut_certified_journalist", 75.0))

    def save_accounting_transaction(self, data: dict) -> int:
        """Records a new billing/collection transaction for a published article."""
        user_id = data.get("user_id")
        user_role = data.get("user_role") or "journalist"
        amount_paid = float(data.get("amount_paid") or 0.0)

        # Compute newspaper cut and net profit based on role / custom settings
        if data.get("newspaper_cut") is not None:
            effective_cut = float(data.get("newspaper_cut"))
        else:
            effective_cut = self.calculate_effective_cut(user_id, user_role)

        newspaper_cut = min(amount_paid, max(0.0, effective_cut))
        journalist_net = max(0.0, amount_paid - newspaper_cut)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accounting_transactions (
                    user_id, author_name, author_email, user_role,
                    article_id, article_title, article_url,
                    client_name, client_phone, amount_paid,
                    newspaper_cut, journalist_net, payment_method,
                    receipt_image_path, settlement_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                data.get("author_name") or "",
                data.get("author_email") or "",
                user_role,
                data.get("article_id"),
                data.get("article_title") or "خبر صحفي",
                data.get("article_url") or "",
                data.get("client_name") or "",
                data.get("client_phone") or "",
                amount_paid,
                newspaper_cut,
                journalist_net,
                data.get("payment_method") or "vodafone_cash",
                data.get("receipt_image_path") or "",
                data.get("settlement_status") or "PENDING",
                data.get("notes") or ""
            ))
            conn.commit()
            return cursor.lastrowid

    def _build_time_filter(self, time_range: str = "all", start_date: str = None, end_date: str = None) -> tuple:
        """Helper to build WHERE clause conditions and parameters for accounting date ranges."""
        conds = []
        params = []
        if time_range == "today":
            conds.append("DATE(created_at) = DATE('now', 'localtime')")
        elif time_range == "week":
            conds.append("DATE(created_at) >= DATE('now', 'localtime', '-7 days')")
        elif time_range == "month":
            conds.append("DATE(created_at) >= DATE('now', 'localtime', 'start of month')")
        elif time_range == "custom" and start_date and end_date:
            conds.append("DATE(created_at) >= DATE(?) AND DATE(created_at) <= DATE(?)")
            params.extend([start_date, end_date])
        return conds, params

    def get_accounting_transactions(self, user_id: int = None, time_range: str = "all", start_date: str = None, end_date: str = None, limit: int = 300) -> list:
        """Retrieves accounting records filtered by user and date range."""
        conds, params = self._build_time_filter(time_range, start_date, end_date)
        if user_id:
            conds.append("user_id = ?")
            params.append(user_id)

        where_clause = f"WHERE {' AND '.join(conds)}" if conds else ""
        query = f"SELECT * FROM accounting_transactions {where_clause} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                amount = float(d.get("amount_paid") or 0.0)
                cut = float(d.get("newspaper_cut") or 0.0)
                net = float(d.get("journalist_net") if d.get("journalist_net") is not None else max(0.0, amount - cut))
                d["amount_paid"] = amount
                d["newspaper_cut"] = cut
                d["journalist_net"] = net
                d["net_profit"] = net
                d["is_settled"] = (d.get("settlement_status") == "SETTLED")
                rows.append(d)
            return rows

    def get_user_financial_stats(self, user_id: int = None, time_range: str = "all", start_date: str = None, end_date: str = None, user_role: str = "journalist") -> dict:
        """Calculates KPI metrics for a journalist or entire newspaper: total articles, gross revenue, newspaper cut, net profit, and pending due."""
        conds, params = self._build_time_filter(time_range, start_date, end_date)
        if user_id:
            conds.append("user_id = ?")
            params.append(user_id)

        where_clause = f"WHERE {' AND '.join(conds)}" if conds else ""
        query = f"""
            SELECT 
                COUNT(id) as total_articles,
                COALESCE(SUM(amount_paid), 0.0) as gross_revenue,
                COALESCE(SUM(newspaper_cut), 0.0) as newspaper_cut,
                COALESCE(SUM(journalist_net), 0.0) as net_profit,
                COALESCE(SUM(CASE WHEN settlement_status = 'PENDING' THEN newspaper_cut ELSE 0.0 END), 0.0) as pending_due
            FROM accounting_transactions
            {where_clause}
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            res = {
                "total_articles": int(row["total_articles"]) if row and row["total_articles"] is not None else 0,
                "gross_revenue": float(row["gross_revenue"]) if row and row["gross_revenue"] is not None else 0.0,
                "newspaper_cut": float(row["newspaper_cut"]) if row and row["newspaper_cut"] is not None else 0.0,
                "net_profit": float(row["net_profit"]) if row and row["net_profit"] is not None else 0.0,
                "journalist_net": float(row["net_profit"]) if row and row["net_profit"] is not None else 0.0,
                "pending_due": float(row["pending_due"]) if row and row["pending_due"] is not None else 0.0
            } if row else {
                "total_articles": 0,
                "gross_revenue": 0.0,
                "newspaper_cut": 0.0,
                "net_profit": 0.0,
                "journalist_net": 0.0,
                "pending_due": 0.0
            }
            settings = self.get_financial_settings()
            if user_id:
                cursor.execute("SELECT role, custom_deduction FROM users WHERE id = ?", (user_id,))
                user_row = cursor.fetchone()
                role = user_row["role"] if user_row else user_role
                res["effective_cut"] = self.calculate_effective_cut(user_id, role)
                res["role"] = role
            else:
                res["effective_cut"] = 0.0
                res["role"] = user_role or "admin"
            res["official_price"] = settings.get("official_article_price", 150.0)
            return res

    def get_admin_financial_overview(self, time_range: str = "all", start_date: str = None, end_date: str = None) -> dict:
        """Calculates newspaper-wide financial overview across all journalists for Admin."""
        conds, params = self._build_time_filter(time_range, start_date, end_date)
        where_clause = f"WHERE {' AND '.join(conds)}" if conds else ""
        query = f"""
            SELECT 
                COUNT(id) as total_transactions,
                COALESCE(SUM(amount_paid), 0.0) as gross_revenue,
                COALESCE(SUM(newspaper_cut), 0.0) as total_newspaper_vault,
                COALESCE(SUM(journalist_net), 0.0) as total_journalist_payouts,
                COALESCE(SUM(CASE WHEN settlement_status = 'PENDING' THEN newspaper_cut ELSE 0.0 END), 0.0) as total_pending_vault,
                COALESCE(SUM(CASE WHEN settlement_status = 'SETTLED' THEN newspaper_cut ELSE 0.0 END), 0.0) as total_settled_vault
            FROM accounting_transactions
            {where_clause}
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            res = dict(row) if row else {
                "total_transactions": 0,
                "gross_revenue": 0.0,
                "total_newspaper_vault": 0.0,
                "total_journalist_payouts": 0.0,
                "total_pending_vault": 0.0,
                "total_settled_vault": 0.0
            }
            settings = self.get_financial_settings()
            res.update(settings)
            return res

    def get_reporters_financial_ledger(self, time_range: str = "all", start_date: str = None, end_date: str = None) -> list:
        """Produces a breakdown ledger for each journalist (billed articles, revenue, cuts, net, pending)."""
        conds, params = self._build_time_filter(time_range, start_date, end_date)
        time_clause = f"AND {' AND '.join(conds)}" if conds else ""

        query = f"""
            SELECT 
                u.id as user_id,
                u.full_name,
                u.email,
                u.role,
                u.custom_deduction,
                COALESCE(COUNT(t.id), 0) as total_articles,
                COALESCE(SUM(t.amount_paid), 0.0) as gross_revenue,
                COALESCE(SUM(t.newspaper_cut), 0.0) as newspaper_cut,
                COALESCE(SUM(t.journalist_net), 0.0) as net_profit,
                COALESCE(SUM(CASE WHEN t.settlement_status = 'PENDING' THEN t.newspaper_cut ELSE 0.0 END), 0.0) as pending_due
            FROM users u
            LEFT JOIN accounting_transactions t ON t.user_id = u.id {time_clause}
            GROUP BY u.id
            ORDER BY gross_revenue DESC, total_articles DESC
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                d["effective_cut"] = self.calculate_effective_cut(d["user_id"], d["role"])
                rows.append(d)
            return rows

    def settle_user_transactions(self, user_id: int, admin_name: str) -> int:
        """Marks all pending transactions for a user as SETTLED once funds have been received."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accounting_transactions 
                SET settlement_status = 'SETTLED', settled_at = CURRENT_TIMESTAMP, settled_by = ?
                WHERE user_id = ? AND settlement_status = 'PENDING'
            """, (admin_name, user_id))
            conn.commit()
            return cursor.rowcount

    def get_unbilled_articles(self, author_email: str = None) -> list:
        """Returns articles published by the user that have not yet been billed in accounting_transactions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if author_email:
                cursor.execute("""
                    SELECT a.id, a.title, a.post_url, a.published_at, c.name as client_name, c.phone as client_phone
                    FROM articles a
                    LEFT JOIN clients c ON a.client_id = c.id
                    LEFT JOIN accounting_transactions t ON (t.article_id = a.id OR (t.article_title = a.title AND a.title != ''))
                    WHERE LOWER(a.author_email) = LOWER(?) AND a.blogger_status = 'PUBLISHED' AND t.id IS NULL
                    ORDER BY a.id DESC LIMIT 50
                """, (author_email.strip().lower(),))
            else:
                cursor.execute("""
                    SELECT a.id, a.title, a.post_url, a.published_at, c.name as client_name, c.phone as client_phone
                    FROM articles a
                    LEFT JOIN clients c ON a.client_id = c.id
                    LEFT JOIN accounting_transactions t ON (t.article_id = a.id OR (t.article_title = a.title AND a.title != ''))
                    WHERE a.blogger_status = 'PUBLISHED' AND t.id IS NULL
                    ORDER BY a.id DESC LIMIT 50
                """)
            return [dict(r) for r in cursor.fetchall()]

    def delete_accounting_transaction(self, transaction_id: int, user_id: int = None, is_admin: bool = False) -> bool:
        """Deletes a transaction record if user owns it or if admin."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if is_admin:
                cursor.execute("DELETE FROM accounting_transactions WHERE id = ?", (transaction_id,))
            else:
                cursor.execute("DELETE FROM accounting_transactions WHERE id = ? AND user_id = ? AND settlement_status = 'PENDING'", (transaction_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    # --- Review Articles Cleanup Operations ---
    @staticmethod
    def _normalize_title_for_match(t: str) -> str:
        if not t:
            return ""
        t = t.strip().lower()
        t = re.sub(r'[إأآا]', 'ا', t)
        t = re.sub(r'[ىي]', 'ي', t)
        t = re.sub(r'ة', 'ه', t)
        t = re.sub(r'["\'`.,:؛!?؟\-–—_()[\]{}«»]', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def get_review_dates_summary(self) -> list:
        """
        Retrieves a summary list of distinct dates that have review articles,
        along with the total count of review articles for each date.
        """
        arabic_months = {
            1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
            7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
        }
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COALESCE(DATE(published_at), DATE(created_at)) as art_date,
                    COUNT(*) as total_count
                FROM articles
                WHERE (post_url LIKE '%review%' OR blog_id IN ('3967122067465937059', '5932774642958705278'))
                  AND (COALESCE(DATE(published_at), DATE(created_at)) IS NOT NULL)
                GROUP BY art_date
                ORDER BY art_date DESC
            """)
            results = []
            for row in cursor.fetchall():
                d_str = row["art_date"]
                formatted_arabic = d_str
                try:
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    m_name = arabic_months.get(dt.month, str(dt.month))
                    formatted_arabic = f"{dt.day} {m_name} {dt.year}"
                except Exception:
                    pass

                results.append({
                    "date": d_str,
                    "date_formatted": formatted_arabic,
                    "total_count": row["total_count"]
                })
            return results

    def get_review_day_articles_with_main_match(self, date_str: str, blogger_service = None, token_path: Optional[str] = None) -> dict:
        """
        Fetches all review articles for a specific date directly from WordPress REST API (and DB),
        pulls all Main newspaper articles in the window of the SAME DAY and the NEXT DAY,
        and compares their titles in real-time to determine which Review articles are
        approved/present on the Main newspaper and which should be targeted for deletion.
        """
        from datetime import datetime, timedelta

        d = datetime.strptime(date_str, "%Y-%m-%d")
        next_d_str = (d + timedelta(days=1)).strftime("%Y-%m-%d")

        # ── 1. GATHER ALL MAIN NEWSPAPER ARTICLES (SAME DAY + NEXT DAY WINDOW) ──
        main_map = {}  # normalized_title -> { title, url, post_id }

        # A. From WordPress API live (Main Site)
        if blogger_service:
            try:
                live_main_posts = blogger_service.get_blog_posts_by_date_window(
                    blogger_service.MAIN_BLOG_ID, date_str, days=2, token_path=token_path
                )
                for p in live_main_posts:
                    norm = self._normalize_title_for_match(p.get("title", ""))
                    if norm:
                        main_map[norm] = {
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "post_id": p.get("id", "")
                        }
            except Exception as e:
                logger.warning(f"Live WordPress Main query fallback to DB: {e}")

        # B. From Database (articles on Main for date_str and next_d_str)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, post_url, post_id, published_at FROM articles
                WHERE post_url NOT LIKE '%review%'
                  AND (DATE(published_at) = DATE(?) OR DATE(published_at) = DATE(?))
            """, (date_str, next_d_str))
            for m in cursor.fetchall():
                norm = self._normalize_title_for_match(m["title"] or "")
                if norm and norm not in main_map:
                    main_map[norm] = {
                        "title": m["title"],
                        "url": m["post_url"],
                        "post_id": m["post_id"]
                    }

        # ── 2. GATHER ALL REVIEW ARTICLES (WORDPRESS LIVE IS SOURCE OF TRUTH) ──
        rev_merged = {}  # wp_post_id or str_key -> dict

        # A. From WordPress API live (Review Site)
        if blogger_service:
            try:
                live_rev_posts = blogger_service.get_blog_posts_by_date_window(
                    blogger_service.REVIEW_BLOG_ID, date_str, days=1, token_path=token_path
                )
                for p in live_rev_posts:
                    pid = str(p.get("id", "")).strip()
                    if pid:
                        rev_merged[pid] = {
                            "id": None,
                            "post_id": pid,
                            "title": p.get("title", ""),
                            "post_url": p.get("url", ""),
                            "published_at": p.get("published", "")
                        }
            except Exception as e:
                logger.warning(f"Live WordPress Review query fallback to DB: {e}")

        # B. Match with / augment from local database
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, post_id, post_url, blogger_status, published_at, created_at
                FROM articles
                WHERE (post_url LIKE '%review%' OR blog_id IN ('3967122067465937059', '5932774642958705278'))
                  AND (DATE(published_at) = DATE(?) OR (published_at IS NULL AND DATE(created_at) = DATE(?)))
                ORDER BY id DESC
            """, (date_str, date_str))
            for r in cursor.fetchall():
                r_title = r["title"] or ""
                r_norm = self._normalize_title_for_match(r_title)
                
                # Check if this DB article matches an existing live WP post
                matched_live_key = None
                for wp_id, wp_item in rev_merged.items():
                    if wp_item.get("title") and self._normalize_title_for_match(wp_item["title"]) == r_norm:
                        matched_live_key = wp_id
                        break
                
                if matched_live_key:
                    rev_merged[matched_live_key]["id"] = r["id"]
                    if not rev_merged[matched_live_key]["post_url"]:
                        rev_merged[matched_live_key]["post_url"] = r["post_url"]
                else:
                    # If not in live WP posts (e.g. only in DB or older Blogger post), add with db key
                    pid = str(r["post_id"] or "").strip()
                    k = pid if pid.isdigit() and len(pid) < 10 else f"db_{r['id']}"
                    if k not in rev_merged:
                        rev_merged[k] = {
                            "id": r["id"],
                            "post_id": pid if (pid.isdigit() and len(pid) < 10) else "",
                            "title": r_title,
                            "post_url": r["post_url"],
                            "published_at": r["published_at"] or r["created_at"]
                        }

        # ── 3. REAL-TIME MATCHING AGAINST SAME DAY + NEXT DAY MAIN ARTICLES ──
        articles = []
        matched_count = 0
        unmatched_count = 0

        for k, rev in rev_merged.items():
            rev_title = rev.get("title", "")
            norm_rev = self._normalize_title_for_match(rev_title)

            matched_main = None
            if norm_rev in main_map:
                matched_main = main_map[norm_rev]
            elif len(norm_rev) >= 20:
                for m_norm, m_obj in main_map.items():
                    if norm_rev in m_norm or m_norm in norm_rev:
                        matched_main = m_obj
                        break

            is_on_main = bool(matched_main)
            if is_on_main:
                matched_count += 1
            else:
                unmatched_count += 1

            rev["is_on_main"] = is_on_main
            rev["main_title"] = matched_main.get("title") if matched_main else None
            rev["main_url"] = matched_main.get("url") if matched_main else None
            articles.append(rev)

        # Sort: Unapproved first (for quick review and action), then Approved
        articles.sort(key=lambda a: (1 if a.get("is_on_main") else 0, str(a.get("id") or a.get("post_id"))))

        return {
            "date": date_str,
            "next_date": next_d_str,
            "window_label": f"{date_str} و {next_d_str}",
            "main_articles_compared_count": len(main_map),
            "total_count": len(articles),
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "articles": articles
        }

    def bulk_delete_review_articles(self, post_ids: list = None, article_ids: list = None) -> int:
        """
        Deletes review articles from the database by post_ids (Blogger IDs) and/or article_ids (DB IDs).
        """
        post_ids = [str(p).strip() for p in (post_ids or []) if str(p).strip()]
        article_ids = [int(a) for a in (article_ids or []) if a]

        if not post_ids and not article_ids:
            return 0

        deleted_rows = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if post_ids:
                placeholders = ",".join("?" for _ in post_ids)
                cursor.execute(f"DELETE FROM articles WHERE post_id IN ({placeholders})", tuple(post_ids))
                deleted_rows += cursor.rowcount

            if article_ids:
                placeholders = ",".join("?" for _ in article_ids)
                cursor.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", tuple(article_ids))
                deleted_rows += cursor.rowcount

            conn.commit()
        return deleted_rows

    # =============================================================
    # CUSTOMER LEADS OPERATIONS (CHIEF EDITOR EXCLUSIVE CRM)
    # =============================================================

    def save_customer_lead(self, data: dict) -> int:
        """
        Saves or updates a customer lead silently extracted during article promotion.
        If a lead with the same non-empty phone exists, updates it and attaches the latest article.
        Otherwise, inserts a new record.
        """
        name = (data.get("client_name") or "عميل كريم").strip()
        phone = (data.get("client_phone") or "").strip()
        category = (data.get("category") or "عام").strip()
        art_title = (data.get("article_title") or "").strip()
        art_url = (data.get("article_url") or "").strip()
        art_id = data.get("article_id")
        promoted_by_name = (data.get("promoted_by_name") or "").strip()
        promoted_by_email = (data.get("promoted_by_email") or "").strip()
        notes = (data.get("notes") or "").strip()
        status = data.get("contact_status") or "NEW"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            existing_id = None
            if phone and len(phone) >= 8:
                cursor.execute("SELECT id FROM customer_leads WHERE client_phone = ? ORDER BY id DESC LIMIT 1", (phone,))
                row = cursor.fetchone()
                if row:
                    existing_id = row[0]

            if not existing_id and art_url and len(art_url) >= 10:
                cursor.execute("SELECT id FROM customer_leads WHERE article_url = ? ORDER BY id DESC LIMIT 1", (art_url,))
                row = cursor.fetchone()
                if row:
                    existing_id = row[0]

            if existing_id:
                cursor.execute("""
                    UPDATE customer_leads
                    SET client_name = CASE WHEN ? != '' AND ? != 'عميل كريم' THEN ? ELSE client_name END,
                        client_phone = CASE WHEN ? != '' THEN ? ELSE client_phone END,
                        category = CASE WHEN ? != 'عام' AND ? != 'أخبار وتقارير عامة' THEN ? ELSE category END,
                        article_title = CASE WHEN ? != '' THEN ? ELSE article_title END,
                        article_url = CASE WHEN ? != '' THEN ? ELSE article_url END,
                        article_id = CASE WHEN ? IS NOT NULL THEN ? ELSE article_id END,
                        promoted_by_name = CASE WHEN ? != '' THEN ? ELSE promoted_by_name END,
                        promoted_by_email = CASE WHEN ? != '' THEN ? ELSE promoted_by_email END,
                        notes = CASE WHEN ? != '' THEN ? ELSE notes END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    name, name, name,
                    phone, phone,
                    category, category, category,
                    art_title, art_title,
                    art_url, art_url,
                    art_id, art_id,
                    promoted_by_name, promoted_by_name,
                    promoted_by_email, promoted_by_email,
                    notes, notes,
                    existing_id
                ))
                conn.commit()
                return existing_id
            else:
                cursor.execute("""
                    INSERT INTO customer_leads (
                        client_name, client_phone, category, article_title, article_url,
                        article_id, promoted_by_name, promoted_by_email, contact_status, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, phone, category, art_title, art_url, art_id, promoted_by_name, promoted_by_email, status, notes))
                conn.commit()
                return cursor.lastrowid

    def get_customer_leads(self, search: str = None, category: str = None, status: str = None, page: int = 1, limit: int = 50) -> dict:
        """
        Retrieves paginated customer leads with optional search, category, and status filters.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            where_clauses = ["1=1"]
            params = []

            if search and search.strip():
                s = f"%{search.strip()}%"
                where_clauses.append("(client_name LIKE ? OR client_phone LIKE ? OR article_title LIKE ? OR promoted_by_name LIKE ?)")
                params.extend([s, s, s, s])

            if category and category != "الكل":
                where_clauses.append("category = ?")
                params.append(category.strip())

            if status and status != "الكل":
                where_clauses.append("contact_status = ?")
                params.append(status.strip())

            where_sql = " AND ".join(where_clauses)

            # Count total
            cursor.execute(f"SELECT COUNT(*) FROM customer_leads WHERE {where_sql}", tuple(params))
            total = cursor.fetchone()[0]

            # Get distinct categories
            cursor.execute("SELECT DISTINCT category FROM customer_leads WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
            categories = [r[0] for r in cursor.fetchall()]

            # Pagination
            offset = max(0, (page - 1) * limit)
            query = f"SELECT * FROM customer_leads WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
            query_params = list(params) + [limit, offset]

            cursor.execute(query, tuple(query_params))
            leads = [dict(row) for row in cursor.fetchall()]

            # Verified phones count
            cursor.execute("SELECT COUNT(*) FROM customer_leads WHERE client_phone IS NOT NULL AND length(client_phone) >= 8")
            verified_phones = cursor.fetchone()[0]

            # Status counts across all leads
            cursor.execute("SELECT contact_status, COUNT(*) FROM customer_leads GROUP BY contact_status")
            sc_rows = cursor.fetchall()
            status_counts = {"ALL": 0, "NEW": 0, "CONTACTED": 0, "VIP": 0, "NOT_INTERESTED": 0}
            cursor.execute("SELECT COUNT(*) FROM customer_leads")
            status_counts["ALL"] = cursor.fetchone()[0]
            for st, cnt in sc_rows:
                if st in status_counts:
                    status_counts[st] = cnt

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "leads": leads,
                "categories": categories,
                "verified_phones": verified_phones,
                "status_counts": status_counts
            }

    def update_customer_lead(self, lead_id: int, status: str = None, notes: str = None, client_name: str = None, client_phone: str = None, category: str = None) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            if status is not None:
                updates.append("contact_status = ?")
                params.append(status.strip())
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes.strip())
            if client_name is not None:
                updates.append("client_name = ?")
                params.append(client_name.strip())
            if client_phone is not None:
                updates.append("client_phone = ?")
                params.append(client_phone.strip())
            if category is not None:
                updates.append("category = ?")
                params.append(category.strip())

            if not updates:
                return False

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(lead_id)

            sql = f"UPDATE customer_leads SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(sql, tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def delete_customer_lead(self, lead_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM customer_leads WHERE id = ?", (lead_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_customer_leads_for_export(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customer_leads ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_customer_lead_by_id(self, lead_id: int) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customer_leads WHERE id = ?", (lead_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==========================================================
    # GEMINI FALLBACK AUDIT & MONITORING METHODS
    # ==========================================================

    def log_gemini_fallback(
        self,
        article_title: str,
        reporter_name: str = "",
        reporter_id: str = "",
        trigger_reason: str = "",
        glm_model: str = "glm-4.7-flash",
        gemini_model: str = "gemini-3.6-flash",
        latency_seconds: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        status: str = "SUCCESS",
        error_details: str = ""
    ) -> int:
        """Logs a Gemini Fallback trigger event to database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO gemini_fallback_logs (
                    article_title, reporter_name, reporter_id, trigger_reason,
                    glm_model, gemini_model, latency_seconds, prompt_tokens,
                    completion_tokens, total_tokens, status, error_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article_title, reporter_name, reporter_id, trigger_reason,
                glm_model, gemini_model, latency_seconds, prompt_tokens,
                completion_tokens, total_tokens, status, error_details
            ))
            conn.commit()
            return cursor.lastrowid

    def get_gemini_fallback_logs(
        self,
        page: int = 1,
        limit: int = 25,
        search: str = None,
        status: str = None
    ) -> dict:
        """Retrieves paginated Gemini Fallback logs with optional search & status filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            where_clauses = ["1=1"]
            params = []

            if search and search.strip():
                s = f"%{search.strip()}%"
                where_clauses.append("(article_title LIKE ? OR reporter_name LIKE ? OR trigger_reason LIKE ?)")
                params.extend([s, s, s])

            if status and status != "الكل":
                where_clauses.append("status = ?")
                params.append(status.strip())

            where_sql = " AND ".join(where_clauses)

            # Total matching
            cursor.execute(f"SELECT COUNT(*) FROM gemini_fallback_logs WHERE {where_sql}", tuple(params))
            total = cursor.fetchone()[0]

            offset = max(0, (page - 1) * limit)
            query = f"SELECT * FROM gemini_fallback_logs WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
            cursor.execute(query, tuple(params + [limit, offset]))
            logs = [dict(row) for row in cursor.fetchall()]

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "logs": logs
            }

    def get_gemini_fallback_stats(self) -> dict:
        """Calculates executive HUD metrics for Gemini Fallback dashboard."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM gemini_fallback_logs")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM gemini_fallback_logs WHERE date(created_at, 'localtime') = date('now', 'localtime')")
            today = cursor.fetchone()[0]

            cursor.execute("SELECT AVG(latency_seconds) FROM gemini_fallback_logs WHERE status = 'SUCCESS' AND latency_seconds > 0")
            avg_lat_row = cursor.fetchone()[0]
            avg_latency = round(avg_lat_row, 2) if avg_lat_row is not None else 0.0

            cursor.execute("SELECT COUNT(*) FROM gemini_fallback_logs WHERE status = 'SUCCESS'")
            success_count = cursor.fetchone()[0]
            success_rate = round((success_count / total * 100), 1) if total > 0 else 100.0

            cursor.execute("SELECT SUM(total_tokens) FROM gemini_fallback_logs")
            sum_tokens = cursor.fetchone()[0] or 0

            return {
                "total_invocations": total,
                "today_invocations": today,
                "avg_latency": avg_latency,
                "success_rate": success_rate,
                "total_tokens": sum_tokens
            }

    # =============================================================
    # FACEBOOK POSTS & COMMERCIAL MANAGEMENT
    # =============================================================

    def save_facebook_post(self, data: dict) -> int:
        """Saves a new Facebook post record or updates an existing one."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fb_post_id = str(data.get("fb_post_id", "")).strip()
            if not fb_post_id:
                raise ValueError("fb_post_id is required")

            cursor.execute("SELECT id FROM facebook_posts WHERE fb_post_id = ?", (fb_post_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE facebook_posts
                    SET post_message = COALESCE(?, post_message),
                        likes_count = COALESCE(?, likes_count),
                        comments_count = COALESCE(?, comments_count),
                        shares_count = COALESCE(?, shares_count),
                        reach_estimate = COALESCE(?, reach_estimate),
                        payment_status = COALESCE(?, payment_status),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    data.get("post_message"),
                    data.get("likes_count"),
                    data.get("comments_count"),
                    data.get("shares_count"),
                    data.get("reach_estimate"),
                    data.get("payment_status"),
                    row[0]
                ))
                conn.commit()
                return row[0]
            else:
                cursor.execute("""
                    INSERT INTO facebook_posts (
                        fb_post_id, article_id, client_id, client_name,
                        post_message, post_url, image_url, payment_status,
                        amount, currency, payment_notes, likes_count,
                        comments_count, shares_count, reach_estimate,
                        published_by_name, published_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    fb_post_id,
                    data.get("article_id"),
                    data.get("client_id"),
                    data.get("client_name"),
                    data.get("post_message"),
                    data.get("post_url"),
                    data.get("image_url"),
                    (data.get("payment_status") or "UNPAID").upper(),
                    float(data.get("amount") or 0.0),
                    data.get("currency") or "EGP",
                    data.get("payment_notes"),
                    int(data.get("likes_count") or 0),
                    int(data.get("comments_count") or 0),
                    int(data.get("shares_count") or 0),
                    int(data.get("reach_estimate") or 0),
                    data.get("published_by_name")
                ))
                conn.commit()
                return cursor.lastrowid

    def update_facebook_post_payment(self, post_id: Union[int, str], payment_status: str, payment_notes: str = None, amount: float = None) -> bool:
        """Updates payment status and notes for a Facebook post."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            status_clean = (payment_status or "UNPAID").strip().upper()
            updates = ["payment_status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status_clean]
            if payment_notes is not None:
                updates.append("payment_notes = ?")
                params.append(payment_notes)
            if amount is not None:
                updates.append("amount = ?")
                params.append(float(amount))

            params.append(str(post_id))
            params.append(str(post_id))
            sql = f"UPDATE facebook_posts SET {', '.join(updates)} WHERE id = ? OR fb_post_id = ?"
            cursor.execute(sql, tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def get_facebook_posts(self, payment_status: str = None, search: str = None, page: int = 1, limit: int = 50) -> dict:
        """Retrieves paginated Facebook posts with financial and search filters."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            where_clauses = ["1=1"]
            params = []

            if payment_status and payment_status.upper() != "ALL":
                where_clauses.append("payment_status = ?")
                params.append(payment_status.upper())

            if search and search.strip():
                kw = f"%{search.strip()}%"
                where_clauses.append("(client_name LIKE ? OR post_message LIKE ? OR payment_notes LIKE ?)")
                params.extend([kw, kw, kw])

            where_sql = " AND ".join(where_clauses)

            # Count total
            cursor.execute(f"SELECT COUNT(*) FROM facebook_posts WHERE {where_sql}", tuple(params))
            total_items = cursor.fetchone()[0]

            offset = (page - 1) * limit
            query_sql = f"""
                SELECT * FROM facebook_posts
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query_sql, tuple(params + [limit, offset]))
            rows = cursor.fetchall()

            return {
                "total": total_items,
                "page": page,
                "limit": limit,
                "posts": [dict(r) for r in rows]
            }

    def get_facebook_overview_stats(self) -> dict:
        """Calculates executive dashboard financial and performance metrics for Facebook."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM facebook_posts")
            total_posts = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM facebook_posts WHERE payment_status = 'PAID'")
            paid_posts = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM facebook_posts WHERE payment_status = 'UNPAID'")
            unpaid_posts = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM facebook_posts WHERE payment_status IN ('EDITORIAL', 'FREE')")
            editorial_posts = cursor.fetchone()[0]

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM facebook_posts WHERE payment_status = 'PAID'")
            paid_amount = cursor.fetchone()[0]

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM facebook_posts WHERE payment_status = 'UNPAID'")
            unpaid_amount = cursor.fetchone()[0]

            cursor.execute("SELECT COALESCE(SUM(likes_count), 0), COALESCE(SUM(comments_count), 0), COALESCE(SUM(shares_count), 0) FROM facebook_posts")
            likes_tot, comments_tot, shares_tot = cursor.fetchone()

            return {
                "total_posts": total_posts,
                "paid_posts": paid_posts,
                "unpaid_posts": unpaid_posts,
                "editorial_posts": editorial_posts,
                "paid_amount": paid_amount,
                "unpaid_amount": unpaid_amount,
                "total_likes": likes_tot or 0,
                "total_comments": comments_tot or 0,
                "total_shares": shares_tot or 0
            }

    def delete_facebook_post_record(self, post_id: Union[int, str]) -> bool:
        """Deletes a Facebook post record from the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM facebook_posts WHERE id = ? OR fb_post_id = ?", (str(post_id), str(post_id)))
            conn.commit()
            return cursor.rowcount > 0

    def save_article_edit_backup(
        self,
        post_id: str,
        site_type: str,
        article_url: str,
        original_title: str,
        original_content: str,
        modified_title: str,
        modified_content: str,
        client_notes: str = "",
        user_id: str = "",
        user_name: str = ""
    ) -> int:
        """Saves a snapshot of an article before edit so it can be restored with 1-click Undo."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO article_edit_backups 
                (post_id, site_type, article_url, original_title, original_content, modified_title, modified_content, client_notes, user_id, user_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(post_id), str(site_type), str(article_url or ""), str(original_title or ""), str(original_content or ""),
                str(modified_title or ""), str(modified_content or ""), str(client_notes or ""), str(user_id or ""), str(user_name or "")
            ))
            conn.commit()
            return cursor.lastrowid

    def get_latest_article_edit_backup(self, post_id: str, site_type: str = None) -> Optional[dict]:
        """Retrieves the most recent backup snapshot for a post."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if site_type:
                cursor.execute("""
                    SELECT * FROM article_edit_backups 
                    WHERE post_id = ? AND site_type = ? AND restored = 0
                    ORDER BY id DESC LIMIT 1
                """, (str(post_id), site_type))
            else:
                cursor.execute("""
                    SELECT * FROM article_edit_backups 
                    WHERE post_id = ? AND restored = 0
                    ORDER BY id DESC LIMIT 1
                """, (str(post_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def mark_article_edit_backup_restored(self, backup_id: int) -> bool:
        """Marks a backup snapshot as restored."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE article_edit_backups SET restored = 1 WHERE id = ?", (backup_id,))
            conn.commit()
            return cursor.rowcount > 0

_MEM_LAST_PUBLISH_TIME: float = 0.0
db = DatabaseManager()
