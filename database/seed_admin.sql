-- ==========================================================
-- كود التفعيل الصحفي الدائم لرئيس التحرير العام (Full Access Admin)
-- منصة جريدة تحت الضوء
-- ==========================================================

-- 1. التأكد من وجود حساب رئيس التحرير في جدول المستخدمين
INSERT OR IGNORE INTO users (
    id, username, password_hash, full_name, role, email, is_active, phone
) VALUES (
    1, 
    'shalllaby1', 
    '09fea9dcfa2654e16d2123e7669969e8$833536741c2067dfa0ad4b2857176d68230bc3bf0290a80606c491af4f963b4a', 
    'أ/ محمد شلبي (رئيس التحرير العام)', 
    'admin', 
    'shalllaby1@gmail.com', 
    1, 
    '01062501088'
);

-- 2. إدراج كود التفعيل الماستر برتبة Admin وحالة مستخدم (USED) لتمكين الدخول الفوري
INSERT OR IGNORE INTO activation_codes (
    code, journalist_name, journalist_phone, role, status, created_by, used_by_email, used_at
) VALUES (
    'TD-SHALABY-ADMIN', 
    'أ/ محمد شلبي (رئيس التحرير العام)', 
    '01062501088', 
    'admin', 
    'USED', 
    'System Master', 
    'shalllaby1@gmail.com', 
    CURRENT_TIMESTAMP
);

-- 3. كود بديل إضافي
INSERT OR IGNORE INTO activation_codes (
    code, journalist_name, journalist_phone, role, status, created_by, used_by_email, used_at
) VALUES (
    'TD-7F4E46-ADMIN', 
    'أ/ محمد شلبي (رئيس التحرير العام)', 
    '01062501088', 
    'admin', 
    'USED', 
    'System Master', 
    'shalllaby1@gmail.com', 
    CURRENT_TIMESTAMP
);
