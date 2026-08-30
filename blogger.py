from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pickle

# الصلاحية المطلوبة للتعامل مع Blogger
SCOPES = [
    "https://www.googleapis.com/auth/blogger"
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.pickle"


def authenticate():
    creds = None

    # لو عملنا تسجيل دخول قبل كده
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    # أول مرة: افتح تسجيل دخول Google
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES
        )

        creds = flow.run_local_server(port=0)

        # حفظ تسجيل الدخول للمرة القادمة
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    return creds


def main():
    print("جاري الاتصال بـ Blogger...")

    creds = authenticate()

    blogger = build(
        "blogger",
        "v3",
        credentials=creds
    )

    # جلب المدونات الموجودة في حساب Google
    blogs = blogger.blogs().listByUser(userId="self").execute()

    items = blogs.get("items", [])

    if not items:
        print("لم يتم العثور على أي مدونة في هذا الحساب.")
        return

    print("\nتم الاتصال بنجاح!\n")
    print("المدونات الموجودة:\n")

    for blog in items:
        print("اسم المدونة:", blog.get("name"))
        print("Blog ID:", blog.get("id"))
        print("الرابط:", blog.get("url"))
        print("-" * 50)


if __name__ == "__main__":
    main()