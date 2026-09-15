import sqlite3
import json
import re
import time
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
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
            cursor.execute("SELECT id, username, full_name, role, email, is_active, created_at, last_login FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, full_name, role, email, is_active, created_at, last_login FROM users WHERE username = ?", (username.strip().lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, full_name, role, email, is_active, created_at, last_login FROM users ORDER BY id ASC")
            return [dict(r) for r in cursor.fetchall()]

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
            cursor.execute("SELECT * FROM users WHERE email = ? OR username = ?", (email_clean, email_clean.split("@")[0]))
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
        suffix = "GOLD" if role == "editor" else ("ADMIN" if role == "admin" else "PRESS")
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
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                if row and row["published_at"]:
                    val = str(row["published_at"]).replace("Z", "").replace(" ", "T")
                    return datetime.fromisoformat(val).timestamp()
        except Exception:
            pass
        return 0.0

    def record_publish_event(self):
        """Records that an article was published right now."""
        global _MEM_LAST_PUBLISH_TIME
        _MEM_LAST_PUBLISH_TIME = time.time()

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
        if role == "admin":
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

_MEM_LAST_PUBLISH_TIME: float = 0.0
db = DatabaseManager()
